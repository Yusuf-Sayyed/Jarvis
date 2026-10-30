"""
Speech synthesis interface for JARVIS voice output.
Manages half-duplex state, prevents audio feedback, serializes playback
through a single managed queue, and provides clean local TTS (Piper with espeak-ng fallback).
"""

import os
import queue
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import wave
from dataclasses import dataclass, field
from typing import Optional

import numpy as np
import soundfile as sf

from core.config import (
    BASE_DIR,
    KOKORO_LANG,
    KOKORO_MODEL_PATH,
    KOKORO_SPEED,
    KOKORO_VOICE,
    KOKORO_VOICES_PATH,
    PIPER_BIN_PATH,
    PIPER_MODEL_PATH,
    POST_SPEECH_COOLDOWN_SECONDS,
    TTS_DIAGNOSTICS,
    TTS_ENGINE,
    TTS_ESPEAK_PITCH,
    TTS_ESPEAK_SPEED,
    TTS_ESPEAK_VOICE,
    TTS_MAX_TIMEOUT_SECONDS,
)

# Warm up Kokoro package and sub-dependencies (phonemizer, dlinfo ldconfig cache)
# at import time so subsequent test mocking or transient errors do not block dynamic linking.
try:
    try:
        from kokoro_onnx import Kokoro as _KokoroClass
    except ImportError:
        for _v in (".venv", ".venv-kokoro"):
            kokoro_pkg = (
                BASE_DIR
                / _v
                / "lib"
                / f"python{sys.version_info.major}.{sys.version_info.minor}"
                / "site-packages"
            )
            if kokoro_pkg.is_dir() and str(kokoro_pkg) not in sys.path:
                sys.path.append(str(kokoro_pkg))
        from kokoro_onnx import Kokoro as _KokoroClass
except Exception:
    _KokoroClass = None

_LAST_SPOKEN: str = ""
_IS_SPEAKING: bool = False
_COOLDOWN_UNTIL: float = 0.0
_STATE_LOCK = threading.RLock()


@dataclass
class _SpeechJob:
    text: str
    clean_text: str
    block: bool
    done_event: threading.Event = field(default_factory=threading.Event)
    success: bool = False
    error: Optional[str] = None
    duration: float = 0.0
    enqueued_at: float = field(default_factory=time.perf_counter)


_SPEECH_QUEUE: queue.Queue[_SpeechJob] = queue.Queue()
_WORKER_THREAD: Optional[threading.Thread] = None
_WORKER_LOCK = threading.Lock()
_ACTIVE_PROC: Optional[subprocess.Popen] = None
_ACTIVE_JOB: Optional[_SpeechJob] = None


def _log_diag(msg: str, is_error: bool = False, is_warning: bool = False):
    """
    Diagnostic logger.
    Detailed timings, sample counts, PIDs, and sentence metrics are restricted to DEBUG mode.
    Useful warnings and errors remain visible.
    """
    from core import config
    is_debug = getattr(config, "LOG_LEVEL", "INFO") == "DEBUG" or getattr(config, "TTS_DIAGNOSTICS", False)

    if os.environ.get("JARVIS_TEST_MODE") and not (is_debug or os.environ.get("JARVIS_DEBUG")):
        if not (is_error or is_warning):
            return

    if is_error:
        print(f"[TTS Error] {msg}")
    elif is_warning:
        print(f"[TTS Warning] {msg}")
    elif is_debug:
        print(f"[TTS Diagnostic] {msg}")


def is_speaking() -> bool:
    """Returns True if speech playback is currently active or queued."""
    global _IS_SPEAKING
    with _STATE_LOCK:
        return _IS_SPEAKING


def is_in_cooldown() -> bool:
    """Returns True if in the post-speech cooldown period."""
    global _COOLDOWN_UNTIL
    with _STATE_LOCK:
        return time.time() < _COOLDOWN_UNTIL


def should_mute_mic() -> bool:
    """
    Returns True if microphone input should be ignored (during speech or cooldown).
    Prevents JARVIS from hearing its own speech output.
    """
    return is_speaking() or is_in_cooldown()


def get_cooldown_remaining() -> float:
    """Returns seconds remaining in the post-speech cooldown."""
    with _STATE_LOCK:
        return max(0.0, _COOLDOWN_UNTIL - time.time())


