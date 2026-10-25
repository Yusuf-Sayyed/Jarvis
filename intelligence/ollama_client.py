"""
Client for the local Ollama LLM service (llama3.2:3b).
"""

import json
import urllib.error
import urllib.request
from core.config import JARVIS_SYSTEM_PROMPT, OLLAMA_API_URL, OLLAMA_MODEL


def ask_ollama(prompt: str) -> str | None:
    """
    Queries the local Ollama instance with the JARVIS system prompt.
    Returns the response string if successful, else None.
    """
    print("\n[Intent: OLLAMA_QUERY]")
    print("[JARVIS] Consulting local intelligence...")

    payload = {
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "system": JARVIS_SYSTEM_PROMPT,
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
                print(f"\n[JARVIS]: \"{answer}\"\n")
                return answer
            else:
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
