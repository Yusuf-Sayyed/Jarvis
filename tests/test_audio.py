"""
Unit tests for audio and volume controls using PipeWire wpctl.
"""

import subprocess
import unittest
from unittest.mock import MagicMock, patch

from actions.audio import change_volume, get_volume_status, set_mute, set_volume


class TestAudioControls(unittest.TestCase):

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_get_volume_status_unmuted(self, mock_run, mock_wpctl):
        mock_run.return_value = MagicMock(returncode=0, stdout="Volume: 0.85\n")
        vol, muted, status_str = get_volume_status()

        self.assertAlmostEqual(vol, 0.85)
        self.assertFalse(muted)
        self.assertEqual(status_str, "85%")

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_get_volume_status_muted(self, mock_run, mock_wpctl):
        mock_run.return_value = MagicMock(returncode=0, stdout="Volume: 0.40 [MUTED]\n")
        vol, muted, status_str = get_volume_status()

        self.assertAlmostEqual(vol, 0.40)
        self.assertTrue(muted)
        self.assertEqual(status_str, "40% [MUTED]")

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_set_volume_within_standard_range(self, mock_run, mock_wpctl):
        # First call: set-volume, second call: get-volume check
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="Volume: 0.70\n"),
            MagicMock(returncode=0, stdout="Volume: 0.70\n"),
        ]

        ok, msg = set_volume(70)
        self.assertTrue(ok)
        self.assertIn("70%", msg)

        # Verify wpctl was called with -l 1.5
        mock_run.assert_any_call(
            ["/usr/bin/wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "70%"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_set_volume_amplification_up_to_150(self, mock_run, mock_wpctl):
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="Volume: 1.40\n"),
            MagicMock(returncode=0, stdout="Volume: 1.40\n"),
        ]

        ok, msg = set_volume(140)
        self.assertTrue(ok)
        self.assertIn("140%", msg)
        self.assertIn("Software amplification", msg)

        mock_run.assert_any_call(
            ["/usr/bin/wpctl", "set-volume", "-l", "1.5", "@DEFAULT_AUDIO_SINK@", "140%"],
            capture_output=True,
            text=True,
            timeout=2.0,
            check=False,
        )

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_change_volume_relative_delta(self, mock_run, mock_wpctl):
        # Query current (0.50), then set (0.65), then verify
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Volume: 0.50\n"),
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="Volume: 0.65\n"),
            MagicMock(returncode=0, stdout="Volume: 0.65\n"),
        ]

        ok, msg = change_volume(15)
        self.assertTrue(ok)
        self.assertIn("65%", msg)

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_set_mute_actions(self, mock_run, mock_wpctl):
        # Test mute True
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="Volume: 0.50 [MUTED]\n"),
        ]
        ok, msg = set_mute(True)
        self.assertTrue(ok)
        self.assertEqual(msg, "Audio muted.")

        # Test unmute False
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout=""),
            MagicMock(returncode=0, stdout="Volume: 0.50\n"),
        ]
        ok_unmute, msg_unmute = set_mute(False)
        self.assertTrue(ok_unmute)
        self.assertIn("unmuted", msg_unmute)

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    def test_set_volume_exceeding_max_limit_fails_without_silent_clamping(self, mock_wpctl):
        ok, msg = set_volume(200)
        self.assertFalse(ok)
        self.assertIn("exceeds maximum supported volume of 150%", msg)

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    def test_set_volume_negative_fails(self, mock_wpctl):
        ok, msg = set_volume(-5)
        self.assertFalse(ok)
        self.assertIn("cannot be negative", msg)

    @patch("actions.audio._get_wpctl_bin", return_value="/usr/bin/wpctl")
    @patch("subprocess.run")
    def test_set_volume_backend_failure(self, mock_run, mock_wpctl):
        mock_run.return_value = MagicMock(returncode=1, stderr="Device or resource busy\n")
        ok, msg = set_volume(80)
        self.assertFalse(ok)
        self.assertIn("Failed to set volume", msg)

    @patch("actions.audio._get_wpctl_bin", return_value=None)
    def test_wpctl_missing_returns_honest_failure(self, mock_wpctl):
        ok, msg = set_volume(50)
        self.assertFalse(ok)
        self.assertIn("not available", msg)


if __name__ == "__main__":
    unittest.main()
