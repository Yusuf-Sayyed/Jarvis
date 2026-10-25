"""
Speech normalization and intent detection for voice commands.
Supports conversational lead-ins, phonetic correction, and YouTube direct playback.
"""

import re
from core.config import EXIT_COMMANDS

CONVERSATIONAL_PREFIXES = (
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*,?\s*)?"
    r"(?:can\s+you\s+|could\s+you\s+|would\s+you\s+|please\s+|will\s+you\s+|i\s+want\s+you\s+to\s+|can\s+we\s+)+"
)


def normalize_spoken_text(text: str) -> str:
    """
    Normalizes common Vosk speech-recognition acoustic splits, phonetic confusions,
    conversational prefixes, and trailing punctuation.
    """
    text = text.lower().strip()

    # Phonetic and compound word repairs
    text = re.sub(r"\byou\s+tube\b", "youtube", text)
    text = re.sub(r"\bgoo\s+gle\b", "google", text)
    text = re.sub(r"\bfire\s+fox\b", "firefox", text)
    text = re.sub(r"\bdown\s+loads\b", "downloads", text)
    text = re.sub(r"\bkon\s+sole\b", "konsole", text)
    text = re.sub(r"\bnew\s+tap\b", "new tab", text)
    text = re.sub(r"\bclose\s+tap\b", "close tab", text)
    text = re.sub(r"\bthis\s+tap\b", "this tab", text)
    text = re.sub(r"\bcurrent\s+tap\b", "current tab", text)
    text = re.sub(r"\bnext\s+tap\b", "next tab", text)

    # Strip trailing punctuation
    text = text.rstrip(".?!,").strip()

    # Strip conversational prefixes ("can you", "please", "could you", etc.)
    cleaned = re.sub(CONVERSATIONAL_PREFIXES, "", text).strip()
    return cleaned


def parse_youtube_play(text: str) -> tuple[str | None, str | None]:
    """
    Detects commands intended to play a video directly on YouTube.
    Returns:
        ('YOUTUBE_FIRST_RESULT', None) for 'open the first youtube result'
        ('YOUTUBE_PLAY', query) for 'play ... on youtube'
        (None, None) if not a play command.
    """
    cleaned = normalize_spoken_text(text)

    # 1. "Open the first YouTube result"
    first_result_phrases = (
        "open the first youtube result", "open first youtube result",
        "open the first result", "open first result",
        "play the first youtube result", "play first youtube result",
        "play the first result", "play first result"
    )
    if cleaned in first_result_phrases:
        return "YOUTUBE_FIRST_RESULT", None

    # 2. "Play <query> on/in YouTube" or "Play on YouTube <query>"
    m = re.match(r"^play\s+(.+?)(?:\s+(?:on|in)\s+youtube)?$", cleaned)
    if m:
        query = m.group(1).strip()
        # Avoid matching generic non-play phrases
        if query:
            return "YOUTUBE_PLAY", query

    m = re.match(r"^play\s+(?:on|in)\s+youtube\s+(.+)$", cleaned)
    if m:
        query = m.group(1).strip()
        if query:
            return "YOUTUBE_PLAY", query

    return None, None


def parse_search_command(text: str) -> tuple[str | None, str | None]:
    """
    Extracts search engine ('google' or 'youtube') and query string.
    Returns:
        (engine, query) if recognized as a search intent, else (None, None).
    """
    cleaned = normalize_spoken_text(text)

    # 1. "find <query> on google|youtube"
    m = re.match(r"^(?:please\s+)?find\s+(.+?)\s+on\s+(google|youtube)$", cleaned)
    if m:
        return m.group(2).strip(), m.group(1).strip()

    # 2. "search google|youtube for <query>"
    m = re.match(r"^(?:please\s+)?search\s+(google|youtube)\s+for\s+(.+)$", cleaned)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # 3. "open firefox and search for <query>", "open a new tab and search for <query>", or "search for <query>"
    m = re.match(r"^(?:open\s+(?:firefox|a\s+new\s+tab)\s+and\s+)?search\s+(?:for\s+)?(.+)$", cleaned)
    if m:
        query = m.group(1).strip()
        engine = "google"
        if " on youtube" in query:
            query = query.replace(" on youtube", "").strip()
            engine = "youtube"
        elif " on google" in query:
            query = query.replace(" on google", "").strip()
            engine = "google"
        return engine, query

    return None, None


