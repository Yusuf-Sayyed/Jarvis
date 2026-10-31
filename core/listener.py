"""
Speech recognition model loader and PyAudio microphone listener.
Supports high-accuracy offline Whisper with Voice Activity Detection (VAD)
as well as a 1-click fallback to Vosk.
"""

import collections
import ctypes
import json
import subprocess
import sys
import time
from collections import deque
from pathlib import Path
from typing import Optional

import numpy as np

from core.config import (
    CHUNK_SIZE,
    FALLBACK_MODEL_DIR,
    MAX_UTTERANCE_SECONDS,
    MIN_UTTERANCE_CHUNKS,
    MODEL_DIR,
    PRE_SPEECH_BUFFER_CHUNKS,
    SAMPLE_RATE,
    STT_ENGINE,
    VAD_SILENCE_TIMEOUT_SECONDS,
    VAD_SPEECH_THRESHOLD,
    WHISPER_COMPUTE_TYPE,
    WHISPER_DEVICE,
    WHISPER_MODEL_DIR,
    WHISPER_MODEL_NAME,
)

# Suppress ALSA noisy warnings on Linux during PyAudio initialization
try:
    ERROR_HANDLER_FUNC = ctypes.CFUNCTYPE(
        None, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p
    )

    def py_error_handler(filename, line, function, err, fmt):
        pass

    c_error_handler = ERROR_HANDLER_FUNC(py_error_handler)
    asound = ctypes.cdll.LoadLibrary("libasound.so.2")
    asound.snd_lib_error_set_handler(c_error_handler)
except Exception:
    pass

import pyaudio


def check_microphone_status() -> bool:
    """Checks if the default microphone is muted in PipeWire / KDE."""
    try:
        result = subprocess.run(
            ["wpctl", "get-volume", "@DEFAULT_AUDIO_SOURCE@"],
            capture_output=True,
            text=True,
            check=False,
        )
        if "MUTED" in result.stdout:
            print("⚠️  [Warning] Your default microphone is currently MUTED in Fedora KDE!")
            print("             Run: wpctl set-mute @DEFAULT_AUDIO_SOURCE@ 0")
            print("             Or click the microphone icon in your KDE system tray to unmute.\n")
            return False
    except Exception:
        pass
    return True


