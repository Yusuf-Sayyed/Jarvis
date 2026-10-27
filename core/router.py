import os
import shutil
import subprocess
from actions import audio, browser, desktop, display, keyboard, media
from actions.resolver import get_app_registry, get_directory_resolver
from actions.workflow import get_workflow_executor
from core.context import get_conversation_context
from core.intent import detect_intent
from core.memory import get_memory_store
import re
from intelligence.ollama_client import ask_ollama


def extract_and_store_user_facts(text: str) -> dict[str, str]:
    """
    Detects personal introductions, locations, and facts from spoken conversation,
    and saves them to the persistent MemoryStore.
    """
    facts = {}
    clean = text.strip()

    # 1. Name: "my name is Yusuf", "call me Yusuf", "my name's Yusuf"
    m_name = re.search(r"\b(?:my\s+name\s+is|my\s+name\'s|call\s+me)\s+([A-Za-z]+)", clean, re.IGNORECASE)
    if m_name:
        name = m_name.group(1).strip().capitalize()
        if name.lower() not in ("jarvis", "a", "an", "the", "sir"):
            facts["user_name"] = name

    # 2. Location: "I live in India", "I'm from India", "I reside in India"
    m_loc = re.search(r"\bi\s+(?:live|reside)\s+in\s+([A-Za-z\s]+?)(?:[.,]|\s+and\b|$)", clean, re.IGNORECASE)
    if not m_loc:
        m_loc = re.search(r"\bi(?:\x27m|\s+am)\s+from\s+([A-Za-z\s]+?)(?:[.,]|\s+and\b|$)", clean, re.IGNORECASE)
    if m_loc:
        loc = m_loc.group(1).strip().title()
        if loc.lower() not in ("a", "an", "the", "here", "there"):
            facts["location"] = loc

    # 3. Age: e.g. "I am 23 years old", "I'm young and 23 yrs old", "I'm 23", "my age is 23"
    m_age = re.search(r"\b(?:i(?:\x27m|\s+am)(?:\s+(?:a\s+)?(?:young|old))?\s+(?:and\s+)?|my\s+age\s+is\s+)(\d{1,2})\s*(?:years?\s+old|yrs?\s+old|yo)?\b", clean, re.IGNORECASE)
    if not m_age:
        m_age = re.search(r"\b(\d{1,2})\s*(?:years?\s+old|yrs?\s+old)\b", clean, re.IGNORECASE)
    if m_age:
        facts["age"] = m_age.group(1)

    # 4. Profession/role: e.g. "I am a software engineer", "I'm a developer", "I work as a programmer"
    m_prof = re.search(r"\bi(?:\x27m|\s+am)\s+(?:a|an)\s+([A-Za-z\s]+?)(?:[.,]|\s+and\b|$)", clean, re.IGNORECASE)
    if m_prof:
        prof = m_prof.group(1).strip()
        if prof.lower() not in ("young", "old", "here", "there", "from", "guy", "man", "person"):
            facts["occupation"] = prof.capitalize()

    # 5. Explicit preferences: "remember that my favorite language is Python"
    m_pref = re.search(r"\bremember\s+(?:that\s+)?my\s+([A-Za-z\s]+?)\s+is\s+([A-Za-z0-9\s]+?)(?:[.,]|$)", clean, re.IGNORECASE)
    if m_pref:
        pref_key = m_pref.group(1).strip().lower().replace(" ", "_")
        pref_val = m_pref.group(2).strip()
        facts[pref_key] = pref_val

    # 6. General remember note: "remember that I am ..." or "remember I ..."
    m_rem_iam = re.search(r"\bremember\s+(?:that\s+)?i(?:\x27m|\s+am)\s+(.+?)(?:[.,]|$)", clean, re.IGNORECASE)
    if m_rem_iam and "age" not in facts and "occupation" not in facts:
        facts["user_note"] = m_rem_iam.group(1).strip()


    if facts:
        try:
            memory = get_memory_store()
            for k, v in facts.items():
                memory.set_preference(k, v)
        except Exception:
            pass

    return facts


