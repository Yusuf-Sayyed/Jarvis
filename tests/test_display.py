"""
Unit tests for display and brightness controls using KDE Solid PowerManagement D-Bus.
"""

import unittest
from unittest.mock import MagicMock, patch

from actions.display import change_brightness, get_brightness_status, set_brightness


class TestDisplayControls(unittest.TestCase):

    @patch("actions.display._get_qdbus_bin", return_value="/usr/bin/qdbus-qt6")
    @patch("subprocess.run")
    def test_get_brightness_status(self, mock_run, mock_qdbus):
        # 1st call: brightnessMax (10000), 2nd call: brightness (4000)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="4000\n"),
        ]

        cur, max_val, pct = get_brightness_status()
        self.assertEqual(cur, 4000)
        self.assertEqual(max_val, 10000)
        self.assertEqual(pct, 40)

    @patch("actions.display._get_qdbus_bin", return_value="/usr/bin/qdbus-qt6")
    @patch("subprocess.run")
    def test_set_brightness_clamped(self, mock_run, mock_qdbus):
        # Query status (10000 max), then setBrightness, then query status (7500)
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="5000\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="7500\n"),
        ]

        ok, msg = set_brightness(75)
        self.assertTrue(ok)
        self.assertIn("75%", msg)

        # Verify setBrightness call with 7500 raw value
        mock_run.assert_any_call(
            [
                "/usr/bin/qdbus-qt6",
                "org.kde.Solid.PowerManagement",
                "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                "org.kde.Solid.PowerManagement.Actions.BrightnessControl.setBrightness",
                "7500",
            ],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )

    @patch("actions.display._get_qdbus_bin", return_value="/usr/bin/qdbus-qt6")
    @patch("subprocess.run")
    def test_set_brightness_safe_minimum_enforced(self, mock_run, mock_qdbus):
        # Attempt to set to 0% -> should clamp to 5% safe minimum
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="2500\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="500\n"),
        ]

        ok, msg = set_brightness(0)
        self.assertTrue(ok)
        self.assertIn("5%", msg)

    @patch("actions.display._get_qdbus_bin", return_value="/usr/bin/qdbus-qt6")
    @patch("subprocess.run")
    def test_change_brightness_relative_delta(self, mock_run, mock_qdbus):
        # Current is 30%, increase by 20% -> 50%
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="3000\n"),
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="3000\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="10000\n"),
            MagicMock(returncode=0, stdout="5000\n"),
        ]

        ok, msg = change_brightness(20)
        self.assertTrue(ok)
        self.assertIn("50%", msg)

    @patch("actions.display._get_qdbus_bin", return_value=None)
    def test_qdbus_missing_returns_honest_failure(self, mock_qdbus):
        ok, msg = set_brightness(50)
        self.assertFalse(ok)
        self.assertIn("not available", msg)


if __name__ == "__main__":
    unittest.main()
