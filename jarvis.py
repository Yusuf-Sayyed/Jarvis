"""
JARVIS - Advanced Voice Assistant for Fedora KDE Linux
Main entry point coordinating listener, session state, and command routing.
"""

import fcntl
import json
import os
import sys
import time
from actions.audio import get_volume_status
from core.config import EXIT_COMMANDS
from core.intent import normalize_spoken_text
from core.listener import (
    CHUNK_SIZE,
    check_microphone_status,
    init_audio_stream,
    init_speech_engine,
)
from core.clap_detector import ClapDetector
from core.router import route_command
from core.wake_word import (
    SessionState,
    extract_wake_command,
    format_time_remaining,
    get_activation_greeting,
    get_startup_greeting,
    has_greeted_this_login_session,
    mark_greeted_this_login_session,
)
from interfaces.speech import speak

_LOCK_FILE_OBJ = None


def acquire_instance_lock() -> bool:
    """
    Ensures only a single instance of JARVIS runs per user session.
    Uses an exclusive non-blocking flock on $XDG_RUNTIME_DIR/jarvis.lock.
    """
    global _LOCK_FILE_OBJ
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        lock_path = os.path.join(runtime_dir, "jarvis.lock")
    else:
        lock_path = f"/tmp/jarvis_{os.getuid()}.lock"

    try:
        f = open(lock_path, "w")
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.write(f"{os.getpid()}\n")
        f.flush()
        _LOCK_FILE_OBJ = f
        return True
    except (IOError, OSError):
        return False


def release_instance_lock():
    """Releases the instance lock file upon shutdown."""
    global _LOCK_FILE_OBJ
    if _LOCK_FILE_OBJ:
        try:
            fcntl.flock(_LOCK_FILE_OBJ, fcntl.LOCK_UN)
            _LOCK_FILE_OBJ.close()
        except Exception:
            pass
        _LOCK_FILE_OBJ = None


def wait_for_audio_readiness(timeout_seconds: float = 6.0) -> bool:
    """
    Waits for PipeWire/WirePlumber and default audio sink to become ready.
    Returns True if audio is ready, False if timed out.
    """
    start = time.time()
    while time.time() - start < timeout_seconds:
        try:
            vol, _, _ = get_volume_status()
            if vol is not None:
                return True
        except Exception:
            pass
        time.sleep(0.4)
    return False


def perform_startup_greeting(stream, speech_engine, force: bool = False):
    """
    Delivers a Tony Stark-style startup greeting once per desktop login session,
    waiting for audio system readiness and draining microphone buffers to avoid self-transcription.
    """
    if not force and has_greeted_this_login_session():
        print("[JARVIS] Startup greeting already delivered for this desktop session. Standing by.")
        return

    # Wait for audio readiness (PipeWire / WirePlumber default sink)
    audio_ready = wait_for_audio_readiness(timeout_seconds=5.0)
    if not audio_ready:
        print("[JARVIS] Audio readiness check timed out. Proceeding with greeting attempt.")

    greeting = get_startup_greeting()
    print(f"\n[JARVIS] {greeting}")

    # Mark as greeted for this desktop session BEFORE speaking (persisted in $XDG_RUNTIME_DIR)
    mark_greeted_this_login_session()

    try:
        speak(greeting, block=True)
    except Exception as e:
        print(f"[JARVIS] Startup greeting speech notice: {e}")

    # Clean microphone buffer to prevent self-transcription
    if stream:
        drain_audio_stream(stream)
    if speech_engine:
        speech_engine.reset_buffers()


def print_banner():
    print("=" * 60)
    print("   JARVIS - Advanced Linux Voice Assistant")
    print("=" * 60)


def print_standby_status():
    print("\n" + "=" * 60)
    print("   STATUS: STANDBY MODE")
    print("   Say 'Hey JARVIS' to activate a 5-minute session.")
    print("   Available in active session:")
    print("     - Searches: 'Search Google for...', 'Search YouTube for...'")
    print("     - YouTube:  'Play [title] on YouTube', 'Play a video on YouTube'")
    print("     - Typing:   'Type [text]', 'Type [text] and press Enter'")
    print("     - Browser:  'Open a new tab', 'Switch to next tab',")
    print("                 'Go back', 'Go forward', 'Refresh the page',")
    print("                 'Close the current tab' (confirms first)")
    print("     - Apps:     'Open Firefox', 'Open Terminal', 'Open Downloads'")
    print("     - Questions: Any question answered locally via Ollama")
    print("   Say 'exit jarvis' or press Ctrl+C to quit at any time.")
    print("=" * 60 + "\n")


def drain_audio_stream(stream):
    """Flushes buffered audio frames from the PyAudio stream to eliminate acoustic echo."""
    try:
        available = stream.get_read_available()
        if available > 0:
            stream.read(available, exception_on_overflow=False)
    except Exception:
        pass


