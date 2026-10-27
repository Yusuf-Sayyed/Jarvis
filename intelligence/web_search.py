"""
Real-time web search and current-information retrieval module for JARVIS.
Retrieves live search results using keyless search providers and grounds
local Ollama answers strictly on retrieved evidence.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from html import unescape
import json
import logging
import re
from typing import Any, Optional
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

from core.config import (
    GROUNDED_SEARCH_SYSTEM_PROMPT,
    OLLAMA_API_URL,
    OLLAMA_GROUNDED_TIMEOUT_SECONDS,
    OLLAMA_MODEL,
    WEB_SEARCH_MAX_RESULTS,
    WEB_SEARCH_PROVIDER,
    WEB_SEARCH_TIMEOUT_SECONDS,
)

logger = logging.getLogger("jarvis.web_search")

DEFAULT_BROWSER_UA = (
    "Mozilla/5.0 (X11; Linux x86_64; rv:128.0) Gecko/20100101 Firefox/128.0"
)


@dataclass
class WebSearchResult:
    """Represents an individual search result item."""
    title: str
    snippet: str
    url: str
    date: Optional[str] = None
    source: Optional[str] = None


class SearchProvider(ABC):
    """Abstract interface for replaceable search backends."""

    @abstractmethod
    def search(
        self, query: str, max_results: int = 5, timeout: int = 8
    ) -> list[WebSearchResult]:
        """Executes search query and returns structured results."""
        pass


class DDGSSearchProvider(SearchProvider):
    """
    Search provider using the keyless 'ddgs' / 'duckduckgo_search' Python library.
    """

    def search(
        self, query: str, max_results: int = 5, timeout: int = 8
    ) -> list[WebSearchResult]:
        try:
            try:
                from ddgs import DDGS
            except ImportError:
                from duckduckgo_search import DDGS
        except ImportError as e:
            raise RuntimeError(
                "Neither 'ddgs' nor 'duckduckgo_search' is installed in the current environment."
            ) from e

        results: list[WebSearchResult] = []
        with DDGS(timeout=timeout) as ddgs:
            raw_items = list(ddgs.text(query, max_results=max_results))
            for item in raw_items:
                title = (item.get("title") or "").strip()
                url = (item.get("href") or "").strip()
                snippet = (item.get("body") or "").strip()
                if not title or not url:
                    continue

                source_domain = None
                try:
                    domain = urllib.parse.urlparse(url).netloc
                    if domain.startswith("www."):
                        domain = domain[4:]
                    source_domain = domain
                except Exception:
                    source_domain = None

                results.append(
                    WebSearchResult(
                        title=title,
                        snippet=snippet,
                        url=url,
                        date=item.get("date"),
                        source=source_domain,
                    )
                )
        return results


class LiveNewsSearchProvider(SearchProvider):
    """
    Keyless real-time news search provider using Google News RSS.
    Provides verified timestamps, authentic source publications, and URLs.
    """

    def search(
        self, query: str, max_results: int = 5, timeout: int = 8
    ) -> list[WebSearchResult]:
        encoded_q = urllib.parse.quote(query)
        url = f"https://news.google.com/rss/search?q={encoded_q}&hl=en-US&gl=US&ceid=US:en"
        req = urllib.request.Request(url, headers={"User-Agent": DEFAULT_BROWSER_UA})

        with urllib.request.urlopen(req, timeout=timeout) as response:
            xml_data = response.read().decode("utf-8", errors="ignore")

        root = ET.fromstring(xml_data)
        items = root.findall(".//item")[:max_results]

        results: list[WebSearchResult] = []
        for item in items:
            title_elem = item.find("title")
            link_elem = item.find("link")
            pub_date_elem = item.find("pubDate")
            source_elem = item.find("source")
            desc_elem = item.find("description")

            title = title_elem.text.strip() if title_elem is not None and title_elem.text else ""
            link = link_elem.text.strip() if link_elem is not None and link_elem.text else ""
            pub_date = pub_date_elem.text.strip() if pub_date_elem is not None and pub_date_elem.text else None
            source = source_elem.text.strip() if source_elem is not None and source_elem.text else None
            snippet = ""
            if desc_elem is not None and desc_elem.text:
                clean_desc = re.sub(r"<[^>]+>", "", unescape(desc_elem.text)).strip()
                snippet = clean_desc

            if not snippet:
                snippet = title

            if title and link:
                results.append(
                    WebSearchResult(
                        title=title,
                        snippet=snippet,
                        url=link,
                        date=pub_date,
                        source=source,
                    )
                )
        return results


class WeatherSearchProvider(SearchProvider):
    """
    Keyless weather information provider using wttr.in.
    Provides real-time temperatures, conditions, humidity, and location.
    """

    def search(
        self, query: str, max_results: int = 5, timeout: int = 8
    ) -> list[WebSearchResult]:
        # Extract location if specified (e.g. "weather in Tokyo" -> "Tokyo")
        loc_match = re.search(r"weather\s+(?:in|for|at)\s+([a-zA-Z\s]+)", query, re.IGNORECASE)
        location = loc_match.group(1).strip() if loc_match else ""
        encoded_loc = urllib.parse.quote(location) if location else ""

        url = f"https://wttr.in/{encoded_loc}?format=j1"
        req = urllib.request.Request(url, headers={"User-Agent": "curl/7.68.0"})

        with urllib.request.urlopen(req, timeout=timeout) as response:
            data = json.loads(response.read().decode("utf-8"))

        current = (data.get("current_condition") or [{}])[0]
        area_info = (data.get("nearest_area") or [{}])[0]
        area_name = (area_info.get("areaName") or [{}])[0].get("value") or (location.capitalize() if location else "Local Area")
        country = (area_info.get("country") or [{}])[0].get("value") or ""

        temp_c = current.get("temp_C", "N/A")
        temp_f = current.get("temp_F", "N/A")
        desc = (current.get("weatherDesc") or [{}])[0].get("value", "Clear")
        humidity = current.get("humidity", "N/A")
        wind = current.get("windspeedKmph", "N/A")

        snippet = (
            f"Current temperature is {temp_c}°C ({temp_f}°F), condition: {desc}. "
            f"Humidity: {humidity}%, Wind speed: {wind} km/h."
        )
        location_label = f"{area_name}, {country}".strip(", ")
        target_url = f"https://wttr.in/{encoded_loc}" if encoded_loc else "https://wttr.in/"

        return [
            WebSearchResult(
                title=f"Current Weather in {location_label}",
                snippet=snippet,
                url=target_url,
                date="Live real-time observation",
                source="wttr.in",
            )
        ]


class DirectDDGSearchProvider(SearchProvider):
    """
    Direct keyless DuckDuckGo search provider.
    """

    def search(
        self, query: str, max_results: int = 5, timeout: int = 8
    ) -> list[WebSearchResult]:
        data = urllib.parse.urlencode({"q": query}).encode("utf-8")
        req = urllib.request.Request(
            "https://lite.duckduckgo.com/lite/",
            data=data,
            headers={
                "User-Agent": DEFAULT_BROWSER_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )

        with urllib.request.urlopen(req, timeout=timeout) as response:
            html = response.read().decode("utf-8", errors="ignore")

        link_matches = [
            (m.group(1), m.group(2))
            for m in re.finditer(
                r"<a[^>]+href=[\"']([^\"']+)[\"'][^>]*>(.*?)</a>", html, re.DOTALL
            )
            if "duckduckgo.com" not in m.group(1)
            and ("http" in m.group(1) or "uddg" in m.group(1))
        ]

        snippet_matches = re.findall(
            r"<td[^>]*class=[\"']result-snippet[\"'][^>]*>(.*?)</td>",
            html,
            re.DOTALL | re.IGNORECASE,
        )

        results: list[WebSearchResult] = []
        for i in range(min(len(link_matches), max_results)):
            raw_href, raw_title = link_matches[i]
            clean_title = re.sub(r"<[^>]+>", "", unescape(raw_title)).strip()

            raw_snip = snippet_matches[i] if i < len(snippet_matches) else ""
            clean_snip = re.sub(r"<[^>]+>", "", unescape(raw_snip)).strip()

            m_uddg = re.search(r"uddg=([^&]+)", raw_href)
            final_url = urllib.parse.unquote(m_uddg.group(1)) if m_uddg else raw_href

            date_str = None
            date_m = re.match(
                r"^(\w+\s+\d{1,2},\s+\d{4}|\d+\s+(?:days?|hours?|weeks?|months?)\s+ago)\s*[-—–]\s*(.*)",
                clean_snip,
                re.IGNORECASE,
            )
            if date_m:
                date_str = date_m.group(1).strip()
                clean_snip = date_m.group(2).strip()

            source_domain = None
            try:
                domain = urllib.parse.urlparse(final_url).netloc
                if domain.startswith("www."):
                    domain = domain[4:]
                source_domain = domain
            except Exception:
                source_domain = None

            results.append(
                WebSearchResult(
                    title=clean_title,
                    snippet=clean_snip,
                    url=final_url,
                    date=date_str,
                    source=source_domain,
                )
            )

        return results


def clean_search_query(text: str) -> str:
    """
    Strips conversational prefixes, wake words, and trailing punctuation
    to produce a clean query for search engines.
    """
    q = text.strip().rstrip(".?!,").strip()
    prefix_pattern = re.compile(
        r"^(?:hey\s+jarvis|jarvis|please|can\s+you(?:\s+please)?|could\s+you(?:\s+please)?|"
        r"find(?:\s+me)?(?:\s+the)?|search(?:\s+for)?(?:\s+the)?|tell\s+me(?:\s+about)?)\s*[,:]?\s*",
        flags=re.IGNORECASE,
    )
    while True:
        new_q = prefix_pattern.sub("", q).strip()
        if new_q == q:
            break
        q = new_q
    return q


def perform_web_search(
    query: str,
    max_results: int = WEB_SEARCH_MAX_RESULTS,
    timeout: int = WEB_SEARCH_TIMEOUT_SECONDS,
    provider_name: Optional[str] = None,
) -> tuple[bool, list[WebSearchResult], str]:
    """
    Performs a web search using the specified or configured provider,
    with automatic fallback if the primary provider is unavailable.

    Returns:
        (success: bool, results: list[WebSearchResult], message: str)
    """
    clean_q = clean_search_query(query)
    if not clean_q:
        return False, [], "Empty search query."

    # 1. Specialized weather routing
    if re.search(r"\b(?:weather|temperature|forecast)\b", clean_q, re.IGNORECASE):
        try:
            weather_provider = WeatherSearchProvider()
            results = weather_provider.search(clean_q, max_results=max_results, timeout=timeout)
            if results:
                return True, results, "Live weather observation retrieved successfully."
        except Exception as e:
            logger.warning("Weather search failed (%s), falling back to web search.", e)

    target_provider = (provider_name or WEB_SEARCH_PROVIDER).lower().strip()

    # 2. Primary provider: ddgs
    if target_provider == "ddgs":
        try:
            provider = DDGSSearchProvider()
            results = provider.search(clean_q, max_results=max_results, timeout=timeout)
            if results:
                return True, results, f"Found {len(results)} live results via ddgs."
        except Exception as e:
            logger.debug("Primary search provider 'ddgs' unavailable: %s. Using fallback.", e)

    # 3. Real-time news provider fallback (Google News RSS - real-time, dated, verified)
    try:
        news_provider = LiveNewsSearchProvider()
        results = news_provider.search(clean_q, max_results=max_results, timeout=timeout)
        if results:
            return True, results, f"Found {len(results)} live news results."
    except Exception as e:
        logger.debug("Live news search provider failed: %s.", e)

    # 4. Direct DDG fallback
    try:
        ddg_direct = DirectDDGSearchProvider()
        results = ddg_direct.search(clean_q, max_results=max_results, timeout=timeout)
        if results:
            return True, results, f"Found {len(results)} live results via direct search."
    except urllib.error.URLError as e:
        return False, [], f"Network connection error: {e.reason}"
    except TimeoutError:
        return False, [], "Web search request timed out."
    except Exception as e:
        return False, [], f"Web search failed: {e}"

    return False, [], "No live search results found."


def build_grounded_evidence(question: str, results: list[WebSearchResult]) -> str:
    """Formats retrieved search results as structured evidence for local Ollama."""
    evidence_blocks = []
    for idx, r in enumerate(results, 1):
        source_label = r.source or "Unknown Source"
        date_label = r.date or "Date not specified / potentially outdated"
        clean_snippet = r.snippet[:280].strip() if r.snippet else r.title
        evidence_blocks.append(
            f"Result [{idx}]:\n"
            f"  Title: {r.title}\n"
            f"  Source: {source_label} | Date: {date_label}\n"
            f"  URL: {r.url}\n"
            f"  Snippet: {clean_snippet}\n"
        )

    evidence_text = "\n".join(evidence_blocks)
    return (
        f"User Question: {question}\n\n"
        f"Live Web Search Evidence:\n"
        f"{evidence_text}\n\n"
        f"Synthesize a clear, concise (2 to 4 sentences) answer for the user based strictly on the evidence above. "
        f"Cite key source names and mention dates when known. Do not include URLs in the spoken answer text."
    )


def ask_ollama_grounded(
    question: str,
    results: list[WebSearchResult],
    timeout: int = OLLAMA_GROUNDED_TIMEOUT_SECONDS,
) -> Optional[str]:
    """
    Queries local Ollama using retrieved evidence and a grounding system prompt.
    """
    if not results:
        return None

    prompt_content = build_grounded_evidence(question, results)
    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt_content,
        "system": GROUNDED_SEARCH_SYSTEM_PROMPT,
        "stream": False,
    }

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=timeout) as response:
            if response.status != 200:
                return None
            data = json.loads(response.read().decode("utf-8"))
            return data.get("response", "").strip()
    except Exception as e:
        logger.error("Failed to query Ollama for grounded search synthesis: %s", e)
        return None


def handle_current_info_query(
    question: str,
    max_results: int = WEB_SEARCH_MAX_RESULTS,
    timeout: int = WEB_SEARCH_TIMEOUT_SECONDS,
) -> tuple[bool, Optional[str], list[WebSearchResult]]:
    """
    High-level handler: searches the web and synthesizes a grounded answer using Ollama.

    Returns:
        (success: bool, answer: Optional[str], results: list[WebSearchResult])
    """
    success, results, msg = perform_web_search(question, max_results=max_results, timeout=timeout)

    if not success or not results:
        if "network" in msg.lower() or "connection" in msg.lower() or "timed out" in msg.lower():
            fail_msg = (
                "I was unable to retrieve live search results due to a network connection error, Sir. "
                "Live information is currently unavailable."
            )
        else:
            fail_msg = f"I could not locate live information for your query, Sir ({msg})."
        return False, fail_msg, []

    # Synthesize answer with local Ollama
    answer = ask_ollama_grounded(question, results)
    if not answer:
        fallback_answer = (
            f"I retrieved {len(results)} live search result(s), Sir, but could not connect to "
            f"local intelligence to synthesize a summary. Please refer to the source links below."
        )
        return True, fallback_answer, results

    return True, answer, results
