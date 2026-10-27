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

# Audio Settings
SAMPLE_RATE = 16000
CHUNK_SIZE = 2048  # 128ms audio chunks at 16kHz (4x 512 samples for neural VAD)

# Voice Activity Detection (VAD) & Endpoint Detection
VAD_SPEECH_THRESHOLD = 0.50        # Neural Silero VAD speech probability threshold
VAD_SILENCE_TIMEOUT_SECONDS = 0.7  # 700ms silence to finalize speech utterance
PRE_SPEECH_BUFFER_CHUNKS = 3       # ~384ms pre-speech audio ring buffer to avoid clipping speech start
MIN_UTTERANCE_CHUNKS = 3           # Discard transient noises shorter than ~384ms
MAX_UTTERANCE_SECONDS = 15.0       # Max speech buffer length before forcing transcription

# Wake-Word & Session Timing
SESSION_TIMEOUT_SECONDS = 300  # 5 minutes active session
WAKE_WORDS = ("hey jarvis", "hi jarvis", "hello jarvis", "jarvis", "ok jarvis", "okay jarvis")
EXIT_COMMANDS = ("exit jarvis", "quit jarvis", "stop jarvis", "exit", "quit")

# Ollama Local LLM Settings
OLLAMA_API_URL = "http://localhost:11434/api/generate"
OLLAMA_MODEL = "llama3.2:3b"

JARVIS_SYSTEM_PROMPT = (
    "You are JARVIS, a concise and intelligent AI assistant inspired by Tony Stark's assistant. "
    "Always identify yourself as JARVIS if asked. Speak politely and calmly, occasionally addressing the user as 'Sir'. "
    "Keep answers brief (1 to 3 sentences maximum), suitable for a voice interface. "
    "Do not output Markdown formatting or code blocks unless explicitly requested. "
    "You operate as part of a Python voice assistant on Fedora KDE Linux. The Python program directly handles "
    "predefined desktop actions (opening Firefox, web searches, opening tabs, typing, opening Konsole, "
    "opening Downloads, and opening YouTube). For any computer action outside these predefined commands, "
    "accurately explain that Python can perform only the actions explicitly implemented in the program, and that "
    "the requested action has not been programmed yet. Never claim to have performed an action you did not perform."
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

