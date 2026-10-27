"""
Unit and regression tests for media and video playback controls.
Tests intent detection fast-path, polite conversational phrasing, MPRIS capability checks,
graceful handling of unavailable sessions, and multi-session ambiguity resolution.
"""

import unittest
from unittest.mock import MagicMock, call, patch

from actions.media import (
    MediaPlayer,
    diagnose_firefox_media_status,
    get_media_players,
    mute_playback,
    pause_playback,
    resume_playback,
    safe_browser_control_fallback,
    seek_playback,
    select_media_player,
    stop_playback,
)
from core.context import get_conversation_context
from core.intent import detect_intent, normalize_spoken_text
from core.router import route_command


class TestMediaIntentDetection(unittest.TestCase):
    """Tests that natural speech variations route deterministically to media control intents."""

    def test_polite_phrasing_routes_to_pause_not_ollama(self):
        # Specific user requirement: "Is it possible for you to pause this video?"
        phrase = "Is it possible for you to pause this video?"
        intent, params = detect_intent(phrase)
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "pause")
        self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_pause_variations_do_not_become_ollama(self):
        variations = [
            "Pause this video.",
            "Can you pause the video?",
            "Pause playback.",
            "Pause the video",
            "Pause video",
            "Pause media",
            "Could you please pause this video?",
            "Would it be possible for you to pause the video?",
            "Are you able to pause this video?",
            "Pause.",
        ]
        for phrase in variations:
            with self.subTest(phrase=phrase):
                intent, params = detect_intent(phrase)
                self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for {phrase}")
                self.assertEqual(params["action"], "pause")
                self.assertNotEqual(intent, "OLLAMA_QUERY", f"Wrongly routed to Ollama for {phrase}")

    def test_resume_and_play_variations(self):
        variations = [
            ("Resume the video.", "resume"),
            ("Can you resume the video?", "resume"),
            ("Continue playing.", "resume"),
            ("Continue playback", "resume"),
            ("Play.", "resume"),
            ("Play the video", "resume"),
            ("Play this video", "resume"),
            ("Unpause the video", "resume"),
            ("Is it possible for you to resume the video?", "resume"),
        ]
        for phrase, expected_action in variations:
            with self.subTest(phrase=phrase):
                intent, params = detect_intent(phrase)
                self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for {phrase}")
                self.assertEqual(params["action"], expected_action)
                self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_stop_variations(self):
        variations = [
            "Stop the video.",
            "Can you stop the video?",
            "Stop playback.",
            "Stop this video",
            "Stop playing",
            "Could you stop the video?",
            "Is it possible for you to stop playback?",
        ]
        for phrase in variations:
            with self.subTest(phrase=phrase):
                intent, params = detect_intent(phrase)
                self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for {phrase}")
                self.assertEqual(params["action"], "stop")
                self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_mute_and_unmute_variations(self):
        mutes = [
            "Mute the video.",
            "Can you mute the video?",
            "Mute this video",
            "Mute playback",
            "Is it possible for you to mute the video?",
        ]
        for phrase in mutes:
            with self.subTest(phrase=phrase):
                intent, params = detect_intent(phrase)
                self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for {phrase}")
                self.assertEqual(params["action"], "mute")
                self.assertTrue(params.get("mute_state"))
                self.assertNotEqual(intent, "OLLAMA_QUERY")

        unmutes = [
            "Unmute the video.",
            "Can you unmute the video?",
            "Unmute this video",
            "Unmute playback",
            "Would it be possible to unmute the video?",
        ]
        for phrase in unmutes:
            with self.subTest(phrase=phrase):
                intent, params = detect_intent(phrase)
                self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for {phrase}")
                self.assertEqual(params["action"], "mute")
                self.assertFalse(params.get("mute_state"))
                self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_seek_variations(self):
        # Skip forward default (10 seconds)
        intent, params = detect_intent("Skip forward.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "seek")
        self.assertEqual(params["offset"], 10)

        # Skip forward explicit seconds
        intent, params = detect_intent("Skip forward 30 seconds")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "seek")
        self.assertEqual(params["offset"], 30)

        # Go back 10 seconds
        intent, params = detect_intent("Go back 10 seconds.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "seek")
        self.assertEqual(params["offset"], -10)

        # Rewind explicit and default
        intent, params = detect_intent("Rewind 15 seconds")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "seek")
        self.assertEqual(params["offset"], -15)

        intent, params = detect_intent("Rewind")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "seek")
        self.assertEqual(params["offset"], -10)

        # Polite wording for seek
        intent, params = detect_intent("Can you go back 10 seconds?")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params["action"], "seek")
        self.assertEqual(params["offset"], -10)


