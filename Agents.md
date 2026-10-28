Set up my existing JARVIS assistant to start automatically when I log in to my Fedora KDE desktop, so I never need to open a terminal to launch it manually.

First inspect my existing project at `~/jarvis`. Identify the correct Python entry point, virtual environment, configuration, and startup requirements. Do not guess paths or create a duplicate assistant.

Requirements:

1. **Automatic startup**
   - Configure a systemd user service that starts JARVIS after my graphical desktop session is available.
   - Use the existing project and its correct virtual environment.
   - Run it as my normal user, never as root.
   - Configure restart-on-failure with a reasonable delay, without creating a rapid restart loop.
   - Ensure it starts only once.
   - Make it easy to check status, stop, restart, and disable the service.
   - Do not require an open Konsole window.

2. **Tony Stark-style greeting**
   - After the desktop session and required audio devices are ready, speak a short greeting through the existing Kokoro TTS voice (`bm_fable`).
   - Example: "Good morning, Sir. Systems are online. What shall we work on today?"
   - Choose the greeting based on local time where practical.
   - Greet only once per login/session, not on every service restart.
   - Do not start speaking before the audio system is ready.
   - If speech fails, log the error without crashing JARVIS.

3. **Preserve existing functionality**
   - Keep the existing wake phrase, five-minute active listening session, Whisper/VAD, memory, workflows, Ollama, desktop actions, and media controls.
   - Prevent JARVIS from transcribing its own greeting.
   - Avoid loading duplicate AI models or starting duplicate listeners.
   - Do not change the current voice or download any models.

4. **Privacy and reliability**
   - Start after I log in, not at the login screen.
   - Keep microphone use and listening status clear.
   - Do not run as root or weaken system security.
   - Keep logs available through `journalctl --user`.
   - Do not make JARVIS automatically execute risky actions on startup.

5. **Implementation**
   - Back up files before modifying them.
   - Create and enable the user service only after verifying its command and paths.
   - Test the service, greeting, logs, and restart behavior.
   - Report the exact files changed and commands to check status, restart, stop, and disable automatic startup.
   - Do not claim startup works unless it was actually tested.

Make the smallest reliable changes to my existing project. Explain any step that requires my approval or manual action.