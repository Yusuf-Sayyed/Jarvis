"""
Regression and unit tests for natural-language intent extraction,
resolver integration, memory fast-path learning, and smart routing.
"""

import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from actions.resolver import AppInfo, get_app_registry, get_directory_resolver
from core.context import get_conversation_context
from core.intent import detect_intent
from core.memory import MemoryStore, get_memory_store
from core.router import route_command


class TestSmartIntentAndRouting(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_smart_mem.sqlite"
        self.memory = MemoryStore(db_path=self.db_path)
        
        # Override singleton instances for isolated testing
        import core.memory as mem_mod
        self.orig_mem = mem_mod._MEMORY_INSTANCE
        mem_mod._MEMORY_INSTANCE = self.memory

        self.context = get_conversation_context()
        self.context.clear_pending()
        self.context.update_interaction(action=None, app=None, target_name=None, target_path=None)

    def tearDown(self):
        import core.memory as mem_mod
        mem_mod._MEMORY_INSTANCE = self.orig_mem
        self.temp_dir.cleanup()

    def test_open_project_natural_intent(self):
        phrase = "Open my Lensify project in Antigravity."
        intent, params = detect_intent(phrase)

        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "open_project")
        self.assertEqual(params["params"]["project"].lower(), "lensify")
        self.assertEqual(params["params"]["app"].lower(), "antigravity")

    @patch("subprocess.Popen")
    def test_route_open_project_and_learn_association(self, mock_popen):
        # Seed mock project directory if real one doesn't exist
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        with patch.object(
            get_directory_resolver(),
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            should_cont, pending = route_command("Open my Lensify project in Antigravity.")
            self.assertTrue(should_cont)
            self.assertIsNone(pending)
            mock_popen.assert_called_once()

            # Verify saved into memory store
            saved_proj = self.memory.get_project("lensify")
            self.assertIsNotNone(saved_proj)
            self.assertEqual(saved_proj["resolved_path"], str(mock_lensify))

            # Verify conversation context was updated
            self.assertEqual(self.context.last_target_path, str(mock_lensify))
            self.assertIn("antigravity", self.context.last_app)

    @patch("subprocess.Popen")
    def test_followup_terminal_there_too(self, mock_popen):
        # Set active context
        mock_lensify = str(Path(self.temp_dir.name) / "Lensify")
        self.context.update_interaction(
            action="open_project",
            app="antigravity",
            target_name="Lensify",
            target_path=mock_lensify,
        )

        # User says: "Open a terminal there too"
        intent, params = detect_intent("Open a terminal there too")
        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "launch_terminal_at")
        self.assertEqual(params["params"]["path"], mock_lensify)

        should_cont, pending = route_command("Open a terminal there too")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        mock_popen.assert_called_once()
        args, kwargs = mock_popen.call_args
        self.assertEqual(args[0][1], "--workdir")
        self.assertEqual(args[0][2], mock_lensify)

    def test_ambiguous_folder_asks_clarification(self):
        cand1 = "/home/yusuf/Desktop/Lensify"
        cand2 = "/home/yusuf/Downloads/Lensify"

        with patch.object(
            get_directory_resolver(),
            "resolve_project_directory",
            return_value=(None, [cand1, cand2]),
        ):
            should_cont, pending = route_command("Open my Lensify project in Antigravity.")
            self.assertTrue(should_cont)
            self.assertEqual(pending, "clarify_folder")
            valid_pending, payload = self.context.get_valid_pending()
            self.assertEqual(valid_pending, "clarify_folder")
            self.assertEqual(len(payload["candidates"]), 2)

    @patch("subprocess.Popen")
    def test_confirmation_handling_with_context(self, mock_popen):
        mock_path = "/home/yusuf/Desktop/Lensify"
        mock_bin = "/usr/bin/antigravity"

        # 1. Set valid pending confirmation
        self.context.set_pending("confirm_open_project", {"app_bin": mock_bin, "path": mock_path})

        intent, params = detect_intent("yes, please")
        self.assertEqual(intent, "CONFIRM_ACTION")
        self.assertEqual(params["action"], "confirm_open_project")

        should_cont, pending = route_command("yes, please")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        mock_popen.assert_called_once_with([mock_bin, mock_path], cwd=mock_path)

        # 2. Vague 'yes' without pending confirmation must NOT execute anything
        self.context.clear_pending()
        intent_no_pending, _ = detect_intent("yes, please")
        self.assertEqual(intent_no_pending, "UNCLEAR_SPEECH")

    def test_terminal_regression(self):
        # Ensure Stage 2 terminal bug fix remains solid
        for cmd in ("Can you open new terminal?", "Open a new terminal", "Launch Konsole"):
            intent, params = detect_intent(cmd)
            self.assertEqual(intent, "DESKTOP_ACTION")
            self.assertEqual(params["action"], "open_terminal")

    def test_unrelated_questions_and_noise(self):
        # Genuine questions route to Ollama
        intent_q, _ = detect_intent("What is quantum computing?")
        self.assertEqual(intent_q, "OLLAMA_QUERY")

        intent_who, _ = detect_intent("Who directed Inception?")
        self.assertEqual(intent_who, "OLLAMA_QUERY")

        # Conversational noise does not route to Ollama
        intent_noise, _ = detect_intent("the table is blue")
        self.assertEqual(intent_noise, "UNCLEAR_SPEECH")

    def test_volume_control_intent(self):
        # Set volume
        intent, params = detect_intent("Set volume to 80%")
        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "volume_set")
        self.assertEqual(params["params"]["percentage"], 80)

        # Volume up / down
        intent_up, params_up = detect_intent("Turn volume up")
        self.assertEqual(intent_up, "SMART_ACTION")
        self.assertEqual(params_up["action"], "volume_change")
        self.assertEqual(params_up["params"]["delta"], 10)

        intent_down, params_down = detect_intent("Volume down by 15%")
        self.assertEqual(intent_down, "SMART_ACTION")
        self.assertEqual(params_down["action"], "volume_change")
        self.assertEqual(params_down["params"]["delta"], -15)

        # Mute / unmute
        intent_mute, params_mute = detect_intent("Mute audio")
        self.assertEqual(intent_mute, "SMART_ACTION")
        self.assertEqual(params_mute["action"], "mute_audio")
        self.assertTrue(params_mute["params"]["mute_state"])

        intent_unmute, params_unmute = detect_intent("Unmute sound")
        self.assertEqual(intent_unmute, "SMART_ACTION")
        self.assertEqual(params_unmute["action"], "mute_audio")
        self.assertFalse(params_unmute["params"]["mute_state"])

    def test_brightness_control_intent(self):
        # Set brightness
        intent, params = detect_intent("Set screen brightness to 65%")
        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "brightness_set")
        self.assertEqual(params["params"]["percentage"], 65)

        # Brightness up / down
        intent_up, params_up = detect_intent("Increase brightness")
        self.assertEqual(intent_up, "SMART_ACTION")
        self.assertEqual(params_up["action"], "brightness_change")
        self.assertEqual(params_up["params"]["delta"], 10)

        intent_down, params_down = detect_intent("Dim the screen")
        self.assertEqual(intent_down, "SMART_ACTION")
        self.assertEqual(params_down["action"], "brightness_change")
        self.assertEqual(params_down["params"]["delta"], -10)

    def test_screenshot_and_window_intent(self):
        # Screenshot
        intent, params = detect_intent("Take a screenshot")
        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "screenshot")
        self.assertEqual(params["params"]["mode"], "fullscreen")

        intent_reg, params_reg = detect_intent("Screenshot area")
        self.assertEqual(intent_reg, "SMART_ACTION")
        self.assertEqual(params_reg["action"], "screenshot")
        self.assertEqual(params_reg["params"]["mode"], "region")

        # Window controls
        intent_min, params_min = detect_intent("Minimize current window")
        self.assertEqual(intent_min, "SMART_ACTION")
        self.assertEqual(params_min["action"], "window_control")
        self.assertEqual(params_min["params"]["action"], "minimize")

        intent_desk, params_desk = detect_intent("Show desktop")
        self.assertEqual(intent_desk, "SMART_ACTION")
        self.assertEqual(params_desk["action"], "window_control")
        self.assertEqual(params_desk["params"]["action"], "show_desktop")

    @patch("actions.audio.set_volume", return_value=(True, "Volume set to 75%."))
    @patch("actions.display.set_brightness", return_value=(True, "Brightness set to 80%."))
    @patch("actions.desktop.take_screenshot", return_value=(True, "Screenshot captured."))
    def test_desktop_controls_routing(self, mock_shot, mock_bright, mock_vol):
        # Route volume
        ok, p = route_command("Set volume to 75%")
        self.assertTrue(ok)
        mock_vol.assert_called_once_with(75)

        # Route brightness
        ok_b, p_b = route_command("Set brightness to 80%")
        self.assertTrue(ok_b)
        mock_bright.assert_called_once_with(80)

        # Route screenshot
        ok_s, p_s = route_command("Take a screenshot")
        self.assertTrue(ok_s)
        mock_shot.assert_called_once_with("fullscreen")


if __name__ == "__main__":
    unittest.main()
