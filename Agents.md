# JARVIS: On-Demand Launch, Complete Shutdown, Desktop Control & YouTube Playback

You are working on my existing local JARVIS AI voice assistant project at `~/jarvis` on Fedora Linux with KDE Plasma, running on Wayland.

Your task is to inspect the existing project and implement the improvements below while preserving all working features. **Do not rebuild the project from scratch.** First inspect the code, entry point, virtual environments, dependencies, current architecture, action handlers, workflows, memory system, speech pipeline, and tests. Identify the actual implementation before making changes.

## 1. Launch JARVIS with Super + J

I want to launch JARVIS only when I need it.

Required behavior:
- Configure a KDE global keyboard shortcut: `Super + J` (Windows key + J).
- Pressing it launches the existing JARVIS application using its correct Python interpreter, virtual environment, working directory, and startup command.
- It must work when triggered from KDE, without requiring an already-open terminal.
- Display useful startup errors instead of silently failing.
- Prevent accidental duplicate instances if the shortcut is pressed multiple times.
- Preserve the existing greeting, voice, wake/session behavior, and functionality where compatible.
- Do not install an always-running wake-word listener or background AI service solely for this feature.
- Do not start unnecessary services or load AI models at login.

Inspect the existing KDE environment and choose the simplest reliable implementation, such as a `.desktop` launcher plus KDE custom shortcut, or a small launch script. Use actual project paths and commands, not guessed ones.

## 2. Saying “bye” must shut down JARVIS completely

When I say “bye,” “goodbye,” or another existing supported exit phrase:
- Stop listening and stop accepting new commands.
- Stop or safely finish ongoing speech playback.
- Release audio devices, microphone streams, and other resources.
- Exit the main process cleanly, including worker threads and child processes owned by JARVIS where appropriate.
- Ensure the process does not remain hidden in the background or continue consuming resources.
- Make sure the shortcut can launch a fresh instance afterward.

Do not terminate unrelated desktop applications or kill all Python processes.

Important distinction:
- JARVIS's own process and in-process models should be released when it exits.
- Ollama or another separately running model server may retain its own model in RAM. Do not kill unrelated or shared services automatically.
- If JARVIS started a dedicated child process for its own work, manage that process safely and clean it up on shutdown.

Verify the shutdown behavior using process checks and logs. Report any separate process that legitimately remains running.

## 3. Control applications across my laptop

I want to use natural voice commands to open applications installed on my laptop, not just a small hardcoded list.

Examples:
- “Open Firefox.”
- “Open Antigravity.”
- “Open Visual Studio Code.”
- “Open the terminal.”
- “Open Settings.”
- “Open my file manager.”
- “Open Downloads.”
- “Open the browser.”
- “Open the music player.”

Requirements:
- Discover installed GUI applications through supported Linux desktop mechanisms, such as `.desktop` application entries and desktop launchers.
- Reuse the existing application registry/resolver if present and extend it instead of creating a competing system.
- Resolve application names case-insensitively and support sensible aliases.
- Prefer desktop launchers or their configured commands so application-specific environment settings are preserved.
- If an application is not installed or its identity is ambiguous, ask a short clarification or explain the problem.
- Never claim an application opened unless the launch operation succeeded.
- Do not hardcode every installed application manually.
- Do not send every simple open-app command to Ollama. Use a fast local action path.

## 4. Navigate folders and open files

I want to control my files and folders naturally through voice.

Examples:
- “Open Downloads.”
- “Open my Documents folder.”
- “Open the JARVIS project folder.”
- “Open the Lensify project in my editor.”
- “Open the file manager at ~/jarvis.”
- “Find my Python practice folder.”
- “Open this project in Antigravity.”
- “Open the README in my JARVIS folder.”

Requirements:
- Support standard user directories and discoverable project directories.
- Reuse the existing project resolver, registry, aliases, and persistent memory.
- Support opening a folder in the default file manager and opening a project in a specified editor.
- Inspect the real installed Antigravity launcher and its supported command-line arguments before implementing editor-folder opening. Do not assume an executable name or CLI syntax.
- Resolve relative paths and `~` safely.
- Validate paths and report missing or ambiguous folders/files.
- Never silently create, overwrite, move, or delete files when I only asked to open or find them.
- If I say “open this project in my editor,” use context only when the intended project and editor are unambiguous; otherwise ask a short question.

## 5. Search YouTube and actually play the requested content

This is important. I want commands like:

- “Search YouTube for Hollywood songs and play the first result.”
- “Search this on youtube.com and play it.”
- “Find the official Interstellar trailer on YouTube and play it.”
- “Play relaxing music on YouTube.”
- “Search YouTube for Python tutorials and open the first video.”
- “Pause the video.”
- “Resume playback.”
- “Stop the video.”
- “Set volume to 50 percent.”
- “Increase the volume to 80 percent.”

Expected behavior for a combined search-and-play command:
1. Recognize the YouTube search query and the request to play a result.
2. Open the correct YouTube search results or use a reliable existing search/playback integration.
3. Select the intended result using the project's existing browser automation capabilities, if available.
4. Open the actual video and initiate playback when technically possible.
5. Verify playback through an available reliable signal, such as browser automation, player state, or MPRIS.
6. Tell me what happened truthfully.

