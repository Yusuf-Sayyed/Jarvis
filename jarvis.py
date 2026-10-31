"""
JARVIS - Advanced Voice Assistant for Fedora KDE Linux
Main entry point coordinating listener, session state, and command routing.
"""

import fcntl
import json
import os
import signal
import sys
import time
from actions.audio import get_volume_status
from core.config import EXIT_COMMANDS
from core.diagnostics import configure_diagnostics_logging, logger
from core.intent import is_exit_command, normalize_spoken_text
from core.listener import (
    CHUNK_SIZE,
    check_microphone_status,
    init_audio_stream,
    init_speech_engine,
    recover_audio_stream,
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
from core.shutdown import (
    perform_clean_shutdown,
    register_audio_context,
    register_lock_release_callback,
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

    register_lock_release_callback(release_instance_lock)
    configure_diagnostics_logging()
    logger.debug("[Lifecycle] JARVIS starting up (PID=%d)...", os.getpid())

    def _handle_termination_signal(signum, frame):
        sig_name = signal.Signals(signum).name if hasattr(signal, "Signals") else str(signum)
        logger.debug("[Lifecycle] Termination signal received (%s). Shutting down cleanly.", sig_name)
        perform_clean_shutdown(
            stream if "stream" in locals() else None,
            audio_mgr if "audio_mgr" in locals() else None,
            speech_engine if "speech_engine" in locals() else None,
            speak_farewell=False,
            reason=f"signal_{sig_name}",
        )

    try:
        signal.signal(signal.SIGTERM, _handle_termination_signal)
    except Exception:
        pass

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
    register_audio_context(stream=stream, audio_mgr=audio_mgr, speech_engine=speech_engine)

    print_standby_status()
    logger.debug("[Lifecycle] Entering STANDBY mode. Waiting for wake word or double clap.")

    # 4. Perform startup greeting (spoken once per desktop login session)
    perform_startup_greeting(stream, speech_engine)

    # 5. Initialize wake-word session state and acoustic clap detector
    session = SessionState()
    clap_detector = ClapDetector()

    try:
        while True:
            # Check 5-minute inactivity timeout
            if session.is_active and session.is_expired():
                logger.debug(
                    "[Lifecycle] Active session timed out after %ds of inactivity. Transitioning to STANDBY.",
                    session.timeout_seconds,
                )
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
                    if stream is not None and stream.is_active():
                        stream.read(CHUNK_SIZE, exception_on_overflow=False)
                except Exception:
                    pass
                speech_engine.reset_buffers()
                continue

            # Safe audio reading with automated stream recovery
            data = None
            try:
                if stream is not None and hasattr(stream, "is_active") and stream.is_active():
                    data = stream.read(CHUNK_SIZE, exception_on_overflow=False)
                else:
                    raise OSError("Microphone stream is inactive or unavailable")
            except (IOError, OSError) as e:
                logger.debug("[Audio] Microphone read error: %s. Attempting stream recovery...", e)
                print(f"\n[JARVIS Warning] Microphone stream interrupted ({e}). Attempting recovery...")
                new_audio_mgr, new_stream = recover_audio_stream(
                    old_audio_mgr=audio_mgr, old_stream=stream, max_retries=3, retry_delay=0.5
                )
                if new_stream is not None and new_audio_mgr is not None:
                    audio_mgr = new_audio_mgr
                    stream = new_stream
                    register_audio_context(stream=stream, audio_mgr=audio_mgr, speech_engine=speech_engine)
                    logger.debug("[Audio] Microphone stream recovered successfully.")
                    print("[JARVIS] Microphone stream reconnected.")
                    continue
                else:
                    logger.debug("[Audio] Stream recovery failed. Retrying in next cycle...")
                    time.sleep(1.0)
                    continue
            except Exception as e:
                logger.debug("[Audio] Unexpected audio error: %s. Attempting stream recovery...", e)
                print(f"\n[JARVIS Warning] Audio stream error ({e}). Attempting recovery...")
                new_audio_mgr, new_stream = recover_audio_stream(
                    old_audio_mgr=audio_mgr, old_stream=stream, max_retries=3, retry_delay=0.5
                )
                if new_stream is not None and new_audio_mgr is not None:
                    audio_mgr = new_audio_mgr
                    stream = new_stream
                    register_audio_context(stream=stream, audio_mgr=audio_mgr, speech_engine=speech_engine)
                    logger.debug("[Audio] Microphone stream recovered successfully.")
                    print("[JARVIS] Microphone stream reconnected.")
                    continue
                else:
                    time.sleep(1.0)
                    continue

            if data is None or len(data) == 0:
                continue

            # In STANDBY mode, check for hands-free two-clap wake trigger
            if not session.is_active:
                if clap_detector.process_chunk(data):
                    session.activate()
                    logger.debug(
                        "[Lifecycle] Entering ACTIVE session via two-clap trigger (timeout=%ds).",
                        session.timeout_seconds,
                    )
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
            try:
                spoken_text = speech_engine.process_audio(
                    data, session_active=session.is_active, time_remaining_str=rem_str
                )
            except Exception as e:
                logger.debug("[STT] Error processing audio frame: %s. Continuing listening loop.", e)
                speech_engine.reset_buffers()
                spoken_text = None

            if spoken_text:
                print("\033[2K\r", end="", flush=True)

                # Global explicit exit commands (e.g. "bye", "goodbye", "quit jarvis", "exit")
                if is_exit_command(spoken_text):
                    logger.debug("[Lifecycle] Explicit exit phrase received ('%s'). Performing clean shutdown.", spoken_text)
                    print(f"\n[Heard] \"{spoken_text}\"")
                    print("[Intent: EXIT]")
                    perform_clean_shutdown(
                        stream,
                        audio_mgr,
                        speech_engine,
                        speak_farewell=True,
                        reason=f"explicit_exit: {spoken_text}",
                    )
                    break

                has_wake, remaining_command = extract_wake_command(spoken_text)

                if not session.is_active:
                    # --- STANDBY MODE ---
                    if has_wake:
                        session.activate()
                        logger.debug(
                            "[Lifecycle] Entering ACTIVE session via wake-word trigger (timeout=%ds).",
                            session.timeout_seconds,
                        )
                        if remaining_command:
                            session.mark_greeted()
                            print("\n" + "=" * 60)
                            print("[ACTIVE] Active session started (5 minutes).")
                            print("         Listening for commands or questions without the wake word.")
                            print("=" * 60)
                            print(f"\n[Heard] \"{remaining_command}\"")
                            try:
                                should_continue, session.pending_action = route_command(
                                    remaining_command, session.pending_action
                                )
                            except Exception as e:
                                logger.debug(
                                    "[Router] Error executing inline command '%s': %s",
                                    remaining_command,
                                    e,
                                    exc_info=True,
                                )
                                print(f"\n[JARVIS Error] An error occurred while processing your request: {e}\n")
                                should_continue = True

                            drain_audio_stream(stream)
                            speech_engine.reset_buffers()
                            if not should_continue:
                                perform_clean_shutdown(
                                    stream,
                                    audio_mgr,
                                    speech_engine,
                                    speak_farewell=True,
                                    reason="command_exit",
                                )
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
                        logger.debug("[Lifecycle] Utterance ignored in STANDBY (no wake word): '%s'", spoken_text)
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
                    try:
                        should_continue, session.pending_action = route_command(
                            cmd_to_run, session.pending_action
                        )
                    except Exception as e:
                        logger.debug(
                            "[Router] Error executing command '%s': %s",
                            cmd_to_run,
                            e,
                            exc_info=True,
                        )
                        print(f"\n[JARVIS Error] An error occurred while processing your request: {e}\n")
                        should_continue = True

                    drain_audio_stream(stream)
                    speech_engine.reset_buffers()
                    if not should_continue:
                        perform_clean_shutdown(
                            stream,
                            audio_mgr,
                            speech_engine,
                            speak_farewell=True,
                            reason="command_exit",
                        )
                        break
                    session.reset_timer()
                    remaining_str = format_time_remaining(session.remaining_seconds())
                    print(f"[ACTIVE | {remaining_str} remaining]")
                    print("-" * 60)

    except KeyboardInterrupt:
        logger.debug("[Lifecycle] Listening loop stopped by user (KeyboardInterrupt / Ctrl+C).")
        print("\n[JARVIS] Stopped by user (Ctrl+C). Goodbye, Sir!")
        perform_clean_shutdown(
            stream if "stream" in locals() else None,
            audio_mgr if "audio_mgr" in locals() else None,
            speech_engine if "speech_engine" in locals() else None,
            speak_farewell=False,
            reason="keyboard_interrupt",
        )
    except Exception as e:
        logger.debug("[Lifecycle] Listening loop stopped by unhandled exception: %s", e, exc_info=True)
        print(f"\n[JARVIS Error] Listening loop encountered an unexpected error: {e}")
        perform_clean_shutdown(
            stream if "stream" in locals() else None,
            audio_mgr if "audio_mgr" in locals() else None,
            speech_engine if "speech_engine" in locals() else None,
            exit_code=1,
            speak_farewell=False,
            reason=f"unhandled_exception: {e}",
        )
    finally:
        perform_clean_shutdown(
            stream if "stream" in locals() else None,
            audio_mgr if "audio_mgr" in locals() else None,
            speech_engine if "speech_engine" in locals() else None,
            speak_farewell=False,
            reason="finally_block",
        )


if __name__ == "__main__":
    main()