class TestMediaActionsMPRIS(unittest.TestCase):
    """Tests MPRIS capability checking, execution, and graceful degradation."""

    def setUp(self):
        self.context = get_conversation_context()
        self.context.clear_pending()

    # --- Scenario 1: Firefox exposes an MPRIS session (Confirmed state) ---

    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_firefox_exposes_mpris_pause_confirmed(self, mock_run, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
            can_pause=True,
            can_control=True,
            metadata={"xesam:title": "Test Video"},
        )
        player_paused = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Paused",
            can_pause=True,
            can_control=True,
            metadata={"xesam:title": "Test Video"},
        )
        mock_get_players.side_effect = [[player], [player_paused]]
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = pause_playback()
        self.assertTrue(ok)
        self.assertIn("Playback state confirmed", msg)
        self.assertIn("Paused video playback on Firefox", msg)
        self.assertIn("Test Video", msg)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("Pause", args)

    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_firefox_exposes_mpris_resume_confirmed(self, mock_run, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Paused",
            can_play=True,
            can_control=True,
            metadata={"xesam:title": "Test Video"},
        )
        player_playing = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
            can_play=True,
            can_control=True,
            metadata={"xesam:title": "Test Video"},
        )
        mock_get_players.side_effect = [[player], [player_playing]]
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = resume_playback()
        self.assertTrue(ok)
        self.assertIn("Playback state confirmed", msg)
        self.assertIn("Resumed video playback on Firefox", msg)
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        self.assertIn("Play", args)

    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_firefox_exposes_mpris_stop_confirmed(self, mock_run, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
            can_control=True,
            metadata={"xesam:title": "Test Video"},
        )
        mock_get_players.return_value = [player]
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = stop_playback()
        self.assertTrue(ok)
        self.assertIn("Playback state confirmed", msg)
        self.assertIn("Stopped video playback on Firefox", msg)
        args = mock_run.call_args[0][0]
        self.assertIn("Stop", args)
        self.assertNotIn("kill", args)
        self.assertNotIn("pkill", args)

    # --- Scenario 2: Firefox has NO MPRIS session (Dispatched unverified with honest explanation) ---

    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    @patch("subprocess.run")
    def test_firefox_no_mpris_pause_unverified(self, mock_run, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": True, "mpris_registered": False, "plasma_extension_installed": False}
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = pause_playback()
        self.assertFalse(ok)  # Never claim confirmed success when unverified
        self.assertIn("could not be verified", msg)
        self.assertIn("Plasma Browser Integration", msg)

    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    @patch("subprocess.run")
    def test_firefox_no_mpris_resume_unverified(self, mock_run, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": True, "mpris_registered": False, "plasma_extension_installed": False}
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = resume_playback()
        self.assertFalse(ok)
        self.assertIn("could not be verified", msg)
        self.assertIn("Plasma Browser Integration", msg)

    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    @patch("subprocess.run")
    def test_firefox_no_mpris_stop_unverified(self, mock_run, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": True, "mpris_registered": False, "plasma_extension_installed": False}
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = stop_playback()
        self.assertFalse(ok)
        self.assertIn("could not be verified", msg)

    # --- Scenario 3: No media is playing / Browser not running ---

    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    def test_no_media_playing_pause(self, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": False, "mpris_registered": False, "plasma_extension_installed": False}
        ok, msg, candidates = pause_playback()
        self.assertFalse(ok)
        self.assertIn("No active media playback session", msg)

    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    def test_no_media_playing_resume(self, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": False, "mpris_registered": False, "plasma_extension_installed": False}
        ok, msg, candidates = resume_playback()
        self.assertFalse(ok)
        self.assertIn("No active media playback session", msg)

    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    def test_no_media_playing_stop(self, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": False, "mpris_registered": False, "plasma_extension_installed": False}
        ok, msg, candidates = stop_playback()
        self.assertFalse(ok)
        self.assertIn("No active media playback session", msg)

    # --- Scenario 4: Multiple players available ---

    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_multiple_players_pause_prefers_playing(self, mock_run, mock_get_players):
        vlc = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.vlc",
            identity="VLC media player",
            playback_status="Paused",
            can_pause=True,
        )
        firefox = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
            can_pause=True,
        )
        mock_get_players.return_value = [vlc, firefox]
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = pause_playback()
        self.assertTrue(ok)
        self.assertIn("Firefox", msg)

    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_multiple_players_resume_prefers_paused(self, mock_run, mock_get_players):
        vlc = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.vlc",
            identity="VLC media player",
            playback_status="Stopped",
            can_play=True,
        )
        firefox = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Paused",
            can_play=True,
        )
        mock_get_players.return_value = [vlc, firefox]
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = resume_playback()
        self.assertTrue(ok)
        self.assertIn("Firefox", msg)

    @patch("actions.media.get_media_players")
    def test_multi_session_ambiguity_prompts_clarification(self, mock_get_players):
        playing_vlc = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.vlc",
            identity="VLC media player",
            playback_status="Playing",
        )
        playing_firefox = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
        )
        mock_get_players.return_value = [playing_vlc, playing_firefox]

        selected, candidates, err = select_media_player([playing_vlc, playing_firefox], action="pause")
        self.assertIsNone(selected)
        self.assertIsNotNone(candidates)
        self.assertEqual(len(candidates), 2)
        self.assertIn("VLC", candidates)
        self.assertIn("Firefox", candidates)

    @patch("actions.media.get_media_players")
    def test_route_command_ambiguity_handling(self, mock_get_players):
        playing_vlc = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.vlc",
            identity="VLC media player",
            playback_status="Playing",
        )
        playing_firefox = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
        )
        mock_get_players.return_value = [playing_vlc, playing_firefox]

        should_cont, pending = route_command("Pause this video.")
        self.assertTrue(should_cont)
        self.assertEqual(pending, "clarify_media_player")
        valid_pending, payload = self.context.get_valid_pending()
        self.assertEqual(valid_pending, "clarify_media_player")
        self.assertEqual(len(payload["candidates"]), 2)

    # --- Capability Guard Tests ---

    @patch("actions.media.get_media_players")
    def test_unsupported_seek_capability_does_not_produce_false_success(self, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
            can_seek=False,
            can_control=True,
        )
        mock_get_players.return_value = [player]

        ok, msg, candidates = seek_playback(10)
        self.assertFalse(ok)
        self.assertIn("Seeking is not supported by Firefox", msg)
        self.assertIsNone(candidates)

    @patch("actions.media.get_media_players")
    def test_unsupported_pause_capability_does_not_produce_false_success(self, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.dummy",
            identity="Dummy Player",
            playback_status="Playing",
            can_pause=False,
            can_control=False,
        )
        mock_get_players.return_value = [player]

        ok, msg, candidates = pause_playback()
        self.assertFalse(ok)
        self.assertIn("Pausing is not supported", msg)

    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_successful_seek_negative_offset_formatting(self, mock_run, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.firefox.instance_1",
            identity="Mozilla Firefox",
            playback_status="Playing",
            can_seek=True,
            can_control=True,
        )
        mock_get_players.return_value = [player]
        mock_run.return_value = MagicMock(returncode=0, stdout="", stderr="")

        ok, msg, candidates = seek_playback(-10)
        self.assertTrue(ok)
        self.assertIn("Skipped back 10 seconds on Firefox", msg)

        args = mock_run.call_args[0][0]
        self.assertIn("Seek", args)
        self.assertIn("x", args)
        self.assertIn("--", args)
        self.assertIn("-10000000", args)


if __name__ == "__main__":
    unittest.main()
