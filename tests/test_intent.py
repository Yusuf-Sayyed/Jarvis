"""
Unit tests for intent detection and command parsing.
"""

import unittest
from core.intent import (
    detect_intent,
    normalize_spoken_text,
    parse_search_command,
    parse_type_command,
)


class TestIntentDetection(unittest.TestCase):

    def test_normalization(self):
        self.assertEqual(normalize_spoken_text("you tube"), "youtube")
        self.assertEqual(normalize_spoken_text("goo gle"), "google")
        self.assertEqual(normalize_spoken_text("fire fox"), "firefox")
        self.assertEqual(normalize_spoken_text("down loads"), "downloads")
        self.assertEqual(normalize_spoken_text("hello world..."), "hello world")

    def test_search_parsing(self):
        eng, q = parse_search_command("search google for python tutorials")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "python tutorials")

        eng, q = parse_search_command("search youtube for iron man trailers")
        self.assertEqual(eng, "youtube")
        self.assertEqual(q, "iron man trailers")

        eng, q = parse_search_command("find the best linux laptops on google")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "the best linux laptops")

        eng, q = parse_search_command("open a new tab and search for python courses")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "python courses")

    def test_type_parsing(self):
        content, enter = parse_type_command("type hello world")
        self.assertEqual(content, "hello world")
        self.assertFalse(enter)

        content, enter = parse_type_command("type python installation guide into the search box")
        self.assertEqual(content, "python installation guide")
        self.assertFalse(enter)

        content, enter = parse_type_command("type quantum computing and press enter")
        self.assertEqual(content, "quantum computing")
        self.assertTrue(enter)

    def test_intent_detection(self):
        intent, params = detect_intent("search google for fedora kde")
        self.assertEqual(intent, "BROWSER_SEARCH")
        self.assertEqual(params["engine"], "google")

        intent, params = detect_intent("type test message")
        self.assertEqual(intent, "TYPE_TEXT")

        intent, params = detect_intent("close the current tab")
        self.assertEqual(intent, "REQUEST_CONFIRMATION")
        self.assertEqual(params["action"], "close_tab")

        intent, params = detect_intent("yes", pending_action="close_tab")
        self.assertEqual(intent, "CONFIRM_ACTION")

        intent, params = detect_intent("no", pending_action="close_tab")
        self.assertEqual(intent, "CANCEL_ACTION")

        intent, _ = detect_intent("exit jarvis")
        self.assertEqual(intent, "EXIT")


if __name__ == "__main__":
    unittest.main()
