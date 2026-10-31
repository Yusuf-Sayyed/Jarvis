"""
Unit tests for JARVIS Agents.md upgrades:
  1. Context-aware conversations & relative project file resolution
  2. Natural media and desktop follow-ups (YouTube multi-result & index selection)
  3. Faster speech & safe interruption without cutting off words
  4. Minimal one-word KDE status widget & runtime state lifecycle
"""

import os
import shutil
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from actions.browser import get_youtube_video_results, open_youtube_result, play_youtube_video
from actions.resolver import FileResolver, get_file_resolver
from core.context import ConversationContext, get_conversation_context
from core.intent import detect_intent, parse_media_command, parse_youtube_play
from core.status import (
    DEFAULT_STATUS,
    VALID_STATUSES,
    clear_runtime_status,
    get_runtime_status,
    get_status_file_path,
    set_runtime_status,
)
from interfaces.speech import (
    POST_SPEECH_COOLDOWN_SECONDS,
    is_in_cooldown,
    is_speaking,
    reset_speech_state,
    set_cooldown,
    stop_speech,
)


class TestContextAndFileResolution(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self.context = ConversationContext()

    def tearDown(self):
        shutil.rmtree(self.tmp_dir, ignore_errors=True)

    def test_current_project_tracking_and_expiration(self):
        """Tests that current project context tracks path and respects TTL."""
        self.context.PROJECT_TTL_SECONDS = 0.5
        proj_dir = os.path.join(self.tmp_dir, "myproject")
        os.makedirs(proj_dir, exist_ok=True)

        self.context.set_current_project("myproject", proj_dir)
        name, path = self.context.get_current_project()
        self.assertEqual(name, "myproject")
        self.assertEqual(path, proj_dir)

        # Wait for TTL expiration
        time.sleep(0.6)
        exp_name, exp_path = self.context.get_current_project()
        self.assertIsNone(exp_name)
        self.assertIsNone(exp_path)

    def test_recent_file_tracking_and_validation(self):
        """Tests that recent file requires existence on disk and respects TTL."""
        file_path = os.path.join(self.tmp_dir, "script.py")
        with open(file_path, "w") as f:
            f.write("print('hello')\n")

        self.context.set_recent_file("script.py", file_path)
        name, path = self.context.get_recent_file()
        self.assertEqual(name, "script.py")
        self.assertEqual(path, file_path)

        # Deleting the file invalidates context immediately (no hallucinated files)
        os.unlink(file_path)
        name_del, path_del = self.context.get_recent_file()
        self.assertIsNone(name_del)
        self.assertIsNone(path_del)

    def test_resolve_main_file_in_project(self):
        """Tests resolving canonical entrypoint in a project folder."""
        proj_dir = os.path.join(self.tmp_dir, "lensify")
        os.makedirs(proj_dir, exist_ok=True)
        main_py = os.path.join(proj_dir, "main.py")
        with open(main_py, "w") as f:
            f.write("# main\n")

        resolver = FileResolver()
        best, candidates = resolver.resolve_relative_file(proj_dir, "the main file")
        self.assertEqual(best, main_py)
        self.assertIn(main_py, candidates)

    def test_resolve_project_named_file(self):
        """Tests resolving jarvis.py inside a jarvis project directory."""
        proj_dir = os.path.join(self.tmp_dir, "jarvis")
        os.makedirs(proj_dir, exist_ok=True)
        jarvis_py = os.path.join(proj_dir, "jarvis.py")
        with open(jarvis_py, "w") as f:
            f.write("# jarvis entrypoint\n")

        resolver = FileResolver()
        best, candidates = resolver.resolve_relative_file(proj_dir, "main")
        self.assertEqual(best, jarvis_py)

    def test_resolve_specific_file_readme(self):
        """Tests resolving readme relative to current project."""
        proj_dir = os.path.join(self.tmp_dir, "project_alpha")
        os.makedirs(proj_dir, exist_ok=True)
        readme = os.path.join(proj_dir, "README.md")
        with open(readme, "w") as f:
            f.write("# Readme\n")

        resolver = FileResolver()
        best, candidates = resolver.resolve_relative_file(proj_dir, "readme")
        self.assertEqual(best, readme)

    def test_resolve_ambiguous_file_returns_candidates(self):
        """Tests that when multiple files match, best is None and candidates list is returned."""
        proj_dir = os.path.join(self.tmp_dir, "multi")
        os.makedirs(proj_dir, exist_ok=True)
        f1 = os.path.join(proj_dir, "client.py")
        f2 = os.path.join(proj_dir, "server.py")
        with open(f1, "w") as f: f.write("")
        with open(f2, "w") as f: f.write("")

        resolver = FileResolver()
        best, candidates = resolver.resolve_relative_file(proj_dir, "main file")
        self.assertIsNone(best)
        self.assertEqual(len(candidates), 2)
        self.assertIn(f1, candidates)
        self.assertIn(f2, candidates)


class TestMediaAndYouTubeFollowups(unittest.TestCase):
    def setUp(self):
        self.context = get_conversation_context()
        self.context.clear_temporary_context()

    def test_parse_youtube_second_result(self):
        """Tests parsing 'play the second result' and 'play the 3rd video'."""
        intent1, params1 = detect_intent("play the second result")
        self.assertEqual(intent1, "YOUTUBE_RESULT_SELECT")
        self.assertEqual(params1.get("index"), 2)

        intent2, params2 = detect_intent("open the third video")
        self.assertEqual(intent2, "YOUTUBE_RESULT_SELECT")
        self.assertEqual(params2.get("index"), 3)

    def test_parse_skip_media(self):
        """Tests that 'skip this' and 'skip' route to media control next."""
        act1, _ = parse_media_command("skip this")
        self.assertEqual(act1, "next")

        act2, _ = parse_media_command("skip")
        self.assertEqual(act2, "next")

    def test_youtube_result_caching_and_index_playback(self):
        """Tests storing YouTube search results in context and picking by index."""
        mock_results = [
            {"title": "Video 1", "url": "https://www.youtube.com/watch?v=vid11111111", "video_id": "vid11111111"},
            {"title": "Video 2", "url": "https://www.youtube.com/watch?v=vid22222222", "video_id": "vid22222222"},
            {"title": "Video 3", "url": "https://www.youtube.com/watch?v=vid33333333", "video_id": "vid33333333"},
        ]
        self.context.set_youtube_results("relaxing music", mock_results, stage="search_page_opened")

        res_item = self.context.get_youtube_result_by_index(2)
        self.assertIsNotNone(res_item)
        self.assertEqual(res_item["url"], "https://www.youtube.com/watch?v=vid22222222")

        with patch("subprocess.Popen") as mock_popen, patch("actions.media.get_media_players", return_value=[]):
            mock_proc = MagicMock()
            mock_proc.poll.return_value = None
            mock_popen.return_value = mock_proc

            res = open_youtube_result(result_index=2)
            self.assertTrue(res.get("success"))
            self.assertEqual(res.get("url"), "https://www.youtube.com/watch?v=vid22222222")
            mock_popen.assert_called()


class TestSpeechAndInterruption(unittest.TestCase):
    def setUp(self):
        reset_speech_state()

    def tearDown(self):
        reset_speech_state()

    def test_stop_speech_for_interruption_bypasses_cooldown(self):
        """Tests that safe interruption stops playback without setting a cooldown that cuts off words."""
        # Standard stop sets cooldown
        set_cooldown(2.0)
        self.assertTrue(is_in_cooldown())

        # Interruption clears cooldown immediately
        stop_speech(for_interruption=True)
        self.assertFalse(is_speaking())
        self.assertFalse(is_in_cooldown())

    def test_normal_stop_speech_preserves_cooldown(self):
        """Tests that normal completion or shutdown maintains cooldown to prevent self-transcription."""
        stop_speech(for_interruption=False)
        self.assertTrue(is_in_cooldown())


class TestStatusWidgetAndRuntimeState(unittest.TestCase):
    def setUp(self):
        clear_runtime_status()

    def tearDown(self):
        clear_runtime_status()

    def test_valid_status_transitions(self):
        """Tests setting and reading valid single-word statuses."""
        for st in ("STANDBY", "LISTENING", "THINKING", "SPEAKING", "ERROR"):
            ok = set_runtime_status(st)
            self.assertTrue(ok)
            data = get_runtime_status()
            self.assertEqual(data["status"], st)

    def test_invalid_status_defaults_to_error(self):
        """Tests that invalid status strings are rejected and mapped safely to ERROR."""
        set_runtime_status("INVALID_CUSTOM_LONG_PHRASE")
        data = get_runtime_status()
        self.assertEqual(data["status"], "ERROR")

    def test_stale_process_detection(self):
        """Tests that if recorded process PID is dead, status automatically reverts to STANDBY."""
        # Use an impossible/dead PID
        dead_pid = 99999999
        path = get_status_file_path()
        import json
        with open(path, "w") as f:
            json.dump({"status": "LISTENING", "pid": dead_pid, "timestamp": time.time()}, f)

        data = get_runtime_status()
        self.assertEqual(data["status"], "STANDBY")
        self.assertIn("process", data.get("details", ""))

    def test_plasmoid_files_installed(self):
        """Tests that the Plasma 6 plasmoid metadata and UI QML are present and syntactically valid."""
        plasmoid_dir = Path.home() / ".local" / "share" / "plasma" / "plasmoids" / "org.kde.plasma.jarvisstatus"
        self.assertTrue(plasmoid_dir.is_dir(), f"Plasmoid directory missing: {plasmoid_dir}")

        metadata_file = plasmoid_dir / "metadata.json"
        self.assertTrue(metadata_file.is_file(), "metadata.json missing")

        import json
        with open(metadata_file, "r") as f:
            meta = json.load(f)
        self.assertEqual(meta.get("KPlugin", {}).get("Id"), "org.kde.plasma.jarvisstatus")
        self.assertEqual(meta.get("KPackageStructure"), "Plasma/Applet")

        qml_file = plasmoid_dir / "contents" / "ui" / "main.qml"
        self.assertTrue(qml_file.is_file(), "main.qml missing")
        with open(qml_file, "r") as f:
            qml_content = f.read()
        self.assertIn("STANDBY", qml_content)
        self.assertIn("LISTENING", qml_content)
        self.assertIn("PlasmoidItem", qml_content)


class TestMultiTurnConversationEndToEnd(unittest.TestCase):
    def setUp(self):
        self.context = get_conversation_context()
        self.context.clear_temporary_context()

    @patch("subprocess.Popen")
    @patch("interfaces.speech.speak")
    def test_multi_turn_project_followup_sequence(self, mock_speak, mock_popen):
        """
        Tests the multi-turn conversational sequence from Agents.md:
          1. "Open my JARVIS project" -> sets current project
          2. "Open the main file" -> resolves jarvis.py
          3. "Run it" -> runs jarvis.py
          4. "Actually, open it in Antigravity" -> switches app to Antigravity
        """
        from core.router import route_command

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        # 1. "Open my JARVIS project"
        route_command("Open my JARVIS project")
        proj_name, proj_path = self.context.get_current_project()
        self.assertEqual(proj_name, "jarvis")
        self.assertIsNotNone(proj_path)
        self.assertTrue(os.path.isdir(proj_path))

        # 2. "Open the main file"
        route_command("Open the main file")
        f_name, f_path = self.context.get_recent_file()
        self.assertEqual(f_name, "jarvis.py")
        self.assertTrue(f_path.endswith("jarvis.py"))

        # 3. "Run it"
        route_command("Run it")
        self.assertTrue(mock_popen.called)

        # 4. "Actually, open it in Antigravity"
        route_command("Actually, open it in Antigravity")
        self.assertIn("antigravity", self.context.last_app.lower())

    @patch("subprocess.Popen")
    @patch("interfaces.speech.speak")
    def test_multi_turn_youtube_followup_sequence(self, mock_speak, mock_popen):
        """
        Tests the natural media follow-up sequence from Agents.md:
          1. Search YouTube for relaxing music
          2. Play the second result
          3. Lower the volume to 30 percent
          4. Skip this
          5. Find instrumental music instead
        """
        from core.router import route_command

        mock_proc = MagicMock()
        mock_proc.poll.return_value = None
        mock_popen.return_value = mock_proc

        with patch("actions.browser.get_youtube_video_results", return_value=[
            {"title": "Track 1", "url": "https://www.youtube.com/watch?v=track111111", "video_id": "track111111"},
            {"title": "Track 2", "url": "https://www.youtube.com/watch?v=track222222", "video_id": "track222222"},
            {"title": "Track 3", "url": "https://www.youtube.com/watch?v=track333333", "video_id": "track333333"},
        ]):
            # 1. Search YouTube for relaxing music
            route_command("Search YouTube for relaxing music")
            results = self.context.get_youtube_results()
            self.assertEqual(len(results), 3)

            # 2. Play the second result
            route_command("Play the second result")
            self.assertEqual(self.context.last_youtube_url, "https://www.youtube.com/watch?v=track222222")

            # 3. Lower the volume to 30 percent
            with patch("actions.audio.set_volume", return_value=(True, "Volume set to 30%")):
                route_command("Lower the volume to 30 percent")

            # 4. Skip this
            with patch("actions.media.next_playback", return_value=(True, "Skipped to next track", None)):
                route_command("Skip this")

            # 5. Find instrumental music instead
            route_command("Find instrumental music instead")
            self.assertEqual(self.context.last_youtube_query, "instrumental music")


if __name__ == "__main__":
    unittest.main()
