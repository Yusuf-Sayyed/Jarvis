"""
Wake-word detection, multi-trigger handling, session state tracking,
and activation greeting management.
"""

import os
import re
import time
from typing import Tuple

from core.config import (
    ACTIVATION_GREETINGS,
    SESSION_TIMEOUT_SECONDS,
    STANDALONE_WAKE_UP_ENABLED,
    WAKE_WORDS,
)

_LAST_GREETING_INDEX: int = -1

# Phonetic variants of JARVIS commonly produced by Whisper
JARVIS_VARIANTS_RE = re.compile(
    r"\b(?:j\.?a\.?r\.?v\.?i\.?s\.?|jarvice|jarves|jervis)\b",
    re.IGNORECASE,
)

NON_COMMAND_FOLLOWERS = {
    "early", "late", "at", "to", "in", "on", "call", "the", "my", "your",
    "everyone", "anybody", "someone", "again", "already", "soon", "tomorrow",
    "yesterday", "itself", "himself", "herself", "myself", "up",
}


def normalize_wake_text(text: str) -> str:
    """Normalizes Whisper variants of JARVIS to canonical 'jarvis' for matching."""
    return JARVIS_VARIANTS_RE.sub("jarvis", text.strip())


def is_direct_wake_up_command(text: str) -> Tuple[bool, str]:
    """
    Checks if 'wake up' is used strictly as a direct imperative command.
    Rejects conversational sentences like 'I wake up early' or 'wake up call'.
    """
    if not STANDALONE_WAKE_UP_ENABLED:
        return False, text

    clean = text.strip()

    # Pattern A: Exact direct command e.g. "wake up", "wake up!", "wake up now", "wake up please", "wake up, sir"
    m_exact = re.match(
        r"^wake\s+up(?:[,:\s]+(?:now|please|sir))?[!.]*$",
        clean,
        re.IGNORECASE,
    )
    if m_exact:
        return True, ""

    # Pattern B: Direct command followed by instruction e.g. "wake up, open terminal"
    m_cmd = re.match(
        r"^wake\s+up[,:\s]+(?:and\s+)?([a-zA-Z].*)$",
        clean,
        re.IGNORECASE,
    )
    if m_cmd:
        rem = m_cmd.group(1).strip()
        first_word = rem.split()[0].lower().rstrip(".,!?")
        # Ensure it is not a non-command follower like "early", "at", "to"
        if first_word in NON_COMMAND_FOLLOWERS:
            return False, text
        return True, rem

    return False, text


def extract_wake_command(text: str) -> Tuple[bool, str]:
    """
    Checks if an utterance contains any configured wake trigger:
    - "Hey JARVIS"
    - "Wake up, JARVIS" / "Wake up JARVIS"
    - "Wake up" (direct imperative only)
    - "Hello JARVIS"
    - "JARVIS" (direct address)
    - Other configured WAKE_WORDS

    Returns:
        (True, remaining_command) if a wake trigger was recognized.
        (False, original_text) if no wake trigger was found.
    """
    cleaned = text.strip()
    norm = normalize_wake_text(cleaned)

    # 1. Multi-phrase wake words first (e.g. "wake up jarvis", "hey jarvis")
    sorted_wakes = sorted(WAKE_WORDS, key=len, reverse=True)
    for wake in sorted_wakes:
        norm_wake = normalize_wake_text(wake).lower()

        # Pattern 1: Wake word at start with optional trailing punctuation
        p_start = re.compile(rf"^{re.escape(norm_wake)}[,:\.?!]*\s*(.*)$", re.IGNORECASE)
        m = p_start.match(norm)
        if m:
            rem = m.group(1).strip().lstrip(",:;!?. ").strip()
            return True, rem

        # Pattern 2: Wake word at end with optional preceding comma
        p_end = re.compile(rf"^(.*?)[,:\.]?\s*{re.escape(norm_wake)}[,:\.\?!]*$", re.IGNORECASE)
        m = p_end.match(norm)
        if m and m.group(1).strip():
            rem = m.group(1).strip().rstrip(",:;!?. ").strip()
            return True, rem

        # Pattern 3: Wake word in the middle
        p_mid = re.compile(rf"^(.*?)[,:\.]?\s*{re.escape(norm_wake)}[,:\.]?\s+(.*)$", re.IGNORECASE)
        m = p_mid.match(norm)
        if m:
            left = m.group(1).strip().rstrip(",:;!?. ").strip()
            right = m.group(2).strip().lstrip(",:;!?. ").strip()
            return True, f"{left} {right}".strip()

    # 2. Check direct imperative "wake up" without explicit "jarvis"
    is_wake_up, rem_wake_up = is_direct_wake_up_command(norm)
    if is_wake_up:
        return True, rem_wake_up

    return False, text


