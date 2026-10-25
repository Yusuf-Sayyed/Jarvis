"""
Vosk speech recognition model and PyAudio microphone listener.
"""

import ctypes
import json
import subprocess
import sys
from core.config import CHUNK_SIZE, MODEL_DIR, SAMPLE_RATE

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
from vosk import KaldiRecognizer, Model, SetLogLevel

# Suppress verbose Vosk Kaldi logging
SetLogLevel(-1)


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


def init_speech_model() -> tuple[Model, KaldiRecognizer]:
    """Loads the Vosk speech model and initializes KaldiRecognizer."""
    if not MODEL_DIR.is_dir():
        print(f"\n[Error] Vosk model directory not found at: '{MODEL_DIR.resolve()}'")
        print("Please ensure 'vosk-model-small-en-us-0.15' is present in this directory.")
        sys.exit(1)

    print(f"Loading speech model from '{MODEL_DIR}'...")
    try:
        model = Model(str(MODEL_DIR))
    except Exception as e:
        print(f"[Error] Failed to load Vosk model: {e}")
        sys.exit(1)

    recognizer = KaldiRecognizer(model, SAMPLE_RATE)
    return model, recognizer


def init_audio_stream() -> tuple[pyaudio.PyAudio, pyaudio.Stream]:
    """Initializes PyAudio and opens the microphone audio stream."""
    try:
        p = pyaudio.PyAudio()
    except Exception as e:
        print(f"[Error] Could not initialize PyAudio: {e}")
        sys.exit(1)

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
        print(f"\n[Error] Could not open microphone stream: {e}")
        print("Please verify your microphone is connected and accessible.")
        p.terminate()
        sys.exit(1)

    return p, stream
