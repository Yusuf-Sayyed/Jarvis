"""
Regression and unit tests for robust volume-intent recognition, spoken number conversion,
acoustic filler tolerance, relative vs absolute parsing, and limit confirmation routing.
"""

import unittest
from unittest.mock import MagicMock, patch

from actions.audio import set_volume
from core.context import get_conversation_context
from core.intent import detect_intent
from core.router import route_command
from intelligence.intent_extractor import (
    extract_smart_intent,
    extract_volume_intent,
    parse_spoken_number,
)


class TestVolumeRecognitionAndRouting(unittest.TestCase):

    def setUp(self):
        self.context = get_conversation_context()
        self.context.clear_pending()

    def tearDown(self):
        self.context.clear_pending()

    def test_spoken_number_normalization(self):
        """Test converting word numbers (including compound forms) to digits."""
        self.assertEqual(parse_spoken_number("fifty percent"), "50 percent")
        self.assertEqual(parse_spoken_number("one hundred percent"), "100 percent")
        self.assertEqual(parse_spoken_number("one hundred fifty percent"), "150 percent")
        self.assertEqual(parse_spoken_number("two hundred percent"), "200 percent")
        self.assertEqual(parse_spoken_number("twenty five percent"), "25 percent")
        self.assertEqual(parse_spoken_number("seventy five percent"), "75 percent")
        self.assertEqual(parse_spoken_number("ten percent"), "10 percent")
        self.assertEqual(parse_spoken_number("zero percent"), "0 percent")

    def test_required_utterance_variations(self):
        """
        Tests the 11 specific user request variations:
          - 'Set volume to 100%.'
          - 'Set the volume to 100%.'
          - 'Set it volume to 100%.'
          - 'Set well volume to 100%.'
          - 'Increase volume to 100%.'
          - 'Turn the volume down.'
          - 'Increase volume by 10%.'
          - 'Set volume 200%.'
          - 'Volume to fifty percent.'
          - 'Mute the volume.'
          - 'Unmute.'
        """
        cases = [
            ("Set volume to 100%.", "set_volume", 100, "absolute", False),
            ("Set the volume to 100%.", "set_volume", 100, "absolute", False),
            ("Set it volume to 100%.", "set_volume", 100, "absolute", False),
            ("Set well volume to 100%.", "set_volume", 100, "absolute", False),
            ("Increase volume to 100%.", "set_volume", 100, "absolute", False),
            ("Turn the volume down.", "decrease_volume", -10, "relative", False),
            ("Increase volume by 10%.", "increase_volume", 10, "relative", False),
            ("Set volume 200%.", "set_volume", 200, "absolute", True),
            ("Volume to fifty percent.", "set_volume", 50, "absolute", False),
            ("Mute the volume.", "mute", None, None, False),
            ("Unmute.", "unmute", None, None, False),
        ]

        for phrase, exp_intent, exp_val, exp_mode, exp_clarify in cases:
            with self.subTest(phrase=phrase):
                res = extract_volume_intent(phrase)
                self.assertIsNotNone(res, f"Failed to extract intent for: '{phrase}'")
                self.assertEqual(res["intent"], exp_intent)
                self.assertEqual(res["value"], exp_val)
                self.assertEqual(res["mode"], exp_mode)
                self.assertEqual(res["requires_clarification"], exp_clarify)

    def test_acoustic_fillers_and_noisy_variations(self):
        """Tolerates speech recognition errors around words like 'well', 'it', 'at', 'the'."""
        noisy = [
            ("set at volume 200%", "set_volume", 200, "absolute", True),
            ("set well volume to 80 percent", "set_volume", 80, "absolute", False),
            ("set it volume to 50 percent", "set_volume", 50, "absolute", False),
            ("volume 80 percent", "set_volume", 80, "absolute", False),
            ("volume to seventy percent", "set_volume", 70, "absolute", False),
            ("turn down the volume by 5 percent", "decrease_volume", -5, "relative", False),
            ("turn up the volume by 25 percent", "increase_volume", 25, "relative", False),
        ]

        for phrase, exp_intent, exp_val, exp_mode, exp_clarify in noisy:
            with self.subTest(phrase=phrase):
                res = extract_volume_intent(phrase)
                self.assertIsNotNone(res, f"Failed to extract noisy variation: '{phrase}'")
                self.assertEqual(res["intent"], exp_intent)
                self.assertEqual(res["value"], exp_val)
                self.assertEqual(res["mode"], exp_mode)
                self.assertEqual(res["requires_clarification"], exp_clarify)

    def test_distinguish_absolute_target_vs_relative_adjustment(self):
        """
        Explicitly proves distinction:
        'Increase volume to 100%' -> target percentage (absolute 100%)
        'Increase volume by 10%' -> adjustment (+10% relative)
        """
        to_res = extract_volume_intent("Increase volume to 100%.")
        self.assertEqual(to_res["intent"], "set_volume")
        self.assertEqual(to_res["action"], "volume_set")
        self.assertEqual(to_res["mode"], "absolute")
        self.assertEqual(to_res["value"], 100)

        by_res = extract_volume_intent("Increase volume by 10%.")
        self.assertEqual(by_res["intent"], "increase_volume")
        self.assertEqual(by_res["action"], "volume_change")
        self.assertEqual(by_res["mode"], "relative")
        self.assertEqual(by_res["value"], 10)

    def test_missing_number_does_not_invent_numbers(self):
        """When user says 'Set volume', do not invent a number; require clarification."""
        res = extract_volume_intent("Set volume.")
        self.assertIsNotNone(res)
        self.assertEqual(res["intent"], "set_volume")
        self.assertEqual(res["action"], "volume_missing_number")
        self.assertIsNone(res["value"])
        self.assertTrue(res["requires_clarification"])
        self.assertEqual(res["clarification_reason"], "missing_number")

    def test_unrelated_sentences_not_interpreted_as_volume(self):
        """Ensures commands with unrelated numbers or math/science phrases are rejected."""
        unrelated = [
            "set a timer for 10 minutes",
            "open terminal",
            "volume of a sphere is 4/3 pi r cubed",
            "search for 100 percent cotton shirts",
            "set brightness to 50%",
            "can you pause the video",
            "what is the weather today",
            "launch firefox",
        ]
        for phrase in unrelated:
            with self.subTest(phrase=phrase):
                self.assertIsNone(extract_volume_intent(phrase), f"Wrongly matched as volume: '{phrase}'")

    @patch("actions.audio.set_volume")
    def test_route_set_volume_standard_range(self, mock_set_vol):
        mock_set_vol.return_value = (True, "Volume set to 100%.")
        cont, pending = route_command("Set volume to 100%.")
        self.assertTrue(cont)
        self.assertIsNone(pending)
        mock_set_vol.assert_called_once_with(100)

    @patch("actions.audio.set_volume")
    def test_route_volume_limit_clarification_and_confirmation(self, mock_set_vol):
        """
        Requesting 200% prompts confirmation to set 150%, and does NOT silently clamp.
        """
        # 1. User asks for 200%
        cont, pending = route_command("Set volume 200%.")
        self.assertTrue(cont)
        self.assertEqual(pending, "confirm_volume_limit")
        mock_set_vol.assert_not_called()

        # 2. User confirms with 'yes'
        mock_set_vol.return_value = (True, "Volume set to 150%. Note: Software amplification above 100% may cause audio distortion.")
        cont2, pending2 = route_command("Yes")
        self.assertTrue(cont2)
        self.assertIsNone(pending2)
        mock_set_vol.assert_called_once_with(150)

    @patch("actions.audio.set_volume")
    def test_route_volume_limit_cancellation(self, mock_set_vol):
        """User cancels when prompted for 150% volume boost."""
        cont, pending = route_command("Set volume 200%.")
        self.assertEqual(pending, "confirm_volume_limit")

        cont2, pending2 = route_command("Cancel")
        self.assertTrue(cont2)
        self.assertIsNone(pending2)
        mock_set_vol.assert_not_called()

    @patch("actions.audio.change_volume")
    def test_route_relative_volume_commands(self, mock_change_vol):
        mock_change_vol.return_value = (True, "Volume set to 40%.")

        # Turn volume down (default -10)
        route_command("Turn the volume down.")
        mock_change_vol.assert_called_with(-10)

        # Increase volume by 10%
        route_command("Increase volume by 10%.")
        mock_change_vol.assert_called_with(10)

    @patch("actions.audio.set_mute")
    def test_route_mute_and_unmute(self, mock_mute):
        mock_mute.return_value = (True, "Audio muted.")
        route_command("Mute the volume.")
        mock_mute.assert_called_with(True)

        mock_mute.return_value = (True, "Audio unmuted (50%).")
        route_command("Unmute.")
        mock_mute.assert_called_with(False)

    @patch("intelligence.intent_extractor.query_ollama_volume_extraction")
    def test_ollama_not_called_for_deterministic_parsing(self, mock_ollama_vol):
        """Proves Ollama is NOT called for recognizable volume commands."""
        extract_smart_intent("Set volume to 100%.")
        mock_ollama_vol.assert_not_called()

        extract_smart_intent("Turn the volume down.")
        mock_ollama_vol.assert_not_called()


if __name__ == "__main__":
    unittest.main()
