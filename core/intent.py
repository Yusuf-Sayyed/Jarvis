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
    r"^(?:open|launch|start|run)\s+(?:(?:a|an|the|another)\s+)?(?:new\s+)?(?:terminal|konsole|console)(?:\s+window)?(?:\s+(?:for\s+me|please))?$",
    re.IGNORECASE,
)

BROWSER_COMMAND_PATTERN = re.compile(
    r"^(?:open|launch|start|run)\s+(?:(?:a|an|the|another)\s+)?(?:new\s+)?(?:browser|web\s+browser|default\s+browser)(?:\s+window)?(?:\s+(?:for\s+me|please))?$",
    re.IGNORECASE,
)

FIREFOX_COMMAND_PATTERN = re.compile(
    r"^(?:open|launch|start|run)\s+(?:(?:a|an|the|another)\s+)?(?:new\s+)?firefox(?:\s+window)?(?:\s+(?:for\s+me|please))?$",
    re.IGNORECASE,
)

RE_APP_LAUNCH_COMMAND = re.compile(
    r"^(?:open|launch|start|run)\s+(?:(?:a|an|the|another)\s+)?(?:new\s+)?(.+?)(?:\s+window)?(?:\s+(?:for\s+me|please))?$",
    re.IGNORECASE,
)

UNCLEAR_NOISE = {
    "um", "uh", "ah", "the", "a", "an", "huh", "oh", "hmm", "and", "or", "so", "to"
}

GENUINE_NOISE_PHRASES = {
    "look at him",
    "you're being tried",
    "the table is blue",
}

DANGLING_CONFIRMATIONS = {
    "yes", "yes please", "yes, please", "yes thanks", "yes, thanks", "yeah", "yep", "no", "nope", "cancel",
    "sure", "ok", "okay", "alright", "all right"
}

RE_AMBIGUOUS_OPEN_PROJECT = re.compile(
    r"^(?:open|launch|start)\s+(?:a\s+|the\s+|my\s+)?(?:project|folder|directory|repo)$",
    re.IGNORECASE,
)
RE_AMBIGUOUS_OPEN_APP = re.compile(
    r"^(?:open|launch|start)\s+(?:an?\s+|the\s+)?(?:application|app|program)$",
    re.IGNORECASE,
)
RE_AMBIGUOUS_BRIGHTNESS = re.compile(
    r"^(?:set|turn|change|adjust)\s+(?:the\s+)?(?:screen\s+|display\s+)?brightness$",
    re.IGNORECASE,
)

RE_CONVERSATIONAL_STATEMENT = re.compile(
    r"\b(?:"
    r"my\s+name\s+is|"
    r"call\s+me\s+[A-Za-z]+|"
    r"let\s+me\s+introduce\s+myself|"
    r"introduce\s+myself|"
    r"nice\s+to\s+meet\s+you|"
    r"pleased\s+to\s+meet\s+you|"
    r"i\s+(?:live|reside)\s+in|"
    r"i(?:\x27m|\s+am)\s+from|"
    r"i(?:\x27m|\s+am)\s+(?:a\s+)?(?:young|old|developer|engineer|coder|student|designer|programmer)|"
    r"\d{1,2}\s*(?:years?\s+old|yrs?\s+old)|"
    r"remember\s+(?:that\s+)?my|"
    r"remember\s+(?:that\s+)?i\b|"
    r"remember\s+this|"
    r"remember\s+me\b|"
    r"remember\b|"
    r"do\s+you\s+remember\b|"
    r"who\s+am\s+i\b|"
    r"what\s+is\s+my\s+name\b|"
    r"where\s+do\s+i\s+live\b|"
    r"how\s+old\s+am\s+i\b|"
    r"what\s+do\s+you\s+know\s+about\s+me\b|"
    r"hello\b|hi\b|hey\b|good\s+(?:morning|afternoon|evening|day)|"
    r"thank\s+you|thanks(?:\s+a\s+lot)?|"
    r"how\s+(?:are\s+you|you\s+are)\s+doing|how\s+are\s+you|how(?:\x27s|\s+is)\s+it\s+going|how\s+do\s+you\s+do"
    r")\b",
    re.IGNORECASE,
)

RE_START_TUTORING = re.compile(
    r"^(?:(?:can\s+you\s+|could\s+you\s+|please\s+|help\s+me\s+|let\'?s\s+|i\s+want\s+to\s+)?)"
    r"(?:"
    r"(?:teach|train|coach)\s+(?:me\s+)?(?:about\s+)?([a-z0-9#+.\s]+?)(?:\s+basics?)?|"
    r"(?:learn|study)\s+([a-z0-9#+.\s]+?)(?:\s+basics?)?|"
    r"start\s+(?:a\s+|the\s+)?([a-z0-9#+.\s]+?)\s+(?:lesson|tutorial|tutoring)|"
    r"give\s+me\s+(?:a\s+|the\s+)?([a-z0-9#+.\s]+?)\s+(?:lesson|tutorial)"
    r")$",
    re.IGNORECASE,
)

