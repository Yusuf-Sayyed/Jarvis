"""
Unit tests for core/memory.py local persistent storage.
"""

import tempfile
import unittest
from pathlib import Path

from core.memory import MemoryStore


class TestMemoryStore(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.sqlite"
        self.store = MemoryStore(db_path=self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_project_entity_lifecycle(self):
        # Save project
        res = self.store.save_project(
            name="Lensify",
            resolved_path="/home/yusuf/Desktop/Lensify",
            aliases=["lensify project", "my lensify"],
            default_app="antigravity",
        )
        self.assertTrue(res)

        # Lookup by canonical name
        proj = self.store.get_project("lensify")
        self.assertIsNotNone(proj)
        self.assertEqual(proj["resolved_path"], "/home/yusuf/Desktop/Lensify")
        self.assertEqual(proj["default_app"], "antigravity")

        # Lookup by alias
        proj_alias = self.store.get_project("my lensify")
        self.assertIsNotNone(proj_alias)
        self.assertEqual(proj_alias["name"], "lensify")

        # Unknown project returns None
        self.assertIsNone(self.store.get_project("non_existent_project"))

    def test_learned_pattern_fast_path(self):
        # Store a fast-path pattern
        phrase = "open lensify in antigravity"
        action = "launch_app"
        params = {"app": "antigravity", "path": "/home/yusuf/Desktop/Lensify"}

        self.store.save_learned_pattern(phrase, action, params)

        # Retrieve pattern
        pattern = self.store.get_learned_pattern("Open Lensify in Antigravity")
        self.assertIsNotNone(pattern)
        self.assertEqual(pattern["target_action"], "launch_app")
        self.assertEqual(pattern["target_params"]["app"], "antigravity")
        self.assertEqual(pattern["success_count"], 1)

        # Re-saving increments success count
        self.store.save_learned_pattern(phrase, action, params)
        pattern_updated = self.store.get_learned_pattern(phrase)
        self.assertEqual(pattern_updated["success_count"], 2)

        # Non-existent pattern
        self.assertIsNone(self.store.get_learned_pattern("unfamiliar phrase"))

    def test_workflow_storage(self):
        triggers = ["start lensify dev", "open lensify for development"]
        steps = [
            {"action": "launch_app", "params": {"app": "antigravity", "path": "/home/yusuf/Desktop/Lensify"}},
            {"action": "launch_terminal", "params": {"path": "/home/yusuf/Desktop/Lensify"}},
        ]

        self.store.save_workflow("lensify_dev", triggers, steps)

        wf = self.store.get_workflow_by_trigger("open lensify for development")
        self.assertIsNotNone(wf)
        self.assertEqual(wf["workflow_id"], "lensify_dev")
        self.assertEqual(len(wf["steps"]), 2)
        self.assertEqual(wf["steps"][0]["action"], "launch_app")

    def test_preferences(self):
        self.store.set_preference("default_editor", "antigravity")
        pref = self.store.get_preference("default_editor")
        self.assertEqual(pref, "antigravity")

        # Default fallback
        self.assertEqual(self.store.get_preference("unknown_pref", "fallback_val"), "fallback_val")

    def test_list_and_clear_learned_entries(self):
        self.store.save_project("test_proj", "/tmp/test")
        self.store.save_learned_pattern("test phrase", "test_act", {})

        entries = self.store.list_learned_entries()
        self.assertTrue(len(entries["entities"]) >= 1)
        self.assertTrue(len(entries["learned_patterns"]) >= 1)

        self.store.clear_learned_entries()
        empty_entries = self.store.list_learned_entries()
        self.assertEqual(len(empty_entries["entities"]), 0)
        self.assertEqual(len(empty_entries["learned_patterns"]), 0)


if __name__ == "__main__":
    unittest.main()