def main():
    if not acquire_instance_lock():
        print("[JARVIS] Another instance is already running. Exiting cleanly to avoid duplicate listeners.")
        sys.exit(0)

    if "--test-greeting" in sys.argv:
        print("[JARVIS] Testing startup greeting...")
        audio_mgr, stream = init_audio_stream()
        speech_engine = init_speech_engine()
        try:
            perform_startup_greeting(stream, speech_engine, force=True)
        finally:
            try:
                stream.stop_stream()
                stream.close()
            except Exception:
                pass
            audio_mgr.terminate()
            release_instance_lock()
        sys.exit(0)

    print_banner()

    # 1. Initialize speech recognition engine (Whisper with VAD, or Vosk fallback)
    speech_engine = init_speech_engine()

    # 2. Check microphone mute status
    check_microphone_status()

    # 3. Open PyAudio audio stream
    audio_mgr, stream = init_audio_stream()

    print_standby_status()

    # 4. Perform startup greeting (spoken once per desktop login session)
    perform_startup_greeting(stream, speech_engine)

    # 5. Initialize wake-word session state and acoustic clap detector
    session = SessionState()
    clap_detector = ClapDetector()

    try:
        while True:
            # Check 5-minute inactivity timeout
            if session.is_active and session.is_expired():
                session.deactivate()
                clap_detector.reset()
                print("\033[2K\r", end="", flush=True)
                print("\n" + "=" * 60)
                print("[STANDBY] 5-minute session expired due to inactivity.")
                print("          Say 'Hey JARVIS' or clap twice to wake me.")
                print("=" * 60 + "\n")

            from interfaces.speech import should_mute_mic
            if should_mute_mic():
                try:
                    stream.read(CHUNK_SIZE, exception_on_overflow=False)
                except Exception:
                    pass
                speech_engine.reset_buffers()
                continue

            try:
                data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
            except (IOError, OSError):
                continue

            if len(data) == 0:
                continue

            # In STANDBY mode, check for hands-free two-clap wake trigger
            if not session.is_active:
                if clap_detector.process_chunk(data):
                    session.activate()
                    greeting = get_activation_greeting()
                    session.mark_greeted()
                    print("\033[2K\r", end="", flush=True)
                    print("\n" + "=" * 60)
                    print(f'[ACTIVE] Two claps detected! "{greeting}" (5 minutes remaining)')
                    print("         Listening for commands or questions without the wake word.")
                    print("=" * 60)
                    speak(greeting, block=True)
                    drain_audio_stream(stream)
                    speech_engine.reset_buffers()
                    session.reset_timer()
                    remaining_str = format_time_remaining(session.remaining_seconds())
                    print(f"[ACTIVE | {remaining_str} remaining]")
                    print("-" * 60)
                    continue

            rem_str = format_time_remaining(session.remaining_seconds()) if session.is_active else ""
            spoken_text = speech_engine.process_audio(
                data, session_active=session.is_active, time_remaining_str=rem_str
            )

            if spoken_text:
                print("\033[2K\r", end="", flush=True)

                # Global exit commands
                clean = normalize_spoken_text(spoken_text)
                if any(clean == cmd or clean.startswith(cmd) for cmd in EXIT_COMMANDS):
                    print(f"\n[Heard] \"{spoken_text}\"")
                    print("[Intent: EXIT]")
                    print("[JARVIS] Goodbye, Sir. Systems powering down.")
                    print("[STATUS: SHUTDOWN | Systems offline]")
                    print("=" * 60)
                    break

                has_wake, remaining_command = extract_wake_command(spoken_text)

                if not session.is_active:
                    # --- STANDBY MODE ---
                    if has_wake:
                        session.activate()
                        if remaining_command:
                            session.mark_greeted()
                            print("\n" + "=" * 60)
                            print("[ACTIVE] Active session started (5 minutes).")
                            print("         Listening for commands or questions without the wake word.")
                            print("=" * 60)
                            print(f"\n[Heard] \"{remaining_command}\"")
                            should_continue, session.pending_action = route_command(
                                remaining_command, session.pending_action
                            )
                            drain_audio_stream(stream)
                            speech_engine.reset_buffers()
                            if not should_continue:
                                print("[STATUS: SHUTDOWN | Systems offline]")
                                print("=" * 60)
                                break
                            session.reset_timer()
                            remaining_str = format_time_remaining(session.remaining_seconds())
                            print(f"[ACTIVE | {remaining_str} remaining]")
                            print("-" * 60)
                        else:
                            greeting = get_activation_greeting()
                            session.mark_greeted()
                            print("\n" + "=" * 60)
                            print(f'[ACTIVE] "{greeting}" (Active session started, 5 minutes)')
                            print("         Listening for commands or questions without the wake word.")
                            print("=" * 60)
                            speak(greeting, block=True)
                            drain_audio_stream(stream)
                            speech_engine.reset_buffers()
                            session.reset_timer()
                            remaining_str = format_time_remaining(session.remaining_seconds())
                            print(f"[ACTIVE | {remaining_str} remaining]")
                            print("-" * 60)
                    else:
                        print(f"[STANDBY] Heard \"{spoken_text}\" (Standing by. Say 'Hey JARVIS' or clap twice to wake me).")

                else:
                    # --- ACTIVE MODE ---
                    cmd_to_run = remaining_command if has_wake else spoken_text

                    if not cmd_to_run and has_wake:
                        session.reset_timer()
                        print(f"\n[ACTIVE] Timer reset. 5 minutes remaining, Sir.")
                        print("-" * 60)
                        continue

                    print(f"\n[Heard] \"{cmd_to_run}\"")
                    should_continue, session.pending_action = route_command(
                        cmd_to_run, session.pending_action
                    )
                    drain_audio_stream(stream)
                    speech_engine.reset_buffers()
                    if not should_continue:
                        print("[STATUS: SHUTDOWN | Systems offline]")
                        print("=" * 60)
                        break
                    session.reset_timer()
                    remaining_str = format_time_remaining(session.remaining_seconds())
                    print(f"[ACTIVE | {remaining_str} remaining]")
                    print("-" * 60)

    except KeyboardInterrupt:
        print("\n[JARVIS] Stopped by user (Ctrl+C). Goodbye, Sir!")
    finally:
        try:
            if "stream" in locals() and stream is not None:
                stream.stop_stream()
                stream.close()
        except Exception:
            pass
        try:
            if "audio_mgr" in locals() and audio_mgr is not None:
                audio_mgr.terminate()
        except Exception:
            pass
        release_instance_lock()


if __name__ == "__main__":
    main()