Important:
- Opening a YouTube search page is not the same as playing a video.
- If autoplay is blocked, the browser is unavailable, the video is inaccessible, or playback cannot be verified, tell me what happened and ask for help only when needed.
- Do not say “playing now” just because a URL was opened.
- Respect normal YouTube access restrictions, login requirements, and browser security.
- Reuse existing browser automation, URL handling, and media controls wherever possible.
- Inspect whether Firefox actually exposes playback through MPRIS on this machine. Do not assume it does.
- Avoid introducing a large new browser automation dependency without checking the existing setup first.
- Use safe URL encoding for search queries.
- Support follow-up commands such as “play it,” “pause it,” and “resume” by retaining the current media/search context.
- Do not let unrelated conversational replies be mistaken for media commands.
- Keep volume control separate from YouTube search/playback when the requested volume operation uses system-wide audio controls.

## 6. Fast routing and honest execution

Inspect the existing intent extractor, router, context manager, workflow engine, action resolver, and memory.

Required behavior:
- Route obvious application, folder, media, and workflow commands through deterministic local handlers before calling Ollama.
- Use Ollama for genuinely ambiguous or conversational requests, not every simple action.
- Preserve conversation context for follow-ups such as “play it,” but only when a unique pending media target exists.
- Execute actions through validated existing handlers. Do not let the LLM generate arbitrary shell commands and execute them without validation.
- Separate intent recognition from action execution.
- Report success only after the relevant handler returns success or a reliable signal confirms the action.
- If an action fails, provide a concise and truthful explanation.
- Preserve existing workflows, aliases, saved memory, session timeout, wake-word behavior, and natural-language interaction.
- Keep all existing projects and their identities separate. Do not invent relationships between JARVIS, Lensify, ManageCrew, or other folders.

## 7. Security and permission boundaries

I want broad control over my own laptop, but implement it safely.

- JARVIS may open applications, browse folders, search the web, and interact with normal desktop applications using the current user's permissions.
- Do not run the assistant as root or use `sudo` automatically.
- Never bypass file permissions, OS security, browser protections, or authentication.
- Require explicit confirmation for destructive or sensitive operations, such as deleting files, overwriting data, installing packages, changing security settings, or executing potentially dangerous commands.
- Do not execute arbitrary commands extracted from speech or model responses.
- Keep an allowlisted set of supported actions and validate their arguments.
- Do not silently upload local files or private information to external services.
- If a request requires elevated permissions or unavailable access, explain the limitation.

## 8. RAM usage and startup performance

My laptop has 16 GB RAM. I do not want JARVIS permanently consuming memory when I am not using it.

- No always-listening service.
- No automatic AI model loading at laptop startup.
- Load speech/AI resources only when JARVIS launches, according to the current architecture.
- Release JARVIS-owned resources on exit.
- Avoid loading Whisper, Ollama models, or Kokoro multiple times unnecessarily.
- Avoid duplicate audio capture, repeated transcription, or repeated intent extraction for one utterance.
- Keep the existing local/offline-first approach and do not introduce paid API requirements.
- Do not download a larger model or add a heavy dependency unless justified and approved.
- Instrument startup and shutdown timing if useful, but keep routine voice responses concise.

## 9. Tests and verification

Add or update automated tests using mocks for external desktop actions.

Cover:
- Correct launcher command and virtual environment.
- Shortcut/launcher setup and duplicate-instance prevention.
- Exit phrases triggering a full, clean JARVIS shutdown.
- A fresh launch working after shutdown.
- Discovering and launching installed applications.
- Opening known folders and projects, including an editor-folder combination.
- Missing application and missing path handling.
- Natural-language YouTube search-and-play routing.
- Distinguishing opening search results from actual playback.
- Follow-up play, pause, resume, stop, and volume commands.
- Failed actions never being reported as successful.
- Existing workflows, memory, and tests continuing to work.

Do not claim that real desktop playback or process shutdown was verified if only mocked tests were run. Clearly separate automated test results from actual manual verification.

## 10. Implementation process and final report

Work in small, safe stages:
1. Inspect and summarize the current implementation and relevant files.
2. Identify the smallest set of necessary changes.
3. Implement the launcher and shutdown lifecycle.
4. Implement or extend application and folder discovery.
5. Improve YouTube command routing and playback verification.
6. Run focused tests, then the existing regression suite.
7. Test the launcher and shutdown on the real desktop when possible.

Before editing, protect user data and preserve existing memory databases, aliases, and workflow definitions. Do not overwrite configuration or recreate the project.

In your final report, provide:
- Files created or changed.
- Exact command used to launch JARVIS.
- Whether `Super + J` is configured and how it was configured.
- Whether saying “bye” was verified to terminate the JARVIS process.
- Whether installed application and folder discovery works.
- Whether YouTube playback was actually verified or only the search page opened.
- Tests run and their actual results.
- Any remaining limitations or manual steps.
- Any background processes that may still use RAM after JARVIS exits.

**Do not just give me a plan or code snippets. Inspect the existing repository and implement the changes where your environment permits. Never invent test results or claim that an action was performed without evidence.**