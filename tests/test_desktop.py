"""
Unit tests for screenshot capture and KDE window controls.
"""

import unittest
from unittest.mock import MagicMock, patch

from actions.desktop import control_window, maximize_window, minimize_window, show_desktop, switch_window, take_screenshot


class TestDesktopControls(unittest.TestCase):

    @patch("shutil.which", return_value="/usr/bin/spectacle")
    @patch("subprocess.Popen")
    def test_take_screenshot_fullscreen(self, mock_popen, mock_which):
        ok, msg = take_screenshot(mode="fullscreen")
        self.assertTrue(ok)
        self.assertIn("successfully", msg)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertEqual(args, ["/usr/bin/spectacle", "-b", "-f"])

    @patch("shutil.which", return_value="/usr/bin/spectacle")
    @patch("subprocess.Popen")
    def test_take_screenshot_region(self, mock_popen, mock_which):
        ok, msg = take_screenshot(mode="region")
        self.assertTrue(ok)
        self.assertIn("successfully", msg)
        mock_popen.assert_called_once()
        args = mock_popen.call_args[0][0]
        self.assertEqual(args, ["/usr/bin/spectacle", "-r"])

    @patch("shutil.which", return_value=None)
    def test_take_screenshot_missing_spectacle(self, mock_which):
        ok, msg = take_screenshot(mode="fullscreen")
        self.assertFalse(ok)
        self.assertIn("not available", msg)

    @patch("shutil.which", return_value="/usr/bin/qdbus-qt6")
    @patch("subprocess.run")
    def test_control_window_actions(self, mock_run, mock_which):
        mock_run.return_value = MagicMock(returncode=0, stdout="")

        # Test minimize
        ok, msg = minimize_window()
        self.assertTrue(ok)
        mock_run.assert_called_with(
            ["/usr/bin/qdbus-qt6", "org.kde.kglobalaccel", "/component/kwin", "org.kde.kglobalaccel.Component.invokeShortcut", "Window Minimize"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )

        # Test maximize
        ok_max, _ = maximize_window()
        self.assertTrue(ok_max)

        # Test show desktop
        ok_dt, _ = show_desktop()
        self.assertTrue(ok_dt)

        # Test switch window
        ok_sw, _ = switch_window()
        self.assertTrue(ok_sw)

    @patch("shutil.which", return_value="/usr/bin/qdbus-qt6")
    def test_control_window_unsupported_action(self, mock_which):
        ok, msg = control_window("destroy_all_monitors")
        self.assertFalse(ok)
        self.assertIn("Unsupported window action", msg)


if __name__ == "__main__":
    unittest.main()
