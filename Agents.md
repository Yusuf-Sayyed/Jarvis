Issue 1: False two-clap detection

Current log:
[ACTIVE] Two claps detected! "Hello, Sir. How can I help you?"

JARVIS activates without me intentionally clapping.

Trace the exact clap detection logic and identify why it triggers falsely.

Check whether speech, microphone startup noise, TTS playback, buffer boundaries, or ordinary background sounds are being counted as claps.

Add a configurable clap detector with stricter thresholds and a short, sharp acoustic-impulse requirement.

Require two distinct qualifying peaks within the configured interval, with appropriate minimum separation and noise-floor checks.

Reject continuous speech, a single clap, keyboard typing where feasible, and JARVIS's own TTS audio.

Calibrate against recent background audio instead of relying on a fixed low threshold.

Do not print "Two claps detected" or activate the session until both clap events have actually passed validation.

Add a temporary configuration switch to disable clap activation immediately if it remains unreliable.

Add diagnostic logging showing candidate peaks and rejection reasons, without dumping raw audio.

Test silence, normal speech, one clap, two deliberate claps, and TTS playback. Do not claim these physical tests passed unless actually performed.

Keep voice wake phrases working even if clap detection is disabled.


# Integrate Piper Neural TTS into JARVIS

I want to replace the current eSpeak NG voice with a natural-sounding Piper neural voice. My project is in `~/jarvis` on Fedora KDE Linux, with 16 GB RAM and an Intel i7-1360P CPU.

Current TTS diagnostics:
- Engine: `espeak-ng`
- Voice: `en-gb-x-rp`
- Pitch: 50
- Speed: 150
- Output: 22050 Hz mono WAV
- Playback: `pw-play`

The current voice sounds robotic, distorted, or crackly.

## 1. Inspect before changing anything
- Inspect `interfaces/speech.py`, `core/config.py`, and the current TTS/playback implementation.
- Identify how speech is synthesized, played, serialized, and cleaned up.
- Back up files before editing.
- Preserve the existing speech interface so the rest of JARVIS does not need to change.

## 2. Choose a suitable Piper voice
- Verify the currently maintained Piper project and installation instructions.
- Choose a lightweight, natural-sounding English voice with clear pronunciation and a polished assistant-like tone.
- Prefer a British English voice if a suitable model is available; otherwise recommend the best natural English alternative.
- Check the model file size, required companion files, license, dependencies, and expected CPU/RAM use.
- Report the selected voice and approximate download size before downloading it.
- Do not use cloud TTS or paid APIs.

## 3. Install and integrate Piper
- Use the project's existing virtual environment where appropriate.
- Install a compatible, maintained Piper implementation using its official instructions.
- Download the chosen voice only after verifying its source and reporting its size.
- Store model files in a dedicated directory such as `~/jarvis/models/piper/`.
- Update the existing speech interface to use Piper while preserving its public methods.
- Keep eSpeak available as a configurable fallback if Piper fails.
- Do not load duplicate models or initialize Piper repeatedly for each sentence.
- Avoid blocking the microphone/listener unnecessarily.

## 4. Fix playback quality
- Verify the generated WAV's actual sample rate, channels, sample format, duration, and amplitude.
- Play the generated audio with `pw-play` using the correct format.
- Prevent overlapping playback, premature file deletion, clipping, and corrupted buffers.
- Keep the TTS speaking lock and microphone pause/buffer-clearing behavior so JARVIS does not hear its own greeting.
- Do not assume playback is correct just because the process exits successfully.

## 5. Test
- Generate a standalone WAV saying: "Hello, Sir. How can I help you?"
- Provide the exact command to play it independently.
- Test short and long sentences, punctuation, repeated calls, and fallback behavior.
- Run relevant automated tests and preserve existing wake-word, clap, memory, workflow, and command functionality.
- Do not claim I have heard or approved the voice. Ask me to listen and confirm its quality.

## 6. Final report
Tell me:
- Which Piper model and voice were selected.
- Where the model files were stored.
- What was installed or changed.
- The exact command to test the WAV.
- Which automated tests actually passed.
- Whether eSpeak fallback works.
- Any manual steps still needed.

Make the smallest safe change. Do not rewrite the project or download additional models without a clear reason.