"""
Speech normalization and intent detection for voice commands.
Supports conversational lead-ins, phonetic correction, YouTube direct playback,
browser search variations, and low-confidence speech guards.
"""

import re
from core.config import EXIT_COMMANDS
from core.context import get_conversation_context
from intelligence.intent_extractor import extract_smart_intent, extract_volume_intent

CONVERSATIONAL_PREFIXES = (
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*,?\s*)?"
    r"(?:"
    r"can\s+you(?:\s+please)?\s+|"
    r"could\s+you(?:\s+please)?\s+|"
    r"would\s+you(?:\s+please)?\s+|"
    r"will\s+you(?:\s+please)?\s+|"
    r"please\s+|"
    r"i\s+want\s+you\s+to\s+|"
    r"can\s+we\s+|"
    r"just\s+|"
    r"is\s+it\s+possible(?:\s+for\s+you)?\s+to\s+|"
    r"would\s+it\s+be\s+possible(?:\s+for\s+you)?\s+to\s+|"
    r"are\s+you\s+able\s+to\s+|"
    r"do\s+you\s+mind\s+"
    r")+"
)

TERMINAL_COMMAND_PATTERN = re.compile(
    r"^(?:open|launch|start)\s+(?:(?:a|another)\s+)?(?:new\s+)?(?:terminal|konsole|console)(?:\s+window)?(?:\s+for\s+me)?$"
)

UNCLEAR_NOISE = {
    "um", "uh", "ah", "the", "a", "an", "huh", "oh", "hmm", "and", "or", "so", "to"
}

# Media control patterns
RE_MEDIA_PAUSE = re.compile(
    r"^(?:pause(?:\s+(?:the\s+|this\s+|current\s+)?(?:video|playback|media|song|track|movie|stream|firefox|youtube|vlc|spotify))?|pause|hold\s+on)$",
    re.IGNORECASE,
)
RE_MEDIA_RESUME = re.compile(
    r"^(?:resume(?:\s+(?:the\s+|this\s+|current\s+)?(?:video|playback|media|playing|song|track|movie|stream|firefox|youtube|vlc|spotify))?|continue\s+(?:playing|playback|the\s+video|video)|unpause(?:\s+(?:the\s+|this\s+)?(?:video|playback|media))?|play(?:\s+(?:the\s+|this\s+|current\s+)?(?:video|playback|media|song|track|movie|stream))?|play)$",
    re.IGNORECASE,
)
RE_MEDIA_STOP = re.compile(
    r"^(?:stop)(?:\s+(?:the\s+|this\s+|current\s+)?(?:video|playback|media|playing|song|track|movie|stream|firefox|youtube|vlc|spotify))?$",
    re.IGNORECASE,
)
RE_MEDIA_MUTE = re.compile(
    r"^(?:(?:mute(?:[,!\s]+mute)*)+|silence|be\s+quiet|quiet)\s+(?:the\s+|this\s+)?(?:video|playback|media|movie|stream|player)(?:\s+audio)?$",
    re.IGNORECASE,
)
RE_MEDIA_UNMUTE = re.compile(
    r"^(?:unmute(?:[,!\s]+unmute)*)+\s+(?:the\s+|this\s+)?(?:video|playback|media|movie|stream|player)(?:\s+audio)?$",
    re.IGNORECASE,
)
RE_MEDIA_SEEK_FWD = re.compile(
    r"^(?:skip\s+forward|skip\s+ahead|fast\s+forward|go\s+forward)(?:\s+(?:by\s+)?(\d+)\s*(?:seconds?|secs?|s)?)?$|^(?:forward)\s+(?:by\s+)?(\d+)\s*(?:seconds?|secs?|s)$",
    re.IGNORECASE,
)
RE_MEDIA_SEEK_BACK = re.compile(
    r"^(?:skip\s+back(?:ward)?|rewind)(?:\s+(?:by\s+)?(\d+)\s*(?:seconds?|secs?|s)?)?$|^(?:go\s+back|backward)\s+(?:by\s+)?(\d+)\s*(?:seconds?|secs?|s)$",
    re.IGNORECASE,
)
RE_MEDIA_NEXT = re.compile(
    r"^(?:next\s+(?:video|track|song|media)|skip\s+(?:video|track|song))$",
    re.IGNORECASE,
)
RE_MEDIA_PREV = re.compile(
    r"^(?:previous|prev)\s+(?:video|track|song|media)$",
    re.IGNORECASE,
)


