"""
Comprehensive regression tests for YouTube search, playback, follow-up context resolution,
volume execution, media controls, and conversation preservation.
"""

import unittest
from unittest.mock import MagicMock, patch

from core.context import get_conversation_context
from core.intent import detect_intent
from core.router import route_command
from actions import browser


class TestYouTubePlaybackAndVolume(unittest.TestCase):

    def setUp(self):
        self.context = get_conversation_context()
        self.context.clear_pending()
        self.context.clear_pending_youtube()
        self.context.last_youtube_query = None
        browser.LAST_YOUTUBE_QUERY = None
        browser.LAST_YOUTUBE_URL = None

    def tearDown(self):
        self.context.clear_pending()
        self.context.clear_pending_youtube()
        self.context.last_youtube_query = None
        browser.LAST_YOUTUBE_QUERY = None
        browser.LAST_YOUTUBE_URL = None

    # -------------------------------------------------------------------------
    # 1. Combined YouTube Search + Playback + Volume Request
    # -------------------------------------------------------------------------
    def test_combined_youtube_search_play_and_volume_intent(self):
        phrase = "Okay, on YouTube search for Hollywood songs and play it at 100% volume"
        intent, params = detect_intent(phrase)
        self.assertEqual(intent, "YOUTUBE_PLAY")
        self.assertEqual(params.get("query"), "hollywood songs")
        self.assertEqual(params.get("volume"), 100)
        self.assertTrue(params.get("auto_play"))

    def test_combined_youtube_search_play_and_volume_execution(self):
        phrase = "Okay, on YouTube search for Hollywood songs and play it at 100% volume"
        with patch("actions.audio.set_volume") as mock_vol, \
             patch("actions.browser.play_youtube_video") as mock_play, \
             patch("interfaces.speech.speak") as mock_speak:

            mock_vol.return_value = (True, "Volume set to 100%.")
            mock_play.return_value = {
                "success": True,
                "stage": "video_opened",
                "url": "https://www.youtube.com/watch?v=mock1234567",
                "query": "hollywood songs",
                "message": "Opened 'hollywood songs' on YouTube, Sir. If blocked by browser autoplay, click the video to play.",
            }

            should_continue, pending = route_command(phrase)
            self.assertTrue(should_continue)
            self.assertIsNone(pending)

            # Volume was set to exactly 100%
            mock_vol.assert_called_once_with(100)
            # Browser playback was initiated with extracted query
            mock_play.assert_called_once_with("hollywood songs")
            # Truthful status was spoken combining volume and video opened
            mock_speak.assert_called_once()
            spoken_text = mock_speak.call_args[0][0]
            self.assertIn("Volume set to 100%", spoken_text)
            self.assertIn("hollywood songs", spoken_text)

    # -------------------------------------------------------------------------
    # 2. "Yes, play it, please" / "Yes, please just play it" with valid pending context
    # -------------------------------------------------------------------------
    def test_followup_play_with_pending_youtube_request(self):
        # Set real pending YouTube search in context
        self.context.set_pending_youtube("King Trailer")

        # Test both natural phrasing variants
        intent1, params1 = detect_intent("Yes, please just play it")
        self.assertEqual(intent1, "YOUTUBE_PLAY")
        self.assertEqual(params1.get("query"), "King Trailer")
        self.assertTrue(params1.get("auto_play"))

        intent2, params2 = detect_intent("Yes, play it, please")
        self.assertEqual(intent2, "YOUTUBE_PLAY")
        self.assertEqual(params2.get("query"), "King Trailer")
        self.assertTrue(params2.get("auto_play"))

    def test_followup_play_with_pending_execution(self):
        self.context.set_pending_youtube("King Trailer")

        with patch("actions.browser.play_youtube_video") as mock_play, \
             patch("interfaces.speech.speak") as mock_speak:

            mock_play.return_value = {
                "success": True,
                "stage": "video_opened",
                "url": "https://www.youtube.com/watch?v=kingtrailer",
                "query": "King Trailer",
                "message": "Opened 'King Trailer' on YouTube, Sir.",
            }

            should_continue, pending = route_command("Yes, please just play it")
            self.assertTrue(should_continue)
            self.assertIsNone(pending)

            # Resolved against pending query without inventing a new title
            mock_play.assert_called_once_with("King Trailer")
            mock_speak.assert_called_once()
            self.assertIn("King Trailer", mock_speak.call_args[0][0])

    # -------------------------------------------------------------------------
    # 3. "Yes, play it" with NO pending request
    # -------------------------------------------------------------------------
    def test_followup_play_with_no_pending_request(self):
        # Verify no pending state exists
        self.context.clear_pending()
        self.context.clear_pending_youtube()
        self.context.last_youtube_query = None

        intent1, _ = detect_intent("Yes, please just play it")
        self.assertEqual(intent1, "YOUTUBE_PLAY_PROMPT")

        intent2, _ = detect_intent("Yes, play it, please")
        self.assertEqual(intent2, "YOUTUBE_PLAY_PROMPT")

    def test_followup_play_with_no_pending_execution_asks_what_to_play(self):
        self.context.clear_pending()
        self.context.clear_pending_youtube()

        with patch("actions.browser.play_youtube_video") as mock_play, \
             patch("interfaces.speech.speak") as mock_speak:

            should_continue, pending = route_command("Yes, play it, please")
            self.assertTrue(should_continue)
            self.assertEqual(pending, "youtube_play")

            # Must NOT call playback with invented search query
            mock_play.assert_not_called()
            # Must ask what the user wants to play
            mock_speak.assert_called_once()
            spoken = mock_speak.call_args[0][0].lower()
            self.assertIn("what video or song would you like me to play", spoken)

    # -------------------------------------------------------------------------
    # 4. YouTube search without playback
    # -------------------------------------------------------------------------
    def test_youtube_search_without_playback(self):
        phrase = "Find the Doomsday trailer on YouTube"
        intent, params = detect_intent(phrase)
        self.assertEqual(intent, "BROWSER_SEARCH")
        self.assertEqual(params.get("engine"), "youtube")
        self.assertEqual(params.get("query"), "the doomsday trailer")

    def test_youtube_search_execution_stores_pending_context(self):
        phrase = "Find the Doomsday trailer on YouTube"
        with patch("actions.browser.search_web") as mock_search, \
             patch("interfaces.speech.speak") as mock_speak:

            mock_search.return_value = {
                "success": True,
                "stage": "search_page_opened",
                "url": "https://www.youtube.com/results?search_query=the+doomsday+trailer",
                "query": "the doomsday trailer",
                "engine": "youtube",
            }

            should_continue, pending = route_command(phrase)
            self.assertTrue(should_continue)
            self.assertIsNone(pending)

            mock_search.assert_called_once_with("the doomsday trailer", "youtube")
            # Searching stores the query for follow-up resolution
            browser.search_web("the doomsday trailer", "youtube")
            self.assertEqual(self.context.get_recent_youtube_query(), "the doomsday trailer")

    # -------------------------------------------------------------------------
    # 5. Media pause / resume
    # -------------------------------------------------------------------------
    def test_media_controls_pause_and_resume(self):
        intent_pause, params_pause = detect_intent("Pause the video")
        self.assertEqual(intent_pause, "MEDIA_CONTROL")
        self.assertEqual(params_pause.get("action"), "pause")

        intent_resume, params_resume = detect_intent("Resume playback")
        self.assertEqual(intent_resume, "MEDIA_CONTROL")
        self.assertEqual(params_resume.get("action"), "resume")

    def test_media_control_execution(self):
        with patch("actions.media.pause_playback", return_value=(True, "Playback paused.", None)) as mock_pause, \
             patch("actions.media.resume_playback", return_value=(True, "Playback resumed.", None)) as mock_resume:

            route_command("Pause the video")
            mock_pause.assert_called_once_with(None)

            route_command("Resume playback")
            mock_resume.assert_called_once_with(None)

    # -------------------------------------------------------------------------
    # 6. Volume setting (up to 150%)
    # -------------------------------------------------------------------------
    def test_volume_setting_intent(self):
        for phrase, expected_vol in [
            ("Set volume to 100%", 100),
            ("Increase volume to 80%", 80),
            ("Set volume to 150%", 150),
        ]:
            intent, params = detect_intent(phrase)
            self.assertEqual(intent, "SMART_ACTION")
            self.assertEqual(params.get("action"), "volume_set")
            self.assertEqual(params.get("params", {}).get("percentage"), expected_vol)

    def test_play_it_at_100_percent_volume_with_pending(self):
        self.context.set_pending_youtube("Hollywood songs")
        intent, params = detect_intent("Play it at 100% volume")
        self.assertEqual(intent, "YOUTUBE_PLAY")
        self.assertEqual(params.get("query"), "Hollywood songs")
        self.assertEqual(params.get("volume"), 100)

    # -------------------------------------------------------------------------
    # 7. Browser playback failure and truthful status reporting
    # -------------------------------------------------------------------------
    def test_browser_playback_failure_reporting(self):
        with patch("actions.browser.play_youtube_video") as mock_play, \
             patch("interfaces.speech.speak") as mock_speak:

            mock_play.return_value = {
                "success": False,
                "stage": "failed",
                "url": None,
                "query": "unavailable video",
                "message": "Failed to launch browser: Executable not found",
            }

            route_command("play unavailable video on youtube")
            mock_speak.assert_called_once()
            spoken = mock_speak.call_args[0][0]
            # Must report the actual failure honestly, not claim playing
            self.assertIn("Failed", spoken)

    def test_browser_autoplay_blocked_truthful_reporting(self):
        with patch("actions.browser.play_youtube_video") as mock_play, \
             patch("interfaces.speech.speak") as mock_speak:

            mock_play.return_value = {
                "success": True,
                "stage": "video_opened",
                "url": "https://www.youtube.com/watch?v=mocktest",
                "query": "trailer",
                "message": "Opened 'trailer' on YouTube, Sir. If blocked by browser autoplay, click the video to play.",
            }

            route_command("play trailer on youtube")
            mock_speak.assert_called_once()
            spoken = mock_speak.call_args[0][0]
            # Explains that video was opened and provides practical next step for autoplay
            self.assertIn("Opened 'trailer'", spoken)
            self.assertIn("autoplay", spoken)

    # -------------------------------------------------------------------------
    # 8. Ordinary conversation mentioning YouTube or 'play' preserved for Ollama
    # -------------------------------------------------------------------------
    def test_ordinary_conversation_preservation(self):
        conversational_phrases = [
            "Can you play chess?",
            "Why do children play games?",
            "What do you think of Hollywood songs?",
            "Tell me about Shakespeare plays",
            "What is your favorite YouTube channel?",
            "Music plays a big role in culture",
            "Do you play any musical instruments?",
        ]

        for phrase in conversational_phrases:
            intent, params = detect_intent(phrase)
            self.assertEqual(
                intent,
                "OLLAMA_QUERY",
                f"Conversational phrase '{phrase}' was incorrectly routed to '{intent}' instead of OLLAMA_QUERY",
            )


if __name__ == "__main__":
    unittest.main()
