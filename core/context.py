"""
Conversation continuity and short-lived context tracking for JARVIS.
Remembers recent applications, directories, and pending confirmations
to resolve follow-ups like 'in that folder' or 'open a terminal there too'.
"""

import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class ConversationContext:
    """Tracks short-term conversational context across multi-turn interactions."""

    last_action: Optional[str] = None
    last_app: Optional[str] = None
    last_app_bin: Optional[str] = None
    last_target_name: Optional[str] = None
    last_target_path: Optional[str] = None
    last_timestamp: float = field(default_factory=time.time)

    # Pending confirmations or clarifications
    pending_action: Optional[str] = None
    pending_payload: Optional[dict[str, Any]] = None
    pending_timestamp: float = 0.0

    # Expiry in seconds
    CONTEXT_TTL_SECONDS: float = 60.0
    CONFIRMATION_TTL_SECONDS: float = 20.0

    def update_interaction(
        self,
        action: Optional[str] = None,
        app: Optional[str] = None,
        app_bin: Optional[str] = None,
        target_name: Optional[str] = None,
        target_path: Optional[str] = None,
    ):
        """Updates recent entities when an action executes successfully."""
        now = time.time()
        if action:
            self.last_action = action
        if app:
            self.last_app = app
        if app_bin:
            self.last_app_bin = app_bin
        if target_name:
            self.last_target_name = target_name
        if target_path:
            self.last_target_path = target_path
        self.last_timestamp = now

    def set_pending(self, action: str, payload: Optional[dict[str, Any]] = None):
        """Sets a pending confirmation or clarification requirement."""
        self.pending_action = action
        self.pending_payload = payload or {}
        self.pending_timestamp = time.time()

    def clear_pending(self):
        """Clears pending state."""
        self.pending_action = None
        self.pending_payload = None
        self.pending_timestamp = 0.0

    def get_valid_pending(self) -> tuple[Optional[str], Optional[dict[str, Any]]]:
        """Returns valid pending action and payload if within TTL window."""
        if not self.pending_action:
            return None, None
        if (time.time() - self.pending_timestamp) > self.CONFIRMATION_TTL_SECONDS:
            self.clear_pending()
            return None, None
        return self.pending_action, self.pending_payload

    def has_active_context(self) -> bool:
        """Checks if recent context has not expired."""
        return (time.time() - self.last_timestamp) <= self.CONTEXT_TTL_SECONDS

    def get_recent_target_path(self) -> Optional[str]:
        """Returns the most recent directory path if still valid."""
        if self.has_active_context():
            return self.last_target_path
        return None

    def get_recent_app(self) -> Optional[str]:
        """Returns the most recent application name if still valid."""
        if self.has_active_context():
            return self.last_app
        return None


# Global context instance
_CONTEXT_INSTANCE: Optional[ConversationContext] = None


def get_conversation_context() -> ConversationContext:
    """Returns the singleton ConversationContext instance."""
    global _CONTEXT_INSTANCE
    if _CONTEXT_INSTANCE is None:
        _CONTEXT_INSTANCE = ConversationContext()
    return _CONTEXT_INSTANCE