def parse_media_command(text: str) -> tuple[str | None, dict]:
    """
    Extracts media control intent and parameters from natural speech.
    Returns:
        (action, params) if recognized as a media control intent, else (None, {}).
    """
    cleaned = normalize_spoken_text(text)

    target = None
    for app in ("firefox", "vlc", "spotify", "chromium", "chrome"):
        if app in cleaned:
            target = app
            break

    if RE_MEDIA_PAUSE.match(cleaned):
        return "pause", {"target": target}
    if RE_MEDIA_RESUME.match(cleaned):
        return "resume", {"target": target}
    if RE_MEDIA_STOP.match(cleaned):
        return "stop", {"target": target}
    if RE_MEDIA_MUTE.match(cleaned):
        return "mute", {"mute_state": True, "target": target}
    if RE_MEDIA_UNMUTE.match(cleaned):
        return "mute", {"mute_state": False, "target": target}

    m = RE_MEDIA_SEEK_FWD.match(cleaned)
    if m:
        sec = m.group(1) or m.group(2)
        offset = int(sec) if sec else 10
        return "seek", {"offset": offset, "target": target}

    m = RE_MEDIA_SEEK_BACK.match(cleaned)
    if m:
        sec = m.group(1) or m.group(2)
        offset = int(sec) if sec else 10
        return "seek", {"offset": -offset, "target": target}

    if RE_MEDIA_NEXT.match(cleaned):
        return "next", {"target": target}
    if RE_MEDIA_PREV.match(cleaned):
        return "previous", {"target": target}

    return None, {}


