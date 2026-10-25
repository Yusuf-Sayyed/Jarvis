"""
Wake-word detection, session state tracking, and timer management.
"""

import time
from core.config import SESSION_TIMEOUT_SECONDS, WAKE_WORDS


def extract_wake_command(text: str) -> tuple[bool, str]:
    """
    Checks if an utterance contains any configured wake word.

    Returns:
        (True, remaining_command) if a wake word was found.
        (False, original_text) if no wake word was found.
    """
    cleaned = text.lower().strip()
    for wake in WAKE_WORDS:
        if cleaned == wake:
            return True, ""
        if cleaned.startswith(wake + " "):
            return True, cleaned[len(wake) + 1:].strip()
        if cleaned.endswith(" " + wake):
            return True, cleaned[:-len(wake) - 1].strip()
        if f" {wake} " in cleaned:
            parts = cleaned.split(f" {wake} ", 1)
            remaining = (parts[0] + " " + parts[1]).strip()
            return True, remaining
    return False, text


def format_time_remaining(seconds: float) -> str:
    """Formats remaining seconds into a string like '4m 32s'."""
    total = max(0, int(seconds))
    mins = total // 60
    secs = total % 60
    return f"{mins}m {secs:02d}s"


class SessionState:
    """Manages STANDBY vs. ACTIVE states and the 5-minute inactivity timer."""

    def __init__(self, timeout_seconds: int = SESSION_TIMEOUT_SECONDS):
        self.timeout_seconds = timeout_seconds
        self.is_active = False
        self.last_activity_time = 0.0
        self.pending_action: str | None = None

    def activate(self):
        """Transitions to ACTIVE mode and resets the timer."""
        self.is_active = True
        self.last_activity_time = time.time()
        self.pending_action = None

    def deactivate(self):
        """Transitions back to STANDBY mode."""
        self.is_active = False
        self.pending_action = None

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
