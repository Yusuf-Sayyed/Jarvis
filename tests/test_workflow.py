"""
Unit and integration tests for multi-step reusable workflows, safe failure halting,
workflow persistence, and fast-path recall in JARVIS.
"""

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from actions.workflow import WorkflowExecutor, get_workflow_executor
from core.context import get_conversation_context
from core.intent import detect_intent
from core.memory import MemoryStore
from core.router import route_command


class TestWorkflowEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.temp_dir.name) / "test_workflow_mem.sqlite"
        self.memory = MemoryStore(db_path=self.db_path)

        import core.memory as mem_mod
        self.orig_mem = mem_mod._MEMORY_INSTANCE
        mem_mod._MEMORY_INSTANCE = self.memory

        self.context = get_conversation_context()
        self.context.clear_pending()
        self.context.update_interaction(action=None, app=None, target_name=None, target_path=None)

        import actions.workflow as wf_mod
        wf_mod._EXECUTOR_INSTANCE = None
        self.executor = WorkflowExecutor()

    def tearDown(self):
        import core.memory as mem_mod
        mem_mod._MEMORY_INSTANCE = self.orig_mem
        import actions.workflow as wf_mod
        wf_mod._EXECUTOR_INSTANCE = None
        self.temp_dir.cleanup()

    def test_workflow_intent_detection(self):
        phrase = "Open the Lensify project in Antigravity, then open Konsole in the same folder."
        intent, params = detect_intent(phrase)

        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "compose_workflow")
        steps = params["params"]["steps"]
        self.assertEqual(len(steps), 2)
        self.assertEqual(steps[0]["action"], "open_project")
        self.assertEqual(steps[0]["params"]["project"].lower(), "lensify")
        self.assertEqual(steps[0]["params"]["app"].lower(), "antigravity")
        self.assertEqual(steps[1]["action"], "launch_terminal_at")

    @patch("subprocess.Popen")
    def test_workflow_execution_success_and_save(self, mock_popen):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        phrase = "Open the Lensify project in Antigravity, then open Konsole in the same folder."

        with patch.object(
            self.executor.dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            ok, summary = self.executor.execute_workflow_steps(
                steps=[
                    {"action": "open_project", "params": {"project": "Lensify", "app": "Antigravity"}},
                    {"action": "launch_terminal_at", "params": {}},
                ],
                trigger_text=phrase,
            )

            self.assertTrue(ok)
            self.assertIn("opened in 'Lensify'", summary)
            self.assertIn("Konsole terminal opened in the same folder", summary)

            # Both Antigravity and Konsole were launched with the same directory
            self.assertEqual(mock_popen.call_count, 2)
            first_call_args = mock_popen.call_args_list[0]
            second_call_args = mock_popen.call_args_list[1]

            self.assertIn(str(mock_lensify), first_call_args[0][0])
            self.assertEqual(second_call_args[0][0][1], "--workdir")
            self.assertEqual(second_call_args[0][0][2], str(mock_lensify))

            # Workflow must now be saved in SQLite memory store
            saved_wf = self.memory.get_workflow_by_trigger(phrase)
            self.assertIsNotNone(saved_wf)
            self.assertEqual(len(saved_wf["steps"]), 2)
            self.assertEqual(saved_wf["success_count"], 1)

    @patch("subprocess.Popen")
    def test_workflow_halts_on_intermediate_failure(self, mock_popen):
        # Step 1: project folder does NOT exist
        phrase = "Open the NonExistent project in Antigravity, then open Konsole in the same folder."

        with patch.object(
            self.executor.dir_resolver,
            "resolve_project_directory",
            return_value=(None, []),
        ):
            ok, summary = self.executor.execute_workflow_steps(
                steps=[
                    {"action": "open_project", "params": {"project": "NonExistent", "app": "Antigravity"}},
                    {"action": "launch_terminal_at", "params": {}},
                ],
                trigger_text=phrase,
            )

            self.assertFalse(ok)
            self.assertIn("Workflow halted at step 1", summary)
            self.assertIn("could not be located", summary)

            # Step 2 must NEVER have been called!
            mock_popen.assert_not_called()

            # Failed workflow must NEVER be saved as a learned workflow!
            saved_wf = self.memory.get_workflow_by_trigger(phrase)
            self.assertIsNone(saved_wf)

    @patch("subprocess.Popen")
    def test_fast_path_recall_of_saved_workflow(self, mock_popen):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        phrase = "setup my lensify workspace"
        steps = [
            {"action": "open_project", "params": {"project": "Lensify", "app": "Antigravity"}},
            {"action": "launch_terminal_at", "params": {}},
        ]

        # 1. Pre-save successful workflow into memory
        self.memory.save_workflow("workflow_lensify", [phrase], steps)

        # 2. Detect intent: should hit Fast-Path memory (< 1ms)
        intent, params = detect_intent(phrase)
        self.assertEqual(intent, "SMART_ACTION")
        self.assertEqual(params["action"], "run_workflow")
        self.assertTrue(params["from_cache"])

        # 3. Route command
        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            should_cont, pending = route_command(phrase)
            self.assertTrue(should_cont)
            self.assertIsNone(pending)
            self.assertEqual(mock_popen.call_count, 2)

    def test_unreliable_patterns_are_disabled(self):
        phrase = "faulty instruction test"
        self.memory.save_learned_pattern(phrase, "dummy_action", {})
        
        # Verify initially enabled
        self.assertIsNotNone(self.memory.get_learned_pattern(phrase))

        # Record failures
        self.memory.record_pattern_failure(phrase)
        self.memory.record_pattern_failure(phrase)

        # After 2 failures exceeding successes, it must be disabled and not returned
        self.assertIsNone(self.memory.get_learned_pattern(phrase))

    @patch("subprocess.Popen")
    def test_conversational_teaching_flow_with_confirmation(self, mock_popen):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        phrase = "When I say start working on Lensify, open the Lensify project in my editor and open a terminal in that project folder."

        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            # Step 1: User teaches workflow -> JARVIS prepares proposal and asks confirmation
            should_cont, pending = route_command(phrase)
            self.assertTrue(should_cont)
            self.assertEqual(pending, "confirm_save_workflow")

            # Must NOT be saved in memory before user confirms
            self.assertIsNone(self.memory.get_workflow_by_trigger("start working on lensify"))

            # Step 2: User confirms with "yes"
            should_cont, pending = route_command("yes")
            self.assertTrue(should_cont)
            self.assertIsNone(pending)

            # Workflow must now be saved in SQLite memory store
            saved_wf = self.memory.get_workflow_by_trigger("start working on lensify")
            self.assertIsNotNone(saved_wf)
            self.assertEqual(saved_wf["name"], "Start Working On Lensify")
            self.assertEqual(len(saved_wf["steps"]), 2)
            self.assertEqual(saved_wf["steps"][0]["action"], "open_project")
            self.assertEqual(saved_wf["steps"][0]["params"]["path"], str(mock_lensify))
            self.assertEqual(saved_wf["steps"][1]["action"], "launch_terminal_at")
            self.assertEqual(saved_wf["steps"][1]["params"]["path"], str(mock_lensify))

    def test_conversational_teaching_canceled_by_user(self):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        phrase = "When I say start working on Lensify, open the Lensify project in my editor and open a terminal in that project folder."

        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            # User proposes workflow
            should_cont, pending = route_command(phrase)
            self.assertEqual(pending, "confirm_save_workflow")

            # User says "no"
            should_cont, pending = route_command("no")
            self.assertTrue(should_cont)
            self.assertIsNone(pending)

            # Workflow must NOT be saved
            self.assertIsNone(self.memory.get_workflow_by_trigger("start working on lensify"))

    def test_conversational_teaching_ambiguous_folder(self):
        phrase = "When I say start working on Lensify, open the Lensify project in my editor and open a terminal in that project folder."
        candidates = ["/home/yusuf/Desktop/Lensify", "/home/yusuf/projects/Lensify"]

        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(None, candidates),
        ):
            # Teaching detects ambiguity
            should_cont, pending = route_command(phrase)
            self.assertTrue(should_cont)
            self.assertEqual(pending, "clarify_workflow_folder")

            # Workflow must NOT be saved yet
            self.assertIsNone(self.memory.get_workflow_by_trigger("start working on lensify"))

            # User clarifies folder choice
            with patch.object(
                get_workflow_executor().dir_resolver,
                "resolve_project_directory",
                return_value=(candidates[0], [candidates[0]]),
            ):
                should_cont, pending = route_command("use the Desktop one")
                self.assertTrue(should_cont)
                self.assertEqual(pending, "confirm_save_workflow")

    def test_conversational_teaching_unsupported_action(self):
        phrase = "When I say teleport, fly to the moon and do backflips."
        should_cont, pending = route_command(phrase)
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow_by_trigger("teleport"))

    def test_persistence_after_restart(self):
        # Save workflow in current memory instance
        steps = [
            {"action": "volume_set", "params": {"percentage": 75}},
            {"action": "brightness_set", "params": {"percentage": 80}},
        ]
        self.memory.save_workflow(
            workflow_id="wf_media_mode",
            trigger_phrases=["media mode"],
            steps=steps,
            name="Media Mode",
        )

        # Simulate fresh application startup by creating a new MemoryStore pointing to the same SQLite DB
        restarted_memory = MemoryStore(db_path=self.db_path)
        loaded_wf = restarted_memory.get_workflow_by_trigger("media mode")
        self.assertIsNotNone(loaded_wf)
        self.assertEqual(loaded_wf["name"], "Media Mode")
        self.assertEqual(len(loaded_wf["steps"]), 2)
        self.assertEqual(loaded_wf["steps"][0]["action"], "volume_set")
        self.assertEqual(loaded_wf["steps"][1]["action"], "brightness_set")

    @patch("subprocess.Popen")
    def test_replay_saved_workflow_ordered_execution(self, mock_popen):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        steps = [
            {"action": "open_project", "params": {"project": "lensify", "app": "Antigravity", "path": str(mock_lensify)}},
            {"action": "launch_terminal_at", "params": {"path": str(mock_lensify)}},
        ]
        self.memory.save_workflow(
            workflow_id="wf_lensify",
            trigger_phrases=["start working on lensify"],
            steps=steps,
            name="Start Working On Lensify",
        )

        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            should_cont, pending = route_command("Start working on Lensify")
            self.assertTrue(should_cont)
            self.assertIsNone(pending)
            self.assertEqual(mock_popen.call_count, 2)

            # Success count incremented and last_used updated
            wf_after = self.memory.get_workflow("wf_lensify")
            self.assertGreaterEqual(wf_after["success_count"], 2)
            self.assertIsNotNone(wf_after["last_used"])

    @patch("subprocess.Popen")
    def test_replay_stops_on_failure_and_reports_step(self, mock_popen):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        # Step 1 valid, Step 2 points to invalid non-existent path
        steps = [
            {"action": "open_project", "params": {"project": "lensify", "app": "Antigravity", "path": str(mock_lensify)}},
            {"action": "launch_terminal_at", "params": {"path": "/nonexistent/invalid/directory"}},
        ]
        self.memory.save_workflow(
            workflow_id="wf_fail_step2",
            trigger_phrases=["run broken workflow"],
            steps=steps,
            name="Broken Workflow",
        )

        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            ok, summary = get_workflow_executor().execute_workflow_steps(
                steps=steps,
                workflow_id="wf_fail_step2",
            )
            self.assertFalse(ok)
            self.assertIn("Workflow halted at step 2", summary)
            # Step 1 was executed, Step 2 was halted
            self.assertEqual(mock_popen.call_count, 1)

            # Failure count must be recorded
            wf_after = self.memory.get_workflow("wf_fail_step2")
            self.assertEqual(wf_after["failure_count"], 1)

    def test_duplicate_trigger_updates_workflow(self):
        # 1. Teach initial workflow
        self.memory.save_workflow(
            workflow_id="wf_dup",
            trigger_phrases=["code lensify"],
            steps=[{"action": "volume_set", "params": {"percentage": 50}}],
            name="Code Lensify",
        )
        self.assertEqual(len(self.memory.list_workflows()), 1)

        # 2. Update with modified steps
        new_steps = [
            {"action": "volume_set", "params": {"percentage": 80}},
            {"action": "brightness_set", "params": {"percentage": 90}},
        ]
        self.memory.save_workflow(
            workflow_id="wf_dup",
            trigger_phrases=["code lensify"],
            steps=new_steps,
            name="Code Lensify",
        )

        # Still only 1 workflow, updated steps
        workflows = self.memory.list_workflows()
        self.assertEqual(len(workflows), 1)
        self.assertEqual(len(workflows[0]["steps"]), 2)

    def test_workflow_management_lifecycle(self):
        # Setup workflow
        self.memory.save_workflow(
            workflow_id="wf_mgmt_test",
            trigger_phrases=["launch dev mode"],
            steps=[{"action": "volume_set", "params": {"percentage": 60}}],
            name="Dev Mode",
        )

        # 1. List workflows
        should_cont, pending = route_command("list workflows")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)

        # 2. Inspect workflow
        should_cont, pending = route_command("inspect workflow Dev Mode")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)

        # 3. Disable workflow
        should_cont, pending = route_command("disable workflow Dev Mode")
        self.assertTrue(should_cont)
        wf = self.memory.get_workflow("Dev Mode")
        self.assertEqual(wf["is_enabled"], 0)

        # Disabled workflow cannot be triggered
        self.assertIsNone(self.memory.get_workflow_by_trigger("launch dev mode"))

        # 4. Enable workflow
        should_cont, pending = route_command("enable workflow Dev Mode")
        self.assertTrue(should_cont)
        wf = self.memory.get_workflow("Dev Mode")
        self.assertEqual(wf["is_enabled"], 1)
        self.assertIsNotNone(self.memory.get_workflow_by_trigger("launch dev mode"))

        # 5. Rename workflow
        should_cont, pending = route_command("rename workflow Dev Mode to Full Dev Mode")
        self.assertTrue(should_cont)
        self.assertIsNone(self.memory.get_workflow("Dev Mode"))
        self.assertIsNotNone(self.memory.get_workflow("Full Dev Mode"))

        # 6. Delete workflow prompt without name first
        should_cont, pending = route_command("delete workflow")
        self.assertTrue(should_cont)
        self.assertEqual(pending, "delete_workflow_prompt")

        # User cancels deletion
        should_cont, pending = route_command("no")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNotNone(self.memory.get_workflow("Full Dev Mode"))

        # Direct deletion when target is caught ("then just delete it")
        should_cont, pending = route_command("delete workflow Full Dev Mode")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Full Dev Mode"))

    def test_delete_workflow_with_comma_transcription(self):
        self.memory.save_workflow(
            workflow_id="wf_lensify_comma",
            trigger_phrases=["start working on lensify"],
            steps=[{"action": "open_project", "params": {"project": "lensify"}}],
            name="Start Working On Lensify",
        )

        # Whisper transcribes with comma: "Delete workflow, start working on Lensify."
        # Directly deletes without confirmation
        should_cont, pending = route_command("Delete workflow, start working on Lensify.")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Start Working On Lensify"))

    def test_delete_workflow_single_word_and_fuzzy(self):
        # 1. Single word match from workflow name: "lensify"
        self.memory.save_workflow(
            workflow_id="wf_lensify_word",
            trigger_phrases=["start working on lensify"],
            steps=[{"action": "open_project", "params": {"project": "lensify"}}],
            name="Start Working On Lensify",
        )
        should_cont, pending = route_command("delete workflow lensify")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Start Working On Lensify"))

        # 2. Fuzzy match with transcription typo: "lensiify" (double 'i')
        self.memory.save_workflow(
            workflow_id="wf_lensify_fuzzy",
            trigger_phrases=["start working on lensify"],
            steps=[{"action": "open_project", "params": {"project": "lensify"}}],
            name="Start Working On Lensify",
        )
        should_cont, pending = route_command("delete workflow lensiify")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Start Working On Lensify"))

        # 3. Phrasing with ampersand: "delete workflow & lensiify"
        self.memory.save_workflow(
            workflow_id="wf_lensify_amp",
            trigger_phrases=["start working on lensify"],
            steps=[{"action": "open_project", "params": {"project": "lensify"}}],
            name="Start Working On Lensify",
        )
        should_cont, pending = route_command("delete workflow & lensiify")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Start Working On Lensify"))

        # 4. Inverted phrasing: "delete the lensiify workflow"
        self.memory.save_workflow(
            workflow_id="wf_lensify_inv",
            trigger_phrases=["start working on lensify"],
            steps=[{"action": "open_project", "params": {"project": "lensify"}}],
            name="Start Working On Lensify",
        )
        should_cont, pending = route_command("delete the lensiify workflow")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Start Working On Lensify"))

        # 5. Conversational multi-turn: "delete workflow" -> prompt -> "lensiify"
        self.memory.save_workflow(
            workflow_id="wf_lensify_prompt",
            trigger_phrases=["start working on lensify"],
            steps=[{"action": "open_project", "params": {"project": "lensify"}}],
            name="Start Working On Lensify",
        )
        should_cont, pending = route_command("delete workflow")
        self.assertTrue(should_cont)
        self.assertEqual(pending, "delete_workflow_prompt")

        should_cont, pending = route_command("lensiify", pending_action=pending)
        self.assertTrue(should_cont)
        self.assertIsNone(pending)
        self.assertIsNone(self.memory.get_workflow("Start Working On Lensify"))

    def test_execution_fails_on_uninstalled_application(self):
        mock_lensify = Path(self.temp_dir.name) / "Lensify"
        mock_lensify.mkdir(exist_ok=True)

        steps = [
            {"action": "open_project", "params": {"project": "lensify", "app": "nonexistent_app", "path": str(mock_lensify)}},
        ]
        self.memory.save_workflow(
            workflow_id="wf_uninstalled_app",
            trigger_phrases=["run with missing app"],
            steps=steps,
            name="Missing App Workflow",
        )

        with patch.object(
            get_workflow_executor().dir_resolver,
            "resolve_project_directory",
            return_value=(str(mock_lensify), [str(mock_lensify)]),
        ):
            ok, summary = get_workflow_executor().execute_workflow_steps(
                steps=steps,
                workflow_id="wf_uninstalled_app",
            )
            self.assertFalse(ok)
            self.assertIn("Workflow halted at step 1", summary)
            self.assertIn("is not installed", summary)

    @patch("actions.desktop.take_screenshot", return_value=(True, "screenshot captured"))
    @patch("actions.display.set_brightness", return_value=(True, "Brightness set to 80%."))
    @patch("actions.audio.set_volume", return_value=(True, "Volume set to 70%."))
    def test_workflow_with_desktop_controls(self, mock_vol, mock_br, mock_ss):
        steps = [
            {"action": "volume_set", "params": {"percentage": 70}},
            {"action": "brightness_set", "params": {"percentage": 80}},
            {"action": "screenshot", "params": {"mode": "fullscreen"}},
        ]
        self.memory.save_workflow(
            workflow_id="wf_desktop_mix",
            trigger_phrases=["focus setup"],
            steps=steps,
            name="Focus Setup",
        )

        ok, summary = get_workflow_executor().execute_workflow_steps(
            steps=steps,
            workflow_id="wf_desktop_mix",
        )
        self.assertTrue(ok)
        self.assertIn("Volume set to 70%", summary)
        self.assertIn("Brightness set to 80%", summary)
        self.assertIn("screenshot captured", summary)
        mock_vol.assert_called_once_with(70)
        mock_br.assert_called_once_with(80)
        mock_ss.assert_called_once_with("fullscreen")

    @patch("urllib.request.urlopen")
    def test_ollama_teaching_fallback_when_grammar_unusual(self, mock_urlopen):
        # When user expresses teaching in an unconventional phrasing that regex cannot parse
        unusual_phrase = "when i say code lensify please prepare my workspace"
        mock_resp_json = {
            "response": '{"trigger": "code lensify", "name": "Code Lensify", "steps": [{"action": "open_terminal", "params": {}}]}'
        }
        mock_cm = MagicMock()
        mock_cm.status = 200
        mock_cm.read.return_value = json.dumps(mock_resp_json).encode("utf-8")
        mock_urlopen.return_value.__enter__.return_value = mock_cm

        import intelligence.intent_extractor as ie
        res = ie.query_ollama_workflow_teaching(unusual_phrase)
        self.assertIsNotNone(res)
        self.assertEqual(res["action"], "teach_workflow")
        self.assertEqual(res["params"]["trigger"], "code lensify")
        self.assertEqual(res["params"]["name"], "Code Lensify")
        self.assertTrue(res["params"]["from_ollama"])

    def test_workflow_help_queries(self):
        from core.intent import detect_intent
        queries = [
            "how can I create a workflow?",
            "how do I teach you a workflow?",
            "how to create a workflow",
            "how do workflows work",
            "Jarvis, how can I create a workflow?",
        ]
        for q in queries:
            intent, params = detect_intent(q)
            self.assertEqual(intent, "SMART_ACTION", f"Failed for query: {q}")
            self.assertEqual(params.get("action"), "workflow_help", f"Failed action for: {q}")

        # Ensure router handles workflow_help without error
        should_cont, pending = route_command("how can I create a workflow?")
        self.assertTrue(should_cont)
        self.assertIsNone(pending)

    @patch("actions.resolver.DirectoryResolver.resolve_project_directory")
    def test_teach_workflow_editor_and_antigravity_aliases(self, mock_dir_resolve):
        mock_dir_resolve.return_value = ("/home/yusuf/Desktop/Lensify", ["/home/yusuf/Desktop/Lensify"])
        from intelligence.intent_extractor import extract_smart_intent

        # 1. anti-gravity editor
        intent1 = extract_smart_intent("When I say start working on Lensify, open Lensify in my anti-gravity editor.")
        self.assertIsNotNone(intent1)
        self.assertEqual(intent1["action"], "teach_workflow")
        self.assertEqual(intent1["params"]["trigger"], "start working on lensify")
        self.assertEqual(len(intent1["params"]["steps"]), 1)
        step1 = intent1["params"]["steps"][0]
        self.assertEqual(step1["action"], "open_project")
        self.assertEqual(step1["params"]["project"], "lensify")
        self.assertIn("Antigravity", step1["params"]["app"])

        # 2. phonetic "lens 5" -> "lensify" and "my editor"
        intent2 = extract_smart_intent("When I say start working on lens 5, open lens 5 in my editor.")
        self.assertIsNotNone(intent2)
        self.assertEqual(intent2["action"], "teach_workflow")
        self.assertEqual(intent2["params"]["trigger"], "start working on lensify")
        step2 = intent2["params"]["steps"][0]
        self.assertEqual(step2["action"], "open_project")
        self.assertEqual(step2["params"]["project"], "lensify")
        # 3. Pronoun reference 'that folder' and 'then' separator
        intent3 = extract_smart_intent("When I say open manage crew then open that folder into editor.")
        self.assertIsNotNone(intent3)
        self.assertEqual(intent3["action"], "teach_workflow")
        self.assertEqual(intent3["params"]["trigger"], "open manage crew")
        step3 = intent3["params"]["steps"][0]
        self.assertEqual(step3["action"], "open_project")
        self.assertIn("Antigravity", step3["params"]["app"])


if __name__ == "__main__":
    import json
    unittest.main()