def normalize_spoken_text(text: str) -> str:
    """
    Normalizes speech-recognition acoustic splits, phonetic confusions,
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
    text = re.sub(r"\b(?:lens\s*(?:5|five|fy|ify|i\s*fy|if\s*i)|lensi+fy)\b", "lensify", text, flags=re.IGNORECASE)

    # Collapse urgent repeated single words (e.g. "mute, mute!" -> "mute", "pause, pause" -> "pause", "stop, stop" -> "stop")
    text = re.sub(r"\b(\w+)(?:[,\s!]+(?:\1\b))+", r"\1", text, flags=re.IGNORECASE)

    # Strip trailing punctuation
    text = text.rstrip(".?!,").strip()

    # Strip leading wake words ("jarvis,", "hey jarvis,", etc.)
    text = re.sub(r"^(?:(?:hey|hi|hello|ok|okay)\s+)?jarvis\s*[,:]?\s*", "", text, flags=re.IGNORECASE).strip()

    # Strip conversational prefixes ("can you", "please", "could you", etc.)
    cleaned = re.sub(CONVERSATIONAL_PREFIXES, "", text).strip()
    result = (cleaned if cleaned else text).rstrip(".?!,").strip()
    return result


def sanitize_search_query(query: str) -> str:
    """Cleans speech bleed and trailing instructions from search queries."""
    q = query.strip()
    if q.startswith("for "):
        q = q[4:].strip()
    if q.startswith("about "):
        q = q[6:].strip()

    # Strip trailing noise like 'and play the first result', 'and play it', 'and open it'
    q = re.sub(
        r"\s+(?:and\s+)?(?:play\s+(?:the\s+)?(?:first\s+)?(?:video|result)?|play\s+it|open\s+(?:the\s+)?(?:first\s+)?result|open\s+it|please).*$",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()
    return q.strip("\"' ")


def parse_youtube_play(text: str) -> tuple[str | None, str | None]:
    """
    Detects commands intended to play a video directly on YouTube.
    Returns:
        ('YOUTUBE_FIRST_RESULT', None) for 'open the first youtube result'
        ('YOUTUBE_PLAY_PROMPT', None) for 'play a video on youtube' without a specific title
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

    # 2. Generic prompt phrases with no specific title
    generic_play_phrases = (
        "play a video on youtube", "play video on youtube", "play on youtube",
        "play a video in youtube", "play something on youtube", "play video in youtube",
    )
    if cleaned in generic_play_phrases:
        return "YOUTUBE_PLAY_PROMPT", None

    # 3. "Play on/in YouTube <query>"
    m = re.match(r"^play\s+(?:on|in)\s+youtube\s+(.+)$", cleaned)
    if m:
        query = sanitize_search_query(m.group(1))
        if query:
            return "YOUTUBE_PLAY", query

    # 4. "Play <query> on/in YouTube"
    m = re.match(r"^play\s+(.+?)\s+(?:on|in)\s+youtube$", cleaned)
    if m:
        query = sanitize_search_query(m.group(1))
        if query and query not in ("a video", "video", "something"):
            return "YOUTUBE_PLAY", query
        return "YOUTUBE_PLAY_PROMPT", None

    # 5. "Play <query>" where query is not generic
    m = re.match(r"^play\s+(.+)$", cleaned)
    if m:
        query = sanitize_search_query(m.group(1))
        if query in (
            "a video", "video", "something", "music on youtube",
            "this video", "the video", "playback", "media"
        ):
            return None, None
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

    # Bare search requests with no query
    if cleaned in ("search youtube", "search on youtube", "youtube search"):
        return "youtube", ""
    if cleaned in ("search google", "search on google", "google search"):
        return "google", ""

    # 1. "search/find on/in google|youtube for <query>" or "search/find google|youtube for <query>"
    m = re.match(r"^(?:please\s+)?(?:search|find)\s+(?:on\s+|in\s+)?(google|youtube)\s+for\s*(.*)$", cleaned)
    if m:
        return m.group(1).strip(), sanitize_search_query(m.group(2))

    # 2. "search/find on/in google|youtube <query>" or "search/find google|youtube <query>"
    m = re.match(r"^(?:please\s+)?(?:search|find)\s+(?:on\s+|in\s+)?(google|youtube)\s+(.+)$", cleaned)
    if m:
        return m.group(1).strip(), sanitize_search_query(m.group(2))

    # 3. "search/find <query> on/in google|youtube" or "search/find for <query> on/in google|youtube"
    m = re.match(r"^(?:please\s+)?(?:search|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(google|youtube)$", cleaned)
    if m:
        return m.group(2).strip(), sanitize_search_query(m.group(1))

    # 4. "google|youtube search (for) <query>"
    m = re.match(r"^(google|youtube)\s+search\s+(?:for\s+)?(.*)$", cleaned)
    if m:
        return m.group(1).strip(), sanitize_search_query(m.group(2))

    # 5. "open firefox/new tab and search for <query>", or generic "search for <query>"
    m = re.match(r"^(?:open\s+(?:firefox|a\s+new\s+tab)\s+and\s+)?search\s+(?:for\s+)?(.*)$", cleaned)
    if m:
        raw_query = m.group(1).strip()
        engine = "google"
        if re.search(r"\b(?:on|in)\s+youtube$", raw_query):
            raw_query = re.sub(r"\b(?:on|in)\s+youtube$", "", raw_query).strip()
            engine = "youtube"
        elif re.search(r"\b(?:on|in)\s+google$", raw_query):
            raw_query = re.sub(r"\b(?:on|in)\s+google$", "", raw_query).strip()
            engine = "google"
        elif raw_query.startswith("on youtube ") or raw_query.startswith("in youtube "):
            raw_query = re.sub(r"^(?:on|in)\s+youtube\s+", "", raw_query).strip()
            engine = "youtube"
        elif raw_query.startswith("on google ") or raw_query.startswith("in google "):
            raw_query = re.sub(r"^(?:on|in)\s+google\s+", "", raw_query).strip()
            engine = "google"
        return engine, sanitize_search_query(raw_query)

    return None, None