def set_cooldown(seconds: float = POST_SPEECH_COOLDOWN_SECONDS):
    """Activates the post-speech cooldown for specified duration."""
    global _COOLDOWN_UNTIL
    with _STATE_LOCK:
        _COOLDOWN_UNTIL = time.time() + max(0.0, seconds)


def stop_speech():
    """Immediately halts active playback and clears pending jobs in queue."""
    global _IS_SPEAKING, _ACTIVE_PROC, _ACTIVE_JOB
    with _STATE_LOCK:
        if _ACTIVE_PROC is not None:
            try:
                _ACTIVE_PROC.terminate()
                _ACTIVE_PROC.wait(timeout=1.0)
            except Exception:
                try:
                    _ACTIVE_PROC.kill()
                except Exception:
                    pass
            _ACTIVE_PROC = None

        # Drain and cancel all pending jobs in queue
        while not _SPEECH_QUEUE.empty():
            try:
                job = _SPEECH_QUEUE.get_nowait()
                job.success = False
                job.error = "Cancelled by stop_speech"
                job.done_event.set()
                _SPEECH_QUEUE.task_done()
            except queue.Empty:
                break

        _ACTIVE_JOB = None
        _IS_SPEAKING = False
        set_cooldown(POST_SPEECH_COOLDOWN_SECONDS)
        _log_diag("Playback stopped and queue cleared")


def reset_speech_state():
    """Resets speaking and cooldown states (used in tests and shutdown)."""
    global _IS_SPEAKING, _COOLDOWN_UNTIL, _ACTIVE_PROC, _LAST_SPOKEN, _CACHED_PLAYER_BIN
    stop_speech()
    _CACHED_PLAYER_BIN = None
    with _STATE_LOCK:
        _IS_SPEAKING = False
        _COOLDOWN_UNTIL = 0.0
        _LAST_SPOKEN = ""


def clean_text_for_speech(text: str) -> str:
    """Strips markdown syntax, citations, and symbols for natural voice delivery."""
    t = text.strip()
    # Strip markdown links [text](url) -> text FIRST
    t = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", t)
    # Strip remaining URLs
    t = re.sub(r"https?://\S+", "", t)
    # Strip markdown bold/italic
    t = re.sub(r"[*_]{1,3}(.*?)[*_]{1,3}", r"\1", t)
    # Strip backticks
    t = t.replace("`", "")
    # Normalize multiple whitespaces
    t = re.sub(r"\s+", " ", t).strip()
    return t


_KOKORO_ENGINE = None
_KOKORO_LOCK = threading.Lock()
_KOKORO_INIT_FAILED = False


def get_kokoro_engine():
    """
    Thread-safe lazy initialization of the Kokoro ONNX model.
    Loads model and voice data once and reuses the singleton instance across all utterances.
    """
    global _KOKORO_ENGINE
    with _KOKORO_LOCK:
        if _KOKORO_ENGINE is not None:
            return _KOKORO_ENGINE

        if not KOKORO_MODEL_PATH.is_file() or not KOKORO_VOICES_PATH.is_file():
            _log_diag(
                f"Kokoro model or voices missing at {KOKORO_MODEL_PATH} / {KOKORO_VOICES_PATH}"
            )
            return None

        try:
            cls = _KokoroClass
            if cls is None:
                try:
                    from kokoro_onnx import Kokoro as cls
                except ImportError:
                    for _v in (".venv", ".venv-kokoro"):
                        kokoro_pkg = (
                            BASE_DIR
                            / _v
                            / "lib"
                            / f"python{sys.version_info.major}.{sys.version_info.minor}"
                            / "site-packages"
                        )
                        if kokoro_pkg.is_dir() and str(kokoro_pkg) not in sys.path:
                            sys.path.append(str(kokoro_pkg))
                    from kokoro_onnx import Kokoro as cls

            _log_diag(
                f"Initializing Kokoro TTS engine (model: {KOKORO_MODEL_PATH.name}, voice: {KOKORO_VOICE})..."
            )
            t0 = time.perf_counter()
            _KOKORO_ENGINE = cls(str(KOKORO_MODEL_PATH), str(KOKORO_VOICES_PATH))
            _log_diag(f"Kokoro TTS initialized in {time.perf_counter() - t0:.2f}s")
            return _KOKORO_ENGINE
        except Exception as e:
            _log_diag(f"Failed to initialize Kokoro TTS: {e}", is_error=True)
            return None


