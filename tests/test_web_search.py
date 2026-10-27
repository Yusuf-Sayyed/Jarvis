"""
Unit tests for Stage 5: Real-Time Web Search and Current Information.
Tests current-info intent recognition, provider parsing, evidence grounding,
Ollama synthesis, error/timeout handling, and source citations without live network dependencies.
"""

import io
import json
import unittest
from unittest.mock import MagicMock, patch
import urllib.error

from core.intent import detect_intent, is_current_info_query
from core.router import route_command
from intelligence.web_search import (
    DirectDDGSearchProvider,
    LiveNewsSearchProvider,
    WeatherSearchProvider,
    WebSearchResult,
    ask_ollama_grounded,
    build_grounded_evidence,
    clean_search_query,
    handle_current_info_query,
    perform_web_search,
)



class TestWebSearchIntentRecognition(unittest.TestCase):
    """Verifies current-events questions trigger search while ordinary queries do not."""

    def test_current_info_queries_recognized(self):
        sample_queries = [
            "What's happening in Japan?",
            "What are today's technology news headlines?",
            "What's the latest news about OpenAI?",
            "What's the weather today?",
            "Find the latest information about Python 3.15.",
            "What is happening right now?",
            "Tell me the latest news on Nvidia",
            "What are current mortgage rates?",
            "What's the weather in Tokyo?",
            "Who won the match today?",
        ]
        for q in sample_queries:
            with self.subTest(query=q):
                self.assertTrue(is_current_info_query(q), f"Failed to identify current query: {q}")
                intent, params = detect_intent(q)
                self.assertEqual(intent, "CURRENT_INFO_QUERY", f"Wrong intent for: {q}")

    def test_ordinary_questions_do_not_trigger_search(self):
        ordinary_questions = [
            "What is photosynthesis?",
            "Why is the sky blue?",
            "How do I reverse a list in Python?",
            "Who was Albert Einstein?",
            "What is an algorithm?",
            "Can you explain recursion?",
            "Tell me a joke.",
            "What is the capital of France?",
        ]
        for q in ordinary_questions:
            with self.subTest(query=q):
                self.assertFalse(is_current_info_query(q), f"False positive for: {q}")
                intent, _ = detect_intent(q)
                self.assertEqual(intent, "OLLAMA_QUERY", f"Expected OLLAMA_QUERY for: {q}")

    def test_desktop_and_media_commands_keep_fast_paths(self):
        system_commands = [
            ("open a terminal", "DESKTOP_ACTION"),
            ("pause the video", "MEDIA_CONTROL"),
            ("set volume to 100%", "SMART_ACTION"),
            ("close current tab", "REQUEST_CONFIRMATION"),
            ("search google for python", "BROWSER_SEARCH"),
            ("start working on lensify", "SMART_ACTION"),
        ]
        for cmd, expected_intent in system_commands:
            with self.subTest(command=cmd):
                intent, _ = detect_intent(cmd)
                self.assertEqual(intent, expected_intent, f"Fast path broken for: {cmd}")


