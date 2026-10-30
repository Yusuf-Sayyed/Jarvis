"""
Unit tests for JARVIS clean shutdown, goodbye voice response,
microphone capture prevention, and single-execution idempotency.
"""

import os
import unittest
from unittest.mock import MagicMock, call, patch

import core.shutdown as shutdown_mod
from core.intent import detect_intent
from core.router import route_command


class TestShutdown(unittest.TestCase):

    def setUp(self):
        os.environ["JARVIS_TEST_MODE"] = "1"
        shutdown_mod.reset_shutdown_state()

    def tearDown(self):
        shutdown_mod.reset_shutdown_state()

    def test_exit_intent_recognition(self):
        """Verifies that all supported exit phrases correctly extract to EXIT intent."""
        exit_phrases = [
            "bye",
            "goodbye",
            "bye jarvis",
            "goodbye jarvis",
            "exit",
            "quit",
            "stop jarvis",
            "see ya",
            "cya",
            "see you later",
            "go to sleep",
            "shut down",
            "shutdown",
            "power down",
            "power off",
            "alright bye",
            "bye for now",
        ]
        for phrase in exit_phrases:
            with self.subTest(phrase=phrase):
                intent, params = detect_intent(phrase)
                self.assertEqual(intent, "EXIT", f"Failed for phrase: '{phrase}'")

    @patch("interfaces.speech.speak")
    def test_speak_goodbye_speaks_and_is_idempotent(self, mock_speak):
        """Verifies that speak_goodbye speaks 'Goodbye, Sir.' and runs only once."""
        mock_speak.return_value = True

        res1 = shutdown_mod.speak_goodbye()
        self.assertTrue(res1)
        self.assertEqual(mock_speak.call_count, 1)
        mock_speak.assert_called_with("Goodbye, Sir.", block=False)

        # Second call must be a no-op (idempotent)
        res2 = shutdown_mod.speak_goodbye()
        self.assertTrue(res2)
        self.assertEqual(mock_speak.call_count, 1)

    @patch("interfaces.speech.speak")
    def test_microphone_stopped_before_goodbye_speech(self, mock_speak):
        """Verifies that the microphone input stream is stopped before goodbye speech occurs."""
        mock_stream = MagicMock()
        mock_stream.is_active.return_value = True
        mock_engine = MagicMock()

        shutdown_mod.register_audio_context(
            stream=mock_stream, speech_engine=mock_engine
        )

        call_order = []
        mock_stream.stop_stream.side_effect = lambda: call_order.append("stop_mic")
        mock_engine.reset_buffers.side_effect = lambda: call_order.append("reset_buffers")
        mock_speak.side_effect = lambda text, block=True: call_order.append("speak")

        shutdown_mod.speak_goodbye(stream=mock_stream, speech_engine=mock_engine)

        self.assertIn("stop_mic", call_order)
        self.assertIn("reset_buffers", call_order)
        self.assertIn("speak", call_order)
        # Verify microphone was stopped before speech was called
        self.assertLess(call_order.index("stop_mic"), call_order.index("speak"))
        self.assertLess(call_order.index("reset_buffers"), call_order.index("speak"))

    @patch("core.shutdown.speak_goodbye")
    def test_router_exit_invokes_speak_goodbye(self, mock_goodbye):
        """Verifies that route_command with EXIT intent calls speak_goodbye and halts loop."""
        mock_goodbye.return_value = True
        should_continue, pending = route_command("bye")
        self.assertFalse(should_continue)
        self.assertIsNone(pending)
        mock_goodbye.assert_called_once()

    @patch("interfaces.speech.speak")
    def test_perform_clean_shutdown_releases_resources_and_is_idempotent(self, mock_speak):
        """Verifies clean shutdown tears down stream, PyAudio, lock, and is idempotent."""
        mock_stream = MagicMock()
        mock_stream.is_active.return_value = True
        mock_audio_mgr = MagicMock()
        mock_engine = MagicMock()
        mock_lock_release = MagicMock()

        shutdown_mod.register_audio_context(
            stream=mock_stream, audio_mgr=mock_audio_mgr, speech_engine=mock_engine
        )
        shutdown_mod.register_lock_release_callback(mock_lock_release)

        # First shutdown invocation
        shutdown_mod.perform_clean_shutdown(speak_farewell=True)

        mock_stream.stop_stream.assert_called()
        mock_stream.close.assert_called_once()
        mock_audio_mgr.terminate.assert_called_once()
        mock_engine.reset_buffers.assert_called()
        mock_lock_release.assert_called_once()

        # Second shutdown invocation (e.g. from finally: block or SIGINT)
        shutdown_mod.perform_clean_shutdown(speak_farewell=True)
        # Calls should still only be 1
        self.assertEqual(mock_stream.close.call_count, 1)
        self.assertEqual(mock_audio_mgr.terminate.call_count, 1)
        self.assertEqual(mock_lock_release.call_count, 1)

    @patch("interfaces.speech.speak")
    def test_tts_failure_does_not_hang_shutdown(self, mock_speak):
        """Verifies that if TTS throws an exception, shutdown completes safely."""
        mock_speak.side_effect = RuntimeError("Audio hardware unavailable")

        mock_stream = MagicMock()
        mock_audio_mgr = MagicMock()
        mock_lock_release = MagicMock()

        shutdown_mod.register_lock_release_callback(mock_lock_release)

        # Should not raise exception and should complete resource release
        shutdown_mod.perform_clean_shutdown(
            stream=mock_stream, audio_mgr=mock_audio_mgr, speak_farewell=True
        )

        mock_stream.close.assert_called_once()
        mock_audio_mgr.terminate.assert_called_once()
        mock_lock_release.assert_called_once()


if __name__ == "__main__":
    unittest.main()
