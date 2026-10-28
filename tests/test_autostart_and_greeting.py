"""
Unit tests for JARVIS automatic startup, instance locking, and Tony Stark-style greeting.
"""

import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from core.wake_word import (
    clear_login_session_greeting,
    get_startup_greeting,
    has_greeted_this_login_session,
    mark_greeted_this_login_session,
)
from jarvis import (
    acquire_instance_lock,
    perform_startup_greeting,
    release_instance_lock,
    wait_for_audio_readiness,
)


class TestStartupGreeting(unittest.TestCase):
    def test_time_based_greetings(self):
        # Morning: 5am - 11am
        for hour in (5, 8, 11):
            greeting = get_startup_greeting(hour)
            self.assertIn("Good morning, Sir", greeting)
            self.assertIn("Systems are online", greeting)

        # Afternoon: 12pm - 4pm
        for hour in (12, 14, 16):
            greeting = get_startup_greeting(hour)
            self.assertIn("Good afternoon, Sir", greeting)
            self.assertIn("Systems are online", greeting)

        # Evening: 5pm - 9pm
        for hour in (17, 19, 21):
            greeting = get_startup_greeting(hour)
            self.assertIn("Good evening, Sir", greeting)
            self.assertIn("Systems are online", greeting)

        # Late Night: 10pm - 4am
        for hour in (22, 23, 0, 2, 4):
            greeting = get_startup_greeting(hour)
            self.assertIn("Good evening, Sir", greeting)
            self.assertIn("Working late", greeting)
            self.assertIn("Systems are online", greeting)

    def test_default_greeting_without_argument(self):
        greeting = get_startup_greeting()
        self.assertIsInstance(greeting, str)
        self.assertIn("Sir", greeting)
        self.assertIn("Systems are online", greeting)


class TestLoginSessionMarker(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_xdg = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp_dir.name

    def tearDown(self):
        if self.orig_xdg is not None:
            os.environ["XDG_RUNTIME_DIR"] = self.orig_xdg
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        self.tmp_dir.cleanup()

    def test_marker_lifecycle(self):
        clear_login_session_greeting()
        self.assertFalse(has_greeted_this_login_session())

        mark_greeted_this_login_session()
        self.assertTrue(has_greeted_this_login_session())

        # Calling mark again is idempotent
        mark_greeted_this_login_session()
        self.assertTrue(has_greeted_this_login_session())

        clear_login_session_greeting()
        self.assertFalse(has_greeted_this_login_session())


class TestAudioReadiness(unittest.TestCase):
    @patch("jarvis.get_volume_status")
    def test_audio_readiness_immediate_success(self, mock_vol):
        mock_vol.return_value = (0.75, False, "75%")
        ready = wait_for_audio_readiness(timeout_seconds=1.0)
        self.assertTrue(ready)

    @patch("jarvis.get_volume_status")
    def test_audio_readiness_timeout(self, mock_vol):
        mock_vol.return_value = (None, False, "device unavailable")
        ready = wait_for_audio_readiness(timeout_seconds=0.3)
        self.assertFalse(ready)


class TestInstanceLocking(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_xdg = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp_dir.name
        release_instance_lock()

    def tearDown(self):
        release_instance_lock()
        if self.orig_xdg is not None:
            os.environ["XDG_RUNTIME_DIR"] = self.orig_xdg
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        self.tmp_dir.cleanup()

    def test_acquire_and_release_lock(self):
        first_lock = acquire_instance_lock()
        self.assertTrue(first_lock)

        # Re-acquiring in same process holding lock succeeds (or fails if separate open)
        # Verify lock file was created
        lock_file = os.path.join(self.tmp_dir.name, "jarvis.lock")
        self.assertTrue(os.path.exists(lock_file))

        release_instance_lock()
        # After release, acquire again
        second_lock = acquire_instance_lock()
        self.assertTrue(second_lock)
        release_instance_lock()


class TestPerformStartupGreeting(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.orig_xdg = os.environ.get("XDG_RUNTIME_DIR")
        os.environ["XDG_RUNTIME_DIR"] = self.tmp_dir.name
        clear_login_session_greeting()

    def tearDown(self):
        clear_login_session_greeting()
        if self.orig_xdg is not None:
            os.environ["XDG_RUNTIME_DIR"] = self.orig_xdg
        else:
            os.environ.pop("XDG_RUNTIME_DIR", None)
        self.tmp_dir.cleanup()

    @patch("jarvis.speak")
    @patch("jarvis.wait_for_audio_readiness", return_value=True)
    def test_greeting_speaks_once_per_session(self, mock_audio, mock_speak):
        stream = MagicMock()
        stream.get_read_available.return_value = 0
        speech_engine = MagicMock()

        # First run: should speak
        perform_startup_greeting(stream, speech_engine, force=False)
        self.assertEqual(mock_speak.call_count, 1)
        self.assertTrue(has_greeted_this_login_session())
        speech_engine.reset_buffers.assert_called_once()

        # Second run (service restart in same session): should NOT speak
        mock_speak.reset_mock()
        perform_startup_greeting(stream, speech_engine, force=False)
        mock_speak.assert_not_called()

        # Forced run: should speak even if session already greeted
        perform_startup_greeting(stream, speech_engine, force=True)
        self.assertEqual(mock_speak.call_count, 1)

    @patch("jarvis.speak", side_effect=RuntimeError("TTS failure"))
    @patch("jarvis.wait_for_audio_readiness", return_value=True)
    def test_greeting_handles_speech_error_gracefully(self, mock_audio, mock_speak):
        stream = MagicMock()
        stream.get_read_available.return_value = 0
        speech_engine = MagicMock()

        # Should not raise exception
        perform_startup_greeting(stream, speech_engine, force=True)
        self.assertTrue(has_greeted_this_login_session())


if __name__ == "__main__":
    unittest.main()
