"""
Client for the local Ollama LLM service (llama3.2:3b).
"""

import json
from typing import Optional
import urllib.error
import urllib.request
from core.config import JARVIS_SYSTEM_PROMPT, OLLAMA_API_URL, OLLAMA_MODEL


KNOWLEDGE_GAP_PHRASES = (
    "couldn't find any information",
    "could not find any information",
    "no information on a known entity",
    "not a known entity",
    "not aware of any",
    "not familiar with",
    "don't have information",
    "do not have information",
    "don't have any information",
    "do not have any information",
    "do not have access to real-time",
    "don't have access to real-time",
    "cannot provide real-time",
    "suggest searching for information",
    "suggest searching on the web",
    "suggest searching in the web browser",
    "suggest searching the web",
    "has not been programmed yet",
    "not been programmed yet",
    "outside my current programming",
    "not an entity within my current programming",
    "not a recognized entity",
    "as an ai, i do not know",
    "as an ai language model, i do not",
    "my knowledge cutoff",
)


def is_knowledge_gap(text: str | None) -> bool:
    """
    Checks if an LLM response indicates lack of knowledge, an unrecognized entity,
    or a request to search online.
    """
    if not text:
        return True
    lower = text.lower()
    return any(p in lower for p in KNOWLEDGE_GAP_PHRASES)


def get_system_prompt_with_memory(additional_context: Optional[list[str]] = None) -> str:
    """
    Constructs the system prompt dynamically with remembered user preferences, identity facts,
    and conversational memories from persistent SQLite storage.
    """
    try:
        from core.memory import get_memory_store
        memory = get_memory_store()
        prefs = memory.get_all_preferences()
        user_memories = memory.list_all_memories()
    except Exception:
        prefs = {}
        user_memories = []

    system = JARVIS_SYSTEM_PROMPT
    knowledge_lines = []

    if prefs.get("user_name"):
        knowledge_lines.append(f"The user's name is {prefs['user_name']}. Address them warmly as 'Sir' or 'Mr. {prefs['user_name']}'.")
    if prefs.get("location"):
        knowledge_lines.append(f"The user resides in {prefs['location']}.")
    if prefs.get("age"):
        knowledge_lines.append(f"The user is {prefs['age']} years old.")
    if prefs.get("occupation"):
        knowledge_lines.append(f"The user's occupation/role is {prefs['occupation']}.")

    for m in user_memories:
        top = m.get("topic", m.get("memory_key", "memory")).title()
        cont = m.get("content", "")
        line = f"{top}: {cont}"
        if line not in knowledge_lines:
            knowledge_lines.append(line)

    if additional_context:
        for item in additional_context:
            if item not in knowledge_lines:
                knowledge_lines.append(item)

    if knowledge_lines:
        system += "\n\nPersistent User Knowledge & Saved Memories:\n" + "\n".join(f"- {l}" for l in knowledge_lines)

    return system


def ask_ollama(prompt: str, print_output: bool = True, additional_context: Optional[list[str]] = None) -> str | None:
    """
    Queries the local Ollama instance with the JARVIS system prompt and user memory.
    Returns the response string if successful, else None.
    """
    print("\n[Intent: OLLAMA_QUERY]")
    print("[JARVIS] Consulting local intelligence...")

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": get_system_prompt_with_memory(additional_context=additional_context),
        "stream": False,
    }

    req = urllib.request.Request(
        OLLAMA_API_URL,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as response:
            if response.status != 200:
                print(f"[JARVIS Error] Ollama returned status code {response.status}.")
                return None

            response_data = json.loads(response.read().decode("utf-8"))
            answer = response_data.get("response", "").strip()
            if answer:
                if print_output:
                    print(f"\n[JARVIS]: \"{answer}\"\n")
                return answer
            else:
                if print_output:
                    print("[JARVIS] I received an empty response, Sir.")
                return None


    except urllib.error.URLError as e:
        if isinstance(e.reason, ConnectionRefusedError) or "Connection refused" in str(e.reason):
            print("[JARVIS Error] Could not connect to Ollama. Please make sure Ollama is running ('ollama serve').")
        else:
            print(f"[JARVIS Error] Connection to Ollama failed: {e.reason}")
        return None
    except TimeoutError:
        print("[JARVIS Error] Ollama request timed out. The model may be busy.")
        return None
    except json.JSONDecodeError:
        print("[JARVIS Error] Received an invalid response from Ollama.")
        return None
    except Exception as e:
        print(f"[JARVIS Error] Unexpected error contacting Ollama: {e}")
        return None
