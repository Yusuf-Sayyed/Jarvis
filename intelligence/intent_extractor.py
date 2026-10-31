"""
Natural-language intent and parameter extraction for JARVIS.
Combines sub-millisecond deterministic entity matching, SQLite fast-path cache,
desktop controls (volume, brightness, screenshot, window management),
reusable multi-step workflows, and structured local Ollama JSON fallback.
"""

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any, Optional

from core.config import OLLAMA_API_URL, OLLAMA_MODEL
from core.context import get_conversation_context
from core.memory import get_memory_store

CONVERSATIONAL_PREFIXES = (
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*,?\s*)?"
    r"(?:"
    r"can\s+you(?:\s+please)?\s+|"
    r"could\s+you(?:\s+please)?\s+|"
    r"would\s+you(?:\s+please)?\s+|"
    r"will\s+you(?:\s+please)?\s+|"
    r"please\s+|"
    r"i\s+want\s+you\s+to\s+|"
    r"can\s+we\s+|"
    r"just\s+|"
    r"is\s+it\s+possible(?:\s+for\s+you)?\s+to\s+|"
    r"would\s+it\s+be\s+possible(?:\s+for\s+you)?\s+to\s+|"
    r"are\s+you\s+able\s+to\s+|"
    r"do\s+you\s+mind\s+"
    r")+"
)


