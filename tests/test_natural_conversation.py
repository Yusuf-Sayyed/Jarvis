"""
Comprehensive tests for JARVIS Natural Conversation, Intent Routing,
Conversational Context, Clarifications, and Kokoro 1.15 Speech Speed.
"""

import os
import unittest
from unittest.mock import MagicMock, patch

import core.config as config
from core.context import get_conversation_context
from core.intent import detect_intent
from core.router import route_command
import interfaces.speech as speech_mod
from intelligence.ollama_client import get_system_prompt_with_memory


class TestNaturalConversationAndRouting(unittest.TestCase):

    def setUp(self):
        os.environ["JARVIS_TEST_MODE"] = "1"
        self.context = get_conversation_context()
        self.context.clear_pending()
        self.context.clear_dialogue()
        speech_mod.reset_speech_state()

    def tearDown(self):
        self.context.clear_pending()
        self.context.clear_dialogue()
        speech_mod.reset_speech_state()

    # --- 1. Natural Conversation and Discussion Sentences ---

    def test_ordinary_conversational_sentences_route_to_ollama(self):
        """Conversational sentences, career questions, and opinions must route to OLLAMA_QUERY."""
        conversational_samples = [
            "How are you?",
            "What should I learn to become a software engineer or DevOps engineer?",
            "So, I was saying that what should I learn to become a software engineer or a DevOps engineer? But I'm thinking to get into the Python more deeply so I can get higher.",
            "I'm thinking of learning Python more deeply.",
            "What do you think about that?",
            "Can you explain why?",
            "Let's discuss my career options.",
            "I feel like learning Rust next.",
            "What is your opinion on microservices versus monoliths?",
            "Could you explain the difference between Docker and Kubernetes?",
        ]
        for phrase in conversational_samples:
            intent, params = detect_intent(phrase)
            self.assertEqual(
                intent,
                "OLLAMA_QUERY",
                f"Expected OLLAMA_QUERY for '{phrase}', got intent '{intent}'",
            )
            self.assertIn("prompt", params)
            self.assertTrue(len(params["prompt"]) > 0)

    # --- 2. Conversational Context & Multi-Turn History ---

    def test_dialogue_turns_recorded_and_passed_to_llm(self):
        """Conversational turns are stored in ConversationContext and passed to the LLM system prompt."""
        self.context.add_dialogue_turn(
            "What should I learn to become a software engineer or DevOps engineer?",
            "Focus on core programming fundamentals, Python, Linux, and containerization.",
        )
        self.context.add_dialogue_turn(
            "I'm thinking of learning Python more deeply.",
            "Python is a versatile foundation for both backend engineering and DevOps automation.",
        )

        turns = self.context.get_recent_dialogue()
        self.assertEqual(len(turns), 2)
        self.assertEqual(turns[0].user, "What should I learn to become a software engineer or DevOps engineer?")

        sys_prompt = get_system_prompt_with_memory()
        self.assertIn("Recent Conversation History:", sys_prompt)
        self.assertIn("What should I learn to become a software engineer or DevOps engineer?", sys_prompt)
        self.assertIn("Python is a versatile foundation", sys_prompt)
        self.assertIn("Please maintain continuity with the ongoing discussion", sys_prompt)

    @patch("core.router.ask_ollama")
    def test_multi_turn_conversation_updates_context(self, mock_ollama):
        """Routing a conversational command automatically records the turn in context."""
        mock_ollama.return_value = "Python offers rich libraries and excellent syntax for both domains, Sir."

        cont, pending = route_command("What do you think about that?")
        self.assertTrue(cont)
        self.assertIsNone(pending)

        recent = self.context.get_recent_dialogue()
        self.assertEqual(len(recent), 1)
        self.assertEqual(recent[0].user, "what do you think about that")
        self.assertEqual(recent[0].assistant, "Python offers rich libraries and excellent syntax for both domains, Sir.")

    # --- 3. Genuinely Unclear Speech vs Normal Speech ---

    def test_genuinely_unclear_speech_and_noise_classified_as_unclear(self):
        """Unintelligible noise, isolated fillers, and acoustic anomalies must remain UNCLEAR_SPEECH."""
        unclear_samples = [
            "Look at him",
            "You're being tried",
            "the table is blue",
            "um",
            "uh",
            "ah",
            "a",
            "the",
            "???",
            "   ",
        ]
        for noise in unclear_samples:
            intent, _ = detect_intent(noise)
            self.assertEqual(
                intent,
                "UNCLEAR_SPEECH",
                f"Expected UNCLEAR_SPEECH for '{noise}', got '{intent}'",
            )

    def test_dangling_confirmation_without_pending_is_unclear(self):
        """Vague confirmation like 'yes, please' without active pending state is UNCLEAR_SPEECH."""
        self.context.clear_pending()
        intent, _ = detect_intent("yes, please")
        self.assertEqual(intent, "UNCLEAR_SPEECH")

        intent_sure, _ = detect_intent("sure")
        self.assertEqual(intent_sure, "UNCLEAR_SPEECH")

    # --- 4. Ambiguous Actions Request Relevant Clarification ---

    def test_ambiguous_actions_prompt_clarification_not_repeat_request(self):
        """Understandable but ambiguous commands ask relevant clarifications rather than 'repeat that'."""
        ambiguous_cases = [
            ("open project", "CLARIFY_ACTION", "open_project", "Which project or folder would you like me to open, Sir?"),
            ("open application", "CLARIFY_ACTION", "launch_app", "Which application would you like me to open, Sir?"),
            ("set brightness", "CLARIFY_ACTION", "brightness_set", "What brightness percentage would you like me to set, Sir?"),
        ]
        for phrase, expected_intent, expected_act, expected_question in ambiguous_cases:
            self.context.clear_pending()
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, expected_intent, f"Failed intent for: {phrase}")
            self.assertEqual(params.get("action"), expected_act, f"Failed action for: {phrase}")
            self.assertEqual(params.get("question"), expected_question)

            # Test route_command speaks the clarification and sets pending state
            cont, pending = route_command(phrase)
            self.assertTrue(cont)
            self.assertEqual(pending, f"clarify_{expected_act}")
            self.assertEqual(speech_mod.get_last_spoken(), speech_mod.clean_text_for_speech(expected_question))

    # --- 5. Known Command Fast Paths Remain Deterministic ---

    @patch("actions.desktop.open_terminal", return_value=True)
    @patch("actions.desktop.open_browser", return_value=True)
    @patch("actions.media.pause_playback", return_value=(True, "Playback paused.", None))
    @patch("actions.audio.set_volume", return_value=(True, "Volume set to 80%."))
    @patch("core.router.ask_ollama")
    def test_known_actions_bypass_ollama(
        self, mock_ollama, mock_set_vol, mock_media, mock_open_browser, mock_open_term
    ):
        """Deterministic system commands must execute through their action handlers and bypass Ollama."""
        commands = [
            ("open terminal", mock_open_term),
            ("open browser", mock_open_browser),
            ("pause music", mock_media),
            ("set volume to 80%", mock_set_vol),
        ]
        for cmd, mock_handler in commands:
            self.context.clear_pending()
            cont, pending = route_command(cmd)
            self.assertTrue(cont)
            self.assertIsNone(pending)
            mock_handler.assert_called()
            mock_ollama.assert_not_called()

    # --- 6. Kokoro 1.15 Speaking Speed and Voice Config ---

    def test_kokoro_speed_configuration(self):
        """Kokoro speed must be configured to 1.15 with bm_fable voice and en-gb language."""
        self.assertEqual(config.KOKORO_SPEED, 1.15)
        self.assertEqual(config.KOKORO_VOICE, "bm_fable")
        self.assertEqual(config.KOKORO_LANG, "en-gb")

    def test_kokoro_synthesis_at_speed_1_15(self):
        """Synthesize a sample sentence at speed 1.15 and verify audio validity and timing."""
        test_text = "I am ready to discuss your software engineering plans, Sir."
        wav_path, sample_rate, duration = speech_mod._synthesize_to_wav(test_text)
        try:
            self.assertIsNotNone(wav_path)
            self.assertTrue(os.path.isfile(wav_path))
            self.assertEqual(sample_rate, 24000)
            self.assertGreater(duration, 0.5)
            # Speed 1.15 should finish this 10-word sentence in under 4.0 seconds
            self.assertLess(duration, 4.0)
        finally:
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)


if __name__ == "__main__":
    unittest.main()