def reset_kokoro_engine():
    """Resets cached Kokoro engine singleton (primarily for testing and re-init)."""
    global _KOKORO_ENGINE, _KOKORO_INIT_FAILED
    with _KOKORO_LOCK:
        if _KOKORO_ENGINE is not None:
            try:
                if hasattr(_KOKORO_ENGINE, "voices") and hasattr(_KOKORO_ENGINE.voices, "close"):
                    _KOKORO_ENGINE.voices.close()
            except Exception:
                pass
        _KOKORO_ENGINE = None
        _KOKORO_INIT_FAILED = False


def _synthesize_kokoro(text: str, wav_path: str) -> bool:
    """
    Synthesizes clean text using Kokoro ONNX neural TTS directly to wav_path.
    Returns True on success, False on failure.
    """
    engine = get_kokoro_engine()
    if engine is None:
        return False

    try:
        _log_diag(
            f"Engine: kokoro | Voice: {KOKORO_VOICE} | Lang: {KOKORO_LANG} | Speed: {KOKORO_SPEED}"
        )
        _log_diag(
            f"Input: {len(text)} chars (\"{text[:50]}{'...' if len(text) > 50 else ''}\")"
        )
        t0 = time.perf_counter()
        audio, sample_rate = engine.create(
            text,
            voice=KOKORO_VOICE,
            speed=KOKORO_SPEED,
            lang=KOKORO_LANG,
        )
        gen_time = time.perf_counter() - t0

        if not isinstance(sample_rate, (int, np.integer)) or sample_rate <= 0:
            _log_diag(f"Kokoro returned invalid sample rate: {sample_rate}")
            if os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
            return False

        if isinstance(audio, (list, tuple)):
            clean_parts = []
            for part in audio:
                p = np.asarray(part, dtype=np.float32).squeeze()
                if p.ndim != 1 or p.size == 0:
                    _log_diag(f"Kokoro returned invalid batch audio array: shape={getattr(part, 'shape', None)}")
                    if os.path.exists(wav_path):
                        try:
                            os.unlink(wav_path)
                        except Exception:
                            pass
                    return False
                clean_parts.append(p)
            audio = np.concatenate(clean_parts, axis=0) if clean_parts else np.zeros((0,), dtype=np.float32)
        else:
            audio = np.asarray(audio, dtype=np.float32).squeeze()

        if audio.ndim != 1 or audio.size == 0 or not np.all(np.isfinite(audio)):
            _log_diag(
                f"Kokoro returned invalid audio array: shape={getattr(audio, 'shape', None)}, size={getattr(audio, 'size', None)}"
            )
            if os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
            return False

        audio = np.clip(audio, -1.0, 1.0)
        sf.write(wav_path, audio, int(sample_rate), subtype="PCM_16")
        if not os.path.isfile(wav_path) or os.path.getsize(wav_path) == 0:
            _log_diag("Kokoro generated audio file is missing or empty")
            if os.path.exists(wav_path):
                try:
                    os.unlink(wav_path)
                except Exception:
                    pass
            return False

        _log_diag(
            f"Kokoro generated in {gen_time:.2f}s (samples={audio.size}, rate={sample_rate}Hz)"
        )
        from core.diagnostics import log_timing
        log_timing("Kokoro generation", gen_time, f"samples={audio.size}, rate={sample_rate}Hz")
        return True
    except Exception as e:
        _log_diag(f"Kokoro audio generation failed: {e}")
        if os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        return False