def parse_type_command(text: str) -> tuple[str | None, bool]:
    """
    Extracts text to type and whether Enter should be pressed.
    Returns:
        (text_to_type, press_enter) if recognized as a typing command, else (None, False).
    """
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


RE_CURRENT_INFO = re.compile(
    r"\b(?:"
    r"what(?:'s|\s+is)\s+happening|"
    r"what(?:'s|\s+is)\s+(?:the\s+)?weather|"
    r"weather\s+(?:in|for|at|today|right\s+now|outside)|"
    r"(?:the\s+)?latest\s+(?:news|info(?:rmation)?|updates?|headlines?|version|release|score|details)|"
    r"(?:recent|breaking)\s+(?:news|headlines?|events?|updates?)|"
    r"news\s+(?:about|on|regarding)|"
    r"(?:today(?:'s)?|tonight(?:'s)?)\s+(?:news|headlines|weather|forecast|score|events?)|"
    r"(?:news|headlines|weather|forecast|score|events?)\s+(?:today|tonight|yesterday|right\s+now|currently)|"
    r"\b(?:today|right\s+now|currently|latest|breaking|recent\s+news)\b|"
    r"\bcurrent\b(?!\s+(?:tab|window|folder|directory|interaction|app))"
    r")",
    re.IGNORECASE,
)


def is_current_info_query(text: str) -> bool:
    """
    Identifies whether an utterance seeks live, real-time web or current news/weather information.
    """
    clean = text.lower().strip()
    return bool(RE_CURRENT_INFO.search(clean))


