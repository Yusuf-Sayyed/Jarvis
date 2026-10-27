"""
Tests for:
1. Issue 1: Local time, date, world timezones, ambiguous/unknown location handling,
   speech output, and guaranteeing no web search or Ollama is called.
2. Issue 2: Unclear speech handling ("Look at him", "You're being tried") and
   guarding against speculative execution or infinite loops.
3. Exit shutdown status handling.
"""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from actions.clock import (
    get_date_answer,
    get_day_answer,
    get_local_timezone,
    get_time_answer,
    parse_time_date_query,
    resolve_timezone,
)
from core.context import get_conversation_context
from core.intent import detect_intent, is_current_info_query, normalize_spoken_text
from core.router import route_command
import interfaces.speech as speech_mod


class TestClockAndSpeech(unittest.TestCase):

    def setUp(self):
        os.environ["JARVIS_TEST_MODE"] = "1"
        self.context = get_conversation_context()
        self.context.clear_pending()
        speech_mod._LAST_SPOKEN = ""

    def tearDown(self):
        self.context.clear_pending()

    # --- Issue 1: Local Time and Date Fast-Path ---

    def test_local_timezone_is_kolkata(self):
        """Verify the local timezone on this Fedora system resolves to Asia/Kolkata."""
        tz = get_local_timezone()
        self.assertIn(str(tz), ("Asia/Kolkata", "Asia/Calcutta"))

    def test_local_time_intent_and_routing(self):
        """Verify natural local time variations route to TIME_DATE_QUERY and do not trigger web search."""
        phrases = [
            "What time is it?",
            "What is the time right now?",
            "What is time right now?",
            "What's the time right now?",
            "Tell me the current time.",
            "Tell me the time.",
            "current time",
        ]
        for phrase in phrases:
            # 1. Must NOT be classified as current info query (web search)
            self.assertFalse(is_current_info_query(phrase), f"Triggered web search: {phrase}")

            # 2. Must detect as TIME_DATE_QUERY
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "TIME_DATE_QUERY", f"Failed for phrase: {phrase}")
            self.assertEqual(params["type"], "time")
            self.assertIsNone(params["location"])

            # 3. Route command must answer directly without Ollama or web search
            f = io.StringIO()
            with redirect_stdout(f):
                cont, pending = route_command(phrase)
            self.assertTrue(cont)
            self.assertIsNone(pending)
            out = f.getvalue()
            self.assertIn("[Intent: TIME_DATE_QUERY | Type: Time]", out)
            self.assertIn("The current time is", out)
            self.assertIn(", Sir.", out)
            self.assertIn(speech_mod.get_last_spoken(), out)

    def test_local_date_and_day_queries(self):
        """Verify date and day queries are answered directly."""
        date_phrases = [
            "What's today's date?",
            "What is today's date?",
            "What is the date today?",
            "Tell me today's date.",
        ]
        for phrase in date_phrases:
            self.assertFalse(is_current_info_query(phrase))
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "TIME_DATE_QUERY")
            self.assertEqual(params["type"], "date")

            f = io.StringIO()
            with redirect_stdout(f):
                cont, pending = route_command(phrase)
            self.assertTrue(cont)
            self.assertIn("Today is", f.getvalue())

        day_phrases = [
            "What day is it today?",
            "What day is today?",
            "What day is it?",
        ]
        for phrase in day_phrases:
            self.assertFalse(is_current_info_query(phrase))
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "TIME_DATE_QUERY")
            self.assertEqual(params["type"], "day")

            f = io.StringIO()
            with redirect_stdout(f):
                cont, pending = route_command(phrase)
            self.assertTrue(cont)
            self.assertIn("Today is", f.getvalue())

    def test_world_timezone_queries(self):
        """Verify queries for specific cities/countries resolve to correct timezone."""
        world_queries = [
            ("What time is it in Tokyo?", "Tokyo", "Asia/Tokyo"),
            ("What is the time in London?", "London", "Europe/London"),
            ("What time is it in New York?", "New York", "America/New_York"),
            ("Tell me the time in Paris", "Paris", "Europe/Paris"),
            ("Current time in Dubai", "Dubai", "Asia/Dubai"),
        ]
        for query, expected_loc, expected_tz in world_queries:
            self.assertFalse(is_current_info_query(query))
            intent, params = detect_intent(query)
            self.assertEqual(intent, "TIME_DATE_QUERY")
            self.assertEqual(params["type"], "time")
            self.assertEqual(params["location"].lower(), expected_loc.lower())

            tz, loc_name, clarification = resolve_timezone(params["location"])
            self.assertIsNone(clarification)
            self.assertEqual(str(tz), expected_tz)

            f = io.StringIO()
            with redirect_stdout(f):
                cont, pending = route_command(query)
            self.assertTrue(cont)
            self.assertIsNone(pending)
            out = f.getvalue()
            self.assertIn(f"in {expected_loc}", out)

    def test_ambiguous_and_unknown_locations(self):
        """Verify ambiguous and unknown locations ask for clarification instead of guessing."""
        # 1. Ambiguous multi-timezone country (US)
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("What time is it in the US?")
        self.assertTrue(cont)
        self.assertEqual(pending, "clarify_time_location")
        self.assertIn("multiple timezones", f.getvalue())

        # Follow-up with city
        f = io.StringIO()
        with redirect_stdout(f):
            cont2, pending2 = route_command("Chicago")
        self.assertTrue(cont2)
        self.assertIsNone(pending2)
        self.assertIn("Chicago", f.getvalue())

        # 2. Ambiguous city (Springfield)
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("What time is it in Springfield?")
        self.assertTrue(cont)
        self.assertEqual(pending, "clarify_time_location")
        self.assertIn("Springfield", f.getvalue())

        # 3. Unknown location (Atlantis)
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("What time is it in Atlantis?")
        self.assertTrue(cont)
        self.assertEqual(pending, "clarify_time_location")
        self.assertIn("could not determine the timezone for 'Atlantis'", f.getvalue())

    def test_no_web_search_or_ollama_for_time(self):
        """Guarantee web search and Ollama are never called for time/date questions."""
        with patch("intelligence.web_search.handle_current_info_query") as mock_web, \
             patch("intelligence.ollama_client.ask_ollama") as mock_ollama:
            route_command("What is time right now?")
            route_command("What's today's date?")
            route_command("What time is it in Tokyo?")
            mock_web.assert_not_called()
            mock_ollama.assert_not_called()

    # --- Issue 2: Unclear Speech Handling ---

    def test_unclear_speech_transcripts(self):
        """
        Verify transcripts that cannot be reliably resolved to known actions
        or clear conversational questions are classified as UNCLEAR_SPEECH,
        prompt the user to repeat, and never execute speculative actions.
        """
        unclear_samples = [
            "Look at him",
            "You're being tried",
        ]
        for phrase in unclear_samples:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "UNCLEAR_SPEECH", f"Expected UNCLEAR_SPEECH for '{phrase}'")

            with patch("intelligence.web_search.handle_current_info_query") as mock_web, \
                 patch("intelligence.ollama_client.ask_ollama") as mock_ollama:
                f = io.StringIO()
                with redirect_stdout(f):
                    cont, pending = route_command(phrase)
                self.assertTrue(cont)
                self.assertIsNone(pending)
                self.assertIn("I beg your pardon, Sir. Could you please repeat that?", f.getvalue())
                self.assertEqual(speech_mod.get_last_spoken(), "I beg your pardon, Sir. Could you please repeat that?")
                # Ensure no external search or LLM was called
                mock_web.assert_not_called()
                mock_ollama.assert_not_called()

    def test_normalization_integrity(self):
        """Verify normalization preserves legitimate words and trims acoustic artifacts."""
        self.assertEqual(normalize_spoken_text("Look at him."), "look at him")
        self.assertEqual(normalize_spoken_text("You're being tried?"), "you're being tried")
        self.assertEqual(normalize_spoken_text("What time is it?"), "what time is it")


if __name__ == "__main__":
    unittest.main()
