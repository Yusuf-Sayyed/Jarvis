"""
Comprehensive unit and regression tests for Media Commands and Logging Configuration.
Verifies:
1. Media stop, pause, resume, play current video, mute, unmute, and volume command routing.
2. Routing commands bypass OLLAMA_QUERY.
3. Truthful failure reporting when no player is available or media operation fails.
4. Normal conversation about music is preserved and routes to OLLAMA_QUERY.
5. Quiet normal console logging vs detailed DEBUG logging.
"""

import io
import os
import unittest
from unittest.mock import MagicMock, patch

from core.context import get_conversation_context
from core.intent import detect_intent
from core.router import route_command
import core.config as config
from interfaces.speech import _log_diag
from actions.media import MediaPlayer


class TestMediaCommandsAndLogging(unittest.TestCase):

    def setUp(self):
        self.context = get_conversation_context()
        self.context.clear_pending()
        self.context.clear_pending_youtube()

    def tearDown(self):
        self.context.clear_pending()
        self.context.clear_pending_youtube()

    # -------------------------------------------------------------------------
    # 1. Stop, Pause, Resume, Play Current Video Commands Bypassing OLLAMA_QUERY
    # -------------------------------------------------------------------------
    def test_stop_music_on_youtube_intent(self):
        phrases = [
            "Can you stop the music which is playing on YouTube?",
            "Stop the music that is playing on YouTube",
            "Stop the music on YouTube",
            "Stop the video on YouTube",
            "Stop the music",
            "Stop playback",
            "Stop playing",
            "Stop playing the music",
        ]
        for phrase in phrases:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for phrase: '{phrase}'")
            self.assertEqual(params.get("action"), "stop", f"Failed action for phrase: '{phrase}'")
            self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_pause_commands_intent(self):
        phrases = [
            "Pause playback",
            "Pause the video",
            "Pause the music",
            "Can you pause the music which is playing on YouTube?",
            "Pause the song",
            "Hold on",
        ]
        for phrase in phrases:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for phrase: '{phrase}'")
            self.assertEqual(params.get("action"), "pause", f"Failed action for phrase: '{phrase}'")
            self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_resume_and_continue_commands_intent(self):
        phrases = [
            "Resume or continue playback",
            "Resume playback",
            "Continue playback",
            "Resume the video",
            "Resume the music",
            "Unpause",
            "Unpause the video",
            "Unpause the music",
        ]
        for phrase in phrases:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for phrase: '{phrase}'")
            self.assertEqual(params.get("action"), "resume", f"Failed action for phrase: '{phrase}'")
            self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_play_current_video_intent(self):
        phrases = [
            "Play the current video",
            "Play this video",
            "Play current video",
            "Play current track",
            "Play current song",
        ]
        for phrase in phrases:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "MEDIA_CONTROL", f"Failed for phrase: '{phrase}'")
            self.assertEqual(params.get("action"), "resume", f"Failed action for phrase: '{phrase}'")
            self.assertNotEqual(intent, "OLLAMA_QUERY")

    # -------------------------------------------------------------------------
    # 2. Mute, Unmute, and Volume Commands
    # -------------------------------------------------------------------------
    def test_mute_and_unmute_commands(self):
        # Mute variations
        for phrase in ["Mute system audio", "Mute the audio", "Mute the volume", "Silence", "Be quiet"]:
            intent, params = detect_intent(phrase)
            self.assertIn(intent, ("MEDIA_CONTROL", "SMART_ACTION"), f"Failed for '{phrase}'")
            self.assertNotEqual(intent, "OLLAMA_QUERY")

        # Unmute variations
        for phrase in ["Unmute system audio", "Unmute the audio", "Unmute the volume"]:
            intent, params = detect_intent(phrase)
            self.assertIn(intent, ("MEDIA_CONTROL", "SMART_ACTION"), f"Failed for '{phrase}'")
            self.assertNotEqual(intent, "OLLAMA_QUERY")

    def test_volume_commands_intent(self):
        phrases = [
            ("Set volume to 100%", 100),
            ("Set volume to 50%", 50),
            ("Increase volume to 80%", 80),
            ("Set volume to 150%", 150),
        ]
        for phrase, expected in phrases:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "SMART_ACTION")
            self.assertEqual(params.get("action"), "volume_set")
            self.assertEqual(params.get("params", {}).get("percentage"), expected)

    # -------------------------------------------------------------------------
    # 3. No Player Available Scenario (Truthful Reporting)
    # -------------------------------------------------------------------------
    @patch("actions.media.get_media_players", return_value=[])
    @patch("actions.media.diagnose_firefox_media_status")
    def test_no_player_available_truthful_failure(self, mock_diag, mock_get_players):
        mock_diag.return_value = {"is_running": False, "mpris_registered": False, "plasma_extension_installed": False}
        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             patch("interfaces.speech.speak") as mock_speak:

            should_continue, pending = route_command("Stop the music")
            self.assertTrue(should_continue)
            self.assertIsNone(pending)

            output = mock_stdout.getvalue()
            self.assertIn("[Intent] MEDIA_CONTROL: stop", output)
            self.assertIn("[JARVIS] Couldn't control playback.", output)
            self.assertIn("No compatible media player was detected", output)

            mock_speak.assert_called_once()
            spoken = mock_speak.call_args[0][0]
            self.assertIn("Couldn't control playback", spoken)

    # -------------------------------------------------------------------------
    # 4. Media Command Failure Reporting (Never False Claims)
    # -------------------------------------------------------------------------
    @patch("actions.media.get_media_players")
    @patch("subprocess.run")
    def test_media_command_failure_reported_truthfully(self, mock_run, mock_get_players):
        player = MediaPlayer(
            bus_name="org.mpris.MediaPlayer2.vlc",
            identity="VLC media player",
            playback_status="Playing",
            can_control=False,  # Cannot control
        )
        mock_get_players.return_value = [player]

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             patch("interfaces.speech.speak") as mock_speak:

            should_continue, pending = route_command("Stop the music")
            self.assertTrue(should_continue)

            output = mock_stdout.getvalue()
            self.assertIn("[Intent] MEDIA_CONTROL: stop", output)
            self.assertIn("[JARVIS] Couldn't control playback.", output)
            self.assertIn("Pause is the available action", output)

            mock_speak.assert_called_once()
            spoken = mock_speak.call_args[0][0]
            self.assertIn("Pause is the available action", spoken)

    # -------------------------------------------------------------------------
    # 5. Media Command Execution Success (Concise Output)
    # -------------------------------------------------------------------------
    @patch("actions.media.stop_playback")
    def test_media_stop_successful_execution(self, mock_stop):
        mock_stop.return_value = (True, "Playback state confirmed: Stopped video playback on Firefox, Sir.", None)

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout, \
             patch("interfaces.speech.speak") as mock_speak:

            route_command("Can you stop the music which is playing on YouTube?")
            output = mock_stdout.getvalue()
            self.assertIn("[Intent] MEDIA_CONTROL: stop", output)
            self.assertIn("[JARVIS] Stopped playback.", output)
            mock_stop.assert_called_once_with("youtube")
            mock_speak.assert_called_once()

    # -------------------------------------------------------------------------
    # 6. Conversational Music Discussions Preserved for Ollama
    # -------------------------------------------------------------------------
    def test_normal_conversation_about_music_bypasses_media_control(self):
        conversational_phrases = [
            "What do you think of Hollywood songs?",
            "Do you like listening to classical music?",
            "Can you play guitar?",
            "Can you play chess?",
            "Tell me about Beethoven's 5th symphony.",
            "Can we discuss rock music?",
            "Why do people enjoy music?",
            "Who is your favorite musical artist?",
            "Shakespeare wrote many famous plays.",
        ]
        for phrase in conversational_phrases:
            intent, _ = detect_intent(phrase)
            self.assertEqual(intent, "OLLAMA_QUERY", f"Phrase '{phrase}' was mistakenly routed to: {intent}")

    # -------------------------------------------------------------------------
    # 7. Quiet Normal Logging vs Detailed DEBUG Logging
    # -------------------------------------------------------------------------
    def test_quiet_normal_logging_suppresses_tts_diagnostics(self):
        # Normal mode: LOG_LEVEL = "INFO", TTS_DIAGNOSTICS = False
        original_level = config.LOG_LEVEL
        original_diag = config.TTS_DIAGNOSTICS
        try:
            config.LOG_LEVEL = "INFO"
            config.TTS_DIAGNOSTICS = False

            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                _log_diag("Synthesis: 0.15s | First audible sound: 0.20s | Playback duration: 1.20s")
                _log_diag("Playback started via pw-play (pid=12345)")
                _log_diag("Audio synthesized: 1.20s | rate=24000Hz | channels=1 | size=57600B")
                output = mock_stdout.getvalue()
                self.assertEqual(output.strip(), "", "Normal mode must not print detailed TTS diagnostics")
        finally:
            config.LOG_LEVEL = original_level
            config.TTS_DIAGNOSTICS = original_diag

    def test_debug_logging_prints_tts_diagnostics(self):
        # Debug mode: LOG_LEVEL = "DEBUG"
        original_level = config.LOG_LEVEL
        original_diag = config.TTS_DIAGNOSTICS
        try:
            config.LOG_LEVEL = "DEBUG"
            config.TTS_DIAGNOSTICS = True

            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                _log_diag("Synthesis: 0.15s | First audible sound: 0.20s | Playback duration: 1.20s")
                output = mock_stdout.getvalue()
                self.assertIn("[TTS Diagnostic]", output)
                self.assertIn("Synthesis: 0.15s", output)
        finally:
            config.LOG_LEVEL = original_level
            config.TTS_DIAGNOSTICS = original_diag

    def test_errors_and_warnings_always_visible(self):
        # Even in normal mode, errors and warnings must remain visible
        original_level = config.LOG_LEVEL
        original_diag = config.TTS_DIAGNOSTICS
        try:
            config.LOG_LEVEL = "INFO"
            config.TTS_DIAGNOSTICS = False

            with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
                _log_diag("All available TTS engines failed to synthesize audio", is_error=True)
                _log_diag("Kokoro TTS unavailable; falling back to secondary engine...", is_warning=True)
                output = mock_stdout.getvalue()
                self.assertIn("[TTS Error] All available TTS engines failed to synthesize audio", output)
                self.assertIn("[TTS Warning] Kokoro TTS unavailable", output)
        finally:
            config.LOG_LEVEL = original_level
            config.TTS_DIAGNOSTICS = original_diag


if __name__ == "__main__":
    unittest.main()
