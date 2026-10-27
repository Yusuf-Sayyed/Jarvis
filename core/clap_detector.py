"""
Acoustic two-clap impulse detector for hands-free JARVIS wake triggering.
Uses local time-domain peak and crest-factor analysis without Whisper or Ollama.
"""

import time
import numpy as np
from core.config import (
    CLAP_CREST_FACTOR_MIN,
    CLAP_ENERGY_THRESHOLD,
    CLAP_MAX_ENERGY_THRESHOLD,
    CLAP_MAX_INTERVAL_SECONDS,
    CLAP_MIN_INTERVAL_SECONDS,
    CLAP_TRIGGER_ENABLED,
)


class ClapDetector:
    """
    Lightweight acoustic detector that tracks two distinct impulsive claps
    separated by a configurable time interval (default: 0.20s - 1.00s).
    """

    def __init__(
        self,
        enabled: bool = CLAP_TRIGGER_ENABLED,
        energy_threshold: int = CLAP_ENERGY_THRESHOLD,
        crest_factor_min: float = CLAP_CREST_FACTOR_MIN,
        min_interval: float = CLAP_MIN_INTERVAL_SECONDS,
        max_interval: float = CLAP_MAX_INTERVAL_SECONDS,
    ):
        self.enabled = enabled
        self.energy_threshold = energy_threshold
        self.crest_factor_min = crest_factor_min
        self.min_interval = min_interval
        self.max_interval = max_interval

        self.last_clap_time: float = 0.0
        self.clap_count: int = 0

    def reset(self):
        """Resets the two-clap state."""
        self.last_clap_time = 0.0
        self.clap_count = 0

    def is_impulse(self, data: bytes) -> bool:
        """
        Analyzes a PCM audio chunk (16-bit signed, 16kHz) for impulsive clap signature.
        Checks both absolute peak energy and crest factor (peak-to-RMS ratio).
        """
        if len(data) < 2:
            return False

        try:
            samples = np.frombuffer(data, dtype=np.int16)
        except Exception:
            return False

        if len(samples) == 0:
            return False

        peak = int(np.max(np.abs(samples)))
        if peak < self.energy_threshold or peak > CLAP_MAX_ENERGY_THRESHOLD:
            return False

        rms = float(np.sqrt(np.mean(samples.astype(np.float64) ** 2)))
        crest_factor = peak / (rms + 1e-6)

        return crest_factor >= self.crest_factor_min

    def process_chunk(self, data: bytes, current_time: float | None = None) -> bool:
        """
        Processes an incoming audio chunk from the microphone.
        Returns True if a valid two-clap trigger sequence is completed.
        """
        if not self.enabled:
            return False

        now = time.time() if current_time is None else current_time

        # Check for timeout on waiting for second clap
        if self.last_clap_time > 0.0 and (now - self.last_clap_time) > self.max_interval:
            self.reset()

        if not self.is_impulse(data):
            return False

        # First clap
        if self.last_clap_time == 0.0:
            self.last_clap_time = now
            self.clap_count = 1
            return False

        # Second clap candidate: evaluate interval
        dt = now - self.last_clap_time
        if dt < self.min_interval:
            # Too fast: acoustic bounce or echo, ignore
            return False

        if self.min_interval <= dt <= self.max_interval:
            # Valid two-clap sequence!
            self.reset()
            return True

        # dt > max_interval (already expired)
        self.last_clap_time = now
        self.clap_count = 1
        return False