def get_activation_greeting() -> str:
    """
    Returns an activation greeting from the configured pool, rotating
    through options to avoid consecutive repeats where practical.
    """
    global _LAST_GREETING_INDEX
    if not ACTIVATION_GREETINGS:
        return "Hello, Sir. How can I help you?"

    n = len(ACTIVATION_GREETINGS)
    if n == 1:
        return ACTIVATION_GREETINGS[0]

    idx = (_LAST_GREETING_INDEX + 1) % n
    _LAST_GREETING_INDEX = idx
    return ACTIVATION_GREETINGS[idx]


def reset_greeting_state():
    """Resets greeting rotation index (used in tests)."""
    global _LAST_GREETING_INDEX
    _LAST_GREETING_INDEX = -1


def get_startup_greeting(hour: int | None = None) -> str:
    """
    Returns a time-aware Tony Stark-style greeting for desktop startup.
    Example: "Good morning, Sir. Systems are online. What shall we work on today?"
    """
    if hour is None:
        hour = time.localtime().tm_hour

    if 5 <= hour < 12:
        return "Good morning, Sir. Systems are online. What shall we work on today?"
    elif 12 <= hour < 17:
        return "Good afternoon, Sir. Systems are online. How may I assist you today?"
    elif 17 <= hour < 22:
        return "Good evening, Sir. Systems are online. Standing by for your instructions."
    else:
        return "Good evening, Sir. Working late tonight. Systems are online and standing by."


def _get_login_greeted_marker_path() -> str:
    """
    Returns path to the login-session greeting marker file located in $XDG_RUNTIME_DIR.
    $XDG_RUNTIME_DIR is created per login session and wiped upon desktop logout/reboot.
    """
    runtime_dir = os.environ.get("XDG_RUNTIME_DIR")
    if runtime_dir and os.path.isdir(runtime_dir):
        return os.path.join(runtime_dir, "jarvis_login_greeted")
    return f"/tmp/jarvis_login_greeted_{os.getuid()}"


def has_greeted_this_login_session() -> bool:
    """Checks whether the startup greeting was already spoken in this desktop login session."""
    return os.path.exists(_get_login_greeted_marker_path())


def mark_greeted_this_login_session() -> None:
    """Records that the startup greeting has been spoken for the current desktop login session."""
    try:
        with open(_get_login_greeted_marker_path(), "w") as f:
            f.write(f"{time.time()}\n")
    except Exception:
        pass


def clear_login_session_greeting() -> None:
    """Clears the session greeting marker (useful for test resets)."""
    p = _get_login_greeted_marker_path()
    try:
        if os.path.exists(p):
            os.remove(p)
    except Exception:
        pass


def format_time_remaining(seconds: float) -> str:
    """Formats remaining seconds into a string like '4m 32s'."""
    total = max(0, int(seconds))
    mins = total // 60
    secs = total % 60
    return f"{mins}m {secs:02d}s"


class SessionState:
    """Manages STANDBY vs. ACTIVE states, greeting status, and the 5-minute inactivity timer."""

    def __init__(self, timeout_seconds: int = SESSION_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self.is_active = False
        self.last_activity_time = 0.0
        self.pending_action: str | None = None
        self.has_greeted: bool = False

    def activate(self):
        """Transitions to ACTIVE mode and resets the timer and greeting flag."""
        self.is_active = True
        self.last_activity_time = time.time()
        self.pending_action = None
        self.has_greeted = False

    def mark_greeted(self):
        """Marks that the activation greeting has been delivered for this session."""
        self.has_greeted = True

    def should_greet(self) -> bool:
        """Returns True if the session has just been activated and has not yet greeted."""
        return self.is_active and not self.has_greeted

    def deactivate(self):
        """Transitions back to STANDBY mode."""
        self.is_active = False
        self.pending_action = None
        self.has_greeted = False

    def reset_timer(self):
        """Resets the inactivity timer to full duration."""
        self.last_activity_time = time.time()

    def is_expired(self) -> bool:
        """Checks if the active session has exceeded the inactivity duration."""
        if not self.is_active:
            return False
        return (time.time() - self.last_activity_time) >= self.timeout_seconds

    def remaining_seconds(self) -> float:
        """Returns the number of seconds left before timeout."""
        if not self.is_active:
            return 0.0
        return max(0.0, self.timeout_seconds - (time.time() - self.last_activity_time))
