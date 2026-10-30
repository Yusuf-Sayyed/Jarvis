import os
import shutil
import subprocess
import time
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


PYTHON_TUTORING_CURRICULUM = {
    1: {
        "question": "What is the first thing you need to do when you start a Python interpreter or editor, such as IDLE or PyCharm?",
        "hint": "Consider whether you are creating a new script file with a specific extension, or typing directly into an interactive shell, Sir.",
        "keywords": ["file", "extension", ".py", "script", "create", "type", "command", "open"],
        "correct_eval": "Partially correct, Sir. In an editor like PyCharm or IDLE, you create a new file with a .py extension, or in an interactive interpreter you can type commands immediately.",
        "general_eval": "In an editor, you first create a new file with a .py extension, or in the interactive prompt you can run commands directly, Sir.",
        "concept_explanation": "In Python, a script is saved in a text file ending with the dot py extension, which tells the operating system and Python interpreter how to run it, Sir.",
    },
    2: {
        "question": "What built-in function or keyword is used to display text on the screen in Python?",
        "hint": "It starts with the letter 'p' and takes arguments inside parentheses, Sir.",
        "keywords": ["print"],
        "correct_eval": "Correct, Sir. The print() function outputs text directly to standard output.",
        "general_eval": "In Python, the built-in print() function is used to output text to the screen, Sir.",
        "concept_explanation": "The print() function takes text or variables inside parentheses and displays them on the console, Sir.",
    },
    3: {
        "question": "How do you store a value, such as a number or word, so you can reuse it later in your Python program?",
        "hint": "It is a named container known as a variable, created with an equals sign, Sir.",
        "keywords": ["variable", "assign", "var"],
        "correct_eval": "Spot on, Sir. You assign the value to a named variable using the equals sign.",
        "general_eval": "In Python, you store values in named variables using the assignment operator, for example x = 10, Sir.",
        "concept_explanation": "Variables are named references in computer memory that hold data you can update and reference throughout your program, Sir.",
    },
    4: {
        "question": "What symbol does Python use to indicate comments that the interpreter should ignore?",
        "hint": "It is the hash or pound symbol on your keyboard, Sir.",
        "keywords": ["#", "hash", "pound"],
        "correct_eval": "Correct, Sir. The hash symbol # is used for single-line comments.",
        "general_eval": "The hash symbol, also known as the pound sign, indicates a comment in Python, Sir.",
        "concept_explanation": "Comments explain code to human readers; Python completely ignores anything on a line following the hash symbol, Sir.",
    },
    5: {
        "question": "What built-in data type would you use to store an ordered collection of multiple items in square brackets?",
        "hint": "It is a sequence type called a list, written with square brackets, Sir.",
        "keywords": ["list", "array"],
        "correct_eval": "Correct, Sir. A list holds ordered, mutable items enclosed in square brackets.",
        "general_eval": "In Python, an ordered collection in square brackets is called a list, Sir.",
        "concept_explanation": "Lists let you store items in sequence, like my_list = [1, 2, 3], and modify them as needed, Sir.",
    },
}


