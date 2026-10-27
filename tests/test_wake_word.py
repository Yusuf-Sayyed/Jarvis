"""
Unit tests for multiple wake triggers, Whisper normalization,
conservative direct command matching, greeting rotation, and session lifecycle.
"""

import time
import unittest
from core.wake_word import (
    SessionState,
    extract_wake_command,
    format_time_remaining,
    get_activation_greeting,
    is_direct_wake_up_command,
    normalize_wake_text,
    reset_greeting_state,
)


class TestWakeWord(unittest.TestCase):

    def setUp(self):
        reset_greeting_state()

    def test_multi_wake_triggers(self):
        """Verify all supported voice wake triggers activate properly."""
        triggers = [
            ("hey jarvis", ""),
            ("Hey JARVIS", ""),
            ("wake up jarvis", ""),
            ("Wake up, JARVIS", ""),
            ("Wake up, Jarvis!", ""),
            ("hello jarvis", ""),
            ("Hello JARVIS", ""),
            ("jarvis", ""),
            ("Jarvis:", ""),
            ("hey jarvis open terminal", "open terminal"),
            ("wake up jarvis what time is it", "what time is it"),
            ("Wake up, Jarvis, check my email", "check my email"),
            ("hello jarvis search google for linux", "search google for linux"),
            ("pause the video, hey jarvis", "pause the video"),
        ]
        for phrase, expected_cmd in triggers:
            has_wake, cmd = extract_wake_command(phrase)
            self.assertTrue(has_wake, f"Failed to match wake trigger: '{phrase}'")
            self.assertEqual(cmd.lower(), expected_cmd.lower(), f"Unexpected remaining command for: '{phrase}'")

    def test_whisper_phonetic_normalization(self):
        """Whisper spelling variations of JARVIS should be recognized safely."""
        variants = [
            ("hey j.a.r.v.i.s.", ""),
            ("hello jarvice", ""),
            ("wake up, jarves", ""),
            ("hey jervis open browser", "open browser"),
        ]
        for phrase, expected_cmd in variants:
            has_wake, cmd = extract_wake_command(phrase)
            self.assertTrue(has_wake, f"Failed variant: '{phrase}'")
            self.assertEqual(cmd.lower(), expected_cmd.lower())

    def test_direct_wake_up_imperative(self):
        """'Wake up' alone activates only when used as a direct imperative command."""
        valid_commands = [
            ("wake up", ""),
            ("Wake up!", ""),
            ("wake up.", ""),
            ("wake up now", ""),
            ("wake up please", ""),
            ("wake up, sir", ""),
            ("Wake up, open terminal", "open terminal"),
            ("wake up and tell me the time", "tell me the time"),
            ("Wake up, what day is today?", "what day is today?"),
        ]
        for phrase, expected_cmd in valid_commands:
            has_wake, cmd = extract_wake_command(phrase)
            self.assertTrue(has_wake, f"Failed direct imperative: '{phrase}'")
            self.assertEqual(cmd.lower(), expected_cmd.lower())

    def test_wake_up_false_positive_protection(self):
        """Conversational phrases containing 'wake up' must NOT trigger activation."""
        false_positives = [
            "I had to wake up early today",
            "did you wake up on time",
            "when you wake up we will go",
            "don't wake up the baby",
            "please don't wake up",
            "it is a wake up call",
            "wake up to reality",
            "wake up early tomorrow",
            "I will wake up at seven",
            "she didn't wake up",
            "wake up call for the team",
        ]
        for phrase in false_positives:
            has_wake, _ = extract_wake_command(phrase)
            self.assertFalse(has_wake, f"False positive triggered for conversational sentence: '{phrase}'")

    def test_unrelated_sentences_do_not_trigger(self):
        """General speech without wake triggers must not activate."""
        sentences = [
            "open firefox",
            "what time is it right now",
            "harvest the vegetables",
            "call customer service",
            "meet me in Paris",
            "Travis is a developer",
        ]
        for phrase in sentences:
            has_wake, _ = extract_wake_command(phrase)
            self.assertFalse(has_wake, f"False positive for unrelated phrase: '{phrase}'")

    def test_activation_greeting_rotation(self):
        """Activation greetings rotate through the pool without consecutive repeats."""
        greetings_seen = []
        for _ in range(8):
            g = get_activation_greeting()
            self.assertTrue(len(g) > 5)
            self.assertIn("Sir", g)
            greetings_seen.append(g)

        # Check no two consecutive greetings are identical
        for i in range(len(greetings_seen) - 1):
            self.assertNotEqual(greetings_seen[i], greetings_seen[i + 1])

    def test_session_state_and_greeting_once_rule(self):
        """SessionState ensures greeting is delivered only once per activation."""
        session = SessionState(timeout_seconds=300)
        self.assertFalse(session.is_active)
        self.assertFalse(session.should_greet())

        # 1. Activation: should_greet becomes True
        session.activate()
        self.assertTrue(session.is_active)
        self.assertTrue(session.should_greet())

        # 2. After greeting is marked: should_greet becomes False
        session.mark_greeted()
        self.assertFalse(session.should_greet())

        # 3. Repeated wake phrase during active session: should_greet remains False
        session.reset_timer()
        self.assertFalse(session.should_greet())

        # 4. Deactivation resets state
        session.deactivate()
        self.assertFalse(session.is_active)
        self.assertFalse(session.should_greet())

    def test_time_formatting(self):
        self.assertEqual(format_time_remaining(300), "5m 00s")
        self.assertEqual(format_time_remaining(272), "4m 32s")
        self.assertEqual(format_time_remaining(5), "0m 05s")
        self.assertEqual(format_time_remaining(0), "0m 00s")


if __name__ == "__main__":
    unittest.main()
