"""
Conversation continuity and short-lived context tracking for JARVIS.
Remembers recent applications, directories, and pending confirmations
to resolve follow-ups like 'in that folder' or 'open a terminal there too'.
"""

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class DialogueTurn:
    """Represents a single conversational exchange turn between user and JARVIS."""
    user: str
    assistant: str
    timestamp: float = field(default_factory=time.time)


@dataclass
class ActivityState:
    """Represents an ongoing interactive task or learning activity, such as Python tutoring."""
    activity_type: str = "tutoring"
    topic: str = "python"
    current_question: str = ""
    last_assistant_question: str = ""
    expected_reply_type: str = "text"
    awaiting_answer: bool = True
    lesson_step: int = 1
    hints_given: int = 0
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    history: list[dict[str, str]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "activity_type": self.activity_type,
            "topic": self.topic,
            "current_question": self.current_question,
            "last_assistant_question": self.last_assistant_question,
            "expected_reply_type": self.expected_reply_type,
            "awaiting_answer": self.awaiting_answer,
            "lesson_step": self.lesson_step,
            "hints_given": self.hints_given,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "history": list(self.history),
        }


@dataclass
class ConversationContext:
    """Tracks short-term conversational context across multi-turn interactions."""

    last_action: Optional[str] = None
    last_app: Optional[str] = None
    last_app_bin: Optional[str] = None
    last_target_name: Optional[str] = None
    last_target_path: Optional[str] = None
    last_timestamp: float = field(default_factory=time.time)

    # Active project context
    current_project_name: Optional[str] = None
    current_project_path: Optional[str] = None
    project_timestamp: float = 0.0
    PROJECT_TTL_SECONDS: float = 300.0

    # Recent file context
    recent_file_name: Optional[str] = None
    recent_file_path: Optional[str] = None
    file_timestamp: float = 0.0
    FILE_TTL_SECONDS: float = 300.0

    # Active task and workflow context
    active_task: Optional[str] = None
    active_workflow: Optional[str] = None

    # Pending confirmations or clarifications
    pending_action: Optional[str] = None
    pending_payload: Optional[dict[str, Any]] = None
    pending_timestamp: float = 0.0

    # Ongoing goal/activity state (e.g. Python tutoring)
    active_activity: Optional[ActivityState] = None
    ACTIVITY_TTL_SECONDS: float = 600.0

    # Short-term conversational dialogue history
    dialogue_turns: list[DialogueTurn] = field(default_factory=list)
    DIALOGUE_TTL_SECONDS: float = 180.0
    MAX_DIALOGUE_TURNS: int = 4

    # Expiry in seconds
    CONTEXT_TTL_SECONDS: float = 60.0
    CONFIRMATION_TTL_SECONDS: float = 20.0

    # YouTube and media playback context tracking
    last_youtube_query: Optional[str] = None
    last_youtube_url: Optional[str] = None
    pending_youtube_query: Optional[str] = None
    pending_youtube_url: Optional[str] = None
    pending_youtube_timestamp: float = 0.0
    YOUTUBE_PENDING_TTL_SECONDS: float = 180.0
    recent_youtube_results: list[dict[str, str]] = field(default_factory=list)
    media_target_state: Optional[str] = None  # 'search_page_opened', 'video_opened', 'playback_confirmed'

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

    def set_pending_youtube(
        self,
        query: str,
        url: Optional[str] = None,
        action: str = "play",
    ):
        """Records a pending YouTube playback/search context for follow-up resolution."""
        now = time.time()
        clean_q = query.strip()
        self.last_youtube_query = clean_q
        self.last_youtube_url = url
        self.pending_youtube_query = clean_q
        self.pending_youtube_url = url
        self.pending_youtube_timestamp = now
        self.last_timestamp = now

    def get_pending_youtube(self) -> tuple[Optional[str], Optional[str]]:
        """
        Returns (pending_query, pending_url) if within TTL window.
        Returns (None, None) if expired or none set.
        """
        if not self.pending_youtube_query:
            return None, None
        if (time.time() - self.pending_youtube_timestamp) > self.YOUTUBE_PENDING_TTL_SECONDS:
            self.clear_pending_youtube()
            return None, None
        return self.pending_youtube_query, self.pending_youtube_url

    def get_recent_youtube_query(self) -> Optional[str]:
        """Returns the most recent YouTube query if within context TTL or pending TTL."""
        pending_q, _ = self.get_pending_youtube()
        if pending_q:
            return pending_q
        if (time.time() - self.last_timestamp) <= self.CONTEXT_TTL_SECONDS:
            return self.last_youtube_query
        return self.last_youtube_query

    def clear_pending_youtube(self):
        """Clears pending YouTube state."""
        self.pending_youtube_query = None
        self.pending_youtube_url = None
        self.pending_youtube_timestamp = 0.0

    def set_current_project(self, name: str, path: str):
        """Sets the active project context."""
        now = time.time()
        self.current_project_name = name
        self.current_project_path = path
        self.project_timestamp = now
        self.last_target_name = name
        self.last_target_path = path
        self.last_timestamp = now

    def get_current_project(self) -> tuple[Optional[str], Optional[str]]:
        """Returns (project_name, project_path) if valid and not expired."""
        if not self.current_project_path:
            return None, None
        if (time.time() - self.project_timestamp) > self.PROJECT_TTL_SECONDS:
            self.clear_current_project()
            return None, None
        if not os.path.isdir(self.current_project_path):
            self.clear_current_project()
            return None, None
        return self.current_project_name, self.current_project_path

    def clear_current_project(self):
        """Clears current project context."""
        self.current_project_name = None
        self.current_project_path = None
        self.project_timestamp = 0.0

    def set_recent_file(self, name: str, path: str):
        """Sets the most recent file context."""
        now = time.time()
        self.recent_file_name = name
        self.recent_file_path = path
        self.file_timestamp = now
        self.last_timestamp = now

    def get_recent_file(self) -> tuple[Optional[str], Optional[str]]:
        """Returns (file_name, file_path) if valid, exists on disk, and not expired."""
        if not self.recent_file_path:
            return None, None
        if (time.time() - self.file_timestamp) > self.FILE_TTL_SECONDS:
            self.clear_recent_file()
            return None, None
        if not os.path.exists(self.recent_file_path):
            self.clear_recent_file()
            return None, None
        return self.recent_file_name, self.recent_file_path

    def clear_recent_file(self):
        """Clears recent file context."""
        self.recent_file_name = None
        self.recent_file_path = None
        self.file_timestamp = 0.0

    def set_youtube_results(
        self,
        query: str,
        results: list[dict[str, str]],
        stage: str = "search_page_opened",
    ):
        """Records a list of YouTube search results and media state for follow-ups."""
        now = time.time()
        self.last_youtube_query = query.strip()
        self.recent_youtube_results = list(results)
        self.media_target_state = stage
        self.pending_youtube_query = query.strip()
        if results and "url" in results[0]:
            self.pending_youtube_url = results[0]["url"]
            self.last_youtube_url = results[0]["url"]
        self.pending_youtube_timestamp = now
        self.last_timestamp = now

    def get_youtube_results(self) -> list[dict[str, str]]:
        """Returns non-expired YouTube search results."""
        if (time.time() - self.pending_youtube_timestamp) > self.YOUTUBE_PENDING_TTL_SECONDS:
            self.recent_youtube_results = []
            return []
        return list(self.recent_youtube_results)

    def get_youtube_result_by_index(self, index: int) -> Optional[dict[str, str]]:
        """
        Retrieves a 1-based YouTube search result (e.g. index=1 for 1st, 2 for 2nd).
        Returns the result dict with 'title' and 'url', or None if out of range / expired.
        """
        results = self.get_youtube_results()
        if not results:
            return None
        zero_idx = index - 1
        if 0 <= zero_idx < len(results):
            return results[zero_idx]
        return None

    def set_media_state(self, stage: str, query: Optional[str] = None, url: Optional[str] = None):
        """Updates media stage: 'search_page_opened', 'video_opened', 'playback_confirmed'."""
        self.media_target_state = stage
        if query:
            self.last_youtube_query = query
        if url:
            self.last_youtube_url = url
        self.last_timestamp = time.time()

    def get_media_state(self) -> Optional[str]:
        """Returns current media target state."""
        return self.media_target_state

    def clear_temporary_context(self):
        """Clears all short-term conversation, project, file, and media follow-up states."""
        self.clear_current_project()
        self.clear_recent_file()
        self.clear_pending()
        self.clear_pending_youtube()
        self.recent_youtube_results = []
        self.media_target_state = None
        self.active_task = None
        self.active_workflow = None
        self.last_target_path = None
        self.last_target_name = None

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

    def add_dialogue_turn(self, user: str, assistant: str):
        """Records a user prompt and assistant response turn into short-term history."""
        now = time.time()
        self.dialogue_turns = [
            t for t in self.dialogue_turns
            if (now - t.timestamp) <= self.DIALOGUE_TTL_SECONDS
        ]
        self.dialogue_turns.append(DialogueTurn(user=user.strip(), assistant=assistant.strip(), timestamp=now))
        if len(self.dialogue_turns) > self.MAX_DIALOGUE_TURNS:
            self.dialogue_turns = self.dialogue_turns[-self.MAX_DIALOGUE_TURNS:]
        self.last_timestamp = now

    def get_recent_dialogue(self) -> list[DialogueTurn]:
        """Returns non-expired recent dialogue turns."""
        now = time.time()
        self.dialogue_turns = [
            t for t in self.dialogue_turns
            if (now - t.timestamp) <= self.DIALOGUE_TTL_SECONDS
        ]
        return list(self.dialogue_turns)

    def clear_dialogue(self):
        """Clears all short-term dialogue history."""
        self.dialogue_turns = []

    def start_activity(
        self,
        activity_type: str,
        topic: str,
        initial_question: str = "",
        expected_reply_type: str = "text",
    ) -> ActivityState:
        """Starts an interactive goal/activity session, e.g. Python tutoring."""
        now = time.time()
        self.active_activity = ActivityState(
            activity_type=activity_type,
            topic=topic,
            current_question=initial_question,
            last_assistant_question=initial_question,
            expected_reply_type=expected_reply_type,
            awaiting_answer=bool(initial_question),
            created_at=now,
            updated_at=now,
        )
        self.last_timestamp = now
        return self.active_activity

    def get_active_activity(self) -> Optional[ActivityState]:
        """Returns the active activity if not expired; clears if timed out."""
        if not self.active_activity:
            return None
        if (time.time() - self.active_activity.updated_at) > self.ACTIVITY_TTL_SECONDS:
            self.stop_activity()
            return None
        return self.active_activity

    def update_activity_question(
        self,
        question: str,
        expected_reply_type: str = "text",
    ):
        """Updates the active question for the ongoing lesson, advancing step count."""
        act = self.get_active_activity()
        if act:
            act.last_assistant_question = act.current_question or question
            act.current_question = question
            act.expected_reply_type = expected_reply_type
            act.awaiting_answer = True
            act.hints_given = 0
            act.lesson_step += 1
            act.updated_at = time.time()
            self.last_timestamp = act.updated_at

    def record_activity_turn(self, question: str, answer: str, feedback: str):
        """Logs a completed QA exchange within the active activity."""
        act = self.get_active_activity()
        if act:
            act.history.append({"question": question, "answer": answer, "feedback": feedback})
            act.updated_at = time.time()
            self.last_timestamp = act.updated_at

    def increment_hint(self) -> int:
        """Increments hint counter for current question and returns current count."""
        act = self.get_active_activity()
        if act:
            act.hints_given += 1
            act.updated_at = time.time()
            return act.hints_given
        return 0

    def stop_activity(self):
        """Terminates the active activity cleanly."""
        self.active_activity = None

    def is_awaiting_activity_answer(self) -> bool:
        """Checks whether the user is actively being asked a question in an ongoing activity."""
        act = self.get_active_activity()
        return bool(act and act.awaiting_answer and act.current_question)


# Global context instance
_CONTEXT_INSTANCE: Optional[ConversationContext] = None


def get_conversation_context() -> ConversationContext:
    """Returns the singleton ConversationContext instance."""
    global _CONTEXT_INSTANCE
    if _CONTEXT_INSTANCE is None:
        _CONTEXT_INSTANCE = ConversationContext()
    return _CONTEXT_INSTANCE
