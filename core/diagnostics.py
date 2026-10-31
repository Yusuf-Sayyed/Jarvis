"""
Lightweight performance and latency diagnostics for JARVIS.
Tracks execution times across speech capture, Whisper transcription,
intent resolution, Ollama inference, desktop actions, Kokoro TTS generation,
and audio playback.

Detailed timings are emitted strictly when LOG_LEVEL is 'DEBUG' or
JARVIS_DEBUG is enabled; normal operating logs remain concise.
"""

import contextlib
import logging
import os
import threading
import time
from typing import Any, Optional

logger = logging.getLogger("jarvis")


def is_debug_mode() -> bool:
    """Returns True if verbose timing and diagnostics logging is enabled."""
    from core import config
    log_level = getattr(config, "LOG_LEVEL", "INFO").upper()
    tts_diag = getattr(config, "TTS_DIAGNOSTICS", False)
    env_debug = os.environ.get("JARVIS_DEBUG", "").lower() in ("1", "true", "yes")
    return log_level == "DEBUG" or tts_diag or env_debug


def configure_diagnostics_logging():
    """Configures the jarvis logger based on LOG_LEVEL and JARVIS_DEBUG settings."""
    level = logging.DEBUG if is_debug_mode() else logging.INFO
    logger.setLevel(level)
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setLevel(level)
        formatter = logging.Formatter("[JARVIS %(levelname)s] %(message)s")
        handler.setFormatter(formatter)
        logger.addHandler(handler)


def log_timing(stage: str, duration: float, details: str = ""):
    """
    Emits a lightweight timing measurement to console if DEBUG mode is enabled.
    Duration is provided in seconds.
    """
    if is_debug_mode():
        extra = f" | {details}" if details else ""
        print(f"[Timing Diagnostic] {stage}: {duration * 1000:.1f}ms{extra}")


class PipelineTimer:
    """
    Thread-local latency tracker for a single end-to-end voice interaction.
    """

    def __init__(self):
        self._timings: dict[str, float] = {}
        self._details: dict[str, str] = {}
        self._t0: float = time.perf_counter()

    def reset(self):
        self._timings.clear()
        self._details.clear()
        self._t0 = time.perf_counter()

    def record(self, stage: str, duration: float, details: str = ""):
        self._timings[stage] = duration
        if details:
            self._details[stage] = details
        log_timing(stage, duration, details)

    @contextlib.contextmanager
    def time_block(self, stage: str, details: str = ""):
        t0 = time.perf_counter()
        try:
            yield
        finally:
            elapsed = time.perf_counter() - t0
            self.record(stage, elapsed, details)

    def get_timings(self) -> dict[str, float]:
        return dict(self._timings)

    def total_elapsed(self) -> float:
        return time.perf_counter() - self._t0

    def log_summary(self, label: str = "Request Pipeline"):
        if not is_debug_mode():
            return
        parts = [f"{k}={v*1000:.1f}ms" for k, v in self._timings.items()]
        total = self.total_elapsed() * 1000
        summary_str = ", ".join(parts) if parts else "no stages recorded"
        print(f"[Timing Diagnostic | {label}] Total: {total:.1f}ms ({summary_str})")


_LOCAL = threading.local()


def get_pipeline_timer() -> PipelineTimer:
    """Returns the thread-local PipelineTimer instance."""
    if not hasattr(_LOCAL, "timer"):
        _LOCAL.timer = PipelineTimer()
    return _LOCAL.timer
