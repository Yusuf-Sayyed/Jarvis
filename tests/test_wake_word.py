"""
Unit tests for wake-word extraction and session state timing.
"""

import time
import unittest
from core.wake_word import (
    SessionState,
    extract_wake_command,
    format_time_remaining,
)


class TestWakeWord(unittest.TestCase):

    def test_wake_word_extraction(self):
        has_wake, cmd = extract_wake_command("hey jarvis")
        self.assertTrue(has_wake)
        self.assertEqual(cmd, "")

        has_wake, cmd = extract_wake_command("hey jarvis open terminal")
        self.assertTrue(has_wake)
        self.assertEqual(cmd, "open terminal")

        has_wake, cmd = extract_wake_command("hello jarvis search google for linux")
        self.assertTrue(has_wake)
        self.assertEqual(cmd, "search google for linux")

        has_wake, cmd = extract_wake_command("open firefox")
        self.assertFalse(has_wake)
        self.assertEqual(cmd, "open firefox")

    def test_time_formatting(self):
        self.assertEqual(format_time_remaining(300), "5m 00s")
        self.assertEqual(format_time_remaining(272), "4m 32s")
        self.assertEqual(format_time_remaining(5), "0m 05s")
        self.assertEqual(format_time_remaining(0), "0m 00s")

    def test_session_state_lifecycle(self):
        session = SessionState(timeout_seconds=2)
        self.assertFalse(session.is_active)

        session.activate()
        self.assertTrue(session.is_active)
        self.assertFalse(session.is_expired())

        # Simulate time passing
        session.last_activity_time = time.time() - 3
        self.assertTrue(session.is_expired())

        session.deactivate()
        self.assertFalse(session.is_active)


if __name__ == "__main__":
    unittest.main()