def route_command(text: str, pending_action: str | None = None) -> tuple[bool, str | None]:
    """
    Detects the intent of spoken text and routes it to the proper action.

    Returns:
        (should_continue: bool, new_pending_action: str | None)
    """
    context = get_conversation_context()
    from interfaces.speech import speak
    from core.diagnostics import log_timing

    t0_intent = time.perf_counter()
    intent, params = detect_intent(text, pending_action)
    log_timing("Intent resolution", time.perf_counter() - t0_intent, f"intent={intent}")

    # 1. Confirmation Responses (Yes / No)
    if intent == "CONFIRM_ACTION":
        action = params.get("action")
        payload = params.get("payload", {})
        print(f"[Intent: CONFIRM_ACTION | Action: {action}]")
        if action == "close_tab":
            keyboard.close_browser_tab()
        elif action == "youtube_play":
            q = payload.get("query") or context.get_recent_youtube_query()
            if q:
                res = browser.play_youtube_video(q)
                msg = res.get("message", f"Playing '{q}' on YouTube, Sir.")
                stage = res.get("stage", "video_opened")
                print(f"[JARVIS | Playback Stage: {stage}] {msg}")
                from interfaces.speech import speak
                speak(msg)
                context.update_interaction(action="youtube_play", app="firefox", target_name=q)
            else:
                prompt_msg = "What video or song would you like me to play on YouTube, Sir?"
                print(f'\n[JARVIS] "{prompt_msg}"\n')
                from interfaces.speech import speak
                speak(prompt_msg)
                context.set_pending("youtube_play")
                return True, "youtube_play"
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
            save_msg = f"Workflow '{w_name}' saved successfully, Sir. You can run it anytime by saying {trigger_str}."
            print(f'\n[JARVIS] "{save_msg}"\n')
            speak(save_msg)
        elif action == "confirm_delete_workflow":
            memory = get_memory_store()
            w_id = payload.get("workflow_id")
            w_name = payload.get("name") or w_id
            ok = memory.delete_workflow(w_id)
            if ok:
                del_msg = f"Workflow '{w_name}' has been deleted, Sir."
                print(f'\n[JARVIS] "{del_msg}"\n')
                speak(del_msg)
            else:
                err_msg = f"Could not delete workflow '{w_name}', Sir."
                print(f'\n[JARVIS Error] {err_msg}\n')
                speak(err_msg)
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

        print(f"[Intent] MEDIA_CONTROL: {action}")

        if action == "pause":
            ok, msg, candidates = media.pause_playback(target)
        elif action in ("resume", "play"):
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
            clarify_text = f"I found multiple active media sessions ({', '.join(candidates)}). Which one would you like me to {action}, Sir?"
            print(f'\n[JARVIS] "{clarify_text}"\n')
            context.set_pending("clarify_media_player", {"candidates": candidates, "action": action, "params": params})
            speak(clarify_text)
            return True, "clarify_media_player"

        if ok:
            console_msg = "Stopped playback." if action == "stop" else (
                "Paused playback." if action == "pause" else (
                    "Resumed playback." if action in ("resume", "play") else msg
                )
            )
            print(f"[JARVIS] {console_msg}")
            speak(msg)
        else:
            if "no active media playback session" in msg.lower() or "no compatible" in msg.lower():
                fail_msg = "Couldn't control playback. No compatible media player was detected."
            else:
                fail_msg = msg
                if not fail_msg.startswith("Couldn't control playback"):
                    fail_msg = f"Couldn't control playback. {fail_msg}"
            print(f"[JARVIS] {fail_msg}")
            speak(fail_msg)
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
                msg = "You have no saved workflows, Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
            else:
                print(f"\n[JARVIS] \"You have {len(workflows)} saved workflow(s), Sir:\"")
                names = []
                for idx, wf in enumerate(workflows, 1):
                    status = "enabled" if wf.get("is_enabled", 1) else "disabled"
                    name = wf.get("name") or wf.get("workflow_id")
                    triggers = ", ".join(f"'{t}'" for t in wf.get("trigger_phrases", []))
                    step_count = len(wf.get("steps", []))
                    print(f"  {idx}. {name} [{status}] - {step_count} step(s)")
                    print(f"     Triggers: {triggers}")
                    names.append(f"{name}")
                print()
                speak(f"You have {len(workflows)} saved workflow(s), Sir: {', '.join(names)}.")
            return True, None

        # Workflow Help & Teaching Instructions
        if smart_action == "workflow_help":
            help_msg = (
                "You can manage workflows entirely by voice, Sir. "
                "To teach me a workflow, say: 'When I say [trigger phrase], [action 1] and [action 2]'. "
                "For example: 'When I say open your folder in editor, open your folder in editor'. "
                "To run a saved workflow, simply speak its name, or say 'run the [name] workflow'. "
                "You can also say 'list workflows', 'rename workflow', or 'delete workflow'."
            )
            print(f'\n[JARVIS] "{help_msg}"\n')
            speak(help_msg)
            return True, None

        # Workflow Management: Inspect
        if smart_action == "inspect_workflow":
            target = smart_params.get("workflow_name", "")
            wf = memory.find_workflow(target)
            if not wf:
                msg = f"I could not find a workflow matching '{target}', Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
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
                speak(f"Workflow {name} is {status} with {len(wf.get('steps', []))} steps.")
            return True, None

        # Workflow Management: Enable / Disable
        if smart_action == "toggle_workflow":
            target = smart_params.get("workflow_name", "")
            enabled = smart_params.get("enabled", True)
            wf = memory.find_workflow(target)
            if wf:
                ok = memory.set_workflow_status(wf["workflow_id"], enabled)
                state_str = "enabled" if enabled else "disabled"
                msg = f"Workflow '{wf.get('name')}' has been {state_str}, Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
            else:
                msg = f"I could not find a workflow matching '{target}', Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
            return True, None

        # Workflow Management: Delete (Direct Deletion when target is specified)
        if smart_action == "delete_workflow":
            target = smart_params.get("workflow_name", "")
            if not target:
                prompt_msg = "Which workflow would you like me to delete, Sir?"
                print(f'\n[JARVIS] "{prompt_msg}"\n')
                speak(prompt_msg)
                context.set_pending("delete_workflow_prompt")
                return True, "delete_workflow_prompt"

            wf = memory.find_workflow(target)
            if not wf:
                msg = f"I could not find a workflow matching '{target}', Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
                return True, None

            ok = memory.delete_workflow(wf["workflow_id"])
            if ok:
                context.clear_pending()
                msg = f"Workflow '{wf.get('name')}' has been deleted, Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
            else:
                msg = f"Could not delete workflow '{wf.get('name')}'.\n"
                print(f'\n[JARVIS Error] {msg}')
                speak(f"Could not delete workflow '{wf.get('name')}', Sir.")
            return True, None

        # Workflow Management: Rename
        if smart_action == "rename_workflow":
            old_name = smart_params.get("old_name", "")
            new_name = smart_params.get("new_name", "")
            ok = memory.update_workflow(old_name, name=new_name)
            if ok:
                msg = f"Workflow has been renamed from '{old_name}' to '{new_name}', Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
            else:
                msg = f"I could not find a workflow named '{old_name}', Sir."
                print(f'\n[JARVIS] "{msg}"\n')
                speak(msg)
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
                res_msg = f"Workflow completed successfully: {msg}"
                print(f"[JARVIS] {res_msg}")
                speak(res_msg)
            else:
                fail_msg = f"Workflow failed: {msg}" if not msg.startswith("Workflow") else msg
                print(f"[JARVIS Error] {fail_msg}")
                speak(fail_msg)
            return True, None

        if smart_action == "workflow_not_found":
            target = smart_params.get("target", "")
            msg = f"I could not find a workflow named '{target}', Sir."
            print(f'\n[JARVIS] "{msg}"\n')
            speak(msg)
            return True, None

        if smart_action == "workflow_ambiguous":
            target = smart_params.get("target", "")
            candidates = smart_params.get("candidates", [])
            names = [w.get("name") or w.get("workflow_id") for w in candidates]
            names_str = ", ".join(f"'{n}'" for n in names)
            msg = f"I found multiple workflows matching '{target}': {names_str}. Which one would you like me to run, Sir?"
            print(f'\n[JARVIS] "{msg}"\n')
            speak(msg)
            context.set_pending("clarify_run_workflow", {"candidates": candidates, "target": target})
            return True, "clarify_run_workflow"

        if smart_action == "workflow_disabled":
            name = smart_params.get("name", "")
            msg = f"Workflow '{name}' is currently disabled, Sir. You can enable it by saying 'enable workflow {name}'."
            print(f'\n[JARVIS] "{msg}"\n')
            speak(msg)
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

        if smart_action == "launch_app":
            app_name = smart_params.get("app") or smart_params.get("project")
            app_info = app_registry.resolve_application(app_name) if app_name else None
            if app_info and app_info.exec_path:
                try:
                    print(f"[JARVIS] Opening {app_info.name}...")
                    subprocess.Popen([app_info.exec_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"[JARVIS] {app_info.name} launched successfully.")
                    context.update_interaction(action="launch_app", app=app_info.name.lower(), app_bin=app_info.exec_path)
                except Exception as e:
                    print(f"[JARVIS Error] Failed to launch {app_info.name}: {e}")
            else:
                print(f"\n[JARVIS Error] Could not find application '{app_name}' on this system, Sir.\n")
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
        from core.shutdown import speak_goodbye
        speak_goodbye()
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
        vol = params.get("volume")
        vol_prefix = ""
        if vol is not None:
            ok, vol_msg = audio.set_volume(vol)
            if ok:
                vol_prefix = f"Volume set to {vol}%. "
            else:
                vol_prefix = f"Volume warning: {vol_msg}. "
        print("[Intent: YOUTUBE_PLAY | Awaiting Query]")
        prompt_msg = f"{vol_prefix}What video or song would you like me to play on YouTube, Sir?"
        print(f'\n[JARVIS] "{prompt_msg}"\n')
        from interfaces.speech import speak
        speak(prompt_msg)
        return True, "youtube_play"

    if intent == "YOUTUBE_PLAY":
        query = params.get("query", "")
        if not query:
            query = context.get_recent_youtube_query() or ""

        vol = params.get("volume")
        vol_prefix = ""
        if vol is not None:
            ok, vol_msg = audio.set_volume(vol)
            if ok:
                vol_prefix = f"Volume set to {vol}%. "
            else:
                vol_prefix = f"Volume warning: {vol_msg}. "

        if not query:
            print("[Intent: YOUTUBE_PLAY | Query Unclear]")
            prompt_msg = f"{vol_prefix}What video or song would you like me to play on YouTube, Sir?"
            print(f'\n[JARVIS] "{prompt_msg}"\n')
            from interfaces.speech import speak
            speak(prompt_msg)
            return True, "youtube_play"

        print(f"[Intent: YOUTUBE_PLAY | Query: \"{query}\"]")
        res = browser.play_youtube_video(query)
        stage = res.get("stage", "video_opened") if isinstance(res, dict) else "video_opened"
        base_msg = res.get("message", f"Opened '{query}' on YouTube, Sir.") if isinstance(res, dict) else f"Opened '{query}' on YouTube, Sir."
        final_msg = f"{vol_prefix}{base_msg}".strip()

        print(f"[JARVIS | Playback Stage: {stage}] {final_msg}")
        from interfaces.speech import speak
        speak(final_msg)
        context.update_interaction(action="youtube_play", app="firefox", target_name=query)
        context.set_pending_youtube(query=query, url=res.get("url") if isinstance(res, dict) else None)
        return True, None

    if intent == "YOUTUBE_FIRST_RESULT":
        vol = params.get("volume")
        vol_prefix = ""
        if vol is not None:
            ok, vol_msg = audio.set_volume(vol)
            if ok:
                vol_prefix = f"Volume set to {vol}%. "
            else:
                vol_prefix = f"Volume warning: {vol_msg}. "
        print("[Intent: YOUTUBE_FIRST_RESULT]")
        res = browser.open_first_youtube_result()
        stage = res.get("stage", "video_opened") if isinstance(res, dict) else "video_opened"
        base_msg = res.get("message", "Opened first result on YouTube, Sir.") if isinstance(res, dict) else "Opened first result on YouTube, Sir."
        final_msg = f"{vol_prefix}{base_msg}".strip()
        print(f"[JARVIS | Stage: {stage}] {final_msg}")
        from interfaces.speech import speak
        speak(final_msg)
        return True, None

    # 5. Web Search Intent (Search results page)
    if intent == "SEARCH_PROMPT":
        engine = params.get("engine", "google")
        vol = params.get("volume")
        vol_prefix = ""
        if vol is not None:
            ok, vol_msg = audio.set_volume(vol)
            if ok:
                vol_prefix = f"Volume set to {vol}%. "
            else:
                vol_prefix = f"Volume warning: {vol_msg}. "
        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Awaiting Query]")
        prompt_msg = f"{vol_prefix}What would you like me to search for on {engine.capitalize()}, Sir?"
        print(f'\n[JARVIS] "{prompt_msg}"\n')
        from interfaces.speech import speak
        speak(prompt_msg)
        return True, f"search_{engine}"

    if intent == "BROWSER_SEARCH":
        engine = params.get("engine", "google")
        query = params.get("query", "")
        vol = params.get("volume")
        vol_prefix = ""
        if vol is not None:
            ok, vol_msg = audio.set_volume(vol)
            if ok:
                vol_prefix = f"Volume set to {vol}%. "
            else:
                vol_prefix = f"Volume warning: {vol_msg}. "

        if not query:
            print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query Unclear]")
            prompt_msg = f"{vol_prefix}What would you like me to search for on {engine.capitalize()}, Sir?"
            print(f'\n[JARVIS] "{prompt_msg}"\n')
            from interfaces.speech import speak
            speak(prompt_msg)
            return True, f"search_{engine}"

        print(f"[Intent: BROWSER_SEARCH | Engine: {engine.capitalize()} | Query: \"{query}\"]")
        res = browser.search_web(query, engine)
        stage = res.get("stage", "search_page_opened") if isinstance(res, dict) else "search_page_opened"
        final_msg = f"{vol_prefix}Searching {engine.capitalize()} for '{query}', Sir."
        print(f"[JARVIS | Stage: {stage}] {final_msg}")
        from interfaces.speech import speak
        speak(final_msg)
        context.update_interaction(action="search_web", app="firefox", target_name=query)
        if engine == "youtube":
            context.set_pending_youtube(query=query)
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
            "open_browser": getattr(desktop, "open_browser", desktop.open_firefox),
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
        elif action == "open_folder":
            t0_act = time.perf_counter()
            folder_target = params.get("path") or params.get("folder", "")
            desktop.open_folder(folder_target)
            log_timing("Action execution", time.perf_counter() - t0_act, f"open_folder='{folder_target}'")
        elif action == "open_folder_not_found":
            folder_name = params.get("folder", "")
            msg = f"I could not locate the folder '{folder_name}' on your system, Sir."
            print(f'\n[JARVIS] "{msg}"\n')
            speak(msg)
        elif action == "launch_app":
            t0_act = time.perf_counter()
            exec_path = params.get("exec_path")
            app_name = params.get("app", "Application")
            if exec_path:
                try:
                    print(f"[JARVIS] Opening {app_name}...")
                    subprocess.Popen([exec_path], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    print(f"[JARVIS] {app_name} launched successfully.")
                    log_timing("Action execution", time.perf_counter() - t0_act, f"launch_app='{app_name}'")
                except Exception as e:
                    print(f"[JARVIS Error] Failed to launch {app_name}: {e}")
            else:
                print(f"[JARVIS Error] Could not determine executable for {app_name}.")
        return True, None

    # 8.9 Ambiguous Action Clarification Handling
    if intent == "CLARIFY_ACTION":
        target_action = params.get("action")
        question = params.get("question", "Could you please specify the details, Sir?")
        print(f"[Intent: CLARIFY_ACTION | Action: {target_action}]")
        print(f'\n[JARVIS] "{question}"\n')
        from interfaces.speech import speak
        speak(question)
        if target_action:
            context.set_pending(f"clarify_{target_action}", params)
            return True, f"clarify_{target_action}"
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
            from interfaces.speech import speak
            speak(answer)
            context.add_dialogue_turn(query, answer)
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

    # 10.5 Interactive Tutoring and Learning Lessons
    if intent == "START_TUTORING":
        topic = params.get("topic", "python")
        step_1 = PYTHON_TUTORING_CURRICULUM.get(1)
        q1 = step_1["question"]
        context.start_activity("tutoring", topic, initial_question=q1)
        response = f"Certainly, Sir. Let's begin with {topic.capitalize()} basics. {q1}"
        print(f"\n[JARVIS]: \"{response}\"\n")
        from interfaces.speech import speak
        speak(response)
        context.add_dialogue_turn(text, response)
        return True, None

    if intent == "TUTORING_CONTROL":
        action = params.get("action")
        act = context.get_active_activity()
        from interfaces.speech import speak

        if action == "stop_lesson":
            context.stop_activity()
            response = "Lesson paused, Sir. Let me know when you would like to resume."
            print(f"\n[JARVIS]: \"{response}\"\n")
            speak(response)
            context.add_dialogue_turn(text, response)
            return True, None

        if not act:
            response = "We do not have an active lesson running, Sir."
            print(f"\n[JARVIS]: \"{response}\"\n")
            speak(response)
            return True, None

        step = act.lesson_step
        curr_step_data = PYTHON_TUTORING_CURRICULUM.get(step, PYTHON_TUTORING_CURRICULUM[1])

        if action == "give_hint":
            context.increment_hint()
            hint_text = curr_step_data.get("hint", "Think about standard beginner Python conventions, Sir.")
            response = f"{hint_text} The question is: {act.current_question}"
            print(f"\n[JARVIS]: \"{response}\"\n")
            speak(response)
            context.add_dialogue_turn(text, response)
            return True, None

        if action == "dont_know":
            next_step = step + 1
            next_data = PYTHON_TUTORING_CURRICULUM.get(next_step)
            expl = curr_step_data.get("general_eval", "The answer is part of basic Python syntax, Sir.")
            if next_data:
                next_q = next_data["question"]
                context.update_activity_question(next_q)
                response = f"No problem, Sir. {expl} Next question: {next_q}"
            else:
                context.stop_activity()
                response = f"No problem, Sir. {expl} That completes our introductory Python lesson for today!"
            print(f"\n[JARVIS]: \"{response}\"\n")
            speak(response)
            context.add_dialogue_turn(text, response)
            return True, None

        if action == "next_question":
            next_step = step + 1
            next_data = PYTHON_TUTORING_CURRICULUM.get(next_step)
            if next_data:
                next_q = next_data["question"]
                context.update_activity_question(next_q)
                response = f"Understood, Sir. Next question: {next_q}"
            else:
                context.stop_activity()
                response = "That brings us to the end of our introductory lesson, Sir. Excellent effort!"
            print(f"\n[JARVIS]: \"{response}\"\n")
            speak(response)
            context.add_dialogue_turn(text, response)
            return True, None

        if action == "explain":
            concept = curr_step_data.get("concept_explanation", "This is a fundamental concept in Python programming, Sir.")
            response = f"{concept} The active question is: {act.current_question}"
            print(f"\n[JARVIS]: \"{response}\"\n")
            speak(response)
            context.add_dialogue_turn(text, response)
            return True, None

    if intent == "TUTORING_ANSWER":
        answer = params.get("answer", text)
        question = params.get("question", "")
        topic = params.get("topic", "python")
        step = params.get("step", 1)
        from interfaces.speech import speak

        act = context.get_active_activity()
        if not act:
            return route_command(text)

        curr_data = PYTHON_TUTORING_CURRICULUM.get(step, PYTHON_TUTORING_CURRICULUM.get(1))
        next_step = step + 1
        next_data = PYTHON_TUTORING_CURRICULUM.get(next_step)

        # Local deterministic evaluation
        ans_lower = answer.lower()
        is_correct = any(kw in ans_lower for kw in curr_data.get("keywords", []))
        feedback = curr_data.get("correct_eval" if is_correct else "general_eval", "")

        from intelligence.ollama_client import ask_tutoring_evaluation
        llm_eval = ask_tutoring_evaluation(topic, question, answer, step=step, history=act.history)

        if llm_eval:
            final_response = llm_eval
            if next_data:
                context.update_activity_question(next_data["question"])
            context.record_activity_turn(question, answer, llm_eval)
        else:
            if next_data:
                next_q = next_data["question"]
                context.update_activity_question(next_q)
                final_response = f"{feedback} Next question: {next_q}"
            else:
                context.stop_activity()
                final_response = f"{feedback} That concludes our initial Python basics lesson, Sir. Well done!"
            context.record_activity_turn(question, answer, feedback)

        print(f"\n[JARVIS]: \"{final_response}\"\n")
        speak(final_response)
        context.add_dialogue_turn(text, final_response)
        return True, None

    if intent == "UNSUPPORTED_ACTION":
        message = params.get("message", "I do not have a tool to perform that action yet, Sir.")
        print(f"\n[JARVIS]: \"{message}\"\n")
        from interfaces.speech import speak
        speak(message)
        context.add_dialogue_turn(text, message)
        return True, None

    # 11. Ollama Fallback with Automatic Real-Time Web Search Bridge & User Memory
    if intent == "OLLAMA_QUERY":
        prompt = params.get("prompt", text)
        extract_and_store_user_facts(prompt or text)
        from intelligence.ollama_client import is_knowledge_gap
        from interfaces.speech import clean_text_for_speech, speak, wait_for_speech_completion

        # Enforce summary by default, full detail only when explicitly requested
        is_detail_requested = any(phrase in (prompt or text).lower() for phrase in (
            "in detail", "explain in detail", "give me more details", "give more details",
            "detailed explanation", "elaborate", "thoroughly", "in depth", "detailed"
        ))
        if is_detail_requested:
            detail_guidance = ["Detailed response mode: The user explicitly requested details. Provide an informative, comprehensive explanation (3 to 5 sentences)."]
        else:
            detail_guidance = ["Summary mode: Spoken voice interface. Keep your answer small and like a brief summary (strictly 1 to 2 short sentences)."]

        streamed_sentences = []

        def handle_streamed_sentence(sentence: str):
            clean = clean_text_for_speech(sentence)
            if clean:
                streamed_sentences.append(clean)
                speak(clean, block=False)

        answer = ask_ollama(
            prompt,
            print_output=False,
            additional_context=detail_guidance,
            on_sentence=handle_streamed_sentence,
        )
        if answer and not is_knowledge_gap(answer):
            print(f"\n[JARVIS]: \"{answer}\"\n")
            if not streamed_sentences:
                speak(answer)
            else:
                wait_for_speech_completion()
            context.add_dialogue_turn(prompt, answer)
            return True, None

        # CRITICAL: Prevent personal or memory queries from leaking to web search!
        from intelligence.memory_extractor import is_personal_memory_query
        if is_personal_memory_query(prompt):
            if answer:
                print(f"\n[JARVIS]: \"{answer}\"\n")
                speak(answer)
                context.add_dialogue_turn(prompt, answer)
            else:
                nomem = "I don't recall that information yet, Sir."
                print(f"\n[JARVIS] {nomem}\n")
                speak(nomem)
                context.add_dialogue_turn(prompt, nomem)
            return True, None

        # If Ollama has a knowledge gap or is unavailable, bridge to real-time web search
        print("[JARVIS] Local intelligence lacks verified data on this entity. Consulting real-time web search...")
        from intelligence.web_search import handle_current_info_query
        success, web_answer, results = handle_current_info_query(prompt)
        if success and web_answer:
            print(f"\n[JARVIS]: \"{web_answer}\"\n")
            speak(web_answer)
            context.add_dialogue_turn(prompt, web_answer)
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
                speak(answer)
                context.add_dialogue_turn(prompt, answer)
            else:
                gap_msg = "I could not find information locally or retrieve current web results, Sir."
                print(f"\n[JARVIS] {gap_msg}\n")
                speak(gap_msg)
        return True, None

    return True, None