def _synthesize_piper(text: str, wav_path: str) -> bool:
    """Synthesizes text using Piper TTS binary to wav_path."""
    if not (PIPER_BIN_PATH.is_file() and PIPER_MODEL_PATH.is_file()):
        return False

    _log_diag(f"Engine: piper | Model: {PIPER_MODEL_PATH.name}")
    _log_diag(f"Input: {len(text)} chars (\"{text[:50]}{'...' if len(text) > 50 else ''}\")")
    cmd = [
        str(PIPER_BIN_PATH),
        "--model", str(PIPER_MODEL_PATH),
        "--output_file", wav_path,
    ]
    try:
        proc = subprocess.run(
            cmd,
            input=text,
            text=True,
            capture_output=True,
            timeout=TTS_MAX_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            _log_diag(f"Piper error (code {proc.returncode}): {proc.stderr}")
            return False
        return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0
    except Exception as e:
        _log_diag(f"Piper synthesis exception: {e}")
        return False


def _synthesize_espeak(text: str, wav_path: str) -> bool:
    """Synthesizes text using espeak-ng binary to wav_path."""
    espeak_bin = shutil.which("espeak-ng") or shutil.which("espeak")
    if not espeak_bin:
        _log_diag("No TTS engine binary found (espeak-ng missing)")
        return False

    _log_diag(f"Engine: espeak-ng | Voice: {TTS_ESPEAK_VOICE} | Pitch: {TTS_ESPEAK_PITCH} | Speed: {TTS_ESPEAK_SPEED}")
    _log_diag(f"Input: {len(text)} chars (\"{text[:50]}{'...' if len(text) > 50 else ''}\")")
    cmd = [
        espeak_bin,
        "-v", TTS_ESPEAK_VOICE,
        "-p", str(TTS_ESPEAK_PITCH),
        "-s", str(TTS_ESPEAK_SPEED),
        "-w", wav_path,
        text,
    ]
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=TTS_MAX_TIMEOUT_SECONDS,
        )
        if proc.returncode != 0:
            _log_diag(f"espeak-ng error (code {proc.returncode}): {proc.stderr}")
            return False
        return os.path.isfile(wav_path) and os.path.getsize(wav_path) > 0
    except Exception as e:
        _log_diag(f"espeak-ng synthesis exception: {e}")
        return False


def _synthesize_to_wav(text: str) -> tuple[Optional[str], int, float]:
    """
    Synthesizes clean text to a temporary WAV file using the configured TTS engine
    with automatic graceful fallback:
    1. Kokoro ONNX neural TTS (configured British English voice via KOKORO_VOICE)
    2. Piper neural TTS (if configured and available)
    3. espeak-ng (lightweight local fallback)

    Returns (wav_path, sample_rate, duration_seconds).
    """
    temp_wav = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
    wav_path = temp_wav.name
    temp_wav.close()

    success = False

    # 1. Kokoro Neural TTS (Default in "auto" or explicit "kokoro")
    if TTS_ENGINE in ("auto", "kokoro"):
        success = _synthesize_kokoro(text, wav_path)
        if not success and TTS_ENGINE == "auto":
            _log_diag("Kokoro TTS unavailable or failed; falling back to secondary engine...", is_warning=True)

    # 2. Piper Neural TTS fallback
    if not success and TTS_ENGINE in ("auto", "piper"):
        success = _synthesize_piper(text, wav_path)
        if not success and TTS_ENGINE == "auto":
            _log_diag("Piper TTS unavailable; falling back to espeak-ng...", is_warning=True)

    # 3. espeak-ng fallback
    if not success:
        success = _synthesize_espeak(text, wav_path)

    if not success or not os.path.isfile(wav_path) or os.path.getsize(wav_path) == 0:
        _log_diag("All available TTS engines failed to synthesize audio", is_error=True)
        if os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        return None, 0, 0.0

    # Inspect the generated WAV file
    try:
        with wave.open(wav_path, "rb") as wf:
            sample_rate = wf.getframerate()
            channels = wf.getnchannels()
            frames = wf.getnframes()
            duration = frames / float(sample_rate) if sample_rate > 0 else 0.0
            size_bytes = os.path.getsize(wav_path)
            _log_diag(f"Audio synthesized: {duration:.2f}s | rate={sample_rate}Hz | channels={channels} | size={size_bytes}B")
            return wav_path, sample_rate, duration
    except Exception as e:
        _log_diag(f"Error reading generated WAV header: {e}")
        if os.path.exists(wav_path):
            try:
                os.unlink(wav_path)
            except Exception:
                pass
        return None, 0, 0.0



_CACHED_PLAYER_BIN: Optional[str] = None


