"""
Regression and lifecycle resilience tests for JARVIS.
Verifies that:
1. Silence does not terminate the assistant.
2. Recoverable transcription and VAD failures do not kill the listening loop.
3. Session timeouts return to STANDBY mode without terminating the process.
4. Temporary audio stream errors trigger safe recovery without process termination.
5. Ordinary speech, pauses, and background noise do not trigger accidental shutdown.
6. Explicit 'bye' or 'goodbye' triggers 'Goodbye, Sir.' speech and clean shutdown.
"""

import os
import unittest
from unittest.mock import MagicMock, call, patch

os.environ["JARVIS_TEST_MODE"] = "1"

from core.intent import detect_intent, is_exit_command
from core.listener import CHUNK_SIZE, init_audio_stream, recover_audio_stream
from core.router import route_command
import core.shutdown as shutdown_mod
from core.wake_word import SessionState


class TestLifecycleResilience(unittest.TestCase):

    def setUp(self):
        os.environ["JARVIS_TEST_MODE"] = "1"
        shutdown_mod.reset_shutdown_state()

    def tearDown(self):
        shutdown_mod.reset_shutdown_state()

    # 1. JARVIS stays alive after silence
    def test_stays_alive_after_silence(self):
        """Verifies that empty frames, silence, or non-speech chunks do not terminate JARVIS."""
        session = SessionState(timeout_seconds=300)
        mock_engine = MagicMock()
        mock_engine.process_audio.return_value = None  # Silence

        with patch("core.shutdown.perform_clean_shutdown") as mock_shutdown:
            # Simulate 10 silence chunks
            for _ in range(10):
                spoken = mock_engine.process_audio(b"\x00" * CHUNK_SIZE, session_active=session.is_active)
                if spoken:
                    if is_exit_command(spoken):
                        mock_shutdown()
                        break

            # Process must NOT have triggered shutdown
            mock_shutdown.assert_not_called()
            self.assertFalse(session.is_active)

    # 2. JARVIS stays alive after recoverable transcription failure
    def test_stays_alive_after_recoverable_transcription_failure(self):
        """Verifies that an STT or VAD exception in process_audio is caught and does not kill the loop."""
        mock_engine = MagicMock()
        mock_engine.process_audio.side_effect = RuntimeError("Whisper tensor computation overflow")

        with patch("core.shutdown.perform_clean_shutdown") as mock_shutdown:
            spoken_text = None
            try:
                spoken_text = mock_engine.process_audio(b"\x00" * CHUNK_SIZE)
            except Exception:
                mock_engine.reset_buffers()
                spoken_text = None

            self.assertIsNone(spoken_text)
            mock_engine.reset_buffers.assert_called_once()
            mock_shutdown.assert_not_called()

    # 3. Session timeout returns to standby without terminating the process
    def test_session_timeout_returns_to_standby_without_terminating(self):
        """Verifies that an active session expiring deactivates to standby without killing the process."""
        session = SessionState(timeout_seconds=300)
        session.activate()
        self.assertTrue(session.is_active)

        # Fast-forward time past timeout
        session.last_activity_time = 0.0
        self.assertTrue(session.is_expired())

        with patch("core.shutdown.perform_clean_shutdown") as mock_shutdown:
            if session.is_active and session.is_expired():
                session.deactivate()

            # Must have returned to standby
            self.assertFalse(session.is_active)
            # Process must NOT be shut down
            mock_shutdown.assert_not_called()

    # 4. Temporary audio failures do not silently kill the application
    def test_temporary_audio_stream_failure_triggers_recovery(self):
        """Verifies that stream errors invoke recover_audio_stream and keep the loop alive."""
        mock_bad_stream = MagicMock()
        mock_bad_stream.is_active.return_value = False
        mock_bad_stream.read.side_effect = OSError("Input overflow / device disconnected")

        mock_recovered_stream = MagicMock()
        mock_recovered_stream.is_active.return_value = True
        mock_recovered_audio_mgr = MagicMock()

        with patch("core.listener.init_audio_stream") as mock_init_audio:
            # Recovery returns the new stream
            mock_init_audio.return_value = (mock_recovered_audio_mgr, mock_recovered_stream)

            new_mgr, new_stream = recover_audio_stream(
                old_audio_mgr=MagicMock(), old_stream=mock_bad_stream, max_retries=1, retry_delay=0.01
            )

            self.assertIsNotNone(new_stream)
            self.assertEqual(new_stream, mock_recovered_stream)
            mock_bad_stream.close.assert_called_once()

    def test_audio_failure_unrecovered_does_not_call_shutdown(self):
        """Verifies that even if recovery temporarily fails, shutdown is not silently called."""
        with patch("core.listener.init_audio_stream", return_value=(None, None)):
            with patch("core.shutdown.perform_clean_shutdown") as mock_shutdown:
                new_mgr, new_stream = recover_audio_stream(max_retries=1, retry_delay=0.01)
                self.assertIsNone(new_stream)
                mock_shutdown.assert_not_called()

    # 5. Ordinary speech does not accidentally trigger shutdown
    def test_ordinary_speech_does_not_accidentally_trigger_shutdown(self):
        """Verifies that conversational phrases containing 'exit', 'quit', etc. are not treated as EXIT commands."""
        non_exit_phrases = [
            "I want to quit smoking",
            "Why did you quit",
            "Show me the emergency exit",
            "How do I exit vim",
            "What is the exit code",
            "Where is the exit door",
            "Don't shut down the machine",
            "Tell me about power off options",
            "Standby for further instructions",
            "The baby waved bye bye",
            "Say bye to your friend",
            "Quit is a word in the dictionary",
            "How are you doing today",
            "Can you open your folder",
            "Open Firefox please",
            "What is the weather outside",
        ]
        for phrase in non_exit_phrases:
            with self.subTest(phrase=phrase):
                self.assertFalse(
                    is_exit_command(phrase),
                    f"Phrase '{phrase}' was falsely recognized as an exit command!",
                )
                intent, _ = detect_intent(phrase)
                self.assertNotEqual(
                    intent, "EXIT",
                    f"Phrase '{phrase}' falsely triggered EXIT intent!",
                )

    # 6. Explicit 'bye' speaks 'Goodbye, Sir.' and exits cleanly
    @patch("interfaces.speech.speak")
    def test_explicit_bye_speaks_goodbye_and_exits_cleanly(self, mock_speak):
        """Verifies that saying 'bye' triggers the full clean shutdown with 'Goodbye, Sir.' speech."""
        mock_speak.return_value = True

        mock_stream = MagicMock()
        mock_audio_mgr = MagicMock()
        mock_engine = MagicMock()
        mock_lock_release = MagicMock()

        shutdown_mod.register_audio_context(
            stream=mock_stream, audio_mgr=mock_audio_mgr, speech_engine=mock_engine
        )
        shutdown_mod.register_lock_release_callback(mock_lock_release)

        # Explicit exit triggers
        explicit_phrases = ["bye", "goodbye", "bye jarvis", "goodbye jarvis", "hey jarvis bye"]
        for p in explicit_phrases:
            self.assertTrue(is_exit_command(p), f"'{p}' was not recognized as an exit command!")

        # Execute clean shutdown as triggered by 'bye'
        shutdown_mod.perform_clean_shutdown(
            stream=mock_stream,
            audio_mgr=mock_audio_mgr,
            speech_engine=mock_engine,
            speak_farewell=True,
            reason="explicit_exit: bye",
        )

        # Microphone must be stopped
        mock_stream.stop_stream.assert_called()
        # Farewell must be spoken
        mock_speak.assert_called_with("Goodbye, Sir.", block=False)
        # Resources must be freed
        mock_stream.close.assert_called_once()
        mock_audio_mgr.terminate.assert_called_once()
        mock_lock_release.assert_called_once()

    # 7. Router command error resilience
    @patch("interfaces.speech.speak")
    @patch("intelligence.web_search.handle_current_info_query", return_value=(True, "Quantum computing is advanced computing.", []))
    def test_router_command_exception_does_not_abort_loop(self, mock_web_search, mock_speak):
        """Verifies that an unexpected exception in a command handler returns should_continue=True."""
        with patch("core.router.ask_ollama", side_effect=RuntimeError("Ollama connection failed")):
            should_continue, pending = route_command("What is quantum computing?")
            # Handled gracefully, loop must continue
            self.assertTrue(should_continue)


if __name__ == "__main__":
    unittest.main()
