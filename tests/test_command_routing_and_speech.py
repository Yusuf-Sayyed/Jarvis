"""
Focused unit tests for:
1. Direct command routing for known applications (browser, firefox, terminal)
   with conversational prefixes and variations.
2. Verified application resolution via AppRegistry and system default browser.
3. Spoken response delivery to the speech interface for Ollama and web search.
4. Robust TTS audio validation and playback failure handling.
"""

import io
import os
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

import numpy as np

from actions.resolver import AppInfo, AppRegistry, get_app_registry
import actions.desktop as desktop
from core.context import get_conversation_context
from core.intent import detect_intent
from core.router import route_command
import interfaces.speech as speech_mod


class TestDirectCommandRoutingAndSpeech(unittest.TestCase):

    def setUp(self):
        os.environ["JARVIS_TEST_MODE"] = "1"
        self.context = get_conversation_context()
        self.context.clear_pending()
        speech_mod.reset_speech_state()

    def tearDown(self):
        self.context.clear_pending()
        speech_mod.reset_speech_state()

    # --- 1. Direct Command Routing Variations ---

    def test_browser_routing_variations(self):
        """Natural variations of open browser must route to DESKTOP_ACTION open_browser, not Ollama."""
        variations = [
            "Open browser.",
            "Could you please open browser?",
            "open browser",
            "open the browser",
            "could you open the browser for me?",
            "can you please open a browser?",
            "launch browser",
            "start browser",
        ]
        for phrase in variations:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "DESKTOP_ACTION", f"Failed intent for: {phrase}")
            self.assertEqual(params.get("action"), "open_browser", f"Failed action for: {phrase}")

    def test_firefox_routing_variations(self):
        """Natural variations of Firefox launch must route to DESKTOP_ACTION open_firefox, not Ollama."""
        variations = [
            "Launch Firefox.",
            "open firefox",
            "could you please launch firefox?",
            "can you start firefox?",
            "start firefox for me",
        ]
        for phrase in variations:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "DESKTOP_ACTION", f"Failed intent for: {phrase}")
            self.assertEqual(params.get("action"), "open_firefox", f"Failed action for: {phrase}")

    def test_terminal_routing_variations(self):
        """Natural variations of terminal launch must route to DESKTOP_ACTION open_terminal, not Ollama."""
        variations = [
            "Open a new terminal.",
            "Could you open the terminal for me?",
            "Open terminal",
            "open the terminal",
            "can you open a new terminal?",
            "launch konsole",
            "start terminal for me",
            "open terminal window",
        ]
        for phrase in variations:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "DESKTOP_ACTION", f"Failed intent for: {phrase}")
            self.assertEqual(params.get("action"), "open_terminal", f"Failed action for: {phrase}")

    def test_conversational_questions_still_route_to_ollama(self):
        """Genuine conversational queries and questions must continue routing to OLLAMA_QUERY."""
        questions = [
            "How are you?",
            "Could you tell me how you are doing today?",
            "What is the theory of relativity?",
            "Who was Alan Turing?",
            "Why is the sky blue?",
        ]
        for q in questions:
            intent, params = detect_intent(q)
            self.assertEqual(intent, "OLLAMA_QUERY", f"Expected OLLAMA_QUERY for: {q}")

    # --- 2. Deterministic Action Execution and Verification ---

    @patch("actions.desktop.open_browser", return_value=True)
    @patch("intelligence.ollama_client.ask_ollama")
    def test_route_open_browser_executes_action_without_ollama(self, mock_ollama, mock_open_browser):
        """Opening browser executes desktop action directly and never asks Ollama."""
        cont, pending = route_command("Could you please open browser?")
        self.assertTrue(cont)
        self.assertIsNone(pending)
        mock_open_browser.assert_called_once()
        mock_ollama.assert_not_called()

    @patch("actions.desktop.open_terminal", return_value=True)
    @patch("intelligence.ollama_client.ask_ollama")
    def test_route_open_terminal_executes_action_without_ollama(self, mock_ollama, mock_open_term):
        """Opening terminal executes desktop action directly and never asks Ollama."""
        cont, pending = route_command("Could you open the terminal for me?")
        self.assertTrue(cont)
        self.assertIsNone(pending)
        mock_open_term.assert_called_once()
        mock_ollama.assert_not_called()

    def test_browser_resolution_uses_app_registry(self):
        """AppRegistry resolves 'browser' to the system browser using configured/curated defaults."""
        registry = get_app_registry()
        app = registry.resolve_application("browser")
        self.assertIsNotNone(app)
        self.assertTrue(os.path.isfile(app.exec_path) or bool(app.exec_path))

    # --- 3. Speech Output Delivery for Final Spoken Responses ---

    def test_ollama_response_delivers_to_speech_interface(self):
        """Conversational response from Ollama must reach the speech interface."""
        mock_reply = "I am operating at peak efficiency, Sir. How may I be of assistance?"
        with patch("core.router.ask_ollama", return_value=mock_reply), \
             patch("interfaces.speech.speak", wraps=speech_mod.speak) as mock_speak:
            cont, pending = route_command("How are you?")
            self.assertTrue(cont)
            self.assertIsNone(pending)
            mock_speak.assert_called_once_with(mock_reply)
            self.assertEqual(speech_mod.get_last_spoken(), speech_mod.clean_text_for_speech(mock_reply))

    def test_web_search_response_delivers_to_speech_interface(self):
        """Real-time web search answer must reach the speech interface."""
        mock_answer = "According to current reports, the mission was completed successfully."
        with patch("intelligence.web_search.handle_current_info_query", return_value=(True, mock_answer, [])):
            cont, pending = route_command("What's the latest news today?")
            self.assertTrue(cont)
            self.assertIsNone(pending)
            self.assertEqual(speech_mod.get_last_spoken(), speech_mod.clean_text_for_speech(mock_answer))

    # --- 4. TTS Failure Handling and Validation ---

    def test_tts_rejects_invalid_audio_shape(self):
        """Kokoro synthesis must reject multidimensional or empty arrays."""
        mock_engine = MagicMock()
        # 2D array instead of 1D
        mock_engine.create.return_value = (np.zeros((2, 100), dtype=np.float32), 24000)

        with patch("interfaces.speech.get_kokoro_engine", return_value=mock_engine):
            ok = speech_mod._synthesize_kokoro("Test text", "/tmp/invalid_shape.wav")
            self.assertFalse(ok)
            self.assertFalse(os.path.exists("/tmp/invalid_shape.wav"))

    def test_tts_rejects_non_finite_audio(self):
        """Kokoro synthesis must reject audio arrays containing NaNs or Infs."""
        mock_engine = MagicMock()
        nan_audio = np.array([0.1, np.nan, 0.3], dtype=np.float32)
        mock_engine.create.return_value = (nan_audio, 24000)

        with patch("interfaces.speech.get_kokoro_engine", return_value=mock_engine):
            ok = speech_mod._synthesize_kokoro("Test text", "/tmp/nan_audio.wav")
            self.assertFalse(ok)
            self.assertFalse(os.path.exists("/tmp/nan_audio.wav"))

    def test_tts_rejects_invalid_sample_rate(self):
        """Kokoro synthesis must reject invalid or zero sample rates."""
        mock_engine = MagicMock()
        mock_engine.create.return_value = (np.zeros(100, dtype=np.float32), 0)

        with patch("interfaces.speech.get_kokoro_engine", return_value=mock_engine):
            ok = speech_mod._synthesize_kokoro("Test text", "/tmp/bad_rate.wav")
            self.assertFalse(ok)
            self.assertFalse(os.path.exists("/tmp/bad_rate.wav"))

    def test_playback_failure_does_not_claim_success(self):
        """If player process exits with non-zero returncode, speak must return False."""
        mock_proc = MagicMock()
        mock_proc.communicate.return_value = ("", "PipeWire buffer underrun")
        mock_proc.returncode = 1
        mock_proc.pid = 99123

        with patch("shutil.which", return_value="/usr/bin/pw-play"), \
             patch("interfaces.speech._synthesize_to_wav", return_value=("/tmp/mock_speech.wav", 24000, 1.0)), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"), \
             patch("subprocess.Popen", return_value=mock_proc):

            os.environ.pop("JARVIS_TEST_MODE", None)
            try:
                ok = speech_mod.speak("Test failure", block=True)
                self.assertFalse(ok, "speak() must not claim success when playback fails")
                self.assertFalse(speech_mod.is_speaking(), "Speaking flag must be reset on failure")
                self.assertTrue(speech_mod.is_in_cooldown(), "Safe cooldown must be activated")
            finally:
                os.environ["JARVIS_TEST_MODE"] = "1"
                speech_mod.reset_speech_state()


if __name__ == "__main__":
    unittest.main()
