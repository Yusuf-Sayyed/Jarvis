"""
Browser actions: Web searches, YouTube direct video playback, and Firefox tab/window management.
"""

import re
import subprocess
import urllib.parse
import urllib.request

# Global state to keep track of the most recent YouTube query for "open the first result"
LAST_YOUTUBE_QUERY: str | None = None


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


def play_youtube_video(query: str):
    """
    Resolves the top video for a query and opens it directly in Firefox.
    Falls back to opening YouTube search results if direct video resolution fails.
    """
    global LAST_YOUTUBE_QUERY
    LAST_YOUTUBE_QUERY = query

    print(f"[JARVIS] Locating best video match for \"{query}\" on YouTube...")
    video_url = get_first_youtube_video_url(query)

    if video_url:
        print(f"[JARVIS] Opening and playing video: {video_url}")
        subprocess.Popen(["firefox", "--new-tab", video_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        # Fallback to search results page
        print(f"[JARVIS] Could not auto-select video. Opening search results for \"{query}\"...")
        encoded_query = urllib.parse.quote_plus(query)
        search_url = f"https://www.youtube.com/results?search_query={encoded_query}"
        subprocess.Popen(["firefox", "--new-tab", search_url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_first_youtube_result():
    """
    Opens the top video for the most recent YouTube search,
    supporting commands like 'open the first YouTube result'.
    """
    global LAST_YOUTUBE_QUERY
    if LAST_YOUTUBE_QUERY:
        print(f"[JARVIS] Opening the first result for previous search: \"{LAST_YOUTUBE_QUERY}\"...")
        play_youtube_video(LAST_YOUTUBE_QUERY)
    else:
        print("[JARVIS] No recent YouTube search found, Sir. What would you like to search for?")


def search_web(query: str, engine: str = "google"):
    """URL-encodes query and opens search results in a new Firefox tab."""
    encoded_query = urllib.parse.quote_plus(query)
    if engine == "youtube":
        global LAST_YOUTUBE_QUERY
        LAST_YOUTUBE_QUERY = query
        url = f"https://www.youtube.com/results?search_query={encoded_query}"
        engine_name = "YouTube"
    else:
        url = f"https://www.google.com/search?q={encoded_query}"
        engine_name = "Google"

    print(f"[JARVIS] Searching {engine_name} for \"{query}\"...")
    subprocess.Popen(["firefox", "--new-tab", url], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_firefox_tab():
    """Opens a new blank tab in Firefox using native CLI IPC."""
    print("[JARVIS] Opening a new tab in Firefox...")
    subprocess.Popen(["firefox", "--new-tab", "about:newtab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def open_firefox_window():
    """Opens a new window in Firefox."""
    print("[JARVIS] Opening a new window in Firefox...")
    subprocess.Popen(["firefox", "--new-window", "about:newtab"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
