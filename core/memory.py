"""
Lightweight, local persistent memory store for JARVIS using SQLite.
Stores user preferences, known project entities, application aliases,
learned command patterns, and reusable workflows without external dependencies.
"""

import difflib
import json
import re
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator, Optional

DEFAULT_DB_PATH = Path.home() / ".local" / "share" / "jarvis" / "memory.sqlite"


class MemoryStore:
    """Manages persistent SQLite storage for learned knowledge and user context."""

    def __init__(self, db_path: Path = DEFAULT_DB_PATH):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    @contextmanager
    def _get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        conn = sqlite3.connect(str(self.db_path), timeout=5.0)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def _init_db(self):
        """Initializes tables and indexes if they do not already exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()

            # 1. Known project and file entities
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS entities (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    entity_type TEXT NOT NULL,
                    name TEXT NOT NULL UNIQUE,
                    aliases_json TEXT NOT NULL DEFAULT '[]',
                    resolved_path TEXT NOT NULL,
                    default_app TEXT,
                    last_used REAL NOT NULL,
                    confidence_score REAL DEFAULT 1.0
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_entity_name ON entities(name)")

            # 2. Application aliases
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS app_aliases (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    spoken_name TEXT NOT NULL UNIQUE,
                    exec_cmd TEXT NOT NULL,
                    desktop_file TEXT,
                    confidence REAL DEFAULT 1.0
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_app_spoken ON app_aliases(spoken_name)")

            # 3. Learned successful patterns (Fast-Path)
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS learned_patterns (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    phrase_pattern TEXT NOT NULL UNIQUE,
                    target_action TEXT NOT NULL,
                    target_params_json TEXT NOT NULL,
                    success_count INTEGER DEFAULT 1,
                    failure_count INTEGER DEFAULT 0,
                    last_success REAL NOT NULL,
                    is_enabled INTEGER DEFAULT 1
                )
                """
            )
            cursor.execute("CREATE INDEX IF NOT EXISTS idx_pattern_phrase ON learned_patterns(phrase_pattern)")

            # 4. Reusable multi-step workflows
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS workflows (
                    workflow_id TEXT PRIMARY KEY,
                    name TEXT,
                    description TEXT,
                    trigger_phrases_json TEXT NOT NULL,
                    steps_json TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    last_used REAL,
                    success_count INTEGER DEFAULT 0,
                    failure_count INTEGER DEFAULT 0,
                    is_enabled INTEGER DEFAULT 1
                )
                """
            )
            # Safe schema migration for existing databases
            for col, col_type in [
                ("name", "TEXT"),
                ("description", "TEXT"),
                ("created_at", "REAL DEFAULT 0.0"),
                ("last_used", "REAL"),
            ]:
                try:
                    cursor.execute(f"ALTER TABLE workflows ADD COLUMN {col} {col_type}")
                except sqlite3.OperationalError:
                    pass


            # 5. User preferences
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS user_preferences (
                    pref_key TEXT PRIMARY KEY,
                    pref_value TEXT NOT NULL,
                    updated_at REAL NOT NULL
                )
                """
            )
            conn.commit()

    # --- Entity / Project Methods ---

    def save_project(
        self,
        name: str,
        resolved_path: str,
        aliases: Optional[list[str]] = None,
        default_app: Optional[str] = None,
    ) -> bool:
        """Saves or updates a recognized project entity."""
        clean_name = name.lower().strip()
        alias_list = [a.lower().strip() for a in (aliases or [])]
        if clean_name not in alias_list:
            alias_list.append(clean_name)

        now = time.time()
        aliases_json = json.dumps(alias_list)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO entities (entity_type, name, aliases_json, resolved_path, default_app, last_used, confidence_score)
                VALUES ('project', ?, ?, ?, ?, ?, 1.0)
                ON CONFLICT(name) DO UPDATE SET
                    aliases_json = excluded.aliases_json,
                    resolved_path = excluded.resolved_path,
                    default_app = COALESCE(excluded.default_app, entities.default_app),
                    last_used = excluded.last_used,
                    confidence_score = MIN(1.0, entities.confidence_score + 0.1)
                """,
                (clean_name, aliases_json, resolved_path, default_app, now),
            )
            conn.commit()
            return True

    def get_project(self, name_or_alias: str) -> Optional[dict[str, Any]]:
        """Resolves a project by its name or alias."""
        clean_lookup = name_or_alias.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # Direct name match
            cursor.execute("SELECT * FROM entities WHERE entity_type = 'project' AND name = ?", (clean_lookup,))
            row = cursor.fetchone()
            if row:
                return dict(row)

            # Search in aliases_json
            cursor.execute("SELECT * FROM entities WHERE entity_type = 'project'")
            for r in cursor.fetchall():
                try:
                    aliases = json.loads(r["aliases_json"])
                    if clean_lookup in aliases:
                        return dict(r)
                except Exception:
                    continue
        return None

    # --- Learned Pattern (Fast-Path) Methods ---

    def save_learned_pattern(
        self, phrase: str, action: str, params: dict[str, Any]
    ) -> bool:
        """Stores or updates a learned command mapping for fast deterministic recall."""
        clean_phrase = phrase.lower().strip()
        now = time.time()
        params_json = json.dumps(params)

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO learned_patterns (phrase_pattern, target_action, target_params_json, success_count, last_success, is_enabled)
                VALUES (?, ?, ?, 1, ?, 1)
                ON CONFLICT(phrase_pattern) DO UPDATE SET
                    target_action = excluded.target_action,
                    target_params_json = excluded.target_params_json,
                    success_count = learned_patterns.success_count + 1,
                    last_success = excluded.last_success,
                    is_enabled = 1
                """,
                (clean_phrase, action, params_json, now),
            )
            conn.commit()
            return True

    def get_learned_pattern(self, phrase: str) -> Optional[dict[str, Any]]:
        """Retrieves a cached pattern if enabled and healthy."""
        clean_phrase = phrase.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT * FROM learned_patterns 
                WHERE phrase_pattern = ? AND is_enabled = 1 AND success_count > failure_count
                """,
                (clean_phrase,),
            )
            row = cursor.fetchone()
            if row:
                res = dict(row)
                res["target_params"] = json.loads(res["target_params_json"])
                return res
        return None

    def record_pattern_failure(self, phrase: str):
        """Increments failure count for a pattern and disables if failures exceed successes."""
        clean_phrase = phrase.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE learned_patterns
                SET failure_count = failure_count + 1,
                    is_enabled = CASE 
                        WHEN (failure_count + 1) >= 2 AND (failure_count + 1) >= success_count THEN 0 
                        ELSE is_enabled 
                    END
                WHERE phrase_pattern = ?
                """,
                (clean_phrase,),
            )
            conn.commit()

    # --- Workflow Methods ---

    def save_workflow(
        self,
        workflow_id: str,
        trigger_phrases: list[str],
        steps: list[dict[str, Any]],
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> bool:
        """Saves or updates a reusable multi-step workflow with structured steps and metadata."""
        w_id = workflow_id.lower().strip()
        cleaned_triggers = [t.lower().strip().rstrip(".?!,").strip() for t in trigger_phrases if t.strip()]
        triggers_json = json.dumps(cleaned_triggers)
        steps_json = json.dumps(steps)
        now = time.time()
        wf_name = (name or (cleaned_triggers[0].title() if cleaned_triggers else w_id)).strip()

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO workflows (
                    workflow_id, name, description, trigger_phrases_json, steps_json,
                    created_at, last_used, success_count, is_enabled
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, 1, 1)
                ON CONFLICT(workflow_id) DO UPDATE SET
                    name = excluded.name,
                    description = COALESCE(excluded.description, workflows.description),
                    trigger_phrases_json = excluded.trigger_phrases_json,
                    steps_json = excluded.steps_json,
                    success_count = workflows.success_count + 1,
                    is_enabled = 1
                """,
                (w_id, wf_name, description, triggers_json, steps_json, now, now),
            )
            conn.commit()
            return True

    def get_workflow(
        self, workflow_id_or_name: str, exact_match: bool = True
    ) -> Optional[dict[str, Any]]:
        """Retrieves a workflow by workflow_id, name, or exact trigger phrase."""
        clean_key = workflow_id_or_name.lower().strip().rstrip(".?!,").strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            # 1. By workflow_id
            cursor.execute("SELECT * FROM workflows WHERE workflow_id = ?", (clean_key,))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                res["trigger_phrases"] = json.loads(res["trigger_phrases_json"])
                res["steps"] = json.loads(res["steps_json"])
                return res

            # 2. By name (case-insensitive)
            cursor.execute("SELECT * FROM workflows WHERE LOWER(name) = ?", (clean_key,))
            row = cursor.fetchone()
            if row:
                res = dict(row)
                res["trigger_phrases"] = json.loads(res["trigger_phrases_json"])
                res["steps"] = json.loads(res["steps_json"])
                return res

            # 3. By trigger
            cursor.execute("SELECT * FROM workflows")
            for r in cursor.fetchall():
                try:
                    triggers = [t.lower().strip() for t in json.loads(r["trigger_phrases_json"])]
                    if clean_key in triggers:
                        res = dict(r)
                        res["trigger_phrases"] = triggers
                        res["steps"] = json.loads(res["steps_json"])
                        return res
                except Exception:
                    continue

        if exact_match:
            return None
        return self.find_workflow(clean_key)

    def find_workflow(self, query: str) -> Optional[dict[str, Any]]:
        """
        Finds a workflow matching a query by:
          1. Exact workflow_id, name, or trigger phrase.
          2. Exact token match against name or triggers (e.g. 'lensify').
          3. Substring match against name or triggers.
          4. Fuzzy token match using difflib.SequenceMatcher with ratio >= 0.72 (e.g. 'lensiify').
        """
        clean_q = query.lower().strip().rstrip(".?!,").strip()
        if not clean_q:
            return None

        # 1. Exact match first
        exact = self.get_workflow(clean_q, exact_match=True)
        if exact:
            return exact

        all_wfs = self.list_workflows(include_disabled=True)
        if not all_wfs:
            return None

        STOP_WORDS = {
            "a", "an", "the", "in", "on", "at", "to", "for", "of", "and",
            "my", "workflow", "named", "called", "&",
        }
        q_tokens = [w for w in re.findall(r"\b\w+\b", clean_q) if w not in STOP_WORDS]
        if not q_tokens:
            q_tokens = re.findall(r"\b\w+\b", clean_q)
        if not q_tokens:
            return None

        scored_candidates: list[tuple[float, float, dict[str, Any]]] = []

        for wf in all_wfs:
            name_str = (wf.get("name") or "").lower()
            triggers_str = " ".join(wf.get("trigger_phrases", [])).lower()
            combined_text = f"{name_str} {triggers_str}".strip()

            wf_tokens = [w for w in re.findall(r"\b\w+\b", combined_text) if w not in STOP_WORDS]
            if not wf_tokens:
                wf_tokens = re.findall(r"\b\w+\b", combined_text)
            if not wf_tokens:
                continue

            score = 0.0

            # 2. Exact token match
            matched_tokens = [qt for qt in q_tokens if qt in wf_tokens]
            if matched_tokens:
                score = 0.90 + 0.05 * (len(matched_tokens) / len(q_tokens))
            elif clean_q in combined_text:
                score = 0.85
            else:
                # 3. Fuzzy token match
                best_ratio = 0.0
                for qt in q_tokens:
                    for wt in wf_tokens:
                        r = difflib.SequenceMatcher(None, qt, wt).ratio()
                        if r > best_ratio:
                            best_ratio = r
                if best_ratio >= 0.72:
                    score = best_ratio

            if score >= 0.72:
                recency = float(wf.get("last_used") or wf.get("created_at") or 0)
                scored_candidates.append((score, recency, wf))

        if scored_candidates:
            scored_candidates.sort(key=lambda item: (item[0], item[1]), reverse=True)
            return scored_candidates[0][2]

        return None

    def get_workflow_by_trigger(self, phrase: str) -> Optional[dict[str, Any]]:
        """Resolves an enabled and healthy workflow matching a trigger phrase."""
        clean_phrase = phrase.lower().strip().rstrip(".?!,").strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM workflows WHERE is_enabled = 1 AND success_count >= failure_count")
            for row in cursor.fetchall():
                try:
                    triggers = [t.lower().strip().rstrip(".?!,").strip() for t in json.loads(row["trigger_phrases_json"])]
                    if clean_phrase in triggers:
                        res = dict(row)
                        res["trigger_phrases"] = triggers
                        res["steps"] = json.loads(res["steps_json"])
                        return res
                except Exception:
                    continue
        return None

    def list_workflows(self, include_disabled: bool = False) -> list[dict[str, Any]]:
        """Returns all workflows ordered by most recently used/created."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if include_disabled:
                cursor.execute("SELECT * FROM workflows ORDER BY COALESCE(last_used, created_at) DESC")
            else:
                cursor.execute("SELECT * FROM workflows WHERE is_enabled = 1 ORDER BY COALESCE(last_used, created_at) DESC")

            results = []
            for row in cursor.fetchall():
                res = dict(row)
                try:
                    res["trigger_phrases"] = json.loads(res["trigger_phrases_json"])
                except Exception:
                    res["trigger_phrases"] = []
                try:
                    res["steps"] = json.loads(res["steps_json"])
                except Exception:
                    res["steps"] = []
                results.append(res)
            return results

    def set_workflow_status(self, workflow_id_or_name: str, is_enabled: bool) -> bool:
        """Enables or disables a workflow."""
        wf = self.find_workflow(workflow_id_or_name)
        if not wf:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "UPDATE workflows SET is_enabled = ? WHERE workflow_id = ?",
                (1 if is_enabled else 0, wf["workflow_id"]),
            )
            conn.commit()
            return True

    def update_workflow(
        self,
        workflow_id_or_name: str,
        name: Optional[str] = None,
        trigger_phrases: Optional[list[str]] = None,
        steps: Optional[list[dict[str, Any]]] = None,
    ) -> bool:
        """Updates name, trigger phrases, or steps of an existing workflow."""
        wf = self.find_workflow(workflow_id_or_name)
        if not wf:
            return False

        new_name = name.strip() if name else wf.get("name")
        new_triggers = (
            [t.lower().strip().rstrip(".?!,").strip() for t in trigger_phrases if t.strip()]
            if trigger_phrases is not None
            else wf.get("trigger_phrases", [])
        )
        new_steps = steps if steps is not None else wf.get("steps", [])

        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE workflows
                SET name = ?, trigger_phrases_json = ?, steps_json = ?
                WHERE workflow_id = ?
                """,
                (new_name, json.dumps(new_triggers), json.dumps(new_steps), wf["workflow_id"]),
            )
            conn.commit()
            return True

    def delete_workflow(self, workflow_id_or_name: str) -> bool:
        """Deletes a workflow from persistent SQLite memory."""
        wf = self.find_workflow(workflow_id_or_name)
        if not wf:
            return False
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM workflows WHERE workflow_id = ?", (wf["workflow_id"],))
            conn.commit()
            return True

    def record_workflow_success(self, workflow_id: str):
        """Records successful execution of a workflow and updates last_used."""
        w_id = workflow_id.lower().strip()
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE workflows
                SET success_count = success_count + 1,
                    last_used = ?
                WHERE workflow_id = ?
                """,
                (now, w_id),
            )
            conn.commit()

    def record_workflow_failure(self, workflow_id: str):
        """Records failure of a workflow, updates last_used, and disables if unreliable."""
        w_id = workflow_id.lower().strip()
        now = time.time()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                UPDATE workflows
                SET failure_count = failure_count + 1,
                    last_used = ?,
                    is_enabled = CASE 
                        WHEN (failure_count + 1) >= 2 AND (failure_count + 1) > success_count THEN 0 
                        ELSE is_enabled 
                    END
                WHERE workflow_id = ?
                """,
                (now, w_id),
            )
            conn.commit()

    # --- Preferences Methods ---

    def set_preference(self, key: str, value: str):
        """Sets a persistent user preference."""
        clean_key = key.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO user_preferences (pref_key, pref_value, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(pref_key) DO UPDATE SET
                    pref_value = excluded.pref_value,
                    updated_at = excluded.updated_at
                """,
                (clean_key, value.strip(), time.time()),
            )
            conn.commit()

    def get_preference(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Gets a persistent user preference."""
        clean_key = key.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT pref_value FROM user_preferences WHERE pref_key = ?",
                (clean_key,),
            )
            row = cursor.fetchone()
            if row:
                return row["pref_value"]
        return default

    def get_all_preferences(self) -> dict[str, str]:
        """Returns all persistent user preferences as a key-value dictionary."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT pref_key, pref_value FROM user_preferences")
            return {row["pref_key"]: row["pref_value"] for row in cursor.fetchall()}


    # --- Inspection & Management ---

    def list_learned_entries(self) -> dict[str, list[dict[str, Any]]]:
        """Returns all learned entities, patterns, and workflows for user inspection."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM entities ORDER BY last_used DESC")
            entities = [dict(r) for r in cursor.fetchall()]

            cursor.execute("SELECT * FROM learned_patterns ORDER BY last_success DESC")
            patterns = [dict(r) for r in cursor.fetchall()]

            workflows = self.list_workflows(include_disabled=True)

            cursor.execute("SELECT * FROM user_preferences")
            preferences = [dict(r) for r in cursor.fetchall()]

            return {
                "entities": entities,
                "learned_patterns": patterns,
                "workflows": workflows,
                "user_preferences": preferences,
            }

    def clear_learned_entries(self):
        """Clears learned patterns and workflows, preserving base preferences."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("DELETE FROM learned_patterns")
            cursor.execute("DELETE FROM workflows")
            cursor.execute("DELETE FROM entities")
            conn.commit()


# Global default instance
_MEMORY_INSTANCE: Optional[MemoryStore] = None


def get_memory_store() -> MemoryStore:
    """Returns the singleton MemoryStore instance."""
    global _MEMORY_INSTANCE
    if _MEMORY_INSTANCE is None:
        _MEMORY_INSTANCE = MemoryStore()
    return _MEMORY_INSTANCE