def _get_player_bin() -> Optional[str]:
    if os.environ.get("JARVIS_TEST_MODE"):
        return shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
    global _CACHED_PLAYER_BIN
    if _CACHED_PLAYER_BIN is None:
        _CACHED_PLAYER_BIN = shutil.which("pw-play") or shutil.which("paplay") or shutil.which("aplay")
    return _CACHED_PLAYER_BIN


def _play_wav_file(wav_path: str, duration: float) -> bool:
    """
    Plays a WAV file using pw-play (or paplay / aplay) with PipeWire buffer draining.
    Ensures the audio stream remains valid until playback finishes completely.
    """
    global _ACTIVE_PROC

    player_bin = _get_player_bin()
    if not player_bin:
        _log_diag("No audio player binary found (pw-play, paplay, aplay)")
        return False

    player_name = os.path.basename(player_bin)
    t0 = time.time()
    proc = None
    try:
        proc = subprocess.Popen(
            [player_bin, wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
        )
        with _STATE_LOCK:
            _ACTIVE_PROC = proc

        _log_diag(f"Playback started via {player_name} (pid={proc.pid})")
        timeout = max(TTS_MAX_TIMEOUT_SECONDS, duration + 5.0)
        stderr_output = ""
        try:
            _, stderr_output = proc.communicate(timeout=timeout)
        except subprocess.TimeoutExpired:
            _log_diag(f"Playback timed out after {timeout}s; terminating process")
            proc.kill()
            proc.communicate()
            return False

        elapsed = time.time() - t0
        from core.diagnostics import log_timing
        log_timing("Audio playback", elapsed, f"player={player_name}, duration={duration:.2f}s")
        if proc.returncode == 0:
            _log_diag(f"Playback completed successfully in {elapsed:.2f}s")
            return True
        else:
            if proc.returncode in (-15, -9, 143, 137):
                _log_diag("Playback process terminated by request")
            else:
                _log_diag(f"Playback process exited with code {proc.returncode}: {stderr_output.strip()}")
            return False

    except Exception as e:
        _log_diag(f"Playback exception: {e}")
        return False
    finally:
        with _STATE_LOCK:
            if proc is not None and _ACTIVE_PROC == proc:
                _ACTIVE_PROC = None


def split_into_sentences(text: str) -> list[str]:
    """Splits text into clean, pronounceable sentence units for pipelined synthesis."""
    chunks = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    return chunks if chunks else [text.strip()]


def _playback_worker_loop():
    """Single background worker loop that processes speech jobs sequentially."""
    global _IS_SPEAKING, _ACTIVE_PROC, _ACTIVE_JOB

    while True:
        try:
            job = _SPEECH_QUEUE.get()
        except Exception:
            break

        if job is None:
            _SPEECH_QUEUE.task_done()
            break

        with _STATE_LOCK:
            _IS_SPEAKING = True
            _ACTIVE_JOB = job

        sentences = split_into_sentences(job.clean_text)
        total_duration = 0.0
        job_success = True

        try:
            if len(sentences) <= 1:
                t0_syn = time.perf_counter()
                wav_path, sample_rate, duration = _synthesize_to_wav(job.clean_text)
                syn_time = time.perf_counter() - t0_syn
                job.duration = duration

                if wav_path and os.path.isfile(wav_path):
                    t_first_audible = time.perf_counter() - job.enqueued_at
                    _log_diag(
                        f"Synthesis: {syn_time:.2f}s | First audible sound: {t_first_audible:.2f}s | Playback duration: {duration:.2f}s"
                    )
                    try:
                        job_success = _play_wav_file(wav_path, duration)
                    finally:
                        if os.path.exists(wav_path):
                            try:
                                os.unlink(wav_path)
                            except Exception:
                                pass
                else:
                    job_success = False
                    job.error = "Synthesis produced no valid audio file"
            else:
                _log_diag(f"Low-latency sentence pipelining active ({len(sentences)} sentences)...")
                from concurrent.futures import ThreadPoolExecutor

                with ThreadPoolExecutor(max_workers=1) as syn_executor:
                    t0_syn = time.perf_counter()
                    next_future = syn_executor.submit(_synthesize_to_wav, sentences[0])

                    for idx in range(len(sentences)):
                        try:
                            curr_wav, curr_rate, curr_dur = next_future.result(timeout=TTS_MAX_TIMEOUT_SECONDS)
                        except Exception as e:
                            _log_diag(f"Pipelined synthesis error for sentence {idx+1}: {e}")
                            curr_wav, curr_rate, curr_dur = None, 0, 0.0

                        # Submit next sentence synthesis while current sentence will be playing
                        if idx + 1 < len(sentences):
                            next_future = syn_executor.submit(_synthesize_to_wav, sentences[idx + 1])
                        else:
                            next_future = None

                        if idx == 0:
                            t_first_audible = time.perf_counter() - job.enqueued_at
                            _log_diag(
                                f"Sentence 1 synthesized in {time.perf_counter() - t0_syn:.2f}s | First audible sound: {t_first_audible:.2f}s"
                            )

                        if curr_wav and os.path.isfile(curr_wav):
                            try:
                                play_ok = _play_wav_file(curr_wav, curr_dur)
                                total_duration += curr_dur
                                if not play_ok:
                                    job_success = False
                            finally:
                                if os.path.exists(curr_wav):
                                    try:
                                        os.unlink(curr_wav)
                                    except Exception:
                                        pass
                        else:
                            _log_diag(f"Sentence {idx+1} could not be synthesized, skipping audio")

                job.duration = total_duration

        except Exception as e:
            job_success = False
            job.error = str(e)
            _log_diag(f"Playback error: {e}")
        finally:
            job.success = job_success
            with _STATE_LOCK:
                _ACTIVE_JOB = None
                _ACTIVE_PROC = None
                if _SPEECH_QUEUE.empty():
                    _IS_SPEAKING = False
                    set_cooldown(POST_SPEECH_COOLDOWN_SECONDS)
                else:
                    _IS_SPEAKING = True

            job.done_event.set()
            _SPEECH_QUEUE.task_done()


def warmup_speech_engine():
    """Warms up the Kokoro TTS engine in a background daemon thread to eliminate first-audio delay."""
    def _do_warmup():
        try:
            get_kokoro_engine()
        except Exception:
            pass
    threading.Thread(target=_do_warmup, daemon=True, name="Kokoro-Warmup-Thread").start()


def wait_for_speech_completion(timeout: float = TTS_MAX_TIMEOUT_SECONDS) -> bool:
    """Waits until all pending speech jobs in the queue finish playing."""
    start = time.perf_counter()
    while time.perf_counter() - start < timeout:
        with _STATE_LOCK:
            if not _IS_SPEAKING and _SPEECH_QUEUE.empty():
                return True
        time.sleep(0.05)
    return False


def _ensure_worker_started():
    """Spawns the singleton background playback worker thread if not running."""
    global _WORKER_THREAD
    with _WORKER_LOCK:
        if _WORKER_THREAD is None or not _WORKER_THREAD.is_alive():
            _WORKER_THREAD = threading.Thread(
                target=_playback_worker_loop, daemon=True, name="TTS-Playback-Worker"
            )
            _WORKER_THREAD.start()


def speak(text: str, block: bool = True) -> bool:
    """
    Speaks text through local TTS engine with full feedback protection.
    Enqueues request into a single managed playback queue to serialize
    playback without drops or overlaps.
    """
    global _LAST_SPOKEN, _IS_SPEAKING

    clean = clean_text_for_speech(text)
    if not clean:
        return False

    with _STATE_LOCK:
        _LAST_SPOKEN = clean

    # Fast-path for unit tests or headless environments
    if os.environ.get("JARVIS_TEST_MODE"):
        with _STATE_LOCK:
            _IS_SPEAKING = True
            try:
                pass
            finally:
                _IS_SPEAKING = False
                set_cooldown(POST_SPEECH_COOLDOWN_SECONDS)
        return True

    _ensure_worker_started()

    job = _SpeechJob(text=text, clean_text=clean, block=block)

    with _STATE_LOCK:
        _IS_SPEAKING = True
        _SPEECH_QUEUE.put(job)

    if block:
        job.done_event.wait(timeout=TTS_MAX_TIMEOUT_SECONDS + 5.0)
        return job.success
    else:
        return True


def get_last_spoken() -> str:
    """Returns the most recent utterance passed to the speech interface."""
    with _STATE_LOCK:
        return _LAST_SPOKEN
