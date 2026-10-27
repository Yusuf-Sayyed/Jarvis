"""
Tests for Conversational Memory in JARVIS:
- Explicit learning of facts and preferences ("remember that...")
- Retrieval and recall of private facts without web search
- Persistence after JARVIS restarts (SQLite storage)
- Updating memories (direct and via conversational clarification)
- Deleting/forgetting memories (direct and via conversational clarification)
- Ambiguity handling and clarification flows
- Distinguishing memories from workflow creation/management
- Offline safety (preventing private memories from leaking to search)
- Verification that success is never reported on DB failure
"""

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path
from unittest.mock import MagicMock, patch

from core.context import get_conversation_context
from core.intent import detect_intent, is_current_info_query
from core.memory import MemoryStore
from core.router import route_command
from intelligence.memory_extractor import (
    extract_fact_with_ollama,
    is_personal_memory_query,
    is_workflow_utterance,
    parse_deterministic_memory,
    parse_memory_request,
)
from intelligence.ollama_client import get_system_prompt_with_memory


class TestConversationalMemory(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_memory.sqlite"
        self.memory = MemoryStore(db_path=self.db_path)

        import core.memory as mem_mod
        self.orig_mem = mem_mod._MEMORY_INSTANCE
        mem_mod._MEMORY_INSTANCE = self.memory

        self.context = get_conversation_context()
        self.context.clear_pending()

    def tearDown(self):
        import core.memory as mem_mod
        mem_mod._MEMORY_INSTANCE = self.orig_mem
        self.context.clear_pending()
        self.temp_dir.cleanup()

    def test_distinguish_memory_from_workflow(self):
        """Requirement 1: Distinguish remembering a fact or preference from saving a workflow."""
        workflow_text = "When I say start working on Lensify, open Lensify in my editor and open terminal"
        self.assertTrue(is_workflow_utterance(workflow_text))
        self.assertIsNone(parse_memory_request(workflow_text))
        w_intent, w_params = detect_intent(workflow_text)
        self.assertEqual(w_intent, "SMART_ACTION")
        self.assertEqual(w_params["action"], "teach_workflow")

        memory_text = "Remember that my eyewear business is called Lensify."
        self.assertFalse(is_workflow_utterance(memory_text))
        m_intent, m_params = detect_intent(memory_text)
        self.assertEqual(m_intent, "MEMORY_ACTION")
        self.assertEqual(m_params["action"], "remember_memory")

        del_wf_text = "Delete the workflow Lensify"
        self.assertTrue(is_workflow_utterance(del_wf_text))
        self.assertIsNone(parse_memory_request(del_wf_text))

    def test_save_facts_and_preferences(self):
        """Requirement 3 & 5: Save persistent memories to SQLite database and verify DB operations."""
        # 1. Eyewear business
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Remember that my eyewear business is called Lensify.")
        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("Lensify", f.getvalue())

        mem_biz = self.memory.get_memory("business_name")
        self.assertIsNotNone(mem_biz)
        self.assertEqual(mem_biz["content"], "Lensify")
        self.assertEqual(mem_biz["category"], "fact")
        self.assertEqual(mem_biz["topic"], "business name")

        # 2. Preference: short answers
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Remember that I prefer short answers.")
        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("short answers", f.getvalue())

        mem_pref = self.memory.get_memory("answer_length")
        self.assertIsNotNone(mem_pref)
        self.assertEqual(mem_pref["content"], "short answers")
        self.assertEqual(mem_pref["category"], "preference")

        # 3. Roommate fact
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Just remember that I live in my room with Farid.")
        self.assertTrue(cont)
        mem_room = self.memory.get_memory("roommate")
        self.assertIsNotNone(mem_room)
        self.assertIn("Farid", mem_room["content"])

        # 4. Associate identity
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Remember that Farid is a Muslim man.")
        self.assertTrue(cont)
        mem_farid = self.memory.get_memory("farid_identity")
        self.assertIsNotNone(mem_farid)
        self.assertEqual(mem_farid["content"], "Farid is a Muslim man")

    def test_persistence_after_restart(self):
        """Requirement 4: Retrieve relevant memories including after restarting JARVIS."""
        self.memory.save_memory(
            memory_key="business_name",
            content="Lensify",
            category="fact",
            topic="business name",
            raw_statement="Remember that my eyewear business is called Lensify.",
        )
        self.memory.save_memory(
            memory_key="roommate",
            content="I live in my room with Farid",
            category="fact",
            topic="roommate",
            raw_statement="Just remember that I live in my room with Farid.",
        )

        # Simulate JARVIS restart: Instantiate a brand new MemoryStore on the same SQLite file
        restarted_memory = MemoryStore(db_path=self.db_path)
        import core.memory as mem_mod
        mem_mod._MEMORY_INSTANCE = restarted_memory

        retrieved_biz = restarted_memory.get_memory("business_name")
        self.assertIsNotNone(retrieved_biz)
        self.assertEqual(retrieved_biz["content"], "Lensify")
        self.assertEqual(retrieved_biz["topic"], "business name")

        retrieved_room = restarted_memory.get_memory("roommate")
        self.assertIsNotNone(retrieved_room)
        self.assertEqual(retrieved_room["content"], "I live in my room with Farid")

        # Check prompt building after restart
        sys_prompt = get_system_prompt_with_memory()
        self.assertIn("Lensify", sys_prompt)
        self.assertIn("Farid", sys_prompt)

    def test_recall_and_listing_memories(self):
        """Requirement 4 & 6: Retrieval and listing of conversational memories."""
        self.memory.save_memory("business_name", "Lensify", topic="business name")
        self.memory.save_memory("roommate", "I live in my room with Farid", topic="roommate")

        # Recall business
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("What do you remember about my business?")
        self.assertTrue(cont)
        self.assertIn("Lensify", f.getvalue())

        # Recall living situation
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Now tell me, with whom I live in my room.")
        self.assertTrue(cont)
        self.assertIn("Farid", f.getvalue())

        # List all memories
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("List all my memories")
        self.assertTrue(cont)
        self.assertIn("Business Name", f.getvalue())
        self.assertIn("Roommate", f.getvalue())

    def test_update_memory_direct_and_clarification(self):
        """Requirement 6 & 7: Update memories and ask for clarification when ambiguous."""
        self.memory.save_memory("business_name", "Lensify", topic="business name")

        # 1. Update without new value (Ambiguous request -> asks clarification)
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Update the business name I previously saved.")
        self.assertTrue(cont)
        self.assertEqual(pending, "clarify_memory_update")
        self.assertIn("What would you like to update your business name to", f.getvalue())

        # Follow-up response with the new value
        f = io.StringIO()
        with redirect_stdout(f):
            cont2, pending2 = route_command("Spectacle World.")
        self.assertTrue(cont2)
        self.assertIsNone(pending2)
        self.assertIn("updated your business name to 'Spectacle World'", f.getvalue())

        # Verify updated in DB
        updated = self.memory.get_memory("business_name")
        self.assertEqual(updated["content"], "Spectacle World")

        # 2. Update directly with "to <new_value>"
        f = io.StringIO()
        with redirect_stdout(f):
            cont3, pending3 = route_command("Update the business name to VisionCraft.")
        self.assertTrue(cont3)
        self.assertIsNone(pending3)
        self.assertIn("VisionCraft", f.getvalue())
        self.assertEqual(self.memory.get_memory("business_name")["content"], "VisionCraft")

    def test_forget_memory_direct_and_clarification(self):
        """Requirement 6 & 7: Delete individual memories and handle ambiguous deletes."""
        self.memory.save_memory("answer_length", "short answers", category="preference", topic="answer length")

        # Direct deletion
        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Forget the preference I told you about answer length.")
        self.assertTrue(cont)
        self.assertIsNone(pending)
        self.assertIn("forgotten", f.getvalue())
        self.assertIsNone(self.memory.get_memory("answer_length"))

        # Ambiguous deletion when multiple memories match
        self.memory.save_memory("farid_roommate", "I live in my room with Farid", topic="Farid Roommate")
        self.memory.save_memory("farid_identity", "Farid is a Muslim man", topic="Farid Identity")

        f = io.StringIO()
        with redirect_stdout(f):
            cont, pending = route_command("Forget Farid")
        self.assertTrue(cont)
        self.assertEqual(pending, "clarify_memory_forget")
        self.assertIn("multiple memories matching 'farid'", f.getvalue().lower())

        # Clarify selection: user chooses the first candidate
        f = io.StringIO()
        with redirect_stdout(f):
            cont2, pending2 = route_command("the first one")
        self.assertTrue(cont2)
        self.assertIsNone(pending2)
        self.assertIn("forgotten", f.getvalue())
        self.assertIsNone(self.memory.get_memory("farid_identity"))
        self.assertIsNotNone(self.memory.get_memory("farid_roommate"))

    def test_offline_safety_no_web_search(self):
        """Requirement 8: Keep memory local and offline. Do not send saved memories to web search."""
        queries = [
            "Now tell me, with whom I live in my room.",
            "What do you remember about my business?",
            "What did I tell you about my roommate?",
            "What are my preferences regarding answer length?",
            "Tell me about Farid who lives with me",
        ]
        for q in queries:
            self.assertTrue(is_personal_memory_query(q), f"Failed to detect personal query: {q}")
            self.assertFalse(is_current_info_query(q), f"Personal query falsely flagged for web search: {q}")

    def test_never_claim_success_on_database_failure(self):
        """Requirement 5: Never claim something was remembered, updated, or forgotten unless DB succeeded."""
        with patch.object(self.memory, "save_memory", return_value=False):
            f = io.StringIO()
            with redirect_stdout(f):
                route_command("Remember that my eyewear business is called Lensify.")
            self.assertIn("Failed to persist", f.getvalue())
            self.assertNotIn("I will remember", f.getvalue())

        self.memory.save_memory("business_name", "Lensify", topic="business name")
        with patch.object(self.memory, "update_memory", return_value=False):
            f = io.StringIO()
            with redirect_stdout(f):
                route_command("Update the business name to VisionCraft.")
            self.assertIn("Could not update memory", f.getvalue())

        with patch.object(self.memory, "delete_memory", return_value=False):
            f = io.StringIO()
            with redirect_stdout(f):
                route_command("Forget the business name.")
            self.assertIn("Could not delete memory", f.getvalue())

    def test_ollama_json_extraction_fallback(self):
        """Requirement 2: Extract facts using existing local Ollama integration when necessary."""
        mock_response = json.dumps({
            "response": json.dumps({
                "key": "cat_name",
                "topic": "cat",
                "category": "fact",
                "content": "My cat is called Whiskers"
            })
        }).encode("utf-8")

        mock_http = MagicMock()
        mock_http.status = 200
        mock_http.read.return_value = mock_response
        mock_http.__enter__.return_value = mock_http

        with patch("urllib.request.urlopen", return_value=mock_http):
            parsed = extract_fact_with_ollama("My pet cat's special name is Whiskers")
            self.assertIsNotNone(parsed)
            self.assertEqual(parsed["key"], "cat_name")
            self.assertEqual(parsed["topic"], "cat")
            self.assertEqual(parsed["content"], "My cat is called Whiskers")


if __name__ == "__main__":
    unittest.main()
