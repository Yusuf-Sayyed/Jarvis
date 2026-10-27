"""
Extraction and intent classification for conversational memories (facts and preferences).
Distinguishes memories from workflows, parses structured attributes, and supports
local Ollama extraction fallback.
"""

import json
import logging
import re
import urllib.request
from typing import Any, Optional

from core.config import OLLAMA_API_URL, OLLAMA_MODEL

logger = logging.getLogger("jarvis.memory_extractor")

# Regex pattern for explicit remember requests
RE_REMEMBER = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*[,:]?\s*)?"
    r"(?:(?:can\s+you\s+|could\s+you\s+|please\s+|just\s+|i\s+want\s+you\s+to\s+)*)"
    r"(?:remember\s+(?:that\s+|this\s*:\s*|this\s+that\s+|this\s+)?|"
    r"note\s+(?:that\s+)?|"
    r"keep\s+in\s+mind\s+(?:that\s+)?|"
    r"don\'t\s+forget\s+(?:that\s+)?)\s*"
    r"(.+)$",
    re.IGNORECASE,
)

# Regex pattern for recall requests
RE_RECALL = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*[,:]?\s*)?"
    r"(?:(?:can\s+you\s+|could\s+you\s+|please\s+)?(?:tell\s+me|show\s+me)\s+)?(?:"
    r"what\s+do\s+you\s+remember\s+(?:about\s+|regarding\s+)?(.*)|"
    r"what\s+did\s+i\s+tell\s+you\s+about\s+(.*)|"
    r"what\s+do\s+you\s+(?:know|recall)\s+about\s+(.*)|"
    r"what\s+are\s+my\s+preferences(?:\s+about\s+(.*))?|"
    r"list\s+(?:all\s+)?(?:my\s+|saved\s+)?memories|"
    r"show\s+(?:all\s+)?(?:my\s+|saved\s+)?memories|"
    r"what\s+memories\s+do\s+you\s+have|"
    r"what\s+(?:is|was)\s+my\s+(.*)|"
    r"(?:now\s+)?tell\s+me[,:]?\s+(?:with\s+whom|who)\s+i\s+live(?:\s+with)?(?:\s+in\s+my\s+room)?|"
    r"(?:with\s+whom|who)\s+do\s+i\s+live(?:\s+with)?(?:\s+in\s+my\s+room)?|"
    r"who\s+lives\s+with\s+me(?:\s+in\s+my\s+room)?"
    r")\b",
    re.IGNORECASE,
)

# Regex pattern for forget requests
RE_FORGET = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*[,:]?\s*)?"
    r"(?:please\s+|just\s+|can\s+you\s+)?(?:"
    r"forget\s+(?:the\s+)?(?:preference\s+i\s+told\s+you\s+about\s+|preference\s+about\s+|preference\s+for\s+|memory\s+about\s+|fact\s+about\s+|what\s+i\s+told\s+you\s+about\s+|that\s+)?(.*)|"
    r"delete\s+(?:the\s+)?(?:memory\s+about\s+|preference\s+about\s+|fact\s+about\s+)?(.*)|"
    r"remove\s+(?:the\s+)?(?:memory\s+about\s+|preference\s+about\s+|fact\s+about\s+)?(.*)"
    r")$",
    re.IGNORECASE,
)

# Regex pattern for update requests
RE_UPDATE = re.compile(
    r"^(?:(?:hey|hi|hello|ok|okay)?\s*jarvis\s*[,:]?\s*)?"
    r"(?:please\s+|just\s+|can\s+you\s+)?(?:"
    r"update\s+(?:the\s+)?(.*)|"
    r"change\s+(?:the\s+)?(?:preference\s+for\s+|memory\s+for\s+)?(.*)"
    r")$",
    re.IGNORECASE,
)


def is_workflow_utterance(text: str) -> bool:
    """
    Returns True if utterance pertains to a workflow (teaching, listing, deleting, toggling).
    Ensures memory extractor strictly distinguishes memories/preferences from workflows.
    """
    clean = text.lower().strip()
    if bool(re.match(r"^(?:when(?:ever)?\s+(?:i\s+say|i\s+tell\s+you|i\s+ask\s+you)|if\s+i\s+say)\b", clean)):
        return True
    if "workflow" in clean or "workflows" in clean:
        return True
    return False


is_workflow_teaching = is_workflow_utterance


def is_personal_memory_query(text: str) -> bool:
    """
    Identifies whether a question is about the user's private life, memories,
    roommate, business, or preferences, preventing it from leaking to web search.
    """
    clean = text.lower().strip()

    # Explicit recall patterns
    if bool(RE_RECALL.search(clean)):
        return True

    # Questions referring to private/personal state
    personal_indicators = (
        r"\b(?:my\s+room|my\s+roommate|with\s+whom\s+i\s+live|who\s+i\s+live\s+with|who\s+lives\s+with\s+me)\b",
        r"\b(?:my\s+business|my\s+company|my\s+startup|my\s+eyewear|lensify)\b",
        r"\b(?:my\s+name|who\s+am\s+i|where\s+do\s+i\s+live|my\s+location|my\s+age|how\s+old\s+am\s+i)\b",
        r"\b(?:my\s+preference|my\s+preferences|what\s+i\s+prefer|i\s+told\s+you|you\s+remember)\b",
        r"\b(?:farid|roommate)\b",
    )
    for pat in personal_indicators:
        if re.search(pat, clean):
            return True

    return False


