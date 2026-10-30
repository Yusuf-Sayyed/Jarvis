# JARVIS — Local AI Voice Assistant for Linux

A local, offline-first AI voice assistant inspired by JARVIS from Iron Man. Built with Python, JARVIS combines voice recognition, natural-language understanding, persistent memory, text-to-speech, and desktop automation to make everyday computer interactions more intuitive.

Designed to run locally without requiring paid AI APIs.

## Features

- **Voice Interaction** — Speak naturally to interact with your assistant.
- **Wake-Word Activation** — Activate JARVIS using a configurable wake phrase and interact during a timed session.
- **Natural-Language Commands** — Understand everyday requests without requiring exact command phrases.
- **Desktop Automation** — Open applications, folders, projects, and supported desktop tools using voice commands.
- **Browser Control** — Open websites, search the web, and interact with supported browser workflows.
- **YouTube Integration** — Search for videos and control supported playback actions.
- **Persistent Memory** — Store useful information and learned mappings across sessions.
- **Custom Workflows** — Create reusable workflows for frequently performed tasks.
- **AI-Powered Responses** — Use a locally running language model through Ollama for conversational requests.
- **Natural-Sounding Speech** — Generate spoken responses using Kokoro TTS.
- **Offline-First Architecture** — Keep core processing local wherever supported, reducing dependence on cloud services.

## Technology Stack

| Technology | Purpose |
|---|---|
| Python | Core application and orchestration |
| Whisper | Speech recognition |
| Silero VAD | Voice activity detection |
| Ollama | Local language-model inference |
| Llama 3.2 | Conversational intelligence |
| Kokoro ONNX | Text-to-speech |
| SQLite | Persistent memory and stored data |
| Linux / KDE Plasma | Desktop environment and automation |
| pytest | Automated testing |

*Features and dependencies may vary with the current project configuration.*

## How It Works

JARVIS combines a local voice pipeline with an action-routing system.

1. **Listen** — Capture microphone input and detect speech.
2. **Transcribe** — Convert spoken words into text.
3. **Understand** — Identify the user's intent and resolve relevant context.
4. **Execute** — Route supported commands to validated action handlers.
5. **Respond** — Provide a spoken response using text-to-speech.
6. **Remember** — Persist supported information, aliases, and workflow data for future sessions.

Simple commands can use direct local handlers, while conversational requests can use the local language model.

## Example Commands

```text
"Hey JARVIS"
"Open Firefox"
"Open Downloads"
"Open my JARVIS project in the editor"
"Search YouTube for Python tutorials"
"Play the first video"
"Pause the video"
"Set volume to 50 percent"
"Remember this for later"
"Run my saved workflow"
"Goodbye"
```

Actual command support depends on the configured actions, installed applications, and integrations.

## Installation

### Prerequisites

- Linux system
- Python and `pip`
- A working microphone and audio output
- [Ollama](https://ollama.com/) for local language-model inference
- Required speech-recognition and text-to-speech model assets

### 1. Clone the repository

```bash
git clone <YOUR_REPOSITORY_URL>
cd jarvis
```

Replace `<YOUR_REPOSITORY_URL>` with your repository's actual Git URL.

### 2. Create a virtual environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

Install the dependencies listed in the repository's requirements file, if provided:

```bash
pip install -r requirements.txt
```

If the project uses additional virtual environments or separate model setup steps, follow the instructions in the corresponding project files.

### 4. Configure the local AI model

Install and start Ollama, then download the configured model if it is not already available:

```bash
ollama pull llama3.2:3b
```

Make sure the model name matches the configuration used by your JARVIS installation.

### 5. Start JARVIS

Use the project's actual entry point and startup instructions. For example, if `jarvis.py` is the configured entry point:

```bash
python jarvis.py
```

Model assets, audio dependencies, and microphone permissions must be configured before voice interaction will work.

## Project Structure

The project uses a modular architecture to separate intelligence, memory, routing, and desktop actions.

```text
jarvis/
├── actions/          # Desktop actions and application resolution
├── core/             # Intent routing, context, and memory
├── intelligence/     # Natural-language intent extraction
├── tests/            # Automated tests
├── models/           # Local model assets, if stored here
├── jarvis.py         # Application entry point, if configured
└── README.md
```

This is an illustrative overview. Refer to the actual repository for the complete structure.

## Privacy and Security

JARVIS is designed around local processing and user-controlled desktop automation.

- Uses locally hosted AI inference where configured.
- Does not require a paid AI API subscription for its local inference path.
- Uses validated action handlers instead of blindly executing model-generated commands.
- Should request confirmation before destructive or sensitive operations.
- May require internet access for web searches, online content, model downloads, or other external integrations.

**Offline-first does not mean every feature works offline.** Online searches and web-based integrations require connectivity, and privacy depends on the configuration of each component.

## Development and Testing

Run the project's automated tests from the repository root:

```bash
pytest
```

Use the test configuration and development instructions provided by the repository. External services and desktop actions may need to be mocked for automated testing.

## Roadmap

Potential improvements include:

- More reliable wake-word detection
- Faster speech-to-response latency
- Improved conversational context and memory
- Expanded application and file navigation
- More reliable browser and media controls
- Safer, more capable desktop automation
- Easier startup and shutdown management

## Contributing

Contributions, bug reports, and suggestions are welcome. Please open an issue to discuss significant changes before submitting a pull request.

## License

Add a license file before distributing the project. Until a license is specified, the repository's reuse and redistribution permissions are not explicitly granted.

---

**JARVIS** — Your computer, ready when you are.