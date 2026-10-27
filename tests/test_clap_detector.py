"""
Unit tests for Acoustic Two-Clap Wake Trigger:
1. Two valid claps within interval (0.2s - 1.0s).
2. Single clap rejection (times out without triggering).
3. Two claps too fast (< 0.20s bounce/echo rejection).
4. Two claps too slow (> 1.00s timeout).
5. Speech rejection (sustained energy, low crest factor).
6. Background noise and low-amplitude typing rejection.
7. Disabled detector configuration.
"""

import unittest
import numpy as np
from core.clap_detector import ClapDetector


def make_clap_chunk(peak: int = 15000) -> bytes:
    """Generates an impulsive acoustic clap chunk (high peak, low RMS)."""
    chunk = np.random.normal(0, 50, 2048).astype(np.float32)
    decay = np.exp(-np.linspace(0, 8, 480))
    spike = np.sin(np.linspace(0, 50, 480)) * decay * peak
    chunk[400:880] += spike
    return np.clip(chunk, -32767, 32767).astype(np.int16).tobytes()


def make_speech_chunk(peak: int = 15000) -> bytes:
    """Generates a continuous speech vowel chunk (high peak, high RMS, low crest factor)."""
    t = np.linspace(0, 0.128, 2048)
    wave = np.sin(2 * np.pi * 220 * t) + 0.6 * np.sin(2 * np.pi * 440 * t)
    wave = (wave / np.max(np.abs(wave))) * peak
    return wave.astype(np.int16).tobytes()


def make_quiet_noise_chunk(peak: int = 1500) -> bytes:
    """Generates low-amplitude room noise or keyboard typing clicks."""
    return np.random.randint(-peak, peak, 2048, dtype=np.int16).tobytes()


class TestClapDetector(unittest.TestCase):

    def setUp(self):
        self.detector = ClapDetector(
            enabled=True,
            energy_threshold=7500,
            crest_factor_min=3.2,
            min_interval=0.20,
            max_interval=1.00,
        )

    def test_two_valid_claps_triggers_activation(self):
        """Two sharp claps 500ms apart must trigger wake activation."""
        clap1 = make_clap_chunk(peak=16000)
        clap2 = make_clap_chunk(peak=17000)

        # Clap 1 at t = 100.0s
        res1 = self.detector.process_chunk(clap1, current_time=100.0)
        self.assertFalse(res1, "First clap should not trigger alone")
        self.assertEqual(self.detector.clap_count, 1)

        # Silence at t = 100.25s
        res_silence = self.detector.process_chunk(make_quiet_noise_chunk(), current_time=100.25)
        self.assertFalse(res_silence)

        # Clap 2 at t = 100.50s (dt = 0.50s, within 0.20s - 1.00s)
        res2 = self.detector.process_chunk(clap2, current_time=100.50)
        self.assertTrue(res2, "Second clap within interval must trigger activation")
        self.assertEqual(self.detector.clap_count, 0)

    def test_single_clap_rejected_on_timeout(self):
        """A single clap without a follow-up clap must time out and not activate."""
        clap = make_clap_chunk(peak=16000)

        # Clap 1 at t = 100.0s
        self.detector.process_chunk(clap, current_time=100.0)
        self.assertEqual(self.detector.clap_count, 1)

        # Silence at t = 101.10s (> 1.0s timeout)
        self.detector.process_chunk(make_quiet_noise_chunk(), current_time=101.10)
        self.assertEqual(self.detector.clap_count, 0)
        self.assertEqual(self.detector.last_clap_time, 0.0)

    def test_claps_too_fast_rejected_as_bounce(self):
        """Two claps < 0.20s apart (e.g. 50ms echo) must be ignored as acoustic reflections."""
        clap1 = make_clap_chunk(peak=16000)
        clap2 = make_clap_chunk(peak=15000)

        self.detector.process_chunk(clap1, current_time=100.0)
        res = self.detector.process_chunk(clap2, current_time=100.08)  # dt = 0.08s
        self.assertFalse(res, "Clap too fast must not trigger")
        self.assertEqual(self.detector.clap_count, 1)

    def test_claps_too_slow_resets_and_treats_as_new_clap(self):
        """Two claps > 1.00s apart should not trigger, second clap becomes new first clap."""
        clap1 = make_clap_chunk(peak=16000)
        clap2 = make_clap_chunk(peak=15000)

        self.detector.process_chunk(clap1, current_time=100.0)
        res = self.detector.process_chunk(clap2, current_time=101.50)  # dt = 1.50s
        self.assertFalse(res, "Clap too slow must not trigger")
        # clap2 is now candidate #1
        self.assertEqual(self.detector.clap_count, 1)
        self.assertEqual(self.detector.last_clap_time, 101.50)

    def test_speech_rejected_due_to_crest_factor(self):
        """Loud spoken voice vowels have low crest factor and must NOT trigger clap detection."""
        speech = make_speech_chunk(peak=18000)
        res = self.detector.process_chunk(speech, current_time=100.0)
        self.assertFalse(res, "Speech must not trigger clap impulse")
        self.assertEqual(self.detector.clap_count, 0)

    def test_background_typing_rejected(self):
        """Low amplitude typing clicks below energy threshold must not trigger."""
        noise = make_quiet_noise_chunk(peak=2500)
        res = self.detector.process_chunk(noise, current_time=100.0)
        self.assertFalse(res)
        self.assertEqual(self.detector.clap_count, 0)

    def test_disabled_detector(self):
        """When disabled via config, clap detector returns False immediately."""
        self.detector.enabled = False
        clap1 = make_clap_chunk(peak=16000)
        clap2 = make_clap_chunk(peak=16000)

        self.assertFalse(self.detector.process_chunk(clap1, current_time=100.0))
        self.assertFalse(self.detector.process_chunk(clap2, current_time=100.5))


if __name__ == "__main__":
    unittest.main()