def detect_intent(text: str, pending_action: str | None = None) -> tuple[str, dict]:
    """
    Analyzes spoken text and determines the structured intent and parameters.

    Returns:
        (intent_name, intent_params)
    """
    clean_text = normalize_spoken_text(text)

    # 1. Pending confirmation and prompt responses
    context = get_conversation_context()
    valid_pending, pending_payload = context.get_valid_pending()
    active_pending = pending_action or valid_pending

    if active_pending:
        affirmative = (
            "yes", "confirm", "do it", "sure", "yeah", "yep", "yes please",
            "yes, please", "close it", "open it", "proceed", "go ahead",
            "save", "save it", "save workflow", "delete", "delete it",
        )
        negative = ("no", "cancel", "stop", "abort", "don't", "dont", "no thanks", "never mind")
        if clean_text in affirmative:
            return "CONFIRM_ACTION", {"action": active_pending, "payload": pending_payload or {}}
        elif clean_text in negative:
            return "CANCEL_ACTION", {"action": active_pending}

    if active_pending == "clarify_workflow_folder":
        candidates = (pending_payload or {}).get("candidates", [])
        chosen = None
        for cand in candidates:
            parts = cand.lower().split("/")
            c_name = parts[-1] if parts else ""
            c_parent = parts[-2] if len(parts) >= 2 else ""
            if cand.lower() in clean_text or (c_parent and c_parent in clean_text):
                chosen = cand
                break
        if not chosen:
            if "first" in clean_text and len(candidates) >= 1:
                chosen = candidates[0]
            elif "second" in clean_text and len(candidates) >= 2:
                chosen = candidates[1]
            elif "third" in clean_text and len(candidates) >= 3:
                chosen = candidates[2]
        if chosen:
            return "CONFIRM_ACTION", {
                "action": "confirm_workflow_folder_choice",
                "payload": {
                    "chosen_path": chosen,
                    **(pending_payload or {}),
                },
            }

    if pending_action == "youtube_play" and clean_text:
        return "YOUTUBE_PLAY", {"query": clean_text}

    if pending_action == "search_google" and clean_text:
        return "BROWSER_SEARCH", {"engine": "google", "query": clean_text}

    if pending_action == "search_youtube" and clean_text:
        return "BROWSER_SEARCH", {"engine": "youtube", "query": clean_text}

    if active_pending == "set_volume_query" and clean_text:
        vol_res = extract_volume_intent(f"set volume to {clean_text}")
        if vol_res and vol_res.get("action") in ("volume_set", "volume_limit_clarification"):
            return "SMART_ACTION", vol_res

    if active_pending == "delete_workflow_prompt" and clean_text:
        return "SMART_ACTION", {"action": "delete_workflow", "params": {"workflow_name": clean_text}}

    if active_pending == "clarify_media_player":
        candidates = (pending_payload or {}).get("candidates", [])
        act = (pending_payload or {}).get("action", "pause")
        extra = (pending_payload or {}).get("params", {})
        selected = None
        for cand in candidates:
            if cand.lower() in clean_text:
                selected = cand
                break
        if not selected:
            if "first" in clean_text and len(candidates) >= 1:
                selected = candidates[0]
            elif "second" in clean_text and len(candidates) >= 2:
                selected = candidates[1]
        if selected:
            return "MEDIA_CONTROL", {"action": act, "target": selected, **extra}

    # 2. Exit commands
    if any(clean_text == cmd or clean_text.startswith(cmd) or clean_text.endswith(cmd) for cmd in EXIT_COMMANDS):
        return "EXIT", {}

    # 3. Close current tab (requests confirmation)
    if any(
        clean_text == trigger or clean_text.startswith(trigger)
        for trigger in ("close the current tab", "close current tab", "close this tab", "close the tab", "close tab")
    ):
        return "REQUEST_CONFIRMATION", {"action": "close_tab"}

    # 3.5 Deterministic Media and Video Playback Controls Fast-Path
    media_action, media_params = parse_media_command(text)
    if media_action is not None:
        return "MEDIA_CONTROL", {"action": media_action, **media_params}

    # 4. YouTube Direct Video Playback (Play ... on YouTube, Open first result, Prompt)
    play_intent, play_query = parse_youtube_play(clean_text)
    if play_intent == "YOUTUBE_FIRST_RESULT":
        return "YOUTUBE_FIRST_RESULT", {}
    if play_intent == "YOUTUBE_PLAY_PROMPT":
        return "YOUTUBE_PLAY_PROMPT", {}
    if play_intent == "YOUTUBE_PLAY":
        return "YOUTUBE_PLAY", {"query": play_query}

    # 5. Web search intent (Google or YouTube search results page)
    engine, query = parse_search_command(clean_text)
    if engine is not None:
        if not query:
            return "SEARCH_PROMPT", {"engine": engine}
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

    if TERMINAL_COMMAND_PATTERN.match(clean_text):
        return "DESKTOP_ACTION", {"action": "open_terminal"}

    if any(trigger in clean_text for trigger in ("open downloads", "open download", "open downloads folder", "downloads folder")):
        return "DESKTOP_ACTION", {"action": "open_downloads"}

    if any(trigger in clean_text for trigger in ("open youtube", "launch youtube", "start youtube")):
        return "DESKTOP_ACTION", {"action": "open_youtube"}

    # 8.5 Natural-Language Smart Intent & Learned Workflow Routing
    smart = extract_smart_intent(clean_text)
    if smart:
        return "SMART_ACTION", smart

    # 8.8 Real-Time Web Search & Current Information Questions (Stage 5)
    if is_current_info_query(clean_text):
        return "CURRENT_INFO_QUERY", {"query": clean_text, "raw": text}

    # 9. Low-confidence / Unclear speech filtering (Prevents random noise from reaching Ollama)
    if clean_text in UNCLEAR_NOISE or len(clean_text) <= 2:
        return "UNCLEAR_SPEECH", {"raw": text}

    # Questions or meaningful conversation statements route to Ollama
    question_starters = (
        "what", "how", "why", "who", "when", "where", "is", "are", "can", "could",
        "would", "will", "tell", "explain", "do", "does", "which"
    )
    is_question = (
        bool(re.search(r"\?\s*$", text))
        or clean_text.endswith("?")
        or any(clean_text.startswith(q + " ") for q in question_starters)
    )
    if is_question:
        return "OLLAMA_QUERY", {"prompt": clean_text}

    return "UNCLEAR_SPEECH", {"raw": text}