def parse_type_command(text: str) -> tuple[str | None, bool]:
    """
    Extracts text to type and whether Enter should be pressed.
    Returns:
        (text_to_type, press_enter) if recognized as a typing command, else (None, False).
    """
    # Use raw text (lowercased) with conversational prefix stripped
    text_clean = re.sub(CONVERSATIONAL_PREFIXES, "", text.strip(), flags=re.IGNORECASE).strip()
    m = re.match(r"^(?:please\s+)?type\s+(.+)$", text_clean, re.IGNORECASE)
    if not m:
        return None, False

    content = m.group(1).strip()
    press_enter = False

    # Check for trailing 'and press enter' or 'press enter'
    enter_m = re.search(r"\s+(?:and\s+)?press\s+enter$", content, re.IGNORECASE)
    if enter_m:
        press_enter = True
        content = content[:enter_m.start()].strip()

    # Check for target specifier like 'into the search box'
    box_m = re.search(r"\s+(?:in|into)\s+the\s+search\s+box$", content, re.IGNORECASE)
    if box_m:
        content = content[:box_m.start()].strip()

    return content, press_enter


def detect_intent(text: str, pending_action: str | None = None) -> tuple[str, dict]:
    """
    Analyzes spoken text and determines the structured intent and parameters.

    Returns:
        (intent_name, intent_params)
    """
    clean_text = normalize_spoken_text(text)

    # 1. Pending confirmation check
    if pending_action == "close_tab":
        if clean_text in ("yes", "confirm", "do it", "sure", "yeah", "yep", "close it"):
            return "CONFIRM_ACTION", {"action": "close_tab"}
        elif clean_text in ("no", "cancel", "stop", "abort", "don't", "dont"):
            return "CANCEL_ACTION", {"action": "close_tab"}

    # 2. Exit commands
    if any(clean_text == cmd or clean_text.startswith(cmd) for cmd in EXIT_COMMANDS):
        return "EXIT", {}

    # 3. Close current tab (requests confirmation)
    if any(
        clean_text == trigger or clean_text.startswith(trigger)
        for trigger in ("close the current tab", "close current tab", "close this tab", "close the tab", "close tab")
    ):
        return "REQUEST_CONFIRMATION", {"action": "close_tab"}

    # 4. YouTube Direct Video Playback (Play ... on YouTube, Open first result)
    play_intent, play_query = parse_youtube_play(clean_text)
    if play_intent == "YOUTUBE_FIRST_RESULT":
        return "YOUTUBE_FIRST_RESULT", {}
    if play_intent == "YOUTUBE_PLAY":
        return "YOUTUBE_PLAY", {"query": play_query}

    # 5. Web search intent (Google or YouTube search results page)
    engine, query = parse_search_command(clean_text)
    if engine:
        return "BROWSER_SEARCH", {"engine": engine, "query": query}

    # 6. Typing intent
    type_content, press_enter = parse_type_command(text)
    if type_content is not None:
        return "TYPE_TEXT", {"content": type_content, "press_enter": press_enter}

    # 7. Browser navigation actions
    if clean_text in ("switch to the next tab", "next tab", "switch tab", "switch to next tab"):
        return "BROWSER_ACTION", {"action": "next_tab"}
    if clean_text in ("go back", "back in browser", "browser back", "previous page", "back"):
        return "BROWSER_ACTION", {"action": "back"}
    if clean_text in ("go forward", "forward in browser", "browser forward", "next page", "forward"):
        return "BROWSER_ACTION", {"action": "forward"}
    if clean_text in ("refresh the page", "refresh page", "refresh", "reload the page", "reload page", "reload"):
        return "BROWSER_ACTION", {"action": "refresh"}

    # 8. Desktop core actions (New tab, windows, applications)
    firefox_tab_triggers = (
        "open another tab in firefox", "open a new tab in firefox", "open new tab in firefox",
        "open another tab", "open a new tab", "open new tab", "another tab in firefox",
        "new tab in firefox", "another tab", "new tab"
    )
    if any(trigger in clean_text for trigger in firefox_tab_triggers):
        return "DESKTOP_ACTION", {"action": "open_firefox_tab"}

    firefox_window_triggers = (
        "open another window in firefox", "open a new window in firefox", "open new window in firefox",
        "another window in firefox", "new window in firefox", "open another window",
        "open a new window", "new window"
    )
    if any(trigger in clean_text for trigger in firefox_window_triggers):
        return "DESKTOP_ACTION", {"action": "open_firefox_window"}

    if any(trigger in clean_text for trigger in ("open firefox", "launch firefox", "start firefox")):
        return "DESKTOP_ACTION", {"action": "open_firefox"}

    if any(trigger in clean_text for trigger in ("open terminal", "launch terminal", "start terminal", "open konsole", "launch konsole")):
        return "DESKTOP_ACTION", {"action": "open_terminal"}

    if any(trigger in clean_text for trigger in ("open downloads", "open download", "open downloads folder", "downloads folder")):
        return "DESKTOP_ACTION", {"action": "open_downloads"}

    if any(trigger in clean_text for trigger in ("open youtube", "launch youtube", "start youtube")):
        return "DESKTOP_ACTION", {"action": "open_youtube"}

    # 9. Unrecognized speech falls back to Ollama
    return "OLLAMA_QUERY", {"prompt": clean_text}
