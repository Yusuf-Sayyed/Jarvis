"""
Configuration settings and constants for JARVIS.
"""

from pathlib import Path

# Paths
BASE_DIR = Path(__file__).resolve().parent.parent

# Speech Recognition Engine: "whisper" or "vosk"
STT_ENGINE = "whisper"

# Whisper STT Settings (High accuracy, local offline transcription)
WHISPER_MODEL_NAME = "base.en"
WHISPER_COMPUTE_TYPE = "int8"
WHISPER_DEVICE = "cpu"
WHISPER_MODEL_DIR = BASE_DIR / "models" / "whisper"

# Vosk Rollback / Fallback Paths (Preserved for 1-click rollback)
MODEL_DIR = BASE_DIR / "models" / "vosk-model-en-us-0.22-lgraph"
FALLBACK_MODEL_DIR = BASE_DIR / "vosk-model-small-en-us-0.15"

# Text-to-Speech (TTS) & Feedback Prevention Settings
TTS_ENGINE = "auto"  # "auto" prioritizes kokoro, then piper, falling back to espeak-ng

# Kokoro Neural TTS Settings (Natural British English Voice)
KOKORO_MODEL_PATH = BASE_DIR / "models" / "kokoro" / "kokoro-v1.0.onnx"
KOKORO_VOICES_PATH = BASE_DIR / "models" / "kokoro" / "voices-v1.0.bin"
KOKORO_VOICE = "bm_george"
KOKORO_LANG = "en-gb"
KOKORO_SPEED = 0.95

# Piper Neural TTS Settings (Preserved fallback)
PIPER_BIN_PATH = BASE_DIR / "bin" / "piper"
PIPER_MODEL_PATH = BASE_DIR / "models" / "piper" / "en_GB-alan-medium.onnx"

# eSpeak-ng Fallback Settings
TTS_ESPEAK_VOICE = "en-gb-x-rp"         # Stable British English Received Pronunciation
TTS_ESPEAK_SPEED = 150                  # Natural measured assistant cadence (WPM)
TTS_ESPEAK_PITCH = 50                   # Center resonant pitch (prevents formant breaking/distortion)
TTS_DIAGNOSTICS = True                  # Concise TTS pipeline diagnostics (engine, duration, player, timing)
POST_SPEECH_COOLDOWN_SECONDS = 0.5      # 500ms post-speech cooldown to suppress room reverb feedback
TTS_MAX_TIMEOUT_SECONDS = 25.0          # Safety timeout preventing indefinite audio lock

# Audio Settings
SAMPLE_RATE = 16000
CHUNK_SIZE = 2048  # 128ms audio chunks at 16kHz (4x 512 samples for neural VAD)

# Voice Activity Detection (VAD) & Endpoint Detection
VAD_SPEECH_THRESHOLD = 0.50        # Neural Silero VAD speech probability threshold
VAD_SILENCE_TIMEOUT_SECONDS = 0.85 # 850ms silence to finalize speech utterance (prevents mid-sentence clipping)
PRE_SPEECH_BUFFER_CHUNKS = 4       # ~512ms pre-speech audio ring buffer to avoid clipping speech start
MIN_UTTERANCE_CHUNKS = 3           # Discard transient noises shorter than ~384ms
MAX_UTTERANCE_SECONDS = 15.0       # Max speech buffer length before forcing transcription

# Wake-Word & Session Timing
SESSION_TIMEOUT_SECONDS = 300  # 5 minutes active session
WAKE_WORDS = (
    "hey jarvis",
    "wake up jarvis",
    "wake up, jarvis",
    "hello jarvis",
    "jarvis",
    "hi jarvis",
    "ok jarvis",
    "okay jarvis",
)
STANDALONE_WAKE_UP_ENABLED = True  # Allows "wake up" alone as a direct imperative command

# Two-Clap Wake Trigger Settings
CLAP_TRIGGER_ENABLED = True          # Enable/disable acoustic two-clap wake trigger
CLAP_ENERGY_THRESHOLD = 7500        # Minimum peak PCM amplitude (0-32767) for impulsive clap
CLAP_MIN_INTERVAL_SECONDS = 0.20    # Minimum interval between claps (200ms rejects bounces/echoes)
CLAP_MAX_INTERVAL_SECONDS = 1.00    # Maximum interval between claps (1000ms timeout)
CLAP_CREST_FACTOR_MIN = 3.2         # Peak-to-RMS ratio (distinguishes claps from sustained speech/vowels)
CLAP_MAX_ENERGY_THRESHOLD = 32500   # Avoid clipping saturation artifacts

# Activation Greetings Pool (spoken once on new session activation)
ACTIVATION_GREETINGS = (
    "Hello, Sir. How can I help you?",
    "I'm listening, Sir. What can I do for you?",
    "At your service, Sir.",
    "Yes, Sir. How may I assist?",
)
GREET_ON_STANDALONE_WAKE = True     # Speak greeting when activated via wake-word or claps without inline command

EXIT_COMMANDS = (
    "exit jarvis", "quit jarvis", "stop jarvis", "exit", "quit",
    "goodbye jarvis", "goodbye", "bye jarvis", "bye", "see ya", "cya", "hello cya"
)


# Ollama Local LLM Settings
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"

JARVIS_SYSTEM_PROMPT = (
    "You are JARVIS, a concise and intelligent AI assistant inspired by Tony Stark's assistant. "
    "Always identify yourself as JARVIS if asked. Speak politely and calmly, occasionally addressing the user as 'Sir'. "
    "Keep answers brief (1 to 3 sentences maximum), suitable for a voice interface. "
    "Do not output Markdown formatting or code blocks unless explicitly requested. "
    "Answer general knowledge, factual, technical, and conversational questions accurately and helpfully using your knowledge. "
    "You operate as part of a Python voice assistant on Fedora KDE Linux with support for desktop navigation, media playback, custom workflows, and real-time web search. "
    "Only if the user asks you to perform an unsupported computer command or control an unsupported application, explain politely that the capability has not been programmed yet."
)


# Real-Time Web Search Settings (Stage 5)
WEB_SEARCH_PROVIDER = "ddgs"  # Options: "ddgs" (Python package) or "direct" (Built-in keyless HTTP fallback)
WEB_SEARCH_MAX_RESULTS = 3
WEB_SEARCH_TIMEOUT_SECONDS = 8
OLLAMA_GROUNDED_TIMEOUT_SECONDS = 40

GROUNDED_SEARCH_SYSTEM_PROMPT = (
    "You are JARVIS, a concise and intelligent AI assistant. "
    "You are provided with real-time web search evidence to answer the user's question. "
    "Do NOT say you cannot access real-time information or that you are an AI without internet access. "
    "Answer the user's question directly, concisely, and factually (1 to 3 sentences maximum) using ONLY the provided evidence. "
    "Mention key source names (e.g. 'According to Reuters') and dates when available. "
    "If the search evidence is insufficient, clearly state that the available search results do not provide enough information. "
    "Do not include URLs in the spoken text."
)