def route_command(text: str, pending_action: str | None = None) -> tuple[bool, str | None]:
    """
    Detects the intent of spoken text and routes it to the proper action.

    Returns:
        (should_continue: bool, new_pending_action: str | None)
    """
    context = get_conversation_context()
    intent, params = detect_intent(text, pending_action)

    # 1. Confirmation Responses (Yes / No)
    if intent == "CONFIRM_ACTION":
        action = params.get("action")
        payload = params.get("payload", {})
        print(f"[Intent: CONFIRM_ACTION | Action: {action}]")
        if action == "close_tab":
            keyboard.close_browser_tab()
        elif action == "confirm_open_project":
            app_bin = payload.get("app_bin")
            target_path = payload.get("path")
            if app_bin and target_path:
                print(f"[JARVIS] Executing confirmed action: {app_bin} in {target_path}...")
                try:
                    proc = subprocess.Popen([app_bin, target_path], cwd=target_path)
                    poll_res = proc.poll()
                    if isinstance(poll_res, int) and poll_res != 0:
                        print(f"[JARVIS Error] Process exited immediately with return code {poll_res}.")
                    else:
                        context.update_interaction(action="open_project", app_bin=app_bin, target_path=target_path)
                except Exception as e:
                    print(f"[JARVIS Error] Failed to launch: {e}")
        elif action == "confirm_volume_limit":
            target_pct = payload.get("target_pct", 150)
            ok, msg = audio.set_volume(target_pct)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
        elif action == "confirm_save_workflow":
            memory = get_memory_store()
            w_id = payload.get("workflow_id")
            w_name = payload.get("name")
            triggers = payload.get("triggers", [])
            steps = payload.get("steps", [])
            memory.save_workflow(
                workflow_id=w_id,
                trigger_phrases=triggers,
                steps=steps,
                name=w_name,
            )
            trigger_str = f"'{triggers[0]}'" if triggers else "your trigger"
            print(f'\n[JARVIS] "Workflow \'{w_name}\' saved successfully, Sir. You can run it anytime by saying {trigger_str}."\n')
        elif action == "confirm_delete_workflow":
            memory = get_memory_store()
            w_id = payload.get("workflow_id")
            w_name = payload.get("name") or w_id
            ok = memory.delete_workflow(w_id)
            if ok:
                print(f'\n[JARVIS] "Workflow \'{w_name}\' has been deleted, Sir."\n')
            else:
                print(f'\n[JARVIS Error] Could not delete workflow \'{w_name}\'.\n')
        elif action == "confirm_workflow_folder_choice":
            memory = get_memory_store()
            chosen_path = payload.get("chosen_path")
            proj = payload.get("project")
            trigger = payload.get("trigger")
            raw_actions = payload.get("raw_actions")
            if proj and chosen_path:
                memory.save_project(proj, chosen_path)
            context.clear_pending()
            teach_phrase = f"when I say {trigger}, {raw_actions}"
            return route_command(teach_phrase)
        elif action == "confirm_memory_update":
            memory = get_memory_store()
            target_key = payload.get("target_key") or payload.get("key")
            new_val = payload.get("new_value", "").strip()
            clean_new = re.sub(
                r"^(?:it\s+is\s+called|it\s+is|it\x27s\s+called|it\x27s|called|named|set\s+it\s+to|change\s+it\s+to|to)\s+",
                "",
                new_val,
                flags=re.IGNORECASE,
            ).strip().strip("'\"")
            clean_new = clean_new.rstrip(".?!,").strip()
            if not clean_new:
                clean_new = new_val

            topic = payload.get("topic") or (target_key.replace("_", " ") if target_key else "memory")
            ok = False
            if target_key and clean_new:
                ok = memory.update_memory(target_key, clean_new)

            if ok:
                print(f'\n[JARVIS] "I have updated your {topic} to \'{clean_new}\', Sir."\n')
            else:
                print(f'\n[JARVIS Error] Could not update {topic} in database.\n')
            context.clear_pending()
            return True, None
        elif action == "confirm_memory_forget":
            memory = get_memory_store()
            target_key = payload.get("target_key")
            topic = payload.get("topic") or (target_key.replace("_", " ") if target_key else "memory")
            ok = False
            if target_key:
                ok = memory.delete_memory(target_key)
            if ok:
                print(f'\n[JARVIS] "I have forgotten that {topic}, Sir."\n')
            else:
                print(f'\n[JARVIS Error] Could not remove {topic} from database.\n')
            context.clear_pending()
            return True, None
        context.clear_pending()
        return True, None

    if intent == "CANCEL_ACTION":
        print("[Intent: CANCEL_ACTION]")
        print("[JARVIS] Action canceled, Sir.")
        context.clear_pending()
        return True, None

    # 1.4 Fast-Path Media and Video Playback Controls (MPRIS D-Bus / Browser Fallback)
    if intent == "MEDIA_CONTROL":
        action = params.get("action")
        target = params.get("target")
        offset = params.get("offset")
        mute_state = params.get("mute_state", True)

        offset_str = f" | Offset: {offset}s" if offset is not None else ""
        target_str = f" | Target: {target}" if target else ""
        print(f"[Intent: MEDIA_CONTROL | Action: {action}{offset_str}{target_str}]")

        if action == "pause":
            ok, msg, candidates = media.pause_playback(target)
        elif action == "resume":
            ok, msg, candidates = media.resume_playback(target)
        elif action == "stop":
            ok, msg, candidates = media.stop_playback(target)
        elif action == "seek":
            ok, msg, candidates = media.seek_playback(offset or 10, target)
        elif action == "mute":
            ok, msg, candidates = media.mute_playback(mute_state, target)
        elif action == "next":
            ok, msg, candidates = media.next_playback(target)
        elif action == "previous":
            ok, msg, candidates = media.previous_playback(target)
        else:
            ok, msg, candidates = False, f"Unknown media action '{action}', Sir.", None

        if candidates and len(candidates) > 1:
            print(f'\n[JARVIS] "I found multiple active media sessions ({", ".join(candidates)}). Which one would you like me to {action}, Sir?"\n')
            context.set_pending("clarify_media_player", {"candidates": candidates, "action": action, "params": params})
            return True, "clarify_media_player"

        if ok:
            print(f"[JARVIS] {msg}")
        elif "could not be verified" in msg.lower() or "dispatched" in msg.lower():
            print(f"[JARVIS Warning] {msg}")
        else:
            print(f"[JARVIS Error] {msg}")
        return True, None

    # 1.5 Smart Intent & Learned Workflow Actions (Natural Language & Follow-ups)
    if intent == "SMART_ACTION":
        smart_action = params.get("action")
        smart_params = params.get("params", {})
        print(f"[Intent: SMART_ACTION | Action: {smart_action}]")

        dir_resolver = get_directory_resolver()
        app_registry = get_app_registry()
        memory = get_memory_store()

        # Conversational Teaching of Workflows
        if smart_action == "teach_workflow":
            if smart_params.get("unsupported"):
                err = smart_params["unsupported"]
                print(f'\n[JARVIS] "I could not create the workflow: {err}"\n')
                return True, None

            if smart_params.get("ambiguity"):
                amb = smart_params["ambiguity"]
                candidates = amb.get("candidates", [])
                proj = amb.get("project", "")
                print(f"\n[JARVIS] \"I found multiple folders matching '{proj}':")
                for c in candidates:
                    print(f"         - {c}")
                print('Which one would you like to use for this workflow, Sir?"\n')
                context.set_pending("clarify_workflow_folder", {
                    "candidates": candidates,
                    "project": proj,
                    "trigger": smart_params.get("trigger"),
                    "raw_actions": smart_params.get("raw_actions"),
                })
                return True, "clarify_workflow_folder"

            trigger = smart_params.get("trigger", "")
            wf_name = smart_params.get("name") or trigger.title()
            steps = smart_params.get("steps", [])

            # Check for existing workflow with matching trigger or name
            existing_wf = memory.get_workflow_by_trigger(trigger) or memory.get_workflow(wf_name)
            w_id = existing_wf["workflow_id"] if existing_wf else f"workflow_{abs(hash(trigger)) % 100000000:08d}"

            print(f'\n[JARVIS] "I have prepared the workflow \'{wf_name}\' with the following steps:')
            for s_idx, step in enumerate(steps, 1):
                desc = step.get("description") or f"{step.get('action')}: {step.get('params')}"
                print(f"         {s_idx}. {desc}")
            print(f"         Trigger phrase: '{trigger}'")
            if existing_wf:
                print(f"         Note: A workflow '{existing_wf.get('name')}' already exists with this trigger. Saving will update it.")
            print('Would you like me to save this workflow, Sir?"')
            print("Say 'yes' to save or 'no' to cancel.\n")

            context.set_pending("confirm_save_workflow", {
                "workflow_id": w_id,
                "name": wf_name,
                "triggers": [trigger],
                "steps": steps,
            })
            return True, "confirm_save_workflow"

        # Workflow Management: List
        if smart_action == "list_workflows":
            workflows = memory.list_workflows(include_disabled=True)
            if not workflows:
                print('\n[JARVIS] "You have no saved workflows, Sir."\n')
            else:
                print(f"\n[JARVIS] \"You have {len(workflows)} saved workflow(s), Sir:\"")
                for idx, wf in enumerate(workflows, 1):
                    status = "enabled" if wf.get("is_enabled", 1) else "disabled"
                    name = wf.get("name") or wf.get("workflow_id")
                    triggers = ", ".join(f"'{t}'" for t in wf.get("trigger_phrases", []))
                    step_count = len(wf.get("steps", []))
                    print(f"  {idx}. {name} [{status}] - {step_count} step(s)")
                    print(f"     Triggers: {triggers}")
                print()
            return True, None

        # Workflow Help & Teaching Instructions
        if smart_action == "workflow_help":
            print(
                '\n[JARVIS] "To teach me a workflow, Sir, say: \'When I say [trigger phrase], [action 1] and [action 2]\'. '
                'For example: \'When I say start working on Lensify, open Lensify in my editor and open a terminal in that project folder.\' '
                'I will validate the actions, confirm the setup, and save it to your memory for automatic execution."\n'
            )
            return True, None

        # Workflow Management: Inspect
        if smart_action == "inspect_workflow":
            target = smart_params.get("workflow_name", "")
            wf = memory.find_workflow(target)
            if not wf:
                print(f'\n[JARVIS] "I could not find a workflow matching \'{target}\', Sir."\n')
            else:
                status = "enabled" if wf.get("is_enabled", 1) else "disabled"
                name = wf.get("name") or wf.get("workflow_id")
                triggers = ", ".join(f"'{t}'" for t in wf.get("trigger_phrases", []))
                print(f"\n[JARVIS] Workflow: {name} [{status}]")
                print(f"  ID: {wf.get('workflow_id')}")
                print(f"  Triggers: {triggers}")
                print(f"  Success count: {wf.get('success_count', 0)} | Failures: {wf.get('failure_count', 0)}")
                if wf.get("last_used"):
                    import datetime
                    dt = datetime.datetime.fromtimestamp(wf["last_used"]).strftime("%Y-%m-%d %H:%M:%S")
                    print(f"  Last used: {dt}")
                print("  Steps:")
                for s_idx, step in enumerate(wf.get("steps", []), 1):
                    desc = step.get("description") or f"{step.get('action')}: {step.get('params')}"
                    print(f"    {s_idx}. {desc}")
                print()
            return True, None

        # Workflow Management: Enable / Disable
        if smart_action == "toggle_workflow":
            target = smart_params.get("workflow_name", "")
            enabled = smart_params.get("enabled", True)
            wf = memory.find_workflow(target)
            if wf:
                ok = memory.set_workflow_status(wf["workflow_id"], enabled)
                state_str = "enabled" if enabled else "disabled"
                print(f'\n[JARVIS] "Workflow \'{wf.get("name")}\' has been {state_str}, Sir."\n')
            else:
                print(f'\n[JARVIS] "I could not find a workflow matching \'{target}\', Sir."\n')
            return True, None

        # Workflow Management: Delete (Direct Deletion when target is specified)
        if smart_action == "delete_workflow":
            target = smart_params.get("workflow_name", "")
            if not target:
                print('\n[JARVIS] "Which workflow would you like me to delete, Sir?"\n')
                context.set_pending("delete_workflow_prompt")
                return True, "delete_workflow_prompt"

            wf = memory.find_workflow(target)
            if not wf:
                print(f'\n[JARVIS] "I could not find a workflow matching \'{target}\', Sir."\n')
                return True, None

            ok = memory.delete_workflow(wf["workflow_id"])
            if ok:
                context.clear_pending()
                print(f'\n[JARVIS] "Workflow \'{wf.get("name")}\' has been deleted, Sir."\n')
            else:
                print(f'\n[JARVIS Error] Could not delete workflow \'{wf.get("name")}\'.\n')
            return True, None

        # Workflow Management: Rename
        if smart_action == "rename_workflow":
            old_name = smart_params.get("old_name", "")
            new_name = smart_params.get("new_name", "")
            ok = memory.update_workflow(old_name, name=new_name)
            if ok:
                print(f'\n[JARVIS] "Workflow has been renamed from \'{old_name}\' to \'{new_name}\', Sir."\n')
            else:
                print(f'\n[JARVIS] "I could not find a workflow named \'{old_name}\', Sir."\n')
            return True, None

        # Multi-Step Workflows (Chained or Saved)
        if smart_action in ("compose_workflow", "run_workflow"):
            steps = smart_params.get("steps", [])
            trigger_text = smart_params.get("trigger_text")
            workflow_id = smart_params.get("workflow_id")

            executor = get_workflow_executor()
            success, msg = executor.execute_workflow_steps(
                steps=steps,
                trigger_text=trigger_text,
                workflow_id=workflow_id,
            )
            if success:
                print(f"[JARVIS] Workflow completed successfully: {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        # Desktop Audio Controls
        if smart_action == "volume_set":
            pct = smart_params.get("percentage", 100)
            ok, msg = audio.set_volume(pct)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        if smart_action == "volume_change":
            delta = smart_params.get("delta", 10)
            ok, msg = audio.change_volume(delta)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        if smart_action == "mute_audio":
            state = smart_params.get("mute_state")
            ok, msg = audio.set_mute(state)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        if smart_action == "volume_limit_clarification":
            req_pct = smart_params.get("requested_percentage", 200)
            max_pct = smart_params.get("max_percentage", 150)
            print(
                f"\n[JARVIS] \"The requested volume is {req_pct}%, but the maximum supported limit "
                f"is {max_pct}% (software amplification). Would you like me to set the volume to {max_pct}%, Sir?\"\n"
            )
            context.set_pending("confirm_volume_limit", {"target_pct": max_pct, "requested_pct": req_pct})
            return True, "confirm_volume_limit"

        if smart_action == "volume_missing_number":
            print('\n[JARVIS] "What volume percentage would you like me to set, Sir?"\n')
            context.set_pending("set_volume_query", {})
            return True, "set_volume_query"

        # Desktop Brightness Controls
        if smart_action == "brightness_set":
            pct = smart_params.get("percentage", 50)
            ok, msg = display.set_brightness(pct)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        if smart_action == "brightness_change":
            delta = smart_params.get("delta", 10)
            ok, msg = display.change_brightness(delta)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        # Screenshot Controls
        if smart_action == "screenshot":
            mode = smart_params.get("mode", "fullscreen")
            ok, msg = desktop.take_screenshot(mode)
            if not ok:
                print(f"[JARVIS Error] {msg}")
            return True, None

        # Window Controls
        if smart_action == "window_control":
            win_action = smart_params.get("action", "")
            ok, msg = desktop.control_window(win_action)
            if ok:
                print(f"[JARVIS] {msg}")
            else:
                print(f"[JARVIS Error] {msg}")
            return True, None

        if smart_action == "open_project":
            project_name = smart_params.get("project")
            app_name = smart_params.get("app")

            target_path, candidates = dir_resolver.resolve_project_directory(project_name)

            if not target_path and len(candidates) > 1:
                print(f"\n[JARVIS] \"I found multiple folders matching '{project_name}':")
                for c in candidates:
                    print(f"         - {c}")
                print('Which one would you like me to open, Sir?"\n')
                context.set_pending("clarify_folder", {"candidates": candidates, "app": app_name})
                return True, "clarify_folder"

            if not target_path:
                print(f'\n[JARVIS] "I could not locate the project folder \'{project_name}\' on your system, Sir."\n')
                memory.record_pattern_failure(text)
                return True, None

            # Resolve application
            app_info = app_registry.resolve_application(app_name or "editor")
            if not app_info:
                print(f'\n[JARVIS] "Application \'{app_name}\' is not installed on this system, Sir."\n')
                memory.record_pattern_failure(text)
                return True, None

            print(f'[JARVIS] Opening project "{project_name}" in {app_info.name}...')
            try:
                if "konsole" in app_info.exec_path.lower():
                    proc = subprocess.Popen([app_info.exec_path, "--workdir", target_path])
                else:
                    proc = subprocess.Popen([app_info.exec_path, target_path], cwd=target_path)

                poll_res = proc.poll()
                if isinstance(poll_res, int) and poll_res != 0:
                    print(f"[JARVIS Error] Process exited immediately with return code {poll_res}.")
                    memory.record_pattern_failure(text)
                    return True, None

                print(f"[JARVIS] {app_info.name} launched successfully.")

                # Save learned association and fast-path pattern to SQLite memory
                memory.save_project(project_name, target_path, default_app=app_info.name.lower())
                memory.save_learned_pattern(
                    text,
                    "open_project",
                    {"project": project_name, "app": app_info.name, "path": target_path},
                )

                # Update conversation context
                context.update_interaction(
                    action="open_project",
                    app=app_info.name.lower(),
                    app_bin=app_info.exec_path,
                    target_name=project_name,
                    target_path=target_path,
                )
            except Exception as e:
                print(f"[JARVIS Error] Failed to launch {app_info.name}: {e}")
                memory.record_pattern_failure(text)

            return True, None

        if smart_action == "launch_terminal_at":
            target_path = smart_params.get("path") or context.get_recent_target_path()
            if not target_path:
                print('\n[JARVIS] "No recent project folder context is active to open a terminal in, Sir."\n')
                return True, None

            konsole_bin = shutil.which("konsole") or "/usr/bin/konsole"
            print(f"[JARVIS] Opening Konsole terminal in {target_path}...")
            try:
                proc = subprocess.Popen([konsole_bin, "--workdir", target_path])
                poll_res = proc.poll()
                if isinstance(poll_res, int) and poll_res != 0:
                    print(f"[JARVIS Error] Konsole failed to launch: return code {poll_res}.")
                    return True, None
                print("[JARVIS] Konsole terminal launched successfully.")
                context.update_interaction(action="open_terminal", app="konsole", target_path=target_path)
            except Exception as e:
                print(f"[JARVIS Error] Failed to launch Konsole: {e}")

            return True, None

        if smart_action in ("open_project_at", "followup_switch_app"):
            target_path = smart_params.get("path") or context.get_recent_target_path()
            app_name = smart_params.get("app")
            if not target_path:
                print('\n[JARVIS] "No recent project folder is active to open, Sir."\n')
                return True, None

            app_info = app_registry.resolve_application(app_name)
            if not app_info:
                print(f'\n[JARVIS] "Application \'{app_name}\' is not installed on this system, Sir."\n')
                return True, None

            print(f'[JARVIS] Opening {target_path} in {app_info.name}...')
            try:
                if "konsole" in app_info.exec_path.lower():
                    proc = subprocess.Popen([app_info.exec_path, "--workdir", target_path])
                else:
                    proc = subprocess.Popen([app_info.exec_path, target_path], cwd=target_path)
                poll_res = proc.poll()
                if isinstance(poll_res, int) and poll_res != 0:
                    print(f"[JARVIS Error] Failed to launch {app_info.name}: return code {poll_res}.")
                    return True, None
                print(f"[JARVIS] {app_info.name} launched successfully.")
                context.update_interaction(
                    action="open_project",
                    app=app_info.name.lower(),
                    app_bin=app_info.exec_path,
                    target_path=target_path,
                )
            except Exception as e:
                print(f"[JARVIS Error] Failed to launch {app_info.name}: {e}")

            return True, None

    # 1.6 Conversational Memory Actions (Facts, Preferences, Recall, Deletion, Update)
    if intent == "MEMORY_ACTION":
        mem_action = params.get("action")
        raw = params.get("raw", text)
        print(f"[Intent: MEMORY_ACTION | Action: {mem_action}]")
        memory = get_memory_store()

        # 1. Explicit Remember Action
        if mem_action == "remember_memory":
            key = params.get("key", "user_memory")
            topic = params.get("topic", "memory")
            category = params.get("category", "fact")
            content = params.get("content", "")
            stmt = params.get("statement", raw)

            if not content:
                print('\n[JARVIS Error] Could not determine the fact or preference to remember, Sir.\n')
                return True, None

            ok = memory.save_memory(
                memory_key=key,
                content=content,
                category=category,
                topic=topic,
                raw_statement=stmt,
            )

            # Requirement 5: Never claim something was remembered unless the database operation succeeded.
            if ok:
                if category == "preference":
                    print(f'\n[JARVIS] "I have noted your preference for {topic}: \'{content}\', Sir."\n')
                else:
                    print(f'\n[JARVIS] "I will remember that {topic}: \'{content}\', Sir."\n')
            else:
                print(f'\n[JARVIS Error] Failed to persist memory for {topic} to the database, Sir.\n')
            return True, None

        # 2. Recall Memory Action
        if mem_action == "recall_memory":
            query = params.get("query", "")
            memories = memory.find_memories(query)

            if not memories:
                print(f'\n[JARVIS] "I could not find any saved memories regarding \'{query}\', Sir."\n')
                return True, None

            if len(memories) == 1:
                mem = memories[0]
                cont = mem.get("content", "")
                top = mem.get("topic", "")
                cat = mem.get("category", "fact")
                if cont.lower().startswith("i live") or cont.lower().startswith("i stay"):
                    ans = "You " + cont[2:]
                    print(f'\n[JARVIS] "{ans}, Sir."\n')
                elif cat == "preference":
                    print(f'\n[JARVIS] "You prefer {cont}, Sir."\n')
                elif top.lower() in ("business name", "business", "company"):
                    print(f'\n[JARVIS] "Your business is called {cont}, Sir."\n')
                elif cont.lower().startswith("i "):
                    ans = "You " + cont[2:]
                    print(f'\n[JARVIS] "{ans}, Sir."\n')
                else:
                    print(f'\n[JARVIS] "I remember that {top} is \'{cont}\', Sir."\n')
            else:
                print(f'\n[JARVIS] "I found the following saved memories regarding \'{query}\', Sir:"')
                for m in memories:
                    print(f"  - {m.get('topic', '').title()}: {m.get('content', '')}")
                print()
            return True, None

        # 3. List Memories Action
        if mem_action == "list_memories":
            memories = memory.list_all_memories()
            if not memories:
                print('\n[JARVIS] "You have no saved memories or preferences, Sir."\n')
            else:
                print(f'\n[JARVIS] "You have {len(memories)} saved memory(ies), Sir:"')
                for idx, m in enumerate(memories, 1):
                    cat = m.get("category", "fact").capitalize()
                    top = m.get("topic", m.get("memory_key", "")).title()
                    cont = m.get("content", "")
                    print(f"  {idx}. [{cat}] {top}: {cont}")
                print()
            return True, None

        # 4. Forget Memory Action
        if mem_action == "forget_memory":
            target = params.get("target", "").strip()
            if not target:
                print('\n[JARVIS] "Which memory or preference would you like me to forget, Sir?"\n')
                context.set_pending("clarify_memory_forget")
                return True, "clarify_memory_forget"

            matches = memory.find_memories(target)
            if not matches:
                print(f'\n[JARVIS] "I could not find any saved memory matching \'{target}\' to forget, Sir."\n')
                return True, None

            if len(matches) > 1:
                # Ambiguous request: multiple matches
                print(f'\n[JARVIS] "I found multiple memories matching \'{target}\':"')
                for idx, m in enumerate(matches, 1):
                    print(f"  {idx}. {m.get('topic', '').title()}: {m.get('content', '')}")
                print('Which one would you like me to forget, Sir?"\n')
                candidates = [m["memory_key"] for m in matches]
                context.set_pending("clarify_memory_forget", {"candidates": candidates, "query": target})
                return True, "clarify_memory_forget"

            # Single match
            target_mem = matches[0]
            ok = memory.delete_memory(target_mem["memory_key"])
            if ok:
                top = target_mem.get("topic") or target_mem["memory_key"].replace("_", " ")
                print(f'\n[JARVIS] "I have forgotten that {top} ({target_mem.get("content")}), Sir."\n')
            else:
                print(f'\n[JARVIS Error] Could not delete memory from the database, Sir.\n')
            return True, None

        # 5. Update Memory Action
        if mem_action == "update_memory":
            target = params.get("target", "").strip()
            new_val = params.get("new_value")

            if not target:
                print('\n[JARVIS] "Which memory or preference would you like me to update, Sir?"\n')
                context.set_pending("clarify_memory_update")
                return True, "clarify_memory_update"

            matches = memory.find_memories(target)
            if not matches:
                print(f'\n[JARVIS] "I could not find any saved memory matching \'{target}\' to update, Sir."\n')
                return True, None

            if len(matches) > 1:
                print(f'\n[JARVIS] "I found multiple memories matching \'{target}\':"')
                for idx, m in enumerate(matches, 1):
                    print(f"  {idx}. {m.get('topic', '').title()}: {m.get('content', '')}")
                print('Which one would you like to update, Sir?"\n')
                candidates = [m["memory_key"] for m in matches]
                context.set_pending("clarify_memory_update", {"candidates": candidates, "query": target, "new_value": new_val})
                return True, "clarify_memory_update"

            target_mem = matches[0]
            if new_val is None:
                # Ambiguous request: No new value provided
                top = target_mem.get("topic") or target_mem["memory_key"].replace("_", " ")
                print(f'\n[JARVIS] "What would you like to update your {top} to, Sir?"\n')
                context.set_pending("clarify_memory_update", {"target_key": target_mem["memory_key"], "topic": top})
                return True, "clarify_memory_update"

            # New value provided directly
            ok = memory.update_memory(target_mem["memory_key"], new_val)
            if ok:
                top = target_mem.get("topic") or target_mem["memory_key"].replace("_", " ")
                print(f'\n[JARVIS] "I have updated your {top} to \'{new_val}\', Sir."\n')
            else:
                print(f'\n[JARVIS Error] Could not update memory in the database, Sir.\n')
            return True, None

    # 2. Exit Command
    if intent == "EXIT":
        print("[Intent: EXIT]")
        print("[JARVIS] Goodbye, Sir. Systems powering down.")
        return False, None

    # 3. Actions Requiring Confirmation (e.g. Close Tab)
    if intent == "REQUEST_CONFIRMATION":
        action = params.get("action")
        print(f"[Intent: BROWSER_ACTION | Action: Close Current Tab (Confirmation Required)]")
        print("\n[JARVIS] \"Are you sure you want to close the current tab, Sir?\"")
        print("         Say 'yes' to confirm or 'no' to cancel.\n")
        return True, action

    # 4. YouTube Direct Video Playback
    if intent == "YOUTUBE_PLAY_PROMPT":
        print("[Intent: YOUTUBE_PLAY | Awaiting Query]")
        print('\n[JARVIS] "What video or song would you like me to play on YouTube, Sir?"\n')
        return True, "youtube_play"

    if intent == "YOUTUBE_PLAY":
        query = params.get("query", "")
        if not query:
            print("[Intent: YOUTUBE_PLAY | Query Unclear]")
            print('\n[JARVIS] "Please state what video or song you would like to play, Sir."\n')
            return True, "youtube_play"

        print(f"[Intent: YOUTUBE_PLAY | Query: \"{query}\"]")
        browser.play_youtube_video(query)
        return True, None

    if intent == "YOUTUBE_FIRST_RESULT":
        print("[Intent: YOUTUBE_FIRST_RESULT]")
        browser.open_first_youtube_result()
        return True, None

    # 5. Web Search Intent (Search results page)
    if intent == "SEARCH_PROMPT":
        engine = params.get("engine", "google")
        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Awaiting Query]")
        print(f'\n[JARVIS] "What would you like me to search for on {engine.capitalize()}, Sir?"\n')
        return True, f"search_{engine}"

    if intent == "BROWSER_SEARCH":
        engine = params.get("engine", "google")
        query = params.get("query", "")
        if not query:
            print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query Unclear]")
            print(f'\n[JARVIS] "I could not identify the search query, Sir. Please say: \'Search {engine.capitalize()} for [your query]\'."\n')
            return True, f"search_{engine}"

        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query: \"{query}\"]")
        browser.search_web(query, engine)
        return True, None

    # 6. Typing Intent
    if intent == "TYPE_TEXT":
        content = params.get("content", "")
        press_enter = params.get("press_enter", False)
        if not content:
            print("[Intent: TYPE_TEXT | Content Unclear]")
            print("[JARVIS] \"Please state what text you would like me to type, Sir.\"")
            return True, None

        print(f"[Intent: TYPE_TEXT | Text: \"{content}\" | Press Enter: {press_enter}]")
        keyboard.type_text(content, press_enter)
        return True, None

    # 7. Browser Navigation Actions
    if intent == "BROWSER_ACTION":
        action = params.get("action")
        print(f"[Intent: BROWSER_ACTION | Action: {action}]")
        keyboard.send_browser_shortcut(action)
        return True, None

    # 8. Desktop Core Launch Actions
    if intent == "DESKTOP_ACTION":
        action = params.get("action")
        print(f"[Intent: DESKTOP_ACTION | Action: {action}]")
        action_map = {
            "open_firefox": desktop.open_firefox,
            "open_firefox_tab": browser.open_firefox_tab,
            "open_firefox_window": browser.open_firefox_window,
            "open_terminal": desktop.open_terminal,
            "open_downloads": desktop.open_downloads,
            "open_youtube": desktop.open_youtube,
        }
        fn = action_map.get(action)
        if fn:
            try:
                fn()
            except Exception as e:
                print(f"[JARVIS Error] Failed to execute action '{action}': {e}")
        return True, None

    # 9. Low-confidence / Unclear speech handling
    if intent == "UNCLEAR_SPEECH":
        print("[Intent: UNCLEAR_SPEECH]")
        unclear_msg = "I beg your pardon, Sir. Could you please repeat that?"
        print(f'\n[JARVIS] "{unclear_msg}"\n')
        from interfaces.speech import speak
        speak(unclear_msg)
        return True, None

    # 9.5 Local Time and Date Fast-Path (No Ollama / No Web Search)
    if intent == "TIME_DATE_QUERY":
        qtype = params.get("type", "time")
        loc = params.get("location")
        loc_str = f" | Location: {loc}" if loc else ""
        print(f"[Intent: TIME_DATE_QUERY | Type: {qtype.capitalize()}{loc_str}]")
        from actions import clock
        from interfaces.speech import speak

        if qtype == "date":
            ok, answer, pending = clock.get_date_answer(loc)
        elif qtype == "day":
            ok, answer, pending = clock.get_day_answer(loc)
        else:
            ok, answer, pending = clock.get_time_answer(loc)

        if ok:
            print(f'\n[JARVIS]: "{answer}"\n')
            speak(answer)
            context.clear_pending()
            return True, None
        else:
            print(f'\n[JARVIS] "{answer}"\n')
            speak(answer)
            if pending:
                context.set_pending(pending, {"original_query": params})
                return True, pending
            return True, None

    # 10. Real-Time Web Search & Grounded Information Retrieval (Stage 5)
    if intent == "CURRENT_INFO_QUERY":
        query = params.get("query", text)
        print(f"[Intent: CURRENT_INFO_QUERY | Query: \"{query}\"]")
        print("[JARVIS] Searching the web for current information...")

        from intelligence.web_search import handle_current_info_query

        success, answer, results = handle_current_info_query(query)

        if success and answer:
            print(f"\n[JARVIS]: \"{answer}\"\n")
            if results:
                print("Sources:")
                for idx, r in enumerate(results, 1):
                    source_str = f" [{r.source}]" if r.source else ""
                    date_str = f" ({r.date})" if r.date else ""
                    print(f"  {idx}.{source_str} {r.title}{date_str}")
                    print(f"     {r.url}")
                print()
        else:
            print(f"\n[JARVIS Error] {answer}\n")
        return True, None

    # 11. Ollama Fallback with Automatic Real-Time Web Search Bridge & User Memory
    if intent == "OLLAMA_QUERY":
        prompt = params.get("prompt", text)
        extract_and_store_user_facts(prompt or text)
        from intelligence.ollama_client import is_knowledge_gap
        answer = ask_ollama(prompt, print_output=False)
        if answer and not is_knowledge_gap(answer):
            print(f"\n[JARVIS]: \"{answer}\"\n")
            return True, None

        # CRITICAL: Prevent personal or memory queries from leaking to web search!
        from intelligence.memory_extractor import is_personal_memory_query
        if is_personal_memory_query(prompt):
            if answer:
                print(f"\n[JARVIS]: \"{answer}\"\n")
            else:
                print("\n[JARVIS] I don't recall that information yet, Sir.\n")
            return True, None

        # If Ollama has a knowledge gap or is unavailable, bridge to real-time web search
        print("[JARVIS] Local intelligence lacks verified data on this entity. Consulting real-time web search...")
        from intelligence.web_search import handle_current_info_query
        success, web_answer, results = handle_current_info_query(prompt)
        if success and web_answer:
            print(f"\n[JARVIS]: \"{web_answer}\"\n")
            if results:
                print("Sources:")
                for idx, r in enumerate(results, 1):
                    source_str = f" [{r.source}]" if r.source else ""
                    date_str = f" ({r.date})" if r.date else ""
                    print(f"  {idx}.{source_str} {r.title}{date_str}")
                    print(f"     {r.url}")
                print()
        else:
            if answer:
                print(f"\n[JARVIS]: \"{answer}\"\n")
            else:
                print("\n[JARVIS] I could not find information locally or retrieve current web results, Sir.\n")
        return True, None

    return True, None
