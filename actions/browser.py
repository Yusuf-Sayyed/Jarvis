"""
Browser actions: Web searches, YouTube direct video playback, and Firefox tab/window management.
"""

import re
import subprocess
import urllib.parse
import urllib.request
from typing import Any

# Global state to keep track of the most recent YouTube query and URL for follow-up resolution
LAST_YOUTUBE_QUERY: str | None = None
LAST_YOUTUBE_URL: str | None = None


def get_first_youtube_video_url(query: str) -> str | None:
    """
    Fetches the YouTube search results page for a query and extracts the top video URL.
    Returns:
        The direct video watch URL (e.g. 'https://www.youtube.com/watch?v=...') or None.
    """
    try:
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
        headers = {"User-Agent": "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) Gecko/20100101 Firefox/130.0"}
        req = urllib.request.Request(search_url, headers=headers)
        with urllib.request.urlopen(req, timeout=5) as response:
            html = response.read().decode("utf-8", errors="ignore")
            # Matches standard 11-character YouTube video IDs
            matches = re.findall(r"/watch\?v=([a-zA-Z0-9_-]{11})", html)
            if matches:
                return f"https://www.youtube.com/watch?v={matches[0]}"
    except Exception as e:
        print(f"[JARVIS Warning] Could not resolve direct YouTube video: {e}")
    return None


def play_youtube_video(query: str) -> dict[str, Any]:
    """
    Resolves the top video for a query and opens it directly in Firefox.
    Attempts playback through safe media controls, verifies playback state,
    and falls back to search results if direct video resolution fails.

    Returns:
        Structured dict with:
          - success: bool
          - stage: 'playback_confirmed' | 'play_command_sent' | 'video_opened' | 'search_page_opened' | 'failed'
          - url: str | None
          - query: str
          - message: str
          - details: dict
    """
    global LAST_YOUTUBE_QUERY, LAST_YOUTUBE_URL
    LAST_YOUTUBE_QUERY = query

    from core.context import get_conversation_context
    ctx = get_conversation_context()

    print(f'[JARVIS] Locating best video match for "{query}" on YouTube...')
    try:
        video_url = get_first_youtube_video_url(query)
    except Exception as e:
        video_url = None

    if video_url:
        LAST_YOUTUBE_URL = video_url
        ctx.set_pending_youtube(query=query, url=video_url, action="play")
        print(f"[JARVIS] Opening and playing video: {video_url}")
        try:
            subprocess.Popen(["firefox", "--new-tab", video_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return {
                "success": False,
                "stage": "failed",
                "url": video_url,
                "query": query,
                "message": f"Failed to launch browser: {e}",
                "details": {"error": str(e)},
            }

        # Attempt safe media playback verification / trigger
        stage = "video_opened"
        autoplay_warning = True
        try:
            from actions import media
            players = media.get_media_players()
            if any(p.playback_status.lower() == "playing" for p in players):
                stage = "playback_confirmed"
                autoplay_warning = False
            else:
                dispatched, _ = media.safe_browser_control_fallback("play")
                if dispatched:
                    stage = "play_command_sent"
        except Exception:
            pass

        if stage == "playback_confirmed":
            msg = f"Playing '{query}' on YouTube, Sir."
        elif stage == "play_command_sent":
            msg = f"Opened '{query}' on YouTube and initiated playback, Sir."
        else:
            msg = f"Opened '{query}' on YouTube, Sir. If blocked by browser autoplay, click the video to play."

        return {
            "success": True,
            "stage": stage,
            "url": video_url,
            "query": query,
            "message": msg,
            "details": {"autoplay_warning": autoplay_warning},
        }
    else:
        # Fallback to search results page
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
        LAST_YOUTUBE_URL = search_url
        ctx.set_pending_youtube(query=query, url=search_url, action="search")
        print(f'[JARVIS] Could not auto-select video. Opening search results for "{query}"...')
        try:
            subprocess.Popen(["firefox", "--new-tab", search_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            return {
                "success": False,
                "stage": "failed",
                "url": search_url,
                "query": query,
                "message": f"Failed to open search results: {e}",
                "details": {"error": str(e)},
            }

        return {
            "success": True,
            "stage": "search_page_opened",
            "url": search_url,
            "query": query,
            "message": f"Could not auto-select video for '{query}'. Opened YouTube search results, Sir.",
            "details": {"autoplay_warning": False},
        }


def open_first_youtube_result() -> dict[str, Any]:
    """
    Opens the top video for the most recent YouTube search,
    supporting commands like 'open the first YouTube result'.
    """
    global LAST_YOUTUBE_QUERY
    from core.context import get_conversation_context
    ctx = get_conversation_context()

    query = LAST_YOUTUBE_QUERY or ctx.get_recent_youtube_query()
    if query:
        print(f'[JARVIS] Opening the first result for previous search: "{query}"...')
        return play_youtube_video(query)
    else:
        msg = "No recent YouTube search found, Sir. What would you like to search for?"
        print(f"[JARVIS] {msg}")
        return {
            "success": False,
            "stage": "no_query",
            "url": None,
            "query": "",
            "message": msg,
            "details": {},
        }


def search_web(query: str, engine: str = "google") -> dict[str, Any]:
    """URL-encodes query and opens search results in a new Firefox tab."""
    encoded_query = urllib.parse.quote_plus(query)
    if engine == "youtube":
        global LAST_YOUTUBE_QUERY, LAST_YOUTUBE_URL
        LAST_YOUTUBE_QUERY = query
        from core.context import get_conversation_context
        ctx = get_conversation_context()
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
        LAST_YOUTUBE_URL = url
        ctx.set_pending_youtube(query=query, url=url, action="search")
        engine_name = "YouTube"
    else:
        url = f"https://www.google.com/search?q={encoded_query}"
        engine_name = "Google"

    print(f'[JARVIS] Searching {engine_name} for "{query}"...')
    try:
        subprocess.Popen(["firefox", "--new-tab", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return {
            "success": True,
            "stage": "search_page_opened",
            "url": url,
            "query": query,
            "engine": engine,
            "message": f"Searching {engine_name} for '{query}', Sir.",
        }
    except Exception as e:
        return {
            "success": False,
            "stage": "failed",
            "url": url,
            "query": query,
            "engine": engine,
            "message": f"Failed to search {engine_name}: {e}",
        }


def open_firefox_tab():
    """Opens a new blank tab in Firefox using native CLI IPC."""
    print("[JARVIS] Opening a new tab in Firefox...")
    subprocess.Popen(["firefox", "--new-tab", "about:newtab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_firefox_window():
    """Opens a new window in Firefox."""
    print("[JARVIS] Opening a new window in Firefox...")
    subprocess.Popen(["firefox", "--new-window", "about:newtab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

