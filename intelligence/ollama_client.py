"""
Client for the local Ollama LLM service (llama3.2:3b).
"""

import json
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


def get_system_prompt_with_memory() -> str:
    """
    Constructs the system prompt dynamically with remembered user preferences and identity facts.
    """
    try:
        from core.memory import get_memory_store
        memory = get_memory_store()
        prefs = memory.get_all_preferences()
    except Exception:
        prefs = {}

    system = JARVIS_SYSTEM_PROMPT
    if prefs:
        system += "\n\nPersistent User Knowledge:"
        if "user_name" in prefs:
            system += f"\n- The user's name is {prefs['user_name']}. Address them warmly as 'Sir' or 'Mr. {prefs['user_name']}'."
        if "location" in prefs:
            system += f"\n- The user resides in {prefs['location']}."
        if "age" in prefs:
            system += f"\n- The user is {prefs['age']} years old."
        if "occupation" in prefs:
            system += f"\n- The user's occupation/role is {prefs['occupation']}."
        for k, v in prefs.items():
            if k not in ("user_name", "location", "age", "occupation"):
                system += f"\n- {k.replace('_', ' ').title()}: {v}"
    return system


def ask_ollama(prompt: str, print_output: bool = True) -> str | None:
    """
    Queries the local Ollama instance with the JARVIS system prompt and user memory.
    Returns the response string if successful, else None.
    """
    print("\n[Intent: OLLAMA_QUERY]")
    print("[JARVIS] Consulting local intelligence...")

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": get_system_prompt_with_memory(),
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
