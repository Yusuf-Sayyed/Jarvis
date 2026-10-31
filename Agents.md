# JARVIS Upgrade: Context, Natural Conversation, Fast Speech & Minimal KDE Widget

Inspect my existing `~/jarvis` project on Fedora KDE Wayland before making changes. Extend the current architecture; do not rebuild it or remove existing features.

## 1. Context-aware conversations

Make JARVIS understand follow-up commands using temporary conversation state.

Example:
- “Open my JARVIS project.”
- “Open the main file.” → Resolve this relative to the current project.
- “Run it.” → Resolve the most recent unambiguous file or task.
- “Actually, open it in Antigravity.” → Update the active task.

Requirements:
- Track the current project, recent file, pending action, active workflow, and recent media search.
- Store only the context needed to resolve follow-ups.
- Expire temporary context after a configurable period and clear it when the task ends or the user switches tasks.
- Ask a concise clarification when multiple interpretations are plausible.
- Keep persistent user memory separate from temporary conversation state.
- Never invent a file, project, previous action, or result.
- Route deterministic commands locally before using Ollama.

## 2. Natural media and desktop follow-ups

Support natural command sequences such as:

“Search YouTube for relaxing music.”
“Play the second result.”
“Lower the volume to 30 percent.”
“Skip this.”
“Find instrumental music instead.”

Also support follow-ups for applications, folders, files, and workflows.

Requirements:
- Maintain recent YouTube results and the current media target.
- Use real browser or media controls supported by the existing environment.
- Distinguish a search result, an opened video, and verified playback.
- Use the actual application or media state to confirm execution wherever possible.
- Never claim an action succeeded merely because an AI model generated a response.
- Preserve existing validated action handlers and require confirmation for risky operations.
- Test ambiguity, expired context, missing results, and action failures.

## 3. Faster, more natural speech

Optimize responsiveness without downloading larger models or requiring paid APIs.

Requirements:
- Measure latency for audio capture, VAD, Whisper, intent extraction, Ollama, action execution, Kokoro generation, and playback.
- Avoid duplicate transcription, repeated model initialization, and unnecessary Ollama calls.
- Improve microphone buffering and speech/silence handling without cutting off words.
- Prevent JARVIS from transcribing its own TTS output.
- Support safe interruption: when I begin speaking during JARVIS's response, stop or cancel the current speech appropriately, capture my new command, and continue listening.
- Add sentence-by-sentence speech generation only if it is compatible with the existing TTS implementation and improves measured latency.
- Keep simple commands on a fast local execution path.
- Provide a brief spoken acknowledgment for genuinely long operations, without delaying short commands.
- Preserve the existing wake-word/session design and ensure recoverable errors do not terminate JARVIS.

Test short, long, interrupted, and failed speech operations.

## 4. A very small KDE status widget — ONE WORD ONLY

I want a tiny JARVIS status indicator near the top corner of my desktop, alongside the clock, battery, or other KDE panel widgets.

**Visual requirement: show exactly one short word at a time. No sentences, cards, graphs, or large dashboard.**

Use these status labels:
- `STANDBY`
- `LISTENING`
- `THINKING`
- `SPEAKING`
- `ERROR`

Requirements:
- Update the word from JARVIS's actual runtime state.
- Use a lightweight, low-resource implementation compatible with Fedora KDE Plasma and Wayland.
- First inspect the installed KDE Plasma version and supported widget/extension mechanisms.
- Prefer a native Plasma widget or another small, reliable panel integration compatible with the installed version. Do not assume Plasma 6 APIs if this machine uses Plasma 5.
- If a native panel widget would require a separate unsupported architecture, implement the smallest reliable alternative and explain the limitation before adding heavy dependencies.
- Keep it optional and easy to disable or remove.
- Do not run a separate AI model or heavy GUI process just for the indicator.
- Use a local, minimal IPC mechanism or an existing event interface to communicate status updates. Do not poll the full JARVIS process constantly.
- Handle stale state correctly if JARVIS crashes or exits.
- On intentional shutdown, return the indicator to `STANDBY` or the defined inactive state.
- When JARVIS is not running, it must not keep JARVIS's models or voice resources in memory.

The panel indicator must remain visually tiny: a single word, minimal padding, no large background panel, and no always-open window. A click may optionally reveal additional diagnostics, but the normal panel display must contain only one word.

## 5. Integration and safety

- Reuse the existing core context, router, intent extractor, memory, workflows, speech pipeline, and action handlers.
- Do not create competing state managers or duplicate audio loops.
- Keep temporary context separate from persistent memory.
- Do not execute arbitrary model-generated shell commands.
- Validate all action arguments and preserve user permissions.
- Keep JARVIS on-demand, with no always-running wake-word service added solely for this feature.
- Preserve `Super + J` launch behavior and the “Goodbye, Sir” spoken shutdown sequence if already implemented.
- Preserve all existing application, folder, browser, media, and workflow functionality.

## 6. Tests and delivery

First inspect the project and report the relevant files and architecture. Then implement changes in small stages.

Add or update tests for:
- Follow-up context and context expiration.
- Current-project file resolution.
- YouTube result selection and playback verification.
- Fast-path routing and failed actions.
- TTS interruption and microphone recovery.
- Status transitions through standby, listening, thinking, speaking, and error.
- Widget behavior after normal shutdown and unexpected process exit.
- Existing workflows and regression tests.

Run the relevant tests and report actual results. Do not claim that the KDE panel integration was tested on the real desktop if only unit tests or mocks were used.

Finally, provide a concise report of changed files, tests, launch/setup instructions, and any remaining manual steps.

**Implement the changes where your environment permits. Inspect first, preserve existing data, keep RAM usage low, and do not fabricate successful actions or test results.**