class SpeechRecognizer:
    """
    Unified offline speech recognizer supporting:
      1. Whisper (faster-whisper) with pre-speech ring buffer and energy/silence VAD.
      2. Vosk (Kaldi recognizer) as a rollback engine.
    """

    def __init__(self, engine: str = STT_ENGINE):
        self.engine = engine.lower()
        self.whisper_model = None
        self.vad_model = None
        self.vosk_recognizer = None

        # Whisper VAD / Utterance state
        self.speech_active = False
        self.speech_start_time = 0.0
        self.silence_start_time = None
        self.speech_frames: list[bytes] = []
        self.pre_buffer = deque(maxlen=PRE_SPEECH_BUFFER_CHUNKS)
        self.last_display_time = 0.0
        self.last_partial_text = ""

        if self.engine == "whisper":
            self._init_whisper()
        else:
            self._init_vosk()

    def _init_whisper(self):
        """Loads faster-whisper offline model and neural VAD."""
        try:
            from faster_whisper import WhisperModel
            from faster_whisper.vad import get_vad_model
        except ImportError:
            print("[Warning] 'faster-whisper' package not found. Falling back to Vosk.")
            self.engine = "vosk"
            self._init_vosk()
            return

        print(f"Loading Whisper speech model ('{WHISPER_MODEL_NAME}', compute={WHISPER_COMPUTE_TYPE})...")
        try:
            self.whisper_model = WhisperModel(
                WHISPER_MODEL_NAME,
                device=WHISPER_DEVICE,
                compute_type=WHISPER_COMPUTE_TYPE,
                download_root=str(WHISPER_MODEL_DIR),
                cpu_threads=4,
            )
            print("Whisper model loaded.")
        except Exception as e:
            print(f"[Warning] Failed to initialize Whisper model: {e}")
            print("Falling back to Vosk speech model...")
            self.engine = "vosk"
            self._init_vosk()
            return

        try:
            self.vad_model = get_vad_model()
            print("Neural Voice Activity Detector (Silero VAD) initialized.")
        except Exception as e:
            print(f"[Warning] Could not load Silero VAD: {e}. Using energy detection.")
            self.vad_model = None

    def _init_vosk(self):
        """Loads Vosk Kaldi offline speech model."""
        from vosk import KaldiRecognizer, Model, SetLogLevel
        SetLogLevel(-1)

        active_model_dir = MODEL_DIR
        if not active_model_dir.is_dir():
            print(f"\n[Warning] Vosk model not found at: '{active_model_dir.resolve()}'")
            if FALLBACK_MODEL_DIR.is_dir():
                print(f"Falling back to small model: '{FALLBACK_MODEL_DIR.resolve()}'")
                active_model_dir = FALLBACK_MODEL_DIR
            else:
                print("[Error] No valid Vosk model directory found.")
                sys.exit(1)

        print(f"Loading Vosk speech model from '{active_model_dir}'...")
        try:
            model = Model(str(active_model_dir))
            self.vosk_recognizer = KaldiRecognizer(model, SAMPLE_RATE)
            self.vosk_recognizer.SetWords(True)
            print("Vosk model loaded and ready.")
        except Exception as e:
            print(f"[Error] Failed to load Vosk model: {e}")
            sys.exit(1)

    def reset_buffers(self):
        """Clears speech audio buffers and pre-speech ring buffer."""
        self.speech_frames.clear()
        self.pre_buffer.clear()
        self.speech_active = False
        self.speech_start_time = 0.0
        self.silence_start_time = None
        self.last_partial_text = ""
        if self.vosk_recognizer is not None:
            try:
                self.vosk_recognizer.Reset()
            except Exception:
                pass

    def process_audio(
        self, data: bytes, session_active: bool = False, time_remaining_str: str = ""
    ) -> str | None:
        """
        Processes an incoming audio frame from PyAudio.
        Suppresses input during TTS playback and post-speech cooldown to prevent feedback.

        Returns:
            Completed spoken utterance string if speech has concluded, else None.
        """
        from interfaces.speech import should_mute_mic
        if should_mute_mic():
            self.reset_buffers()
            return None

        if self.engine == "whisper":
            return self._process_whisper(data, session_active, time_remaining_str)
        else:
            return self._process_vosk(data, session_active, time_remaining_str)

    def _process_whisper(
        self, data: bytes, session_active: bool, time_remaining_str: str
    ) -> str | None:
        # Detect voice activity via neural Silero VAD (or energy fallback)
        samples = np.frombuffer(data, dtype=np.int16).astype(np.float32) / 32768.0
        is_speech = False
        if self.vad_model is not None and len(samples) % 512 == 0:
            try:
                vad_out = self.vad_model(samples)
                is_speech = float(np.max(vad_out)) >= VAD_SPEECH_THRESHOLD
            except Exception as e:
                from core.diagnostics import logger
                logger.debug("[STT] Silero VAD evaluation error: %s. Using energy fallback.", e)
                rms = float(np.sqrt(np.mean(np.square(samples * 32768.0))))
                is_speech = rms >= 2500
        else:
            rms = float(np.sqrt(np.mean(np.square(samples * 32768.0))))
            is_speech = rms >= 2500

        now = time.time()
        tag = f"[ACTIVE | {time_remaining_str} left]" if session_active else "[STANDBY | Say 'Hey JARVIS']"

        if not self.speech_active:
            # Maintain pre-speech audio ring buffer to avoid clipping speech onset
            self.pre_buffer.append(data)
            if is_speech:
                self.speech_active = True
                self.speech_start_time = now
                self.silence_start_time = None
                self.speech_frames = list(self.pre_buffer)
                self.speech_frames.append(data)
                self.last_display_time = now
                print(f"\033[2K\r{tag} 🎤 Listening...", end="", flush=True)
            return None

        # Currently accumulating speech
        self.speech_frames.append(data)
        elapsed = now - self.speech_start_time

        if is_speech:
            # Continued voice activity resets silence counter
            self.silence_start_time = None
            if now - self.last_display_time >= 0.35:
                self.last_display_time = now
                print(f"\033[2K\r{tag} 🎤 Listening ({elapsed:.1f}s)...", end="", flush=True)
        else:
            # Potential end of speech (silence chunk)
            if self.silence_start_time is None:
                self.silence_start_time = now

        # Check if silence timeout reached or max utterance duration exceeded
        silence_duration = (now - self.silence_start_time) if self.silence_start_time else 0.0
        should_finalize = (
            silence_duration >= VAD_SILENCE_TIMEOUT_SECONDS or elapsed >= MAX_UTTERANCE_SECONDS
        )

        if not should_finalize:
            return None

        # Finalize utterance
        self.speech_active = False
        print("\033[2K\r", end="", flush=True)

        frames_to_transcribe = self.speech_frames
        self.speech_frames = []

        capture_duration = max(0.0, now - self.speech_start_time)
        from core.diagnostics import log_timing
        log_timing("Speech capture", capture_duration, f"chunks={len(frames_to_transcribe)}")

        if len(frames_to_transcribe) < MIN_UTTERANCE_CHUNKS:
            # Discard short transient clicks or coughs
            return None

        raw_pcm = b"".join(frames_to_transcribe)
        audio_float = np.frombuffer(raw_pcm, dtype=np.int16).astype(np.float32) / 32768.0

        try:
            t0 = time.perf_counter()
            segments, _ = self.whisper_model.transcribe(
                audio_float,
                language="en",
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500, speech_pad_ms=250),
                beam_size=3,
                condition_on_previous_text=False,
            )
            text = "".join(s.text for s in segments).strip()
            log_timing("Whisper transcription", time.perf_counter() - t0, f"text='{text}'")
            return text if text else None
        except Exception as e:
            from core.diagnostics import logger
            logger.debug("[STT] Whisper transcription error encountered: %s", e)
            print(f"\n[Warning] Whisper transcription error: {e}")
            return None

    def _process_vosk(
        self, data: bytes, session_active: bool, time_remaining_str: str
    ) -> str | None:
        tag = f"[ACTIVE | {time_remaining_str} left]" if session_active else "[STANDBY | Say 'Hey JARVIS']"

        if self.vosk_recognizer.AcceptWaveform(data):
            result = json.loads(self.vosk_recognizer.Result())
            text = result.get("text", "").strip()
            print("\033[2K\r", end="", flush=True)
            self.last_partial_text = ""
            return text if text else None
        else:
            partial_data = json.loads(self.vosk_recognizer.PartialResult())
            partial_text = partial_data.get("partial", "").strip()
            if partial_text and partial_text != self.last_partial_text:
                self.last_partial_text = partial_text
                print(f"\033[2K\r{tag} 🎤 Hearing: \"{partial_text}\"...", end="", flush=True)
            return None


