"""
Browser actions: Web searches (Google & YouTube) and Firefox tab/window management.
"""

import subprocess
import urllib.parse


def search_web(query: str, engine: str = "google"):
    """URL-encodes query and opens search results in a new Firefox tab."""
    encoded_query = urllib.parse.quote_plus(query)
    if engine == "youtube":
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
