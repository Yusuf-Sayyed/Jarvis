"""
Multi-step composable workflow engine for JARVIS.
Executes chained actions sequentially, checks intermediate results,
halts on failures safely, and persists reusable workflows in SQLite memory.
"""

import os
import shutil
import subprocess
from typing import Any, Optional

from actions.resolver import get_app_registry, get_directory_resolver
from core.context import get_conversation_context
from core.memory import get_memory_store


class WorkflowExecutor:
    """Executes a list of validated action steps sequentially with verified results."""

    def __init__(self):
        self.memory = get_memory_store()
        self.context = get_conversation_context()
        self.app_registry = get_app_registry()
        self.dir_resolver = get_directory_resolver()

    def execute_workflow_steps(
        self,
        steps: list[dict[str, Any]],
        trigger_text: Optional[str] = None,
        workflow_id: Optional[str] = None,
    ) -> tuple[bool, str]:
        """
        Executes a sequence of steps safely.
        Each step: {'action': '...', 'params': {...}}
        Returns (all_succeeded: bool, report_message: str)
        """
        from actions import audio, desktop, display

        executed_descriptions = []
        shared_path: Optional[str] = None

        for idx, step in enumerate(steps):
            action = step.get("action")
            params = step.get("params", {})

            # 1. Step: open_project
            if action == "open_project":
                project = params.get("project")
                app_name = params.get("app") or "editor"
                target_path = params.get("path")

                if not target_path or not os.path.isdir(target_path):
                    target_path, candidates = self.dir_resolver.resolve_project_directory(project)

                if not target_path or not os.path.isdir(target_path):
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: Project folder '{project}' could not be located."

                app_info = self.app_registry.resolve_application(app_name)
                if not app_info or not shutil.which(app_info.exec_path):
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: Application '{app_name}' is not installed."

                try:
                    if "konsole" in app_info.exec_path.lower():
                        p = subprocess.Popen([app_info.exec_path, "--workdir", target_path])
                    else:
                        p = subprocess.Popen([app_info.exec_path, target_path], cwd=target_path)

                    poll_res = p.poll()
                    if isinstance(poll_res, int) and poll_res != 0:
                        if workflow_id:
                            self.memory.record_workflow_failure(workflow_id)
                        return False, f"Workflow halted at step {idx + 1}: Failed to launch {app_info.name}."

                    shared_path = target_path
                    self.context.update_interaction(
                        action="open_project",
                        app=app_info.name.lower(),
                        app_bin=app_info.exec_path,
                        target_name=project,
                        target_path=target_path,
                    )
                    executed_descriptions.append(f"{app_info.name} opened in '{project}'")
                except Exception as e:
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: {e}"

            # 2. Step: launch_terminal_at
            elif action == "launch_terminal_at":
                target_path = params.get("path") or shared_path or self.context.get_recent_target_path()
                if not target_path or not os.path.isdir(target_path):
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: Working directory is invalid or not found."

                konsole_bin = shutil.which("konsole") or "/usr/bin/konsole"
                try:
                    p = subprocess.Popen([konsole_bin, "--workdir", target_path])
                    poll_res = p.poll()
                    if isinstance(poll_res, int) and poll_res != 0:
                        if workflow_id:
                            self.memory.record_workflow_failure(workflow_id)
                        return False, f"Workflow halted at step {idx + 1}: Failed to launch Konsole."

                    self.context.update_interaction(action="open_terminal", app="konsole", target_path=target_path)
                    executed_descriptions.append("Konsole terminal opened in the same folder")
                except Exception as e:
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: {e}"

            # 3. Step: volume_set
            elif action == "volume_set":
                pct = params.get("percentage", 100)
                ok, msg = audio.set_volume(pct)
                if not ok:
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: {msg}"
                executed_descriptions.append(msg)

            # 4. Step: brightness_set
            elif action == "brightness_set":
                pct = params.get("percentage", 50)
                ok, msg = display.set_brightness(pct)
                if not ok:
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: {msg}"
                executed_descriptions.append(msg)

            # 5. Step: screenshot
            elif action == "screenshot":
                mode = params.get("mode", "fullscreen")
                ok, msg = desktop.take_screenshot(mode)
                if not ok:
                    if workflow_id:
                        self.memory.record_workflow_failure(workflow_id)
                    return False, f"Workflow halted at step {idx + 1}: {msg}"
                executed_descriptions.append("screenshot captured")

            # 6. Core Desktop Actions
            elif action == "open_firefox_tab":
                from actions import browser
                browser.open_firefox_tab()
                executed_descriptions.append("new Firefox tab opened")

            elif action == "open_firefox_window":
                from actions import browser
                browser.open_firefox_window()
                executed_descriptions.append("new Firefox window opened")

            elif action == "open_terminal":
                desktop.open_terminal()
                executed_descriptions.append("terminal opened")

            elif action == "open_downloads":
                desktop.open_downloads()
                executed_descriptions.append("downloads folder opened")

            elif action == "open_youtube":
                desktop.open_youtube()
                executed_descriptions.append("YouTube opened")

            else:
                if workflow_id:
                    self.memory.record_workflow_failure(workflow_id)
                return False, f"Workflow halted: Unsupported action '{action}' in workflow."

        # All steps succeeded!
        summary = ", and ".join(executed_descriptions) + "."

        if workflow_id:
            self.memory.record_workflow_success(workflow_id)

        # Save reusable workflow to SQLite memory if trigger_text was provided
        if trigger_text:
            w_id = "workflow_" + str(abs(hash(trigger_text)))[:8]
            self.memory.save_workflow(
                workflow_id=w_id,
                trigger_phrases=[trigger_text.lower().strip()],
                steps=steps,
            )

        return True, summary


# Global executor instance
_EXECUTOR_INSTANCE: Optional[WorkflowExecutor] = None


def get_workflow_executor() -> WorkflowExecutor:
    global _EXECUTOR_INSTANCE
    if _EXECUTOR_INSTANCE is None:
        _EXECUTOR_INSTANCE = WorkflowExecutor()
    return _EXECUTOR_INSTANCE