class TestWebSearchProviders(unittest.TestCase):
    """Tests web search providers, HTML/RSS/JSON parsing, and error handling."""

    def test_clean_search_query(self):
        self.assertEqual(
            clean_search_query("Hey JARVIS, what's happening in Japan?"),
            "what's happening in Japan",
        )
        self.assertEqual(
            clean_search_query("Please find the latest information about Python 3.15."),
            "latest information about Python 3.15",
        )
        self.assertEqual(
            clean_search_query("Can you tell me about OpenAI news?"),
            "OpenAI news",
        )

    def test_live_news_provider_parsing(self):
        sample_rss = """<?xml version="1.0" encoding="UTF-8"?>
        <rss version="2.0">
          <channel>
            <title>Google News</title>
            <item>
              <title>OpenAI Unveils Major Research Framework - Reuters</title>
              <link>https://news.google.com/articles/sample1</link>
              <pubDate>Tue, 27 Oct 2026 12:00:00 GMT</pubDate>
              <source url="https://www.reuters.com">Reuters</source>
              <description>&lt;p&gt;OpenAI announced new safety collaborations today.&lt;/p&gt;</description>
            </item>
          </channel>
        </rss>"""

        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_rss.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            provider = LiveNewsSearchProvider()
            results = provider.search("OpenAI news", max_results=3)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.title, "OpenAI Unveils Major Research Framework - Reuters")
        self.assertEqual(r.url, "https://news.google.com/articles/sample1")
        self.assertEqual(r.source, "Reuters")
        self.assertEqual(r.date, "Tue, 27 Oct 2026 12:00:00 GMT")
        self.assertIn("safety collaborations", r.snippet)

    def test_weather_provider_parsing(self):
        sample_wttr = {
            "current_condition": [
                {
                    "temp_C": "22",
                    "temp_F": "72",
                    "weatherDesc": [{"value": "Partly cloudy"}],
                    "humidity": "50",
                    "windspeedKmph": "10",
                }
            ],
            "nearest_area": [
                {
                    "areaName": [{"value": "Tokyo"}],
                    "country": [{"value": "Japan"}],
                }
            ],
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(sample_wttr).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            provider = WeatherSearchProvider()
            results = provider.search("weather in Tokyo", max_results=1)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertIn("Tokyo", r.title)
        self.assertIn("22°C", r.snippet)
        self.assertIn("Partly cloudy", r.snippet)
        self.assertEqual(r.source, "wttr.in")

    def test_direct_ddg_provider_parsing(self):
        sample_html = """
        <html>
        <body>
          <table>
            <tr><td><a href="/l/?uddg=https%3A%2F%2Fwww.python.org%2Frelease%2F315" class="result-link">Python 3.15 Release</a></td></tr>
            <tr><td class="result-snippet">Oct 24, 2026 - Python 3.15 is now officially available with new features.</td></tr>
          </table>
        </body>
        </html>
        """
        mock_resp = MagicMock()
        mock_resp.read.return_value = sample_html.encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            provider = DirectDDGSearchProvider()
            results = provider.search("Python 3.15", max_results=1)

        self.assertEqual(len(results), 1)
        r = results[0]
        self.assertEqual(r.title, "Python 3.15 Release")
        self.assertEqual(r.url, "https://www.python.org/release/315")
        self.assertEqual(r.source, "python.org")
        self.assertEqual(r.date, "Oct 24, 2026")


class TestGroundedEvidenceAndSynthesis(unittest.TestCase):
    """Tests evidence formatting, Ollama query construction, and date grounding."""

    def test_evidence_formatting_includes_source_and_date(self):
        results = [
            WebSearchResult(
                title="Japan Tech Summit 2026",
                snippet="Discussions on emerging AI innovations.",
                url="https://japantimes.co.jp/tech",
                date="Mon, 26 Oct 2026",
                source="japantimes.co.jp",
            ),
            WebSearchResult(
                title="Historical Overview",
                snippet="General background context.",
                url="https://example.com/history",
                date=None,  # Missing date
                source="example.com",
            ),
        ]
        evidence = build_grounded_evidence("What's happening in Japan?", results)

        self.assertIn("japantimes.co.jp", evidence)
        self.assertIn("Mon, 26 Oct 2026", evidence)
        self.assertIn("https://japantimes.co.jp/tech", evidence)
        # Undated result is explicitly flagged as potentially outdated
        self.assertIn("Date not specified / potentially outdated", evidence)

    def test_ask_ollama_grounded_success(self):
        results = [
            WebSearchResult(
                title="OpenAI Update",
                snippet="OpenAI releases new safety evaluation.",
                url="https://openai.com/news",
                date="Today",
                source="openai.com",
            )
        ]
        mock_response = MagicMock()
        mock_response.status = 200
        mock_response.read.return_value = json.dumps(
            {"response": "OpenAI announced a new safety evaluation today, as reported by openai.com."}
        ).encode("utf-8")
        mock_response.__enter__.return_value = mock_response

        with patch("urllib.request.urlopen", return_value=mock_response):
            answer = ask_ollama_grounded("What's the latest news about OpenAI?", results)

        self.assertIsNotNone(answer)
        self.assertIn("OpenAI announced a new safety evaluation", answer)

    def test_ask_ollama_grounded_handles_empty_results(self):
        answer = ask_ollama_grounded("Any question?", [])
        self.assertIsNone(answer)


class TestRouterCurrentInfoExecution(unittest.TestCase):
    """Tests router execution, error handling, timeouts, and source display."""

    @patch("intelligence.web_search.handle_current_info_query")
    def test_current_info_routes_and_prints_sources(self, mock_handler):
        mock_results = [
            WebSearchResult(
                title="OpenAI Safety Framework",
                snippet="New academic partnership announced.",
                url="https://reuters.com/openai",
                date="Mon, 26 Oct 2026",
                source="reuters.com",
            ),
            WebSearchResult(
                title="The Verge Tech News",
                snippet="Detailed breakdown of recent AI developments.",
                url="https://theverge.com/ai",
                date="Tue, 27 Oct 2026",
                source="theverge.com",
            ),
        ]
        mock_handler.return_value = (
            True,
            "OpenAI announced a major new academic framework on October 26, 2026, according to Reuters.",
            mock_results,
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            cont, pending = route_command("What's the latest news about OpenAI?")
            output = mock_stdout.getvalue()

        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("CURRENT_INFO_QUERY", output)
        self.assertIn("OpenAI announced a major new academic framework", output)
        self.assertIn("Sources:", output)
        self.assertIn("https://reuters.com/openai", output)
        self.assertIn("https://theverge.com/ai", output)
        self.assertIn("[reuters.com]", output)

    @patch("intelligence.web_search.perform_web_search")
    def test_network_connection_error_handled_gracefully(self, mock_search):
        mock_search.return_value = (
            False,
            [],
            "Network connection error: [Errno -3] Temporary failure in name resolution",
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            cont, pending = route_command("What's happening in Japan?")
            output = mock_stdout.getvalue()

        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("CURRENT_INFO_QUERY", output)
        self.assertIn("unable to retrieve live search results due to a network connection error", output)
        # Confirms assistant did not claim to know breaking news without internet
        self.assertNotIn("Here is what is happening", output)

    @patch("intelligence.web_search.perform_web_search")
    def test_search_timeout_handled_gracefully(self, mock_search):
        mock_search.return_value = (
            False,
            [],
            "Web search request timed out.",
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            cont, pending = route_command("What are today's technology news headlines?")
            output = mock_stdout.getvalue()

        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("unable to retrieve live search results due to a network connection error", output)

    @patch("intelligence.web_search.perform_web_search")
    def test_empty_results_handled(self, mock_search):
        mock_search.return_value = (
            False,
            [],
            "No live search results found.",
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            cont, pending = route_command("What's the latest news on unknownkeyword9999?")
            output = mock_stdout.getvalue()

        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("could not locate live information for your query", output)

    def test_search_phrases_trigger_current_info_query(self):
        cases = [
            ("Search the web for Claude", "claude"),
            ("Look up Claude", "claude"),
            ("Search online for Claude", "claude"),
            ("Web search Claude", "claude"),
        ]
        for utterance, expected_q in cases:
            with self.subTest(utterance=utterance):
                intent, params = detect_intent(utterance)
                self.assertEqual(intent, "CURRENT_INFO_QUERY")
                self.assertEqual(params.get("query"), expected_q)

    def test_is_knowledge_gap_detection(self):
        from intelligence.ollama_client import is_knowledge_gap
        gap_examples = [
            "Sir, I couldn't find any information on a known entity or concept named 'Claude.'",
            "Sir, I'm afraid Claude is not a known entity within my current programming.",
            "I do not have access to real-time information.",
            "I suggest searching for information on the web.",
        ]
        for text in gap_examples:
            with self.subTest(text=text):
                self.assertTrue(is_knowledge_gap(text))

        self.assertFalse(is_knowledge_gap("Photosynthesis is how plants produce glucose."))
        self.assertFalse(is_knowledge_gap("Albert Einstein was a German physicist."))

    @patch("core.router.ask_ollama")
    @patch("intelligence.web_search.handle_current_info_query")
    def test_ollama_knowledge_gap_bridges_to_web_search(self, mock_search, mock_ollama):
        mock_ollama.return_value = "Sir, I couldn't find any information on a known entity named Claude."
        mock_search.return_value = (
            True,
            "Claude is an advanced AI assistant created by Anthropic.",
            [
                WebSearchResult(
                    title="Anthropic Claude Overview",
                    snippet="Claude AI details.",
                    url="https://anthropic.com/claude",
                    date="Mon, 26 Oct 2026",
                    source="anthropic.com",
                )
            ],
        )

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            cont, pending = route_command("What is Claude?")
            output = mock_stdout.getvalue()

        self.assertTrue(cont)
        self.assertIsNone(pending)
        mock_search.assert_called_once_with("what is claude")
        self.assertIn("Local intelligence lacks verified data on this entity. Consulting real-time web search", output)
        self.assertIn("Claude is an advanced AI assistant created by Anthropic", output)
        self.assertIn("https://anthropic.com/claude", output)

    @patch("core.router.ask_ollama")
    @patch("intelligence.web_search.handle_current_info_query")
    def test_ollama_known_answer_does_not_call_web_search(self, mock_search, mock_ollama):
        mock_ollama.return_value = "Photosynthesis is the process by which green plants produce glucose."

        with patch("sys.stdout", new_callable=io.StringIO) as mock_stdout:
            cont, pending = route_command("What is photosynthesis?")
            output = mock_stdout.getvalue()

        self.assertTrue(cont)
        self.assertIsNone(pending)
        mock_search.assert_not_called()
        self.assertIn("Photosynthesis is the process by which green plants produce glucose", output)


if __name__ == "__main__":
    unittest.main()