def parse_deterministic_memory(statement: str) -> Optional[dict[str, str]]:
    """
    Fast sub-millisecond pattern matching for common memory patterns.
    """
    clean = statement.strip().rstrip(".?!,").strip()

    # 1. Eyewear / business: "my eyewear business is called Lensify", "my business is Lensify"
    m_biz = re.search(
        r"\bmy\s+(?:eyewear\s+)?business(?:\s+name)?\s+(?:is\s+called|is\s+named|is)\s+['\"]?(.+?)['\"]?$",
        clean,
        re.IGNORECASE,
    )
    if m_biz:
        val = m_biz.group(1).strip()
        return {
            "key": "business_name",
            "topic": "business name",
            "category": "fact",
            "content": val,
        }

    # 2. Preference: "I prefer short answers", "I like concise answers"
    m_pref = re.search(
        r"\bi\s+(?:prefer|like|want)\s+(.+)$",
        clean,
        re.IGNORECASE,
    )
    if m_pref:
        val = m_pref.group(1).strip()
        # Extract topic from preference
        topic = "preference"
        key = "user_preference"
        if "answer" in val or "response" in val or "short" in val or "brief" in val or "length" in val:
            topic = "answer length"
            key = "answer_length"
        elif "theme" in val or "dark" in val or "light" in val:
            topic = "theme"
            key = "preferred_theme"
        elif "editor" in val:
            topic = "editor"
            key = "preferred_editor"
        return {
            "key": key,
            "topic": topic,
            "category": "preference",
            "content": val,
        }

    # 3. Roommate / Living arrangement: "I live in my room with Farid"
    m_room = re.search(
        r"\bi\s+(?:live|reside|stay)(?:\s+in\s+my\s+room)?\s+with\s+([A-Za-z]+)",
        clean,
        re.IGNORECASE,
    )
    if m_room:
        roommate_name = m_room.group(1).strip().capitalize()
        return {
            "key": "roommate",
            "topic": "roommate",
            "category": "fact",
            "content": f"I live in my room with {roommate_name}",
        }

    # 4. Identity / Associate: "Farid is a Muslim man"
    m_person = re.search(
        r"^([A-Za-z]+)\s+is\s+(.+)$",
        clean,
        re.IGNORECASE,
    )
    if m_person:
        person_name = m_person.group(1).strip().capitalize()
        desc = m_person.group(2).strip()
        if person_name.lower() not in ("it", "this", "that", "there", "here", "today", "yesterday"):
            key = f"{person_name.lower()}_identity"
            return {
                "key": key,
                "topic": person_name,
                "category": "fact",
                "content": f"{person_name} is {desc}",
            }

    # 5. Name: "my name is Yusuf"
    m_name = re.search(r"\b(?:my\s+name\s+is|my\s+name\'s|call\s+me)\s+([A-Za-z]+)", clean, re.IGNORECASE)
    if m_name:
        name = m_name.group(1).strip().capitalize()
        return {
            "key": "user_name",
            "topic": "name",
            "category": "profile",
            "content": name,
        }

    # 6. Location: "I live in India"
    m_loc = re.search(r"\bi\s+(?:live|reside)\s+in\s+([A-Za-z\s]+?)$", clean, re.IGNORECASE)
    if m_loc:
        loc = m_loc.group(1).strip().title()
        return {
            "key": "location",
            "topic": "location",
            "category": "profile",
            "content": loc,
        }

    # 7. Age: "I am 23 years old", "I'm 23"
    m_age = re.search(r"\b(?:i(?:\x27m|\s+am)(?:\s+(?:a\s+)?(?:young|old))?\s+(?:and\s+)?|my\s+age\s+is\s+)(\d{1,2})\s*(?:years?\s+old|yrs?\s+old|yo)?\b", clean, re.IGNORECASE)
    if m_age:
        age_val = m_age.group(1).strip()
        return {
            "key": "age",
            "topic": "age",
            "category": "profile",
            "content": age_val,
        }

    # 8. Explicit "my [topic] is [value]"
    m_topic = re.search(r"\bmy\s+([A-Za-z\s]+?)\s+is\s+['\"]?(.+?)['\"]?$", clean, re.IGNORECASE)
    if m_topic:
        top_name = m_topic.group(1).strip()
        val = m_topic.group(2).strip()
        key_name = top_name.lower().replace(" ", "_")
        return {
            "key": key_name,
            "topic": top_name,
            "category": "fact",
            "content": val,
        }

    return None