RE_FILE_CREATION_COMMAND = re.compile(
    r"^(?:please\s+)?(?:can\s+you\s+)?(?:create|make|write|generate|touch)\s+(?:a\s+|an\s+)?(?:new\s+)?(?:file|script|code\s+file)(?:\s+(?:called|named)\s+([a-zA-Z0-9_.-]+)|\s+([a-zA-Z0-9_.-]+\.[a-zA-Z0-9]+))?.*$",
    re.IGNORECASE,
)


# Media control patterns
_MEDIA_NOUNS = r"(?:(?:the\s+|this\s+|my\s+|that\s+|all\s+)?(?:current\s+)?)(?:video|playback|media|music|playing|song|track|movie|stream|audio)"
_MEDIA_TARGETS = r"(?:youtube|firefox|vlc|spotify|chromium|chrome|browser|player)"
_MEDIA_CLAUSE = (
    r"(?:"
    r"(?:\s+(?:which|that)\s+is\s+(?:currently\s+)?(?:playing|running|active))|"
    r"(?:\s+(?:currently\s+)?(?:playing|running|active))"
    r")?"
    r"(?:\s+(?:on|in)\s+" + _MEDIA_TARGETS + r")?"
)

RE_MEDIA_PAUSE = re.compile(
    r"^(?:"
    r"(?:pause|hold\s+on)(?:\s+" + _MEDIA_NOUNS + r")?" + _MEDIA_CLAUSE + r"|"
    r"pause\s+" + _MEDIA_TARGETS + r"(?:\s+(?:playback|video|music|song))?|"
    r"pause"
    r")$",
    re.IGNORECASE,
)
RE_MEDIA_RESUME = re.compile(
    r"^(?:"
    r"resume(?:\s+or\s+continue\s+playback)?(?:\s+playback|\s+playing|\s+" + _MEDIA_NOUNS + r")?" + _MEDIA_CLAUSE + r"|"
    r"continue(?:\s+playback|\s+playing|\s+" + _MEDIA_NOUNS + r")?" + _MEDIA_CLAUSE + r"|"
    r"unpause(?:\s+playback|\s+" + _MEDIA_NOUNS + r")?" + _MEDIA_CLAUSE + r"|"
    r"play(?:\s+" + _MEDIA_NOUNS + r")(?:\s+(?:on|in)\s+" + _MEDIA_TARGETS + r")?|"
    r"resume\s+" + _MEDIA_TARGETS + r"(?:\s+(?:playback|video|music|song))?|"
    r"play"
    r")$",
    re.IGNORECASE,
)
RE_MEDIA_STOP = re.compile(
    r"^(?:"
    r"stop(?:\s+playing)?(?:\s+" + _MEDIA_NOUNS + r")?" + _MEDIA_CLAUSE + r"|"
    r"stop\s+" + _MEDIA_TARGETS + r"(?:\s+(?:playback|video|music|song))?|"
    r"stop"
    r")$",
    re.IGNORECASE,
)
RE_MEDIA_MUTE = re.compile(
    r"^(?:(?:mute(?:[,!\s]+mute)*)+|silence|be\s+quiet|quiet)(?:\s+(?:the\s+|this\s+|system\s+)?(?:video|playback|media|movie|stream|player|audio|sound|volume))?$",
    re.IGNORECASE,
)
RE_MEDIA_UNMUTE = re.compile(
    r"^(?:unmute(?:[,!\s]+unmute)*)+(?:\s+(?:the\s+|this\s+|system\s+)?(?:video|playback|media|movie|stream|player|audio|sound|volume))?$",
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
    for app in ("firefox", "vlc", "spotify", "chromium", "chrome", "youtube"):
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


def is_conversational_play_mention(raw_text: str) -> bool:
    """
    Identifies whether 'play' is used conversationally rather than as an executable
    media or YouTube command, preserving Ollama dialogue.
    """
    low = raw_text.lower().strip().rstrip(".?!,")
    # Questions about playing games, sports, instruments, roles
    if re.search(
        r"\b(?:can\s+you|could\s+you|do\s+you|are\s+you\s+able\s+to|did\s+you|have\s+you\s+ever|can\s+we)\s+play(?:ed)?\s+"
        r"(?:chess|games?|video\s+games?|cards?|football|soccer|basketball|tennis|cricket|golf|guitar|piano|violin|drums?|instruments?|roles?|with\s+me)\b",
        low,
    ):
        return True
    # Inquiries about why/how/what regarding play
    if re.search(r"\b(?:why\s+do|how\s+do|what\s+is|what\s+are|tell\s+me\s+about|discuss)\b.*?\b(?:play|plays|playing)\b", low):
        return True
    # Theatrical plays / Shakespeare
    if re.search(r"\b(?:shakespeare|theatre|theater|broadway|drama|stage)\b.*?\bplays?\b", low):
        return True
    # Idiomatic play ("plays a role", etc.)
    if re.search(r"\bplays?\s+(?:a\s+role|a\s+part|an\s+important\s+role|a\s+key\s+role|in\s+culture|in\s+society)\b", low):
        return True
    # General music/song opinions, tastes, discussions
    if re.search(r"\b(?:what\s+do\s+you\s+think\s+of|do\s+you\s+like|tell\s+me\s+about|who\s+is\s+your\s+favorite|do\s+you\s+listen\s+to)\b.*?\b(?:songs?|music|videos?|artists?|bands?|albums?)\b", low):
        return True
    if re.search(r"\b(?:talk\s+about|discuss|chat\s+about|conversation\s+about|opinion\s+on)\b.*?\b(?:music|songs?|artists?|albums?|bands?)\b", low):
        return True
    if re.search(r"\b(?:why\s+do|how\s+do|what\s+makes)\b.*?\b(?:music|songs?|melod(?:y|ies))\b", low):
        return True
    return False


def extract_embedded_volume(text: str) -> tuple[str, int | None]:
    """
    Extracts trailing or embedded volume adjustments from an utterance.
    E.g. 'search for hollywood songs and play it at 100% volume' -> ('search for hollywood songs and play it', 100)
    E.g. 'play it at 100% volume' -> ('play it', 100)
    E.g. 'set volume to 100%' -> ('set volume to 100%', 100)
    """
    from intelligence.intent_extractor import parse_spoken_number
    normalized = parse_spoken_number(text.lower().strip())
    normalized = re.sub(r"\b(?:percent|percentage)\b", "%", normalized)

    patterns = [
        # "and play it at 100% volume", "at 100% volume", "with 100% volume"
        r"\b(?:and\s+)?(?:set(?:\s+the)?\s+volume\s+(?:to\s+|at\s+))(\d{1,3})\s*%?\b",
        r"\b(?:and\s+)?(?:at|with)\s+(\d{1,3})\s*%\s*(?:volume)?\b",
        r"\b(?:and\s+)?(?:at|with)\s+(\d{1,3})\s+volume\b",
        r"\b(?:and\s+)?(?:at|with)\s+volume\s+(\d{1,3})\s*%?\b",
        r"\b(?:and\s+)?(?:at|with)\s+(\d{1,3})\s*%\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, normalized, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            cleaned = normalized[:m.start()] + " " + normalized[m.end():]
            cleaned = re.sub(r"\s+", " ", cleaned).strip()
            return cleaned, val

    return text, None


def extract_embedded_play(text: str) -> tuple[str, bool]:
    """
    Detects trailing play directives in combined utterances.
    E.g. 'search youtube for hollywood songs and play it' -> ('search youtube for hollywood songs', True)
    E.g. 'find the doomsday trailer on youtube' -> ('find the doomsday trailer on youtube', False)
    """
    patterns = [
        r"\s+(?:and\s+)?(?:just\s+)?(?:play\s+it|play\s+this|play\s+the\s+video|play\s+the\s+first\s+result|play\s+first\s+result|auto\s*play\s*it|play\s+it\s+please|please\s+play\s+it)\s*$",
        r"\s+(?:and\s+)?play\s*$",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            cleaned = text[:m.start()].strip()
            return cleaned, True
    return text, False


RE_FOLLOW_UP_PLAY = re.compile(
    r"^(?:(?:yes|yeah|yep|sure|ok|okay)\s*[,:]?\s*)?"
    r"(?:(?:please|just|go\s+ahead\s+and)\s+)*"
    r"(?:play\s+it|just\s+play\s+it|go\s+ahead\s+and\s+play\s+it)"
    r"(?:[,\s]+(?:please|for\s+me))?$",
    re.IGNORECASE,
)


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

    # Strip leading conversational greetings followed by comma or colon ("okay, on youtube...", "alright, search...")
    text = re.sub(r"^(?:(?:ok|okay|well|alright)\s*[,:]\s*)+(?=[a-z0-9])", "", text, flags=re.IGNORECASE).strip()

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

    # Strip embedded volume request: e.g. "at 100% volume", "at 100 percent volume", "at 100%"
    q = re.sub(
        r"\s+(?:and\s+)?(?:(?:at|with|set(?:\s+the)?\s+volume\s+to|volume\s+at)\s+\d{1,3}\s*%?\s*(?:volume)?|at\s+\d{1,3}\s*%).*$",
        "",
        q,
        flags=re.IGNORECASE,
    ).strip()

    # Strip trailing noise like 'and play the first result', 'and play it', 'and open it'
    q = re.sub(
        r"\s+(?:and\s+)?(?:just\s+)?(?:play\s+(?:the\s+)?(?:first\s+)?(?:video|result)?|play\s+it(?:\s+please)?|open\s+(?:the\s+)?(?:first\s+)?result|open\s+it|please).*$",
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
        ('YOUTUBE_PLAY', query) for 'play ... on youtube' or 'search ... and play it'
        (None, None) if not a play command.
    """
    if is_conversational_play_mention(text):
        return None, None

    cleaned = normalize_spoken_text(text)
    cleaned_no_vol, _ = extract_embedded_volume(cleaned)

    # 1. "Open the first YouTube result" / "Play the first result"
    first_result_phrases = (
        "open the first youtube result", "open first youtube result",
        "open the first result", "open first result",
        "play the first youtube result", "play first youtube result",
        "play the first result", "play first result"
    )
    if cleaned_no_vol in first_result_phrases:
        return "YOUTUBE_FIRST_RESULT", None

    # 2. Generic prompt phrases with no specific title
    generic_play_phrases = (
        "play a video on youtube", "play video on youtube", "play on youtube",
        "play a video in youtube", "play something on youtube", "play video in youtube",
        "play youtube video", "play youtube",
    )
    if cleaned_no_vol in generic_play_phrases:
        return "YOUTUBE_PLAY_PROMPT", None

    # 3. Combined search + play:
    # "on youtube search for <query> and play it" / "search youtube for <query> and play it"
    # "search for <query> on youtube and play it" / "find <query> on youtube and play it"
    # "search for <query> and play it"
    cleaned_base, auto_play = extract_embedded_play(cleaned_no_vol)
    if auto_play:
        m = re.match(r"^(?:on\s+youtube\s+)?(?:search|find)\s+(?:on\s+|in\s+)?(?:youtube\s+)?(?:for\s+)?(.+?)(?:\s+(?:on|in)\s+youtube)?$", cleaned_base)
        if m:
            query = sanitize_search_query(m.group(1))
            if query:
                return "YOUTUBE_PLAY", query
        m = re.match(r"^youtube\s+search\s+(?:for\s+)?(.+)$", cleaned_base)
        if m:
            query = sanitize_search_query(m.group(1))
            if query:
                return "YOUTUBE_PLAY", query

    # 4. "Play on/in YouTube <query>"
    m = re.match(r"^play\s+(?:on|in)\s+youtube\s+(.+)$", cleaned_no_vol)
    if m:
        query = sanitize_search_query(m.group(1))
        if query:
            return "YOUTUBE_PLAY", query

    # 5. "Play <query> on/in YouTube"
    m = re.match(r"^play\s+(.+?)\s+(?:on|in)\s+youtube$", cleaned_no_vol)
    if m:
        query = sanitize_search_query(m.group(1))
        if query and query not in ("a video", "video", "something", "music"):
            return "YOUTUBE_PLAY", query
        return "YOUTUBE_PLAY_PROMPT", None

    # 6. "Play <query>" where query is not generic
    m = re.match(r"^play\s+(.+)$", cleaned_no_vol)
    if m:
        query = sanitize_search_query(m.group(1))
        if query in (
            "a video", "video", "something", "music on youtube",
            "this video", "the video", "the current video", "current video",
            "current track", "current song", "playback", "media", "it"
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
    cleaned_no_vol, _ = extract_embedded_volume(cleaned)

    # Bare search requests with no query
    if cleaned_no_vol in ("search youtube", "search on youtube", "youtube search"):
        return "youtube", ""
    if cleaned_no_vol in ("search google", "search on google", "google search"):
        return "google", ""

    # 0. "on youtube search (for) <query>"
    m = re.match(r"^on\s+youtube\s+(?:search|find)\s+(?:for\s+)?(.+)$", cleaned_no_vol)
    if m:
        return "youtube", sanitize_search_query(m.group(1))

    # 1. "search/find on/in google|youtube for <query>" or "search/find google|youtube for <query>"
    m = re.match(r"^(?:please\s+)?(?:search|find)\s+(?:on\s+|in\s+)?(google|youtube)\s+for\s*(.*)$", cleaned_no_vol)
    if m:
        return m.group(1).strip(), sanitize_search_query(m.group(2))

    # 2. "search/find on/in google|youtube <query>" or "search/find google|youtube <query>"
    m = re.match(r"^(?:please\s+)?(?:search|find)\s+(?:on\s+|in\s+)?(google|youtube)\s+(.+)$", cleaned_no_vol)
    if m:
        return m.group(1).strip(), sanitize_search_query(m.group(2))

    # 3. "search/find <query> on/in google|youtube" or "search/find for <query> on/in google|youtube"
    m = re.match(r"^(?:please\s+)?(?:search|find)\s+(?:for\s+)?(.+?)\s+(?:on|in)\s+(google|youtube)$", cleaned_no_vol)
    if m:
        return m.group(2).strip(), sanitize_search_query(m.group(1))

    # 4. "google|youtube search (for) <query>"
    m = re.match(r"^(google|youtube)\s+search\s+(?:for\s+)?(.*)$", cleaned_no_vol)
    if m:
        return m.group(1).strip(), sanitize_search_query(m.group(2))

    # 5. "open firefox/new tab and search for <query>", or generic "search for <query>"
    m = re.match(r"^(?:open\s+(?:firefox|a\s+new\s+tab)\s+and\s+)?search\s+(?:for\s+)?(.*)$", cleaned_no_vol)
    if m:
        raw_query = m.group(1).strip()
        # If the search explicitly targets the web / online rather than a browser engine, delegate to web search
        if re.match(r"^(?:the\s+web|online|the\s+internet)\b", raw_query, re.IGNORECASE):
            return None, None
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
    r"\bcurrent\b(?!\s+(?:tab|window|folder|directory|interaction|app))|"
    r"(?:search|look\s+up)\s+(?:the\s+web|online|the\s+internet)\s+for\b|"
    r"(?:search|look\s+up)\s+for\s+(?:.+?)\s+(?:on|in)\s+(?:the\s+web|the\s+internet|online)\b|"
    r"look\s+up\b|"
    r"web\s+search\b"
    r")",
    re.IGNORECASE,
)


def is_current_info_query(text: str) -> bool:
    """
    Identifies whether an utterance seeks live, real-time web or current news/weather information.
    Guarantees that private personal memory questions and local time/date questions never trigger web search.
    """
    from intelligence.memory_extractor import is_personal_memory_query
    if is_personal_memory_query(text):
        return False
    from actions.clock import parse_time_date_query
    if parse_time_date_query(text) is not None:
        return False
    clean = text.lower().strip()
    if RE_CONVERSATIONAL_STATEMENT.search(clean):
        return False
    return bool(RE_CURRENT_INFO.search(clean))


def detect_intent(text: str, pending_action: str | None = None) -> tuple[str, dict]:
    """
    Analyzes spoken text and determines the structured intent and parameters.

    Returns:
        (intent_name, intent_params)
    """
    is_conversational = is_conversational_play_mention(text)
    clean_text = normalize_spoken_text(text)

    # 1. Pending confirmation and prompt responses
    context = get_conversation_context()
    valid_pending, pending_payload = context.get_valid_pending()
    active_pending = pending_action or valid_pending

    affirmative = (
        "yes", "confirm", "do it", "sure", "yeah", "yep", "yes please",
        "yes, please", "close it", "open it", "proceed", "go ahead",
        "save", "save it", "save workflow", "delete", "delete it",
    )
    negative = ("no", "cancel", "stop", "abort", "don't", "dont", "no thanks", "never mind")

    if pending_action == "youtube_play" and clean_text:
        if clean_text in affirmative or RE_FOLLOW_UP_PLAY.match(clean_text):
            pending_q, pending_url = context.get_pending_youtube()
            if not pending_q:
                pending_q = (pending_payload or {}).get("query") or context.get_recent_youtube_query()
            if pending_q:
                params = {"query": pending_q, "url": pending_url, "auto_play": True}
                return "YOUTUBE_PLAY", params
            else:
                return "YOUTUBE_PLAY_PROMPT", {}
        elif clean_text in negative:
            return "CANCEL_ACTION", {"action": "youtube_play"}
        elif not is_conversational:
            if TERMINAL_COMMAND_PATTERN.match(clean_text):
                return "DESKTOP_ACTION", {"action": "open_terminal"}
            if BROWSER_COMMAND_PATTERN.match(clean_text) or FIREFOX_COMMAND_PATTERN.match(clean_text):
                return "DESKTOP_ACTION", {"action": "open_browser"}
            vol_res = extract_volume_intent(clean_text)
            if vol_res and vol_res.get("action") in ("volume_set", "volume_change", "mute_audio"):
                return "SMART_ACTION", vol_res
            text_no_vol, emb_vol = extract_embedded_volume(clean_text)
            params = {"query": text_no_vol, "auto_play": True}
            if emb_vol is not None:
                params["volume"] = emb_vol
            return "YOUTUBE_PLAY", params

    if active_pending:
        if clean_text in affirmative:
            return "CONFIRM_ACTION", {"action": active_pending, "payload": pending_payload or {}}
        elif clean_text in negative:
            return "CANCEL_ACTION", {"action": active_pending}

    # Follow-up play resolution against pending/recent YouTube context
    if not is_conversational:
        text_no_vol, follow_vol = extract_embedded_volume(clean_text)
        if RE_FOLLOW_UP_PLAY.match(text_no_vol):
            pending_q, pending_url = context.get_pending_youtube()
            if not pending_q:
                pending_q = context.get_recent_youtube_query()
            if not pending_q:
                from actions import browser
                pending_q = browser.LAST_YOUTUBE_QUERY

            if pending_q:
                params = {"query": pending_q, "url": pending_url, "auto_play": True}
                if follow_vol is not None:
                    params["volume"] = follow_vol
                return "YOUTUBE_PLAY", params
            else:
                params = {}
                if follow_vol is not None:
                    params["volume"] = follow_vol
                return "YOUTUBE_PLAY_PROMPT", params

    # Dangling confirmation/rejection tokens without active pending confirmation
    norm_confirm = clean_text.replace(",", "").strip()
    if not active_pending and (
        clean_text in DANGLING_CONFIRMATIONS
        or norm_confirm in DANGLING_CONFIRMATIONS
        or clean_text.rstrip(".").rstrip(",") in DANGLING_CONFIRMATIONS
    ):
        return "UNCLEAR_SPEECH", {"raw": text}

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

    if active_pending == "clarify_memory_update" and clean_text:
        return "CONFIRM_ACTION", {
            "action": "confirm_memory_update",
            "payload": {"new_value": text.strip(), **(pending_payload or {})},
        }

    if active_pending == "clarify_memory_forget" and clean_text:
        candidates = (pending_payload or {}).get("candidates", [])
        chosen = None
        for cand in candidates:
            if cand.lower().replace("_", " ") in clean_text or cand.lower() in clean_text:
                chosen = cand
                break
        if not chosen:
            if "first" in clean_text and len(candidates) >= 1:
                chosen = candidates[0]
            elif "second" in clean_text and len(candidates) >= 2:
                chosen = candidates[1]
            elif "third" in clean_text and len(candidates) >= 3:
                chosen = candidates[2]
            else:
                chosen = clean_text.strip().replace(" ", "_")
        return "CONFIRM_ACTION", {
            "action": "confirm_memory_forget",
            "payload": {"target_key": chosen, **(pending_payload or {})},
        }

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

    if active_pending == "clarify_time_location" and clean_text:
        from actions.clock import parse_time_date_query
        new_q = parse_time_date_query(text)
        if new_q is not None:
            return "TIME_DATE_QUERY", new_q
        orig = (pending_payload or {}).get("original_query", {})
        q_type = orig.get("type", "time")
        return "TIME_DATE_QUERY", {"type": q_type, "location": clean_text, "raw": text}

    if active_pending == "clarify_open_project" and clean_text:
        return "SMART_ACTION", {"action": "open_project", "params": {"project": clean_text, "app": "editor"}}

    if active_pending == "clarify_launch_app" and clean_text:
        from actions.resolver import get_app_registry
        app_info = get_app_registry().resolve_application(clean_text)
        if app_info:
            return "DESKTOP_ACTION", {"action": "launch_app", "app": app_info.name, "exec_path": app_info.exec_path}
        return "DESKTOP_ACTION", {"action": "launch_app", "app": clean_text}

    if active_pending == "clarify_lesson_or_command" and clean_text:
        orig_command = (pending_payload or {}).get("command", "")
        context.clear_pending()
        if any(w in clean_text for w in ("command", "execute", "run", "open", "launch", "yes", "yeah", "yep", "sure")):
            clean_cmd = normalize_text_for_intent(orig_command)
            if TERMINAL_COMMAND_PATTERN.match(clean_cmd):
                return "DESKTOP_ACTION", {"action": "open_terminal"}
            if BROWSER_COMMAND_PATTERN.match(clean_cmd):
                return "DESKTOP_ACTION", {"action": "open_browser"}
            if FIREFOX_COMMAND_PATTERN.match(clean_cmd):
                return "DESKTOP_ACTION", {"action": "open_firefox"}
            m_app = RE_APP_LAUNCH_COMMAND.match(clean_cmd)
            if m_app:
                from actions.resolver import get_app_registry
                app_target = m_app.group(1).strip().lower()
                app_info = get_app_registry().resolve_application(app_target)
                if app_info:
                    return "DESKTOP_ACTION", {"action": "launch_app", "app": app_info.name, "exec_path": app_info.exec_path}
            return "DESKTOP_ACTION", {"action": "launch_app", "app": orig_command}
        else:
            act = context.get_active_activity()
            q = act.current_question if act else ""
            top = act.topic if act else "python"
            st = act.lesson_step if act else 1
            return "TUTORING_ANSWER", {"answer": orig_command, "question": q, "topic": top, "step": st}

    # 2. Exit commands
    if any(clean_text == cmd or clean_text.startswith(cmd) or clean_text.endswith(cmd) for cmd in EXIT_COMMANDS):
        return "EXIT", {}

    # 2.5 Active Tutoring & Interactive Activity Context
    if context.is_awaiting_activity_answer():
        # High-priority hardware volume adjustments override tutoring
        vol_res = extract_volume_intent(clean_text)
        if vol_res and vol_res.get("action") in ("volume_set", "volume_change", "mute_audio"):
            return "SMART_ACTION", vol_res

        # Media pause/stop overrides tutoring
        m_act, m_params = parse_media_command(text)
        if m_act in ("pause", "stop"):
            return "MEDIA_CONTROL", {"action": m_act, **m_params}

        # Tutoring lifecycle controls
        if any(k in clean_text for k in (
            "stop the lesson", "stop lesson", "stop tutoring", "exit lesson",
            "quit lesson", "pause lesson", "end the lesson", "end lesson",
            "stop teaching", "cancel lesson"
        )):
            return "TUTORING_CONTROL", {"action": "stop_lesson"}

        if any(k in clean_text for k in (
            "give me a hint", "give a hint", "can i have a hint", "need a hint",
            "hint please", "hint", "clue", "give me a clue"
        )):
            return "TUTORING_CONTROL", {"action": "give_hint"}

        if any(clean_text == k or clean_text.startswith(k) for k in (
            "i don't know", "i dont know", "no idea", "not sure",
            "i have no idea", "dunno", "pass"
        )):
            return "TUTORING_CONTROL", {"action": "dont_know"}

        if any(clean_text == k for k in (
            "next question", "skip question", "skip", "next", "move on", "next one"
        )):
            return "TUTORING_CONTROL", {"action": "next_question"}

        if any(k in clean_text for k in (
            "explain that", "explain this", "explain why", "elaborate", "can you explain"
        )):
            return "TUTORING_CONTROL", {"action": "explain"}

        # Check for ambiguous direct desktop command vs lesson answer
        is_desktop_cmd = bool(
            TERMINAL_COMMAND_PATTERN.match(clean_text) or
            BROWSER_COMMAND_PATTERN.match(clean_text) or
            FIREFOX_COMMAND_PATTERN.match(clean_text)
        )
        if is_desktop_cmd:
            act = context.get_active_activity()
            q_lower = (act.current_question if act else "").lower()
            if not any(w in q_lower for w in ("editor", "terminal", "browser", "app", "application", "tool", "program")):
                return "CLARIFY_ACTION", {
                    "action": "clarify_lesson_or_command",
                    "command": clean_text,
                    "question": f"Did you mean to run '{clean_text}', or is that your answer to the lesson question, Sir?",
                    "raw": text,
                }

        # Utterance is treated as the answer to the active lesson question
        act = context.get_active_activity()
        return "TUTORING_ANSWER", {
            "answer": clean_text,
            "question": act.current_question if act else "",
            "topic": act.topic if act else "python",
            "step": act.lesson_step if act else 1,
            "raw": text,
        }

    # 2.8 Interactive Learning & Tutoring Sessions Initiation
    m_tutoring = RE_START_TUTORING.match(clean_text)
    if m_tutoring:
        matched_topic = next((g for g in m_tutoring.groups() if g), "python").strip().lower()
        if "python" in matched_topic or matched_topic == "":
            matched_topic = "python"
        return "START_TUTORING", {"topic": matched_topic, "raw": text}

    # 2.9 Unsupported File Creation Commands (Safeguard against LLM hallucinations)
    if RE_FILE_CREATION_COMMAND.match(clean_text):
        return "UNSUPPORTED_ACTION", {
            "action": "create_file",
            "message": "I do not have a tool to create files on your filesystem yet, Sir.",
            "raw": text,
        }

    # 3. Close current tab (requests confirmation)
    if any(
        clean_text == trigger or clean_text.startswith(trigger)
        for trigger in ("close the current tab", "close current tab", "close this tab", "close the tab", "close tab")
    ):
        return "REQUEST_CONFIRMATION", {"action": "close_tab"}

    # 3.4 Hardware Volume and Media Controls Fast-Path
    if not is_conversational:
        vol_res = extract_volume_intent(clean_text)
        if vol_res:
            return "SMART_ACTION", vol_res

        media_action, media_params = parse_media_command(text)
        if media_action is not None:
            return "MEDIA_CONTROL", {"action": media_action, **media_params}

        # 4. YouTube Direct Video Playback (Play ... on YouTube, Open first result, Prompt, Combined)
        text_no_vol, emb_vol = extract_embedded_volume(text)
        play_intent, play_query = parse_youtube_play(text_no_vol)
        if play_intent == "YOUTUBE_FIRST_RESULT":
            params = {}
            if emb_vol is not None:
                params["volume"] = emb_vol
            return "YOUTUBE_FIRST_RESULT", params
        if play_intent == "YOUTUBE_PLAY_PROMPT":
            params = {}
            if emb_vol is not None:
                params["volume"] = emb_vol
            return "YOUTUBE_PLAY_PROMPT", params
        if play_intent == "YOUTUBE_PLAY":
            params = {"query": play_query, "auto_play": True}
            if emb_vol is not None:
                params["volume"] = emb_vol
            return "YOUTUBE_PLAY", params

        # 5. Web search intent (Google or YouTube search results page)
        engine, query = parse_search_command(text_no_vol)
        if engine is not None:
            params = {"engine": engine, "query": query}
            if emb_vol is not None:
                params["volume"] = emb_vol
            if not query:
                return "SEARCH_PROMPT", params
            return "BROWSER_SEARCH", params

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

    if any(trigger in clean_text for trigger in ("open downloads", "open download", "open downloads folder", "downloads folder")):
        return "DESKTOP_ACTION", {"action": "open_downloads"}

    if any(trigger in clean_text for trigger in ("open youtube", "launch youtube", "start youtube")):
        return "DESKTOP_ACTION", {"action": "open_youtube"}

    if TERMINAL_COMMAND_PATTERN.match(clean_text):
        return "DESKTOP_ACTION", {"action": "open_terminal"}

    if BROWSER_COMMAND_PATTERN.match(clean_text):
        return "DESKTOP_ACTION", {"action": "open_browser"}

    if FIREFOX_COMMAND_PATTERN.match(clean_text):
        return "DESKTOP_ACTION", {"action": "open_firefox"}

    # Dynamic application resolution via AppRegistry
    m_app = RE_APP_LAUNCH_COMMAND.match(clean_text)
    if m_app:
        app_target = m_app.group(1).strip().lower()
        # Avoid intercepting project actions like "open lensify in antigravity", folders, or follow-ups ("there", "here")
        if not any(k in app_target for k in ("there", "here", "project", "folder", "directory", "repo", "workflow", " in ", " into ")):
            from actions.resolver import get_app_registry
            app_info = get_app_registry().resolve_application(app_target)
            if app_info:
                canon = app_info.name.lower()
                if "firefox" in canon or "firefox" in app_info.exec_path.lower():
                    return "DESKTOP_ACTION", {"action": "open_browser" if "browser" in app_target else "open_firefox"}
                if "konsole" in canon or "konsole" in app_info.exec_path.lower():
                    return "DESKTOP_ACTION", {"action": "open_terminal"}
                return "DESKTOP_ACTION", {"action": "launch_app", "app": app_info.name, "exec_path": app_info.exec_path}

    # 8.4 Dedicated Local Time and Date Fast-Path (No Ollama / No Web Search)
    from actions.clock import parse_time_date_query
    time_date_intent = parse_time_date_query(text)
    if time_date_intent is not None:
        return "TIME_DATE_QUERY", time_date_intent

    # 8.5 Conversational Memory Management (Facts & Preferences)
    from intelligence.memory_extractor import parse_memory_request
    mem_intent = parse_memory_request(text)
    if mem_intent:
        return "MEMORY_ACTION", mem_intent

    # 8.6 Natural-Language Smart Intent & Learned Workflow Routing
    smart = extract_smart_intent(clean_text)
    if smart:
        return "SMART_ACTION", smart

    # 8.8 Real-Time Web Search & Current Information Questions (Stage 5)
    if is_current_info_query(clean_text):
        query = clean_text
        query = re.sub(
            r"^(?:please\s+)?(?:can\s+you\s+)?(?:search\s+(?:the\s+web|online|the\s+internet)\s+(?:for\s+)?|"
            r"search\s+for\s+|"
            r"look\s+up\s+|"
            r"web\s+search\s+for\s+|"
            r"web\s+search\s+)",
            "",
            query,
            flags=re.IGNORECASE,
        ).strip()
        query = re.sub(r"\s+(?:on|in)\s+(?:the\s+web|the\s+internet|online)$", "", query, flags=re.IGNORECASE).strip()
        return "CURRENT_INFO_QUERY", {"query": query or clean_text, "raw": text}

    # 8.9 Understandable but ambiguous action commands (Ask relevant clarification)
    if RE_AMBIGUOUS_OPEN_PROJECT.match(clean_text):
        return "CLARIFY_ACTION", {
            "action": "open_project",
            "question": "Which project or folder would you like me to open, Sir?",
            "raw": text,
        }

    if RE_AMBIGUOUS_OPEN_APP.match(clean_text):
        return "CLARIFY_ACTION", {
            "action": "launch_app",
            "question": "Which application would you like me to open, Sir?",
            "raw": text,
        }

    if RE_AMBIGUOUS_BRIGHTNESS.match(clean_text):
        return "CLARIFY_ACTION", {
            "action": "brightness_set",
            "question": "What brightness percentage would you like me to set, Sir?",
            "raw": text,
        }

    # 9. Low-confidence / Unclear speech filtering (Genuinely unintelligible noise or unusable input)
    if not clean_text:
        return "UNCLEAR_SPEECH", {"raw": text}

    if clean_text in UNCLEAR_NOISE or len(clean_text) <= 2:
        return "UNCLEAR_SPEECH", {"raw": text}

    if not re.search(r"[a-zA-Z]", clean_text):
        return "UNCLEAR_SPEECH", {"raw": text}

    if clean_text in GENUINE_NOISE_PHRASES:
        return "UNCLEAR_SPEECH", {"raw": text}

    # 10. Natural Conversation, Questions, Opinions, Career Discussions, and Follow-ups
    # Route all understandable conversational speech to local intelligence (Ollama)
    return "OLLAMA_QUERY", {"prompt": text.strip() if is_conversational else clean_text}

