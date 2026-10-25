Improve my existing JARVIS assistant in `~/jarvis` so it can perform browser searches and type text from my voice commands.

**First inspect the existing code and explain your planned changes before editing. Preserve the current working features, Vosk + PyAudio offline recognition, Ollama integration, wake phrase, and five-minute active-session timeout if implemented. Do not rewrite the project from scratch.**

### 1. Voice-controlled browser searches
Support natural commands such as:
- “Search Google for Python tutorials.”
- “Search YouTube for Iron Man trailers.”
- “Find the best Linux laptops on Google.”
- “Open Firefox and search for Fedora KDE tips.”
- “Open a new tab and search for Python courses.”
- “Search for [anything I say].”

Extract the actual search terms accurately. URL-encode the query and open the correct search results in Firefox. Do not send these obvious browser actions to Ollama.

### 2. Type what I say
Support commands such as:
- “Type hello world.”
- “Type Python installation guide into the search box.”
- “Type [spoken text] and press Enter.”

Use a suitable desktop automation method compatible with Fedora KDE. Inspect available tools and permissions first; explain any dependencies before installing them. Only type into the intended, focused field. Do not press Enter automatically unless the command explicitly requests it.

### 3. Browser keyboard actions
Support:
- “Open a new tab.”
- “Close the current tab” — ask for confirmation first.
- “Switch to the next tab.”
- “Go back.”
- “Go forward.”
- “Refresh the page.”

Use explicit, predefined functions for these actions. Do not let Ollama generate or execute shell commands.

### 4. Reliability and safety
- Normalize case, punctuation, spacing, and common Vosk transcription variations.
- Do not execute partial speech-recognition results.
- Print the recognized phrase and detected intent for debugging.
- If the search query is unclear, ask me to repeat it.
- Confirm before destructive or risky actions.
- Never claim an action succeeded unless the relevant operation was actually performed.
- Keep everything local/offline except the browser pages I explicitly request to open.
- Do not introduce paid APIs.

### 5. Test and explain
After editing, tell me exactly which files changed, which dependencies (if any) were added, and how to test every command. Include a test for the five-minute inactivity timeout.

Make changes incrementally and avoid breaking existing commands. Do not download a different speech model automatically.





Refactor my existing JARVIS project at `~/jarvis` into a clean, modular Python architecture.

Before making changes:
1. Inspect every relevant existing file, especially `jarvis.py`.
2. Identify the currently working features and dependencies.
3. Propose a migration plan that preserves existing behavior.

Create a maintainable structure with these modules:

- `jarvis.py` — application entry point
- `core/listener.py` — Vosk and PyAudio speech recognition
- `core/wake_word.py` — wake phrase and active-session timeout
- `core/intent.py` — command normalization and intent detection
- `core/router.py` — dispatching commands to handlers
- `core/config.py` — paths and shared configuration
- `actions/browser.py` — browser searches and tab actions
- `actions/keyboard.py` — keyboard input and shortcuts
- `actions/desktop.py` — application and folder launching
- `intelligence/ollama_client.py` — local Ollama API
- `interfaces/speech.py` — future text-to-speech integration
- `tests/` — automated tests for important behavior

Add `__init__.py` files wherever Python package imports require them.

Requirements:
- Preserve the existing virtual environment, Vosk model, Ollama integration, and working commands.
- Keep all speech recognition offline.
- Do not download models or install dependencies without asking first.
- Do not duplicate functionality across modules.
- Use clear function names, type hints where useful, and useful error handling.
- Keep `jarvis.py` small and focused on starting the application.
- Never use `shell=True` or allow Ollama to execute arbitrary shell commands.
- Keep the existing wake-word and five-minute inactivity behavior if already implemented.
- Add unit tests for command routing where practical.
- Do not implement new browser or keyboard features during this refactor.

Make a backup of the existing code before editing. Migrate incrementally, then run available tests and verify that the existing commands still work. If something cannot be tested, clearly tell me rather than claiming it works.

When finished, show me the final directory tree, summarize every changed file, list test results, and give me the exact commands to launch JARVIS.

Do not delete the original backup or the Vosk model.