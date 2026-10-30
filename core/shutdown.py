"""
Clean shutdown coordination for JARVIS.
Handles goodbye speech, microphone silence, audio stream deallocation,
instance lock release, and process termination.
"""

import os
import sys
import threading
import time
from typing import Callable, Optional

_SHUTDOWN_LOCK = threading.RLock()
_SHUTDOWN_COMPLETED = False
_GOODBYE_SPOKEN = False

# Active runtime handles
_REGISTERED_STREAM = None
_REGISTERED_AUDIO_MGR = None
_REGISTERED_SPEECH_ENGINE = None
_LOCK_RELEASE_CALLBACK: Optional[Callable[[], None]] = None


def register_audio_context(stream=None, audio_mgr=None, speech_engine=None):
    """Registers active audio stream, PyAudio manager, and speech recognizer engine."""
    global _REGISTERED_STREAM, _REGISTERED_AUDIO_MGR, _REGISTERED_SPEECH_ENGINE
    with _SHUTDOWN_LOCK:
        if stream is not None:
            _REGISTERED_STREAM = stream
        if audio_mgr is not None:
            _REGISTERED_AUDIO_MGR = audio_mgr
        if speech_engine is not None:
            _REGISTERED_SPEECH_ENGINE = speech_engine


def register_lock_release_callback(fn: Callable[[], None]):
    """Registers the callback to release the instance lock file."""
    global _LOCK_RELEASE_CALLBACK
    with _SHUTDOWN_LOCK:
        _LOCK_RELEASE_CALLBACK = fn


def reset_shutdown_state():
    """Resets shutdown state flags (primarily for testing)."""
    global _SHUTDOWN_COMPLETED, _GOODBYE_SPOKEN
    global _REGISTERED_STREAM, _REGISTERED_AUDIO_MGR, _REGISTERED_SPEECH_ENGINE, _LOCK_RELEASE_CALLBACK
    with _SHUTDOWN_LOCK:
        _SHUTDOWN_COMPLETED = False
        _GOODBYE_SPOKEN = False
        _REGISTERED_STREAM = None
        _REGISTERED_AUDIO_MGR = None
        _REGISTERED_SPEECH_ENGINE = None
        _LOCK_RELEASE_CALLBACK = None


def _stop_microphone(stream=None, speech_engine=None):
    """
    Stops the microphone stream and flushes speech recognizer buffers immediately.
    Guarantees the microphone does not capture the goodbye audio or background noise.
    """
    target_stream = stream or _REGISTERED_STREAM
    target_engine = speech_engine or _REGISTERED_SPEECH_ENGINE

    if target_stream is not None:
        try:
            if hasattr(target_stream, "is_active") and target_stream.is_active():
                target_stream.stop_stream()
        except Exception:
            pass

    if target_engine is not None:
        try:
            if hasattr(target_engine, "reset_buffers"):
                target_engine.reset_buffers()
        except Exception:
            pass


def speak_goodbye(
    timeout_seconds: float = 6.0,
    stream=None,
    speech_engine=None,
) -> bool:
    """
    Speaks 'Goodbye, Sir.' using Kokoro TTS and waits until playback finishes.
    Guarantees it executes only once.
    Safely handles TTS failure or timeout without hanging.
    """
    global _GOODBYE_SPOKEN
    with _SHUTDOWN_LOCK:
        if _GOODBYE_SPOKEN:
            return True
        _GOODBYE_SPOKEN = True

    # 1. Stop microphone immediately to prevent capturing goodbye audio
    _stop_microphone(stream=stream, speech_engine=speech_engine)

    farewell_text = "Goodbye, Sir."
    print(f'\n[JARVIS] "{farewell_text}"')

    # Fast-path for unit tests or headless test environments
    if os.environ.get("JARVIS_TEST_MODE"):
        try:
            from interfaces.speech import speak
            speak(farewell_text, block=False)
        except Exception:
            pass
        return True

    success = False
    try:
        from interfaces.speech import speak

        done_event = threading.Event()

        def _tts_worker():
            nonlocal success
            try:
                success = speak(farewell_text, block=True)
            except Exception as ex:
                print(f"[JARVIS Shutdown Warning] Speech synthesis failed: {ex}")
            finally:
                done_event.set()

        tts_thread = threading.Thread(
            target=_tts_worker, daemon=True, name="Shutdown-Goodbye-TTS"
        )
        tts_thread.start()

        # Wait with watchdog timeout so JARVIS never hangs indefinitely
        finished = done_event.wait(timeout=timeout_seconds)
        if not finished:
            print("[JARVIS Shutdown Warning] Goodbye speech timed out; proceeding with clean shutdown.")
    except Exception as e:
        print(f"[JARVIS Shutdown Warning] Error during goodbye playback: {e}")

    return success


def perform_clean_shutdown(
    stream=None,
    audio_mgr=None,
    speech_engine=None,
    exit_code: int = 0,
    speak_farewell: bool = True,
    timeout_seconds: float = 6.0,
):
    """
    Orchestrates the complete, clean, idempotent shutdown sequence for JARVIS:
    1. Stops listening immediately (stops mic stream & clears STT buffers) to prevent self-transcription.
    2. Speaks 'Goodbye, Sir.' using Kokoro TTS and blocks until playback finishes.
    3. Releases all audio streams and PyAudio resources.
    4. Releases the single-instance lock file.
    5. Exits the process completely so it frees RAM.
    """
    global _SHUTDOWN_COMPLETED
    with _SHUTDOWN_LOCK:
        if _SHUTDOWN_COMPLETED:
            return
        _SHUTDOWN_COMPLETED = True

    # Use explicitly passed objects or fall back to registered handles
    target_stream = stream or _REGISTERED_STREAM
    target_audio_mgr = audio_mgr or _REGISTERED_AUDIO_MGR
    target_engine = speech_engine or _REGISTERED_SPEECH_ENGINE

    # 1. Stop microphone stream immediately
    _stop_microphone(stream=target_stream, speech_engine=target_engine)

    # 2. Vocalize goodbye if requested and not yet spoken
    if speak_farewell and not _GOODBYE_SPOKEN:
        speak_goodbye(
            timeout_seconds=timeout_seconds,
            stream=target_stream,
            speech_engine=target_engine,
        )

    print("[STATUS: SHUTDOWN | Systems offline]")
    print("=" * 60)

    # 3. Release audio resources
    if target_stream is not None:
        try:
            if hasattr(target_stream, "close"):
                target_stream.close()
        except Exception:
            pass

    if target_audio_mgr is not None:
        try:
            if hasattr(target_audio_mgr, "terminate"):
                target_audio_mgr.terminate()
        except Exception:
            pass

    try:
        from interfaces.speech import stop_speech, reset_speech_state
        stop_speech()
        reset_speech_state()
    except Exception:
        pass

    # 4. Release single-instance lock so Super+J or fresh launch succeeds immediately
    global _LOCK_RELEASE_CALLBACK
    if _LOCK_RELEASE_CALLBACK is not None:
        try:
            _LOCK_RELEASE_CALLBACK()
        except Exception:
            pass
    else:
        try:
            from jarvis import release_instance_lock
            release_instance_lock()
        except Exception:
            pass

    # 5. Flush stdio
    try:
        sys.stdout.flush()
        sys.stderr.flush()
    except Exception:
        pass

    # 6. Exit process (unless bypassed in unit tests)
    if not os.environ.get("JARVIS_TEST_MODE"):
        sys.exit(exit_code)