def init_speech_engine() -> SpeechRecognizer:
    """Initializes and returns the configured speech recognition engine."""
    return SpeechRecognizer(STT_ENGINE)


def init_speech_model() -> tuple[SpeechRecognizer, SpeechRecognizer]:
    """Compatibility wrapper returning recognizer instance."""
    engine = init_speech_engine()
    return engine, engine


def init_audio_stream(fatal: bool = True) -> tuple[Optional[pyaudio.PyAudio], Optional[pyaudio.Stream]]:
    """Initializes PyAudio and opens the microphone audio stream."""
    try:
        p = pyaudio.PyAudio()
    except Exception as e:
        from core.diagnostics import logger
        logger.debug("[Audio] Could not initialize PyAudio: %s", e)
        print(f"[Error] Could not initialize PyAudio: {e}")
        if fatal:
            sys.exit(1)
        return None, None

    try:
        default_dev = p.get_default_input_device_info()
        print(f"Audio Device: {default_dev.get('name', 'Default')}")
    except Exception:
        pass

    try:
        stream = p.open(
            format=pyaudio.paInt16,
            channels=1,
            rate=SAMPLE_RATE,
            input=True,
            frames_per_buffer=CHUNK_SIZE,
        )
        stream.start_stream()
    except Exception as e:
        from core.diagnostics import logger
        logger.debug("[Audio] Could not open microphone stream: %s", e)
        print(f"\n[Error] Could not open microphone stream: {e}")
        print("Please verify your microphone is connected and accessible.")
        try:
            p.terminate()
        except Exception:
            pass
        if fatal:
            sys.exit(1)
        return None, None

    return p, stream


def recover_audio_stream(
    old_audio_mgr: Optional[pyaudio.PyAudio] = None,
    old_stream: Optional[pyaudio.Stream] = None,
    max_retries: int = 3,
    retry_delay: float = 0.5,
) -> tuple[Optional[pyaudio.PyAudio], Optional[pyaudio.Stream]]:
    """
    Safely tears down interrupted or failed audio stream resources and attempts
    to re-open a fresh PyAudio microphone stream without killing the application.
    """
    from core.diagnostics import logger
    logger.debug("[Audio] Audio stream recovery initiated (max_retries=%d)...", max_retries)

    if old_stream is not None:
        try:
            if hasattr(old_stream, "stop_stream") and old_stream.is_active():
                old_stream.stop_stream()
        except Exception:
            pass
        try:
            if hasattr(old_stream, "close"):
                old_stream.close()
        except Exception:
            pass

    if old_audio_mgr is not None:
        try:
            if hasattr(old_audio_mgr, "terminate"):
                old_audio_mgr.terminate()
        except Exception:
            pass

    for attempt in range(1, max_retries + 1):
        time.sleep(retry_delay)
        p, stream = init_audio_stream(fatal=False)
        if p is not None and stream is not None:
            logger.debug("[Audio] Microphone stream recovered successfully on attempt %d.", attempt)
            return p, stream
        logger.debug("[Audio] Stream recovery attempt %d/%d failed.", attempt, max_retries)

    logger.debug("[Audio] All %d stream recovery attempts failed.", max_retries)
    return None, None