def extract_fact_with_ollama(statement: str) -> Optional[dict[str, str]]:
    """
    Uses local Ollama (llama3.2:3b) with JSON schema to extract key, topic,
    category, and content when deterministic regex does not recognize the phrasing.
    """
    clean_statement = statement.strip()
    prompt = (
        "Analyze the user's factual or preference statement and extract memory metadata. "
        "Return a valid JSON object with EXACTLY these four keys:\n"
        "- \"key\": a clean snake_case identifier (e.g. \"business_name\", \"roommate\", \"answer_length\")\n"
        "- \"topic\": a short 1 to 3 word topic title (e.g. \"business\", \"Farid\", \"answer length\")\n"
        "- \"category\": either \"preference\" or \"fact\"\n"
        "- \"content\": the clean, concise fact or preference value to remember\n\n"
        f"User Statement: \"{clean_statement}\"\n"
        "JSON:"
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
        with urllib.request.urlopen(req, timeout=6) as response:
            if response.status == 200:
                raw_json = json.loads(response.read().decode("utf-8")).get("response", "").strip()
                data = json.loads(raw_json)
                key = str(data.get("key", "")).strip().lower().replace(" ", "_")
                content = str(data.get("content", "")).strip()
                topic = str(data.get("topic", "")).strip()
                category = str(data.get("category", "fact")).strip().lower()
                if key and content:
                    return {
                        "key": key,
                        "topic": topic or key.replace("_", " "),
                        "category": category if category in ("preference", "fact") else "fact",
                        "content": content,
                    }
    except Exception as e:
        logger.debug("Local Ollama extraction failed: %s", e)

    # Fallback to normalized slug
    words = re.findall(r"\b[A-Za-z0-9]+\b", clean_statement)
    slug = "_".join(words[:4]).lower() if words else "user_memory"
    return {
        "key": slug,
        "topic": " ".join(words[:3]) if words else "memory",
        "category": "fact",
        "content": clean_statement,
    }


def parse_memory_request(text: str) -> Optional[dict[str, Any]]:
    """
    Analyzes an utterance for conversational memory operations.
    Returns structured intent payload if it is a memory action, else None.
    """
    # Guard: Workflow creation instructions are NOT memory actions
    if is_workflow_teaching(text):
        return None

    clean = text.strip()

    # 1. Remember command: "Remember that my eyewear business is called Lensify"
    m_rem = RE_REMEMBER.match(clean)
    if m_rem:
        statement = m_rem.group(1).strip()
        # Fast deterministic extraction
        parsed = parse_deterministic_memory(statement)
        if not parsed:
            parsed = extract_fact_with_ollama(statement)

        if parsed:
            return {
                "action": "remember_memory",
                "key": parsed["key"],
                "topic": parsed["topic"],
                "category": parsed["category"],
                "content": parsed["content"],
                "statement": statement,
                "raw": text,
            }

    # 2. Forget command: "Forget the preference I told you about answer length"
    m_forg = RE_FORGET.match(clean)
    if m_forg:
        target = (m_forg.group(1) or m_forg.group(2) or m_forg.group(3) or "").strip().rstrip(".?!,").strip()
        # Clean target query
        target = re.sub(r"^(?:that\s+|about\s+|for\s+)", "", target, flags=re.IGNORECASE).strip()
        return {
            "action": "forget_memory",
            "target": target,
            "raw": text,
        }

    # 3. Update command: "Update the business name I previously saved"
    m_upd = RE_UPDATE.match(clean)
    if m_upd:
        phrase = (m_upd.group(1) or m_upd.group(2) or "").strip().rstrip(".?!,").strip()
        # Check if new value is provided via "to <value>"
        m_split = re.search(r"\s+to\s+['\"]?(.+?)['\"]?$", phrase, re.IGNORECASE)
        if m_split:
            target = phrase[:m_split.start()].strip()
            new_value = m_split.group(1).strip()
        else:
            target = phrase
            new_value = None

        target = re.sub(r"^(?:the\s+)?(?:previously\s+saved\s+)?", "", target, flags=re.IGNORECASE).strip()
        target = re.sub(r"\s+i\s+(?:previously\s+)?saved$", "", target, flags=re.IGNORECASE).strip()

        return {
            "action": "update_memory",
            "target": target,
            "new_value": new_value,
            "raw": text,
        }

    # 4. Recall command: "What do you remember about my business?"
    m_rec = RE_RECALL.search(clean)
    if m_rec:
        # Check if asking to list all memories
        if re.search(r"\b(?:list|show)\s+(?:all\s+)?(?:my\s+|saved\s+)?memories\b", clean, re.IGNORECASE) or \
           re.search(r"\bwhat\s+(?:memories\s+do\s+you\s+have|do\s+you\s+remember(?:\s+about\s+me)?)$", clean, re.IGNORECASE):
            return {
                "action": "list_memories",
                "raw": text,
            }

        # Specific topic query
        groups = [g for g in m_rec.groups() if g]
        query = groups[0].strip().rstrip(".?!,").strip() if groups else clean
        return {
            "action": "recall_memory",
            "query": query,
            "raw": text,
        }

    return None
