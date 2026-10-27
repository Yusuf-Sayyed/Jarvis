"""
Unit tests for intent detection, speech normalization, and YouTube playback parsing.
"""

import unittest
from core.intent import (
    detect_intent,
    normalize_spoken_text,
    parse_search_command,
    parse_type_command,
    parse_youtube_play,
)


class TestIntentDetection(unittest.TestCase):

    def test_normalization(self):
        self.assertEqual(normalize_spoken_text("you tube"), "youtube")
        self.assertEqual(normalize_spoken_text("goo gle"), "google")
        self.assertEqual(normalize_spoken_text("fire fox"), "firefox")
        self.assertEqual(normalize_spoken_text("down loads"), "downloads")
        self.assertEqual(normalize_spoken_text("new tap"), "new tab")
        self.assertEqual(normalize_spoken_text("close tap"), "close tab")
        self.assertEqual(normalize_spoken_text("this tap"), "this tab")
        self.assertEqual(normalize_spoken_text("hello world..."), "hello world")
        # Conversational prefix stripping
        self.assertEqual(normalize_spoken_text("Can you please open a new tab?"), "open a new tab")
        self.assertEqual(normalize_spoken_text("Hey JARVIS, can you play music on YouTube?"), "play music on youtube")
        self.assertEqual(normalize_spoken_text("Could you close this tab?"), "close this tab")

    def test_youtube_search_vs_direct_playback(self):
        # 1. YouTube Search (results page)
        eng, q = parse_search_command("search youtube for python tutorials")
        self.assertEqual(eng, "youtube")
        self.assertEqual(q, "python tutorials")

        intent, params = detect_intent("search youtube for python tutorials")
        self.assertEqual(intent, "BROWSER_SEARCH")
        self.assertEqual(params["engine"], "youtube")
        self.assertEqual(params["query"], "python tutorials")

        # 2. YouTube Direct Playback
        p_intent, p_q = parse_youtube_play("play iron man trailer on youtube")
        self.assertEqual(p_intent, "YOUTUBE_PLAY")
        self.assertEqual(p_q, "iron man trailer")

        intent, params = detect_intent("play iron man trailer on youtube")
        self.assertEqual(intent, "YOUTUBE_PLAY")
        self.assertEqual(params["query"], "iron man trailer")

        intent, params = detect_intent("can you play relaxing music on youtube?")
        self.assertEqual(intent, "YOUTUBE_PLAY")
        self.assertEqual(params["query"], "relaxing music")

        # 3. Open the first result
        intent, _ = detect_intent("open the first youtube result")
        self.assertEqual(intent, "YOUTUBE_FIRST_RESULT")

        # 4. Play video prompt when no title is given
        intent, _ = detect_intent("play a video on youtube")
        self.assertEqual(intent, "YOUTUBE_PLAY_PROMPT")

        intent, _ = detect_intent("play on youtube")
        self.assertEqual(intent, "YOUTUBE_PLAY_PROMPT")

    def test_search_parsing(self):
        # Direct search with 'for'
        eng, q = parse_search_command("search google for python tutorials")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "python tutorials")

        # 'search on google for...' and 'search on youtube for...'
        eng, q = parse_search_command("search on youtube for iron man videos")
        self.assertEqual(eng, "youtube")
        self.assertEqual(q, "iron man videos")

        eng, q = parse_search_command("search on google for python tutorials")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "python tutorials")

        # 'search for ... on youtube/google'
        eng, q = parse_search_command("search for iron man videos on youtube")
        self.assertEqual(eng, "youtube")
        self.assertEqual(q, "iron man videos")

        # Conversational prefix
        eng, q = parse_search_command("can you search google for python tutorials")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "python tutorials")

        # Trailing speech bleed / noise removal
        eng, q = parse_search_command("search for iron man videos and play the first result")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "iron man videos")

        # 'find ... on google/youtube'
        eng, q = parse_search_command("find the best linux laptops on google")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "the best linux laptops")

        eng, q = parse_search_command("find iron man trailers on youtube")
        self.assertEqual(eng, "youtube")
        self.assertEqual(q, "iron man trailers")

        eng, q = parse_search_command("open a new tab and search for python courses")
        self.assertEqual(eng, "google")
        self.assertEqual(q, "python courses")

        # Search with no query
        eng, q = parse_search_command("search youtube")
        self.assertEqual(eng, "youtube")
        self.assertEqual(q, "")

        intent, params = detect_intent("search youtube")
        self.assertEqual(intent, "SEARCH_PROMPT")
        self.assertEqual(params["engine"], "youtube")

    def test_type_parsing(self):
        content, enter = parse_type_command("type hello world")
        self.assertEqual(content, "hello world")
        self.assertFalse(enter)

        content, enter = parse_type_command("type python installation guide into the search box")
        self.assertEqual(content, "python installation guide")
        self.assertFalse(enter)

        content, enter = parse_type_command("type quantum computing and press enter")
        self.assertEqual(content, "quantum computing")
        self.assertTrue(enter)

    def test_browser_tab_intents(self):
        # Open a new tab
        intent, params = detect_intent("open a new tab")
        self.assertEqual(intent, "DESKTOP_ACTION")
        self.assertEqual(params["action"], "open_firefox_tab")

        intent, params = detect_intent("could you open a new tab?")
        self.assertEqual(intent, "DESKTOP_ACTION")
        self.assertEqual(params["action"], "open_firefox_tab")

        # Close tab requires confirmation
        intent, params = detect_intent("close this tab")
        self.assertEqual(intent, "REQUEST_CONFIRMATION")
        self.assertEqual(params["action"], "close_tab")

        intent, params = detect_intent("can you close the current tab?")
        self.assertEqual(intent, "REQUEST_CONFIRMATION")
        self.assertEqual(params["action"], "close_tab")

    def test_unsupported_and_ambiguous_commands(self):
        # Conversational questions route to Ollama
        intent, params = detect_intent("what is the speed of light?")
        self.assertEqual(intent, "OLLAMA_QUERY")

        intent, params = detect_intent("who built jarvis?")
        self.assertEqual(intent, "OLLAMA_QUERY")

        # Unclear noise/fillers must NOT route to Ollama
        intent, _ = detect_intent("um")
        self.assertEqual(intent, "UNCLEAR_SPEECH")

        intent, _ = detect_intent("the")
        self.assertEqual(intent, "UNCLEAR_SPEECH")

        intent, _ = detect_intent("a")
        self.assertEqual(intent, "UNCLEAR_SPEECH")

    def test_confirmation_states(self):
        intent, params = detect_intent("yes", pending_action="close_tab")
        self.assertEqual(intent, "CONFIRM_ACTION")

        intent, params = detect_intent("no", pending_action="close_tab")
        self.assertEqual(intent, "CANCEL_ACTION")

        # Follow-up for youtube play prompt
        intent, params = detect_intent("iron man trailer", pending_action="youtube_play")
        self.assertEqual(intent, "YOUTUBE_PLAY")
        self.assertEqual(params["query"], "iron man trailer")

        # Follow-up for search prompt
        intent, params = detect_intent("python tutorials", pending_action="search_google")
        self.assertEqual(intent, "BROWSER_SEARCH")
        self.assertEqual(params["engine"], "google")
        self.assertEqual(params["query"], "python tutorials")

        intent, params = detect_intent("no", pending_action="close_tab")
        self.assertEqual(intent, "CANCEL_ACTION")


    def test_terminal_command_variations(self):
        # Specific natural variations required
        terminal_variations = [
            "Open terminal",
            "Open a new terminal",
            "Can you open new terminal?",
            "Can you open a new terminal?",
            "Can you open terminal?",
            "Launch Konsole",
            "Start terminal for me",
            "start a terminal for me",
            "open konsole",
            "launch terminal",
            "open a terminal",
            "open console",
        ]
        for phrase in terminal_variations:
            intent, params = detect_intent(phrase)
            self.assertEqual(
                intent,
                "DESKTOP_ACTION",
                f"Phrase '{phrase}' should route to DESKTOP_ACTION, got {intent}",
            )
            self.assertEqual(
                params.get("action"),
                "open_terminal",
                f"Phrase '{phrase}' should trigger open_terminal, got {params}",
            )

        # Unrelated questions that must NOT trigger terminal action or overmatch
        unrelated_queries = [
            "Can you explain quantum computing?",
            "Can you tell me what time it is?",
            "Can you bake a cake?",
            "What is a terminal illness?",
            "Can you open a bank account?",
        ]
        for query in unrelated_queries:
            intent, params = detect_intent(query)
            self.assertNotEqual(
                intent,
                "DESKTOP_ACTION",
                f"Unrelated query '{query}' should not route to DESKTOP_ACTION",
            )
            self.assertNotEqual(
                params.get("action"),
                "open_terminal",
                f"Unrelated query '{query}' should never trigger open_terminal",
            )

    def test_media_controls_intent(self):
        # 1. Polite pause request (Must not route to OLLAMA_QUERY)
        intent, params = detect_intent("Is it possible for you to pause this video?")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "pause")

        # 2. Direct pause
        intent, params = detect_intent("Pause this video.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "pause")

        # 3. Resume and Play
        intent, params = detect_intent("Resume the video.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "resume")

        intent, params = detect_intent("Continue playing.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "resume")

        intent, params = detect_intent("Play.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "resume")

        # 4. Stop
        intent, params = detect_intent("Stop the video.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "stop")

        # 5. Seek
        intent, params = detect_intent("Skip forward.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "seek")
        self.assertEqual(params.get("offset"), 10)

        intent, params = detect_intent("Go back 10 seconds.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "seek")
        self.assertEqual(params.get("offset"), -10)

        # 6. Mute and Unmute
        intent, params = detect_intent("Mute the video.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "mute")
        self.assertTrue(params.get("mute_state"))

        intent, params = detect_intent("Unmute the video.")
        self.assertEqual(intent, "MEDIA_CONTROL")
        self.assertEqual(params.get("action"), "mute")
        self.assertFalse(params.get("mute_state"))


if __name__ == "__main__":
    unittest.main()
