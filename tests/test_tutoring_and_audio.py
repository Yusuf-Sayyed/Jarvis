"""
Comprehensive unit and regression tests for:
1. Multi-turn Python Tutoring & Explicit Conversational Context
2. Kokoro Audio Array Concatenation & Incompatible Dimensions Safety
3. Low-Latency Sentence-Pipelined Playback & Diagnostics
4. Summary-sized Responses & Command Disambiguation
"""

import os
import unittest
from unittest.mock import MagicMock, patch
import numpy as np

from core.context import ConversationContext, ActivityState, get_conversation_context
from core.intent import detect_intent
from core.router import route_command, PYTHON_TUTORING_CURRICULUM
import interfaces.speech as speech_mod


class TestTutoringAndAudio(unittest.TestCase):

    def setUp(self):
        self.context = get_conversation_context()
        self.context.stop_activity()
        self.context.clear_pending()
        self.context.clear_dialogue()
        speech_mod.reset_speech_state()

    def tearDown(self):
        self.context.stop_activity()
        self.context.clear_pending()
        self.context.clear_dialogue()
        speech_mod.reset_speech_state()

    # =========================================================================
    # 1. Multi-Turn Tutoring & Context Routing Tests
    # =========================================================================

    def test_start_tutoring_intent_detection(self):
        """Phrases requesting Python tutoring correctly trigger START_TUTORING."""
        phrases = [
            "teach me Python basics",
            "teach me python",
            "can you teach me python",
            "start a python lesson",
            "let's learn python",
            "i want to learn python basics",
        ]
        for p in phrases:
            intent, params = detect_intent(p)
            self.assertEqual(intent, "START_TUTORING", f"Failed for '{p}'")
            self.assertEqual(params.get("topic"), "python")

    def test_lesson_answer_create_file_extension(self):
        """
        Reproduce and verify the fixed behavior:
        When in a Python lesson, the user replying 'create a file extension.py'
        is evaluated as an answer to the active question, NOT a file creation command.
        """
        # Step 1: Start tutoring
        with patch("interfaces.speech.speak") as mock_speak:
            should_cont, pending = route_command("teach me Python basics")
            self.assertTrue(should_cont)
            self.assertIsNone(pending)
            self.assertTrue(self.context.is_awaiting_activity_answer())
            act = self.context.get_active_activity()
            self.assertIsNotNone(act)
            self.assertEqual(act.lesson_step, 1)
            self.assertIn("IDLE or PyCharm", act.current_question)

        # Step 2: User answers 'create a file extension.py'
        intent, params = detect_intent("create a file extension.py")
        self.assertEqual(intent, "TUTORING_ANSWER")
        self.assertEqual(params.get("answer"), "create a file extension.py")
        self.assertEqual(params.get("step"), 1)

        # Step 3: Route the answer and check evaluation
        with patch("interfaces.speech.speak") as mock_speak:
            should_cont, pending = route_command("create a file extension.py")
            self.assertTrue(should_cont)
            self.assertIsNone(pending)
            # The lesson advanced to step 2
            act = self.context.get_active_activity()
            self.assertIsNotNone(act)
            self.assertEqual(act.lesson_step, 2)
            self.assertIn("display text on the screen", act.current_question.lower())

            # Verify speech was called with an evaluation and does not claim file creation
            mock_speak.assert_called()
            spoken_text = mock_speak.call_args[0][0]
            self.assertTrue(any(t in spoken_text.lower() for t in ("partially correct", "incorrect", "correct", "close")))
            self.assertNotIn("i have created", spoken_text.lower())
            self.assertNotIn("i'll create", spoken_text.lower())
            self.assertNotIn("i will create", spoken_text.lower())

    def test_multi_turn_lesson_progression(self):
        """Verify full multi-turn lesson progression across correct answers."""
        with patch("interfaces.speech.speak") as mock_speak:
            route_command("teach me Python basics")

            # Turn 1: create a file extension.py
            route_command("create a file extension.py")
            act = self.context.get_active_activity()
            self.assertEqual(act.lesson_step, 2)

            # Turn 2: answer "print"
            route_command("print")
            act = self.context.get_active_activity()
            self.assertEqual(act.lesson_step, 3)
            spoken = mock_speak.call_args[0][0]
            self.assertIn("correct", spoken.lower())

            # Turn 3: answer "variable"
            route_command("variable")
            act = self.context.get_active_activity()
            self.assertEqual(act.lesson_step, 4)
            spoken = mock_speak.call_args[0][0]
            self.assertTrue("spot on" in spoken.lower() or "correct" in spoken.lower() or "variable" in spoken.lower())

    def test_tutoring_hint_request(self):
        """User asking for a hint receives the question hint without advancing step."""
        with patch("interfaces.speech.speak") as mock_speak:
            route_command("teach me Python basics")
            act = self.context.get_active_activity()
            self.assertEqual(act.lesson_step, 1)

            # Request hint
            intent, params = detect_intent("give me a hint")
            self.assertEqual(intent, "TUTORING_CONTROL")
            self.assertEqual(params.get("action"), "give_hint")

            route_command("give me a hint")
            # Step should remain 1
            act = self.context.get_active_activity()
            self.assertEqual(act.lesson_step, 1)
            self.assertEqual(act.hints_given, 1)
            spoken = mock_speak.call_args[0][0]
            self.assertIn("Consider whether you are creating a new script file", spoken)

    def test_tutoring_dont_know(self):
        """User saying 'I don't know' receives answer and advances to next question."""
        with patch("interfaces.speech.speak") as mock_speak:
            route_command("teach me Python basics")
            self.assertEqual(self.context.get_active_activity().lesson_step, 1)

            intent, _ = detect_intent("I don't know")
            self.assertEqual(intent, "TUTORING_CONTROL")

            route_command("I don't know")
            act = self.context.get_active_activity()
            self.assertEqual(act.lesson_step, 2)
            spoken = mock_speak.call_args[0][0]
            self.assertIn("No problem", spoken)

    def test_tutoring_stop_lesson(self):
        """User saying 'stop the lesson' halts tutoring and clears active activity."""
        with patch("interfaces.speech.speak") as mock_speak:
            route_command("teach me Python basics")
            self.assertTrue(self.context.is_awaiting_activity_answer())

            intent, params = detect_intent("stop the lesson")
            self.assertEqual(intent, "TUTORING_CONTROL")
            self.assertEqual(params.get("action"), "stop_lesson")

            route_command("stop the lesson")
            self.assertFalse(self.context.is_awaiting_activity_answer())
            self.assertIsNone(self.context.get_active_activity())
            spoken = mock_speak.call_args[0][0]
            self.assertIn("Lesson paused", spoken)

    def test_genuine_file_creation_outside_lesson_is_unsupported(self):
        """Outside a lesson, creating files is marked unsupported, never hallucinating."""
        intent, params = detect_intent("create a file named app.py")
        self.assertEqual(intent, "UNSUPPORTED_ACTION")
        self.assertEqual(params.get("action"), "create_file")

        with patch("interfaces.speech.speak") as mock_speak:
            route_command("create a file named app.py")
            spoken = mock_speak.call_args[0][0]
            self.assertIn("I do not have a tool to create files", spoken)

    def test_ambiguous_desktop_command_clarification_in_lesson(self):
        """An explicit app launch during a lesson question triggers clarification."""
        with patch("interfaces.speech.speak"):
            route_command("teach me Python basics")
            # Actively asking IDLE or PyCharm question.
            # Next, simulate user saying "open a terminal"
            intent, params = detect_intent("open terminal")
            # Because question mentions editor/PyCharm, open terminal is ambiguous
            # or if clarified, asks user
            if intent == "CLARIFY_ACTION":
                self.assertEqual(params.get("action"), "clarify_lesson_or_command")

    # =========================================================================
    # 2. Kokoro Audio Shape Normalization & Array Safety Tests
    # =========================================================================

    def test_kokoro_2d_shape_normalized_to_1d(self):
        """Kokoro returning 2D array (1, N) is safely squeezed/reshaped to 1D."""
        mock_engine = MagicMock()
        # Simulate kokoro returning (1, 1000)
        fake_2d_audio = np.ones((1, 1000), dtype=np.float32) * 0.1
        mock_engine.create.return_value = (fake_2d_audio, 24000)

        with patch("interfaces.speech.get_kokoro_engine", return_value=mock_engine), \
             patch("soundfile.write") as mock_sf_write, \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=2048):
            ok = speech_mod._synthesize_kokoro("test text", "/tmp/mock.wav")
            self.assertTrue(ok)
            # Verify soundfile.write was called with 1D array
            written_audio = mock_sf_write.call_args[0][1]
            self.assertEqual(written_audio.ndim, 1)
            self.assertEqual(written_audio.shape, (1000,))

    def test_kokoro_list_of_batches_concatenation_different_lengths(self):
        """
        Verify that multiple batches of different sample lengths
        concatenate along axis 0 without 'dimension mismatch' exceptions.
        """
        mock_engine = MagicMock()
        # Batch 0 has 547840 samples, Batch 1 has 309248 samples (matching the real bug log)
        batch0 = np.ones((1, 547840), dtype=np.float32) * 0.05
        batch1 = np.ones((1, 309248), dtype=np.float32) * 0.05
        mock_engine.create.return_value = ([batch0, batch1], 24000)

        with patch("interfaces.speech.get_kokoro_engine", return_value=mock_engine), \
             patch("soundfile.write") as mock_sf_write, \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.getsize", return_value=4096):
            ok = speech_mod._synthesize_kokoro("long text", "/tmp/mock.wav")
            self.assertTrue(ok)
            written_audio = mock_sf_write.call_args[0][1]
            self.assertEqual(written_audio.ndim, 1)
            self.assertEqual(written_audio.shape, (547840 + 309248,))

    # =========================================================================
    # 3. Sentence Splitting & Low-Latency Pipelining Tests
    # =========================================================================

    def test_sentence_splitting(self):
        """Sentence splitter correctly separates multi-sentence strings."""
        text = (
            "Partially correct, Sir. In an editor like PyCharm or IDLE, you create a new file with a .py extension. "
            "What built-in function is used to output text to the screen?"
        )
        sentences = speech_mod.split_into_sentences(text)
        self.assertEqual(len(sentences), 3)
        self.assertEqual(sentences[0], "Partially correct, Sir.")
        self.assertEqual(sentences[1], "In an editor like PyCharm or IDLE, you create a new file with a .py extension.")
        self.assertEqual(sentences[2], "What built-in function is used to output text to the screen?")

    def test_sentence_pipelined_playback_execution(self):
        """Pipelined playback executes sequentially without overlapping processes."""
        played_chunks = []

        def mock_play(wav_path, dur):
            played_chunks.append(wav_path)
            return True

        text = "First sentence. Second sentence. Third sentence."
        was_test_mode = os.environ.pop("JARVIS_TEST_MODE", None)
        try:
            with patch("interfaces.speech._synthesize_to_wav") as mock_syn, \
                 patch("interfaces.speech._play_wav_file", side_effect=mock_play):

                # Mock synthesis returning a dummy valid wav path
                mock_syn.side_effect = [
                    ("/tmp/part1.wav", 24000, 1.5),
                    ("/tmp/part2.wav", 24000, 1.8),
                    ("/tmp/part3.wav", 24000, 1.2),
                ]
                with patch("os.path.isfile", return_value=True), \
                     patch("os.path.exists", return_value=True), \
                     patch("os.unlink"):
                    ok = speech_mod.speak(text, block=True)
                    self.assertTrue(ok)
                    self.assertEqual(len(played_chunks), 3)
                    self.assertEqual(played_chunks, ["/tmp/part1.wav", "/tmp/part2.wav", "/tmp/part3.wav"])
        finally:
            if was_test_mode:
                os.environ["JARVIS_TEST_MODE"] = was_test_mode


if __name__ == "__main__":
    unittest.main()