def _clean_input(text: str) -> str:
    cleaned = text.lower().strip().rstrip(".?!,").strip()
    cleaned = re.sub(r"^(?:(?:hey|hi|hello|ok|okay)\s+)?jarvis\s*[,:]?\s*", "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(CONVERSATIONAL_PREFIXES, "", cleaned).strip()
    cleaned = re.sub(r"\b(?:lens\s*(?:5|five|fy|ify|i\s*fy|if\s*i)|lensi+fy)\b", "lensify", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\b(\w+)(?:[,\s!]+(?:\1\b))+", r"\1", cleaned, flags=re.IGNORECASE).strip()
    return cleaned.rstrip(".?!,").strip()


# Workflow chaining & teaching
RE_WORKFLOW_SPLIT = re.compile(
    r"\s*,\s*(?:and\s+)?then\s+|\s+(?:and\s+)?then\s+",
    re.IGNORECASE,
)
RE_STEP_SPLIT = re.compile(
    r"\s*,\s*(?:and\s+)?then\s+|\s+(?:and\s+)?then\s+|\s*,\s*(?:and\s+)?|\s+and\s+",
    re.IGNORECASE,
)
RE_TEACH_WORKFLOW = re.compile(
    r"^(?:when(?:ever)?\s+(?:i\s+say|i\s+tell\s+you\s+to|i\s+ask\s+you\s+to)|if\s+i\s+say)\s+"
    r"['\"]?(.+?)['\"]?\s*"
    r"(?:,\s*(?:then\s+)?|\s+(?:then\s+|,?\s*then\s+)|\s+(?=(?:open|launch|start|set|turn|take|mute|unmute)\b))"
    r"(.+)$",
    re.IGNORECASE,
)

# Workflow management commands
RE_LIST_WORKFLOWS = re.compile(
    r"^(?:list\s+(?:all\s+)?(?:my\s+|saved\s+)?workflows|show\s+(?:all\s+)?(?:my\s+|saved\s+)?workflows|what\s+workflows\s+(?:do\s+you\s+know|are\s+saved))$",
    re.IGNORECASE,
)
RE_INSPECT_WORKFLOW = re.compile(
    r"^(?:inspect|view|describe|details\s+of)\s+(?:the\s+)?workflow\s*[,:]?\s*(?:named\s+|called\s+)?['\"]?(.+?)['\"]?$|"
    r"^(?:show|get)\s+(?:the\s+)?workflow\s*[,:]?\s*(?:named\s+|called\s+)?['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)
RE_ENABLE_WORKFLOW = re.compile(
    r"^(?:enable|turn\s+on|activate)\s+(?:the\s+)?workflow\s*[,:]?\s*(?:named\s+|called\s+)?['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)
RE_DISABLE_WORKFLOW = re.compile(
    r"^(?:disable|turn\s+off|deactivate)\s+(?:the\s+)?workflow\s*[,:]?\s*(?:named\s+|called\s+)?['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)
RE_DELETE_WORKFLOW = re.compile(
    r"^(?:delete|remove)\s+(?:the\s+)?workflow(?:\s*[,:]?\s*(?:and\s+|&\s+)?(?:named\s+|called\s+)?['\"]?(.+?)['\"]?)?$|"
    r"^(?:delete|remove)\s+(?:the\s+)?['\"]?(.+?)['\"]?\s+workflow$",
    re.IGNORECASE,
)
RE_RENAME_WORKFLOW = re.compile(
    r"^rename\s+(?:the\s+)?workflow\s*[,:]?\s*(?:named\s+|called\s+)?['\"]?(.+?)['\"]?\s+to\s+['\"]?(.+?)['\"]?$",
    re.IGNORECASE,
)
RE_HELP_WORKFLOW = re.compile(
    r"^(?:"
    r"how\s+(?:can\s+i|do\s+i|to)\s+(?:create|make|teach|add|set\s+up|save)\s+(?:a\s+|new\s+|my\s+)?workflows?|"
    r"how\s+(?:do\s+i|can\s+i|to)\s+teach\s+(?:you\s+)?(?:a\s+)?workflows?|"
    r"how\s+(?:can\s+i|do\s+i|to)\s+(?:run|execute|trigger|start|launch|call)\s+(?:a\s+|my\s+|the\s+|any\s+)?workflows?|"
    r"how\s+do\s+workflows\s+work|"
    r"how\s+do\s+i\s+work\s+with\s+workflows?|"
    r"how\s+(?:to\s+use|can\s+i\s+use|do\s+i\s+use)\s+workflows?|"
    r"workflow\s+help|"
    r"help\s+(?:with\s+)?workflows?|"
    r"explain\s+workflows?"
    r")$",
    re.IGNORECASE,
)


# Spoken Number Normalization for Numeric Voice Commands
NUM_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4,
    "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
    "ten": 10, "eleven": 11, "twelve": 12, "thirteen": 13,
    "fourteen": 14, "fifteen": 15, "sixteen": 16, "seventeen": 17,
    "eighteen": 18, "nineteen": 19, "twenty": 20, "thirty": 30,
    "forty": 40, "fifty": 50, "sixty": 60, "seventy": 70,
    "eighty": 80, "ninety": 90,
}


def parse_spoken_number(text: str) -> str:
    """
    Normalizes spoken number words (e.g. 'fifty', 'one hundred fifty', 'two hundred')
    into numeric digits ('50', '150', '200') within a transcript string.
    """
    tokens = text.lower().replace("-", " ").split()
    out = []
    i = 0
    n = len(tokens)

    while i < n:
        val = None
        consumed = 0

        # Pattern: [one|two|three...] hundred [and] [twenty [five]]
        if tokens[i] in NUM_WORDS and i + 1 < n and tokens[i + 1] == "hundred":
            mult = NUM_WORDS[tokens[i]]
            val = mult * 100
            consumed = 2
            next_idx = i + 2
            if next_idx < n and tokens[next_idx] == "and":
                next_idx += 1
                consumed += 1
            if next_idx < n and tokens[next_idx] in NUM_WORDS:
                sub_val = NUM_WORDS[tokens[next_idx]]
                consumed += 1
                next_idx += 1
                if (
                    next_idx < n
                    and tokens[next_idx] in NUM_WORDS
                    and tokens[next_idx - 1] in ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
                    and NUM_WORDS[tokens[next_idx]] < 10
                ):
                    sub_val += NUM_WORDS[tokens[next_idx]]
                    consumed += 1
                val += sub_val
        elif tokens[i] == "hundred":
            val = 100
            consumed = 1
            next_idx = i + 1
            if next_idx < n and tokens[next_idx] == "and":
                next_idx += 1
                consumed += 1
            if next_idx < n and tokens[next_idx] in NUM_WORDS:
                sub_val = NUM_WORDS[tokens[next_idx]]
                consumed += 1
                next_idx += 1
                if (
                    next_idx < n
                    and tokens[next_idx] in NUM_WORDS
                    and tokens[next_idx - 1] in ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety")
                    and NUM_WORDS[tokens[next_idx]] < 10
                ):
                    sub_val += NUM_WORDS[tokens[next_idx]]
                    consumed += 1
                val += sub_val
        elif tokens[i] in ("twenty", "thirty", "forty", "fifty", "sixty", "seventy", "eighty", "ninety"):
            val = NUM_WORDS[tokens[i]]
            consumed = 1
            if i + 1 < n and tokens[i + 1] in NUM_WORDS and NUM_WORDS[tokens[i + 1]] < 10:
                val += NUM_WORDS[tokens[i + 1]]
                consumed = 2
        elif tokens[i] in NUM_WORDS:
            val = NUM_WORDS[tokens[i]]
            consumed = 1

        if val is not None:
            out.append(str(val))
            i += consumed
        else:
            out.append(tokens[i])
            i += 1

    return " ".join(out)


VOL_NOUN = r"(?:volume|sound|audio)"
VOL_FILLERS = r"(?:the\s+|it\s+|well\s+|at\s+|a\s+|that\s+|this\s+|my\s+)*"


def extract_volume_intent(text: str) -> Optional[dict[str, Any]]:
    """
    Deterministic volume-intent parser.
    Recognizes natural variations such as:
      - 'Set volume to 100%.' / 'Set the volume to 100%.'
      - 'Set it volume to 100%.' / 'Set well volume to 100%.'
      - 'Increase volume to 100%.' (absolute target)
      - 'Turn the volume down.' / 'Turn volume up.'
      - 'Increase volume by 10%.' / 'Decrease volume by 15%.'
      - 'Set volume 200%.' (triggers validation clarification)
      - 'Volume to fifty percent.' (normalized spoken numbers)
      - 'Mute the volume.' / 'Unmute.'

    Returns:
        Structured dict with keys:
          - intent: 'set_volume' | 'increase_volume' | 'decrease_volume' | 'mute' | 'unmute'
          - action: 'volume_set' | 'volume_change' | 'mute_audio' | 'volume_limit_clarification' | 'volume_missing_number'
          - params: dict
          - mode: 'absolute' | 'relative' | None
          - value: int | None
          - requires_clarification: bool
          - clarification_reason: str | None
        or None if not a volume command.
    """
    cleaned = text.lower().strip().rstrip(".?!,").strip()
    cleaned = re.sub(CONVERSATIONAL_PREFIXES, "", cleaned, flags=re.IGNORECASE).strip()
    cleaned = re.sub(r"\b(?:percent|percentage)\b", "%", cleaned)
    cleaned = parse_spoken_number(cleaned)

    # Disqualify non-volume commands immediately
    if any(k in cleaned for k in ("brightness", "timer", "alarm", "screen", "search", "youtube", "tab")):
        return None

    # MUTE / UNMUTE (matches "mute", "mute, mute", "mute mute", "mute mute mute", "silence", "be quiet", "quiet", etc.)
    if re.match(rf"^(?:(?:unmute(?:[,!\s]+unmute)*)+)(?:\s+{VOL_FILLERS}(?:{VOL_NOUN}|it|this|audio))?$", cleaned):
        return {
            "intent": "unmute",
            "action": "mute_audio",
            "params": {"mute_state": False},
            "mode": None,
            "value": None,
            "requires_clarification": False,
            "clarification_reason": None,
        }

    if re.match(rf"^(?:(?:mute(?:[,!\s]+mute)*)+|silence|be\s+quiet|quiet)(?:\s+{VOL_FILLERS}(?:{VOL_NOUN}|it|this|audio))?$", cleaned):
        return {
            "intent": "mute",
            "action": "mute_audio",
            "params": {"mute_state": True},
            "mode": None,
            "value": None,
            "requires_clarification": False,
            "clarification_reason": None,
        }

    # Louder / Quieter standalone
    if re.match(r"^(?:make\s+it\s+)?louder$", cleaned) or cleaned in ("turn it up", "turn up"):
        return {
            "intent": "increase_volume",
            "action": "volume_change",
            "params": {"delta": 10},
            "mode": "relative",
            "value": 10,
            "requires_clarification": False,
            "clarification_reason": None,
        }

    if re.match(r"^(?:make\s+it\s+)?quieter$", cleaned) or cleaned in ("turn it down", "turn down"):
        return {
            "intent": "decrease_volume",
            "action": "volume_change",
            "params": {"delta": -10},
            "mode": "relative",
            "value": -10,
            "requires_clarification": False,
            "clarification_reason": None,
        }

    has_vol_keyword = bool(re.search(rf"\b{VOL_NOUN}\b", cleaned))
    if not has_vol_keyword:
        return None

    # Pattern 1: Absolute Target Setting
    # 1a. Explicit "to" or "at" before number (e.g. "increase volume to 100%", "set volume to 100%", "volume to 50%")
    m_abs = re.search(
        rf"(?:(?:set|turn|change|adjust|increase|raise|lower|decrease|put)?\s+{VOL_FILLERS}{VOL_NOUN}\s+(?:to\s+|at\s+)(\d{{1,3}})\s*%?|"
        rf"^{VOL_NOUN}\s+(?:to\s+|at\s+)(\d{{1,3}})\s*%?)",
        cleaned,
    )
    if m_abs:
        val_str = m_abs.group(1) or m_abs.group(2)
        val = int(val_str)
        if val > 150:
            return {
                "intent": "set_volume",
                "action": "volume_limit_clarification",
                "params": {"requested_percentage": val, "max_percentage": 150},
                "mode": "absolute",
                "value": val,
                "requires_clarification": True,
                "clarification_reason": "exceeds_max_volume",
            }
        return {
            "intent": "set_volume",
            "action": "volume_set",
            "params": {"percentage": max(0, val)},
            "mode": "absolute",
            "value": max(0, val),
            "requires_clarification": False,
            "clarification_reason": None,
        }

    # 1b. "set [fillers] volume (\d+)%?" (without "to/at", e.g. "set volume 200%", "set at volume 200%")
    m_set_direct = re.search(
        rf"^(?:set|turn|change|adjust)\s+{VOL_FILLERS}{VOL_NOUN}\s+(\d{{1,3}})\s*%?$",
        cleaned,
    )
    if m_set_direct:
        val = int(m_set_direct.group(1))
        if val > 150:
            return {
                "intent": "set_volume",
                "action": "volume_limit_clarification",
                "params": {"requested_percentage": val, "max_percentage": 150},
                "mode": "absolute",
                "value": val,
                "requires_clarification": True,
                "clarification_reason": "exceeds_max_volume",
            }
        return {
            "intent": "set_volume",
            "action": "volume_set",
            "params": {"percentage": max(0, val)},
            "mode": "absolute",
            "value": max(0, val),
            "requires_clarification": False,
            "clarification_reason": None,
        }

    # 1c. "volume (\d+)%?"
    m_vol_num = re.search(rf"^{VOL_NOUN}\s+(\d{{1,3}})\s*%?$", cleaned)
    if m_vol_num:
        val = int(m_vol_num.group(1))
        if val > 150:
            return {
                "intent": "set_volume",
                "action": "volume_limit_clarification",
                "params": {"requested_percentage": val, "max_percentage": 150},
                "mode": "absolute",
                "value": val,
                "requires_clarification": True,
                "clarification_reason": "exceeds_max_volume",
            }
        return {
            "intent": "set_volume",
            "action": "volume_set",
            "params": {"percentage": max(0, val)},
            "mode": "absolute",
            "value": max(0, val),
            "requires_clarification": False,
            "clarification_reason": None,
        }

    # Pattern 2: Relative Increase
    m_rel_up = re.search(
        rf"^(?:increase|raise|turn\s+up|boost)\s+{VOL_FILLERS}{VOL_NOUN}(?:\s+by\s+(\d{{1,3}})\s*%?)?|"
        rf"^turn\s+{VOL_FILLERS}{VOL_NOUN}\s+up(?:\s+by\s+(\d{{1,3}})\s*%?)?|"
        rf"^{VOL_NOUN}\s+up(?:\s+by\s+(\d{{1,3}})\s*%?)?",
        cleaned,
    )
    if m_rel_up:
        num_str = m_rel_up.group(1) or m_rel_up.group(2) or m_rel_up.group(3)
        delta = int(num_str) if num_str else 10
        return {
            "intent": "increase_volume",
            "action": "volume_change",
            "params": {"delta": delta},
            "mode": "relative",
            "value": delta,
            "requires_clarification": False,
            "clarification_reason": None,
        }

    # Pattern 3: Relative Decrease
    m_rel_down = re.search(
        rf"^(?:decrease|lower|reduce|turn\s+down)\s+{VOL_FILLERS}{VOL_NOUN}(?:\s+by\s+(\d{{1,3}})\s*%?)?|"
        rf"^turn\s+{VOL_FILLERS}{VOL_NOUN}\s+down(?:\s+by\s+(\d{{1,3}})\s*%?)?|"
        rf"^{VOL_NOUN}\s+down(?:\s+by\s+(\d{{1,3}})\s*%?)?",
        cleaned,
    )
    if m_rel_down:
        num_str = m_rel_down.group(1) or m_rel_down.group(2) or m_rel_down.group(3)
        delta = int(num_str) if num_str else 10
        return {
            "intent": "decrease_volume",
            "action": "volume_change",
            "params": {"delta": -delta},
            "mode": "relative",
            "value": -delta,
            "requires_clarification": False,
            "clarification_reason": None,
        }

    # Missing number detection: e.g. "set volume", "set the volume", "set it volume"
    if re.search(rf"^(?:set|turn|change|adjust)\s+{VOL_FILLERS}{VOL_NOUN}$", cleaned):
        return {
            "intent": "set_volume",
            "action": "volume_missing_number",
            "params": {},
            "mode": "absolute",
            "value": None,
            "requires_clarification": True,
            "clarification_reason": "missing_number",
        }

    return None

# Display / Brightness controls
RE_BRIGHTNESS_SET = re.compile(
    r"^(?:set|turn|change|adjust)?\s*(?:the\s+)?(?:screen\s+|display\s+)?brightness\s+(?:to\s+)?(\d{1,3})\s*(?:%|percent)?$",
    re.IGNORECASE,
)
RE_BRIGHTNESS_UP = re.compile(
    r"^(?:turn\s+(?:the\s+)?brightness\s+up|brightness\s+up|increase\s+(?:the\s+)?(?:screen\s+)?brightness|brighter|make\s+(?:the\s+)?screen\s+brighter)(?:\s+by\s+(\d{1,3})\s*(?:%|percent)?)?$",
    re.IGNORECASE,
)
RE_BRIGHTNESS_DOWN = re.compile(
    r"^(?:turn\s+(?:the\s+)?brightness\s+down|brightness\s+down|decrease\s+(?:the\s+)?(?:screen\s+)?brightness|lower\s+(?:the\s+)?(?:screen\s+)?brightness|dim\s+(?:the\s+)?(?:screen)?|dimmer)(?:\s+by\s+(\d{1,3})\s*(?:%|percent)?)?$",
    re.IGNORECASE,
)

# Screenshot controls
RE_SCREENSHOT = re.compile(
    r"^(?:take\s+(?:a\s+)?screenshot|capture\s+(?:the\s+)?screen|screenshot)$",
    re.IGNORECASE,
)
RE_SCREENSHOT_REGION = re.compile(
    r"^(?:take\s+(?:a\s+)?(?:region|area)\s+screenshot|screenshot\s+(?:region|area)|capture\s+(?:an?\s+)?(?:area|region))$",
    re.IGNORECASE,
)

# Window controls
RE_WINDOW_MINIMIZE = re.compile(
    r"^minimize(?:\s+(?:the|this|current)?\s*window)?$",
    re.IGNORECASE,
)
RE_WINDOW_MAXIMIZE = re.compile(
    r"^maximize(?:\s+(?:the|this|current)?\s*window)?$",
    re.IGNORECASE,
)
RE_SHOW_DESKTOP = re.compile(
    r"^(?:show\s+desktop|hide\s+(?:all\s+)?windows)$",
    re.IGNORECASE,
)
RE_SWITCH_WINDOW = re.compile(
    r"^(?:switch\s+(?:the\s+|to\s+next\s+)?window|next\s+window)$",
    re.IGNORECASE,
)

# Deterministic project & application patterns
RE_OPEN_PROJECT_IN_APP = re.compile(
    r"^(?:open|launch|start)\s+(?:my\s+|the\s+)?(.+?)(?:\s+(?:project|folder|directory|repo))*\s+in\s+(.+)$",
    re.IGNORECASE,
)
RE_OPEN_APP_IN_PROJECT = re.compile(
    r"^(?:open|launch|start)\s+(.+?)\s+in\s+(?:my\s+|the\s+)?(.+?)(?:\s+(?:folder|project|directory|repo))*$",
    re.IGNORECASE,
)
RE_OPEN_PROJECT_SOLO = re.compile(
    r"^(?:open|launch)\s+(?:my\s+|the\s+)?([a-zA-Z0-9_\-\.]+)\s+(?:project|folder|repo)$",
    re.IGNORECASE,
)
RE_TERMINAL_THERE = re.compile(
    r"^(?:open|launch|start)\s+(?:a\s+)?(?:new\s+)?(?:terminal|konsole|console)\s+(?:there|there\s+too|in\s+that\s+(?:project\s+)?folder|in\s+that\s+(?:project\s+)?directory|in\s+the\s+same\s+(?:project\s+)?directory|in\s+the\s+same\s+(?:project\s+)?folder)$",
    re.IGNORECASE,
)
RE_FOLDER_FOLLOWUP = re.compile(
    r"^(?:in|inside)\s+(?:my\s+|the\s+)?(.+?)(?:\s+(?:folder|directory|project))?$",
    re.IGNORECASE,
)
RE_OPEN_THAT_IN_APP = re.compile(
    r"^(?:now\s+)?(?:open|launch)\s+that\s+in\s+(.+)$",
    re.IGNORECASE,
)
RE_USE_APP_INSTEAD = re.compile(
    r"^(?:actually\s+)?use\s+(.+?)(?:\s+instead)?$",
    re.IGNORECASE,
)


def parse_teaching_request(clean_text: str) -> Optional[dict[str, Any]]:
    """
    Parses conversational workflow teaching requests like:
      'When I say start working on Lensify, open the Lensify project in my editor and open a terminal in that project folder.'
    Resolves each step against registered actions and resolvers, validating folders and applications.
    Returns structured intent with action 'teach_workflow', or None if not a teaching command.
    """
    m = RE_TEACH_WORKFLOW.match(clean_text)
    if not m:
        if clean_text.startswith("when i say ") or clean_text.startswith("whenever i say ") or clean_text.startswith("if i say "):
            return query_ollama_workflow_teaching(clean_text)
        return None

    raw_trigger = m.group(1).strip()
    raw_actions = m.group(2).strip()

    # Strip trailing "then" or punctuation from trigger if present
    raw_trigger = re.sub(r"\s+then$", "", raw_trigger, flags=re.IGNORECASE).strip()

    trigger_clean = raw_trigger.strip("'\"").strip().rstrip(".?!,").strip().lower()
    if not trigger_clean:
        return None

    name = raw_trigger.strip("'\"").strip().rstrip(".?!,").strip().title()

    sub_commands = [c.strip() for c in RE_STEP_SPLIT.split(raw_actions) if c.strip()]
    if not sub_commands:
        return {
            "action": "teach_workflow",
            "params": {
                "unsupported": "No action steps were specified in the workflow.",
                "trigger": trigger_clean,
            },
        }

    from actions.resolver import get_app_registry, get_directory_resolver
    app_registry = get_app_registry()
    dir_resolver = get_directory_resolver()

    steps = []
    shared_path: Optional[str] = None

    for idx, sub in enumerate(sub_commands):
        sub_cleaned = _clean_input(sub)
        step_intent = extract_smart_intent(sub_cleaned, skip_teaching=True)

        if not step_intent or not step_intent.get("action"):
            return {
                "action": "teach_workflow",
                "params": {
                    "unsupported": f"Could not understand step {idx + 1}: '{sub}'.",
                    "trigger": trigger_clean,
                },
            }

        act = step_intent["action"]
        params = step_intent.get("params", {})

        if act == "open_project":
            project = params.get("project")
            app_name = params.get("app") or "editor"

            # Check if project is an anaphoric / pronoun reference (e.g. "that folder", "that", "folder", "it", "the project")
            pronouns = ("that", "that folder", "the folder", "folder", "it", "this folder", "this", "the project", "that project")
            if not project or project.lower().strip() in pronouns:
                # 1. Check if trigger specifies a project (e.g. "open manage crew" -> "manage crew")
                trig_cand = re.sub(
                    r"^(?:open|launch|start(?:\s+working\s+on)?|work\s+on|code)\s+",
                    "",
                    trigger_clean,
                    flags=re.IGNORECASE,
                ).strip()
                trig_path, _ = dir_resolver.resolve_project_directory(trig_cand)
                if trig_path:
                    project = trig_cand
                elif shared_path:
                    project = os.path.basename(shared_path)
                elif self_recent := context.get_recent_target_path():
                    project = os.path.basename(self_recent)

            target_path, candidates = dir_resolver.resolve_project_directory(project)
            if not target_path and len(candidates) > 1:
                return {
                    "action": "teach_workflow",
                    "params": {
                        "ambiguity": {
                            "type": "folder",
                            "project": project,
                            "candidates": candidates,
                            "app": app_name,
                            "step_idx": idx,
                        },
                        "trigger": trigger_clean,
                        "raw_actions": raw_actions,
                    },
                }

            if not target_path:
                return {
                    "action": "teach_workflow",
                    "params": {
                        "unsupported": f"Project folder '{project}' could not be located on your system.",
                        "trigger": trigger_clean,
                    },
                }

            app_info = app_registry.resolve_application(app_name)
            if not app_info:
                return {
                    "action": "teach_workflow",
                    "params": {
                        "unsupported": f"Application '{app_name}' is not installed on this system.",
                        "trigger": trigger_clean,
                    },
                }

            shared_path = target_path
            steps.append({
                "action": "open_project",
                "params": {
                    "project": project,
                    "app": app_info.name,
                    "path": target_path,
                },
                "description": f"Open project '{project.title()}' ({target_path}) in {app_info.name}",
            })

        elif act == "launch_terminal_at":
            target_path = shared_path or params.get("path") or context.get_recent_target_path()
            if not target_path:
                return {
                    "action": "teach_workflow",
                    "params": {
                        "unsupported": f"Terminal step '{sub}' requires a project folder context.",
                        "trigger": trigger_clean,
                    },
                }
            steps.append({
                "action": "launch_terminal_at",
                "params": {"path": target_path},
                "description": f"Open Konsole terminal in {target_path}",
            })

        elif act == "volume_set":
            pct = params.get("percentage", 100)
            steps.append({
                "action": "volume_set",
                "params": {"percentage": pct},
                "description": f"Set volume to {pct}%",
            })

        elif act == "volume_change":
            delta = params.get("delta", 10)
            steps.append({
                "action": "volume_change",
                "params": {"delta": delta},
                "description": f"Change volume by {delta}%",
            })

        elif act == "mute_audio":
            st = params.get("mute_state", True)
            steps.append({
                "action": "mute_audio",
                "params": {"mute_state": st},
                "description": "Mute audio" if st else "Unmute audio",
            })

        elif act == "brightness_set":
            pct = params.get("percentage", 50)
            steps.append({
                "action": "brightness_set",
                "params": {"percentage": pct},
                "description": f"Set brightness to {pct}%",
            })

        elif act == "screenshot":
            mode = params.get("mode", "fullscreen")
            steps.append({
                "action": "screenshot",
                "params": {"mode": mode},
                "description": f"Take {mode} screenshot",
            })

        elif act in ("open_firefox_tab", "open_firefox_window", "open_terminal", "open_downloads", "open_youtube"):
            steps.append({
                "action": act,
                "params": {},
                "description": act.replace("_", " ").capitalize(),
            })

        else:
            return {
                "action": "teach_workflow",
                "params": {
                    "unsupported": f"Action '{act}' in step '{sub}' is not supported in workflows.",
                    "trigger": trigger_clean,
                },
            }

    return {
        "action": "teach_workflow",
        "params": {
            "trigger": trigger_clean,
            "name": name,
            "steps": steps,
        },
    }


def query_ollama_workflow_teaching(command_text: str) -> Optional[dict[str, Any]]:
    """
    Bounded fallback using local Ollama (llama3.2:3b) to interpret teaching requests
    when natural phrasing exceeds deterministic regex grammar.
    Never executes or generates arbitrary Python or shell commands.
    """
    prompt = (
        f'Analyze this workflow teaching voice instruction: "{command_text}"\n'
        'Extract trigger phrase and action steps into JSON format only:\n'
        '{\n'
        '  "trigger": "phrase that triggers the workflow",\n'
        '  "name": "short workflow name",\n'
        '  "steps": [\n'
        '    {"action": "open_project", "params": {"project": "name", "app": "name"}},\n'
        '    {"action": "launch_terminal_at", "params": {}}\n'
        '  ]\n'
        '}\n'
        'Supported actions strictly: open_project, launch_terminal_at, volume_set, brightness_set, screenshot.\n'
        'Output ONLY the JSON object.'
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=3.5) as resp:
            if resp.status == 200:
                raw_data = json.loads(resp.read().decode("utf-8"))
                text_resp = raw_data.get("response", "").strip()
                if text_resp:
                    data = json.loads(text_resp)
                    trigger = data.get("trigger", "").lower().strip()
                    steps = data.get("steps", [])
                    name = data.get("name") or trigger.title()
                    if trigger and steps:
                        return {
                            "action": "teach_workflow",
                            "params": {
                                "trigger": trigger,
                                "name": name,
                                "steps": steps,
                                "from_ollama": True,
                            },
                        }
    except Exception:
        pass

    return None


def extract_smart_intent(text: str, skip_teaching: bool = False) -> Optional[dict[str, Any]]:
    """
    Extracts structured intent and parameters from natural speech.

    Progression:
      1. Reusable Workflow Fast-Path in SQLite Memory (< 1ms)
      1.5 Workflow Management Commands (< 1ms)
      1.8 Conversational Workflow Teaching (< 1ms deterministic)
      2. Single-Command Learned Pattern Fast-Path (< 1ms)
      3. Multi-Step Chained Workflow Detection (< 1ms)
      4. Desktop Controls (Volume, Brightness, Screenshot, Window) (< 1ms)
      5. Conversational Follow-Up Patterns (< 1ms)
      6. Deterministic Project Entity Patterns (< 1ms)
      7. Local Ollama structured JSON extraction (fallback for unfamiliar phrasing)
    """
    clean_text = _clean_input(text)
    if not clean_text:
        return None

    memory = get_memory_store()
    context = get_conversation_context()

    # 1. Workflow Management Commands (< 1ms)
    if RE_LIST_WORKFLOWS.match(clean_text):
        return {"action": "list_workflows", "params": {}}

    if RE_HELP_WORKFLOW.match(clean_text):
        return {"action": "workflow_help", "params": {}}

    m_insp = RE_INSPECT_WORKFLOW.match(clean_text)
    if m_insp:
        target_name = (m_insp.group(1) or m_insp.group(2)).strip().strip("'\"").rstrip(".?!,").strip()
        return {"action": "inspect_workflow", "params": {"workflow_name": target_name}}

    m_en = RE_ENABLE_WORKFLOW.match(clean_text)
    if m_en:
        target_name = m_en.group(1).strip().strip("'\"").rstrip(".?!,").strip()
        return {"action": "toggle_workflow", "params": {"workflow_name": target_name, "enabled": True}}

    m_dis = RE_DISABLE_WORKFLOW.match(clean_text)
    if m_dis:
        target_name = m_dis.group(1).strip().strip("'\"").rstrip(".?!,").strip()
        return {"action": "toggle_workflow", "params": {"workflow_name": target_name, "enabled": False}}

    m_del = RE_DELETE_WORKFLOW.match(clean_text)
    if m_del:
        target_name = (m_del.group(1) or m_del.group(2) or "").strip().strip("'\"").rstrip(".?!,").strip()
        return {"action": "delete_workflow", "params": {"workflow_name": target_name}}

    m_ren = RE_RENAME_WORKFLOW.match(clean_text)
    if m_ren:
        old_n = m_ren.group(1).strip().strip("'\"").rstrip(".?!,").strip()
        new_n = m_ren.group(2).strip().strip("'\"").rstrip(".?!,").strip()
        return {"action": "rename_workflow", "params": {"old_name": old_n, "new_name": new_n}}

    # 1.5 Conversational Workflow Teaching (< 1ms deterministic)
    if not skip_teaching:
        teach_intent = parse_teaching_request(clean_text)
        if teach_intent:
            return teach_intent

    # 1.8 Reusable Workflow Fast-Path by Trigger or Spoken Name (< 1ms)
    wf, candidates, target_name, is_explicit = memory.resolve_workflow_by_spoken_name(clean_text)
    if wf:
        return {
            "action": "run_workflow",
            "workflow_id": wf["workflow_id"],
            "params": {
                "workflow_id": wf["workflow_id"],
                "steps": wf["steps"],
                "name": wf.get("name"),
                "trigger_text": clean_text,
            },
            "from_cache": True,
        }
    if candidates and len(candidates) > 1:
        return {
            "action": "workflow_ambiguous",
            "params": {
                "candidates": candidates,
                "target": target_name or clean_text,
            },
        }
    if is_explicit:
        disabled_wf, _, _, _ = memory.resolve_workflow_by_spoken_name(clean_text, enabled_only=False)
        if disabled_wf and not disabled_wf.get("is_enabled", 1):
            return {
                "action": "workflow_disabled",
                "params": {"name": disabled_wf.get("name") or target_name},
            }
        return {
            "action": "workflow_not_found",
            "params": {"target": target_name or clean_text},
        }

    # 2. Single-Command Learned Pattern Fast-Path (< 1ms)
    cached = memory.get_learned_pattern(clean_text)
    if cached:
        return {
            "action": cached["target_action"],
            "params": cached.get("target_params", {}),
            "from_cache": True,
        }

    # 3. Multi-Step Chained Workflow Detection (e.g. "..., then ...")
    sub_commands = [c.strip() for c in RE_WORKFLOW_SPLIT.split(clean_text) if c.strip()]
    if len(sub_commands) > 1:
        steps = []
        all_resolved = True
        for sub in sub_commands:
            step_intent = extract_smart_intent(sub)
            if step_intent and step_intent.get("action"):
                steps.append({"action": step_intent["action"], "params": step_intent.get("params", {})})
            else:
                all_resolved = False
                break
        if all_resolved and len(steps) > 1:
            return {
                "action": "compose_workflow",
                "params": {"steps": steps, "trigger_text": clean_text},
                "from_cache": False,
            }

    # 4. Desktop Hardware Controls (< 1ms)
    # 4a. Robust Volume & Audio Controls (< 1ms deterministic)
    vol_res = extract_volume_intent(clean_text)
    if vol_res:
        return {
            "action": vol_res["action"],
            "params": vol_res["params"],
            "intent": vol_res.get("intent"),
            "mode": vol_res.get("mode"),
            "value": vol_res.get("value"),
            "requires_clarification": vol_res.get("requires_clarification", False),
            "clarification_reason": vol_res.get("clarification_reason"),
            "from_cache": False,
        }

    # 4f. Brightness Set
    m_br_set = RE_BRIGHTNESS_SET.match(clean_text)
    if m_br_set:
        pct = max(5, min(100, int(m_br_set.group(1))))
        return {"action": "brightness_set", "params": {"percentage": pct}, "from_cache": False}

    # 4g. Brightness Up
    m_br_up = RE_BRIGHTNESS_UP.match(clean_text)
    if m_br_up:
        delta = int(m_br_up.group(1)) if m_br_up.group(1) else 10
        return {"action": "brightness_change", "params": {"delta": delta}, "from_cache": False}

    # 4h. Brightness Down
    m_br_down = RE_BRIGHTNESS_DOWN.match(clean_text)
    if m_br_down:
        delta = int(m_br_down.group(1)) if m_br_down.group(1) else 10
        return {"action": "brightness_change", "params": {"delta": -delta}, "from_cache": False}

    # 4i. Screenshot (Fullscreen / Region)
    if RE_SCREENSHOT_REGION.match(clean_text):
        return {"action": "screenshot", "params": {"mode": "region"}, "from_cache": False}
    if RE_SCREENSHOT.match(clean_text):
        return {"action": "screenshot", "params": {"mode": "fullscreen"}, "from_cache": False}

    # 4j. Window Controls
    if RE_WINDOW_MINIMIZE.match(clean_text):
        return {"action": "window_control", "params": {"action": "minimize"}, "from_cache": False}
    if RE_WINDOW_MAXIMIZE.match(clean_text):
        return {"action": "window_control", "params": {"action": "maximize"}, "from_cache": False}
    if RE_SHOW_DESKTOP.match(clean_text):
        return {"action": "window_control", "params": {"action": "show_desktop"}, "from_cache": False}
    if RE_SWITCH_WINDOW.match(clean_text):
        return {"action": "window_control", "params": {"action": "switch"}, "from_cache": False}

    # 5. Conversational Follow-Up Patterns (< 1ms)
    if RE_TERMINAL_THERE.match(clean_text):
        target_path = context.get_recent_target_path()
        return {"action": "launch_terminal_at", "params": {"path": target_path}, "is_followup": True}

    m_folder = RE_FOLDER_FOLLOWUP.match(clean_text)
    if m_folder:
        folder_name = m_folder.group(1).strip()
        recent_app = context.get_recent_app() or "konsole"
        return {"action": "open_project", "params": {"project": folder_name, "app": recent_app}, "is_followup": True}

    m_that = RE_OPEN_THAT_IN_APP.match(clean_text)
    if m_that:
        app_name = m_that.group(1).strip()
        target_path = context.get_recent_target_path()
        return {"action": "open_project_at", "params": {"path": target_path, "app": app_name}, "is_followup": True}

    m_switch = RE_USE_APP_INSTEAD.match(clean_text)
    if m_switch:
        new_app = m_switch.group(1).strip()
        target_path = context.get_recent_target_path()
        return {"action": "followup_switch_app", "params": {"app": new_app, "path": target_path}, "is_followup": True}

    # 6. Deterministic Project Entity Patterns (< 1ms)
    m_in = re.match(r"^(?:open|launch|start)\s+(.+?)\s+(?:in|into)\s+(.+)$", clean_text, re.IGNORECASE)
    if m_in:
        p1 = m_in.group(1).rstrip(".?!,").strip()
        p2 = m_in.group(2).rstrip(".?!,").strip()

        c1 = re.sub(r"^(?:my\s+|the\s+)", "", p1.lower().strip())
        c1_clean = re.sub(r"(?:\s+(?:project|folder|directory|repo))+$", "", c1).strip()

        c2 = re.sub(r"^(?:my\s+|the\s+)", "", p2.lower().strip())
        c2_clean = re.sub(r"(?:\s+(?:project|folder|directory|repo))+$", "", c2).strip()

        from actions.resolver import get_app_registry, get_directory_resolver
        app_registry = get_app_registry()
        dir_resolver = get_directory_resolver()

        app1 = app_registry.resolve_application(c1_clean)
        app2 = app_registry.resolve_application(c2_clean)

        explicit_folder_1 = bool(re.search(r"\b(?:project|folder|directory|repo)\b", c1))
        explicit_folder_2 = bool(re.search(r"\b(?:project|folder|directory|repo)\b", c2))

        if app2 and not app1:
            # "open <project> in <app>" (e.g. "open Lensify in my editor", "open Lensify in anti-gravity editor")
            proj = c1_clean
            app = c2_clean
        elif app1 and not app2:
            # "open <app> in <project>" (e.g. "open terminal in Lensify", "open Konsole in my project folder")
            app = c1_clean
            proj = c2_clean
        elif explicit_folder_1 and not explicit_folder_2:
            proj = c1_clean
            app = c2_clean
        elif explicit_folder_2 and not explicit_folder_1:
            app = c1_clean
            proj = c2_clean
        else:
            dir1, _ = dir_resolver.resolve_project_directory(c1_clean)
            dir2, _ = dir_resolver.resolve_project_directory(c2_clean)
            if dir1 and not dir2:
                proj = c1_clean
                app = c2_clean
            elif dir2 and not dir1:
                app = c1_clean
                proj = c2_clean
            else:
                proj = c1_clean
                app = c2_clean

        return {"action": "open_project", "params": {"project": proj, "app": app}, "from_cache": False}

    m3 = RE_OPEN_PROJECT_SOLO.match(clean_text)
    if m3:
        target = m3.group(1).rstrip(".?!,").strip()
        target = re.sub(r"(?:\s+(?:project|folder|directory|repo))+$", "", target, flags=re.IGNORECASE).strip()
        return {"action": "open_project", "params": {"project": target, "app": None}, "from_cache": False}

    # 7. Fallback: Local Ollama Structured JSON Extractor
    # 7a. Volume Bounded Fallback (only if volume keywords present and deterministic parsing did not resolve)
    if any(k in clean_text.lower() for k in ("volume", "sound", "audio", "louder", "quieter")):
        extracted_vol = query_ollama_volume_extraction(clean_text)
        if extracted_vol:
            return extracted_vol

    # 7b. Project & App Entities Fallback
    # Discard purely ambiguous command phrases that lack a specific entity target
    if re.match(
        r"^(?:open|launch|start)\s+(?:a\s+|an?\s+|the\s+|my\s+)?(?:project|folder|directory|repo|app|application|program)$",
        clean_text.lower().strip()
    ):
        return None

    action_clues = ("open ", "launch ", "start ", "edit ", "develop ", "work on ")
    if any(clean_text.lower().startswith(clue) for clue in action_clues) or " in " in clean_text.lower():
        # Deterministic fast-path before querying Ollama
        from actions.resolver import get_app_registry, get_directory_resolver
        target_raw = re.sub(r"^(?:open|launch|start|edit|develop|work on)\s+(?:on\s+|my\s+|the\s+)?", "", clean_text, flags=re.IGNORECASE).strip()
        target_clean = re.sub(r"(?:\s+(?:project|folder|directory|repo))+$", "", target_raw, flags=re.IGNORECASE).strip()
        if target_clean and not any(k in target_clean for k in ("there", "here", "workflow", "tab", "window")):
            proj_path, _ = get_directory_resolver().resolve_project_directory(target_clean)
            if proj_path:
                return {
                    "action": "open_project",
                    "params": {"project": target_clean, "app": None},
                    "from_cache": True,
                }
            app_match = get_app_registry().resolve_application(target_clean)
            if app_match:
                return {
                    "action": "launch_app",
                    "params": {"app": app_match.name, "project": None},
                    "from_cache": True,
                }

        # Fallback to Ollama structured extraction only for unfamiliar non-deterministic phrasing
        extracted = query_ollama_structured_extraction(clean_text)
        if extracted and extracted.get("action") in ("open_project", "launch_app"):
            target_proj = extracted.get("target")
            if target_proj and any(p in target_proj.lower() for p in ("name of", "target project", "or null", "null", "none")):
                target_proj = None
            if extracted["action"] == "open_project" and not target_proj:
                return None
            return {
                "action": extracted["action"],
                "params": {
                    "project": target_proj,
                    "app": extracted.get("app"),
                },
                "from_ollama": True,
            }

    return None


def query_ollama_volume_extraction(command_text: str) -> Optional[dict[str, Any]]:
    """
    Bounded fallback for volume extraction using local Ollama (llama3.2:3b).
    Strictly used when deterministic parsing cannot resolve an utterance containing
    volume or audio keywords. Never invents numbers missing from the transcript.
    """
    prompt = (
        f'Analyze this voice instruction: "{command_text}"\n'
        'Extract volume intent into JSON format only:\n'
        '{\n'
        '  "action": "set_volume" | "increase_volume" | "decrease_volume" | "mute" | "unmute" | null,\n'
        '  "percentage": integer percentage (0-200) or null,\n'
        '  "delta": relative integer adjustment (e.g. 10, -10) or null\n'
        '}\n'
        'Never invent a number missing from the transcript.\n'
        'Output ONLY the JSON object.'
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                raw_data = json.loads(resp.read().decode("utf-8"))
                text_resp = raw_data.get("response", "").strip()
                if text_resp:
                    data = json.loads(text_resp)
                    action = data.get("action")
                    if action == "set_volume" and data.get("percentage") is not None:
                        pct = int(data["percentage"])
                        if pct > 150:
                            return {
                                "action": "volume_limit_clarification",
                                "params": {"requested_percentage": pct, "max_percentage": 150},
                                "from_ollama": True,
                            }
                        return {
                            "action": "volume_set",
                            "params": {"percentage": max(0, pct)},
                            "from_ollama": True,
                        }
                    elif action == "increase_volume":
                        d = int(data.get("delta")) if data.get("delta") is not None else 10
                        return {
                            "action": "volume_change",
                            "params": {"delta": abs(d)},
                            "from_ollama": True,
                        }
                    elif action == "decrease_volume":
                        d = int(data.get("delta")) if data.get("delta") is not None else 10
                        return {
                            "action": "volume_change",
                            "params": {"delta": -abs(d)},
                            "from_ollama": True,
                        }
                    elif action == "mute":
                        return {
                            "action": "mute_audio",
                            "params": {"mute_state": True},
                            "from_ollama": True,
                        }
                    elif action == "unmute":
                        return {
                            "action": "mute_audio",
                            "params": {"mute_state": False},
                            "from_ollama": True,
                        }
    except Exception:
        pass

    return None


def query_ollama_structured_extraction(command_text: str) -> Optional[dict[str, Any]]:
    """
    Queries local Ollama (llama3.2:3b) strictly to extract command entities in JSON.
    Never executes or generates shell commands. Has a bounded 4.0s timeout.
    """
    prompt = (
        f'Analyze this desktop voice instruction: "{command_text}"\n'
        'Extract intent into JSON format only:\n'
        '{\n'
        '  "action": "open_project" | "launch_app" | "general_question",\n'
        '  "target": "name of target project or folder, or null",\n'
        '  "app": "name of target application (e.g. Antigravity, Konsole, Firefox, VS Code), or null"\n'
        '}\n'
        'Output ONLY the JSON object.'
    )

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "format": "json",
        "stream": False,
    }

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=4.0) as resp:
            if resp.status == 200:
                raw_data = json.loads(resp.read().decode("utf-8"))
                text_resp = raw_data.get("response", "").strip()
                if text_resp:
                    return json.loads(text_resp)
    except Exception:
        # Fallback gracefully if Ollama is busy or times out
        pass

    return None
