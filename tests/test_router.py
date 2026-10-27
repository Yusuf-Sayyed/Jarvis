"""
Unit tests for command routing: YouTube playback, browser tab actions, and confirmation flows.
"""

import unittest
from unittest.mock import MagicMock, patch
from core.router import route_command


class TestRouter(unittest.TestCase):

    def test_exit_command(self):
        should_continue, pending = route_command("exit jarvis")
        self.assertFalse(should_continue)
        self.assertIsNone(pending)

    def test_close_tab_confirmation_flow(self):
        # 1. User says "close this tab" -> asks for confirmation
        should_continue, pending = route_command("close this tab")
        self.assertTrue(should_continue)
        self.assertEqual(pending, "close_tab")

        # 2. User says "no" -> cancels action
        should_continue, pending = route_command("no", pending_action="close_tab")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)

        # 3. User says "can you close the current tab?"
        should_continue, pending = route_command("can you close the current tab?")
        self.assertTrue(should_continue)
        self.assertEqual(pending, "close_tab")

        # 4. User says "yes" -> confirms and clears pending action
        should_continue, pending = route_command("yes", pending_action="close_tab")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)

    @patch("actions.browser.open_firefox_tab")
    def test_open_new_tab(self, mock_firefox_tab):
        should_continue, pending = route_command("open a new tab")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)
        mock_firefox_tab.assert_called_once()

    @patch("actions.browser.play_youtube_video")
    def test_youtube_playback_routing(self, mock_play):
        should_continue, pending = route_command("play relaxing music on youtube")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)
        mock_play.assert_called_once_with("relaxing music")

    @patch("actions.browser.open_first_youtube_result")
    def test_youtube_first_result_routing(self, mock_first_result):
        should_continue, pending = route_command("open the first youtube result")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)
        mock_first_result.assert_called_once()

    def test_search_and_play_prompts(self):
        # 1. Play prompt when title is missing
        should_continue, pending = route_command("play a video on youtube")
        self.assertTrue(should_continue)
        self.assertEqual(pending, "youtube_play")

        # 2. Search prompt when query is missing
        should_continue, pending = route_command("search youtube")
        self.assertTrue(should_continue)
        self.assertEqual(pending, "search_youtube")

        # 3. Unclear speech does not crash or exit
        should_continue, pending = route_command("um")
        self.assertTrue(should_continue)
        self.assertIsNone(pending)

    @patch("actions.desktop.open_terminal")
    def test_terminal_routing(self, mock_open_term):
        # Verify terminal command variations route cleanly without prompting or exit
        for phrase in ("open terminal", "can you open new terminal?", "launch konsole", "start terminal for me"):
            should_continue, pending = route_command(phrase)
            self.assertTrue(should_continue)
            self.assertIsNone(pending)
        self.assertEqual(mock_open_term.call_count, 4)

    @patch("subprocess.Popen")
    def test_open_konsole_in_project_folder_routes_to_smart_action(self, mock_popen):
        """
        Regression test: 'Open Konsole in my Lensify project folder.' must NOT be hijacked
        as generic open_terminal; it must route to smart action with target project path.
        """
        with patch("actions.resolver.DirectoryResolver.resolve_project_directory", return_value=("/home/yusuf/Desktop/Lensify", ["/home/yusuf/Desktop/Lensify"])):
            should_continue, pending = route_command("Open Konsole in my Lensify project folder.")
            self.assertTrue(should_continue)
            self.assertIsNone(pending)
            mock_popen.assert_called_once()
            args = mock_popen.call_args[0][0]
            self.assertIn("konsole", args[0].lower())
            self.assertIn("--workdir", args)
            self.assertIn("/home/yusuf/Desktop/Lensify", args)


if __name__ == "__main__":
    unittest.main()
