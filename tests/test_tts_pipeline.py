"""
Unit tests and pipeline validation for Speech Synthesis, Kokoro Integration, and Audio Playback.
Tests:
1. Kokoro singleton initialization and reuse.
2. Kokoro voice configuration (bm_george, en-gb, 0.95 speed).
3. Short sentence synthesis (Kokoro 24000 Hz valid WAV).
4. Long sentence synthesis without truncation.
5. Graceful fallback to espeak-ng if Kokoro fails.
6. Error recovery after synthesis or player failures (no hang, assistant survives).
7. Sequential FIFO response queueing without overlapping playback.
8. Half-duplex feedback prevention (should_mute_mic active during speech and cooldown).
"""

import os
import time
import unittest
from unittest.mock import MagicMock, patch

import core.config as config
import interfaces.speech as speech_mod


class TestTTSPipeline(unittest.TestCase):

    def setUp(self):
        speech_mod.reset_speech_state()

    def tearDown(self):
        speech_mod.reset_speech_state()

    def test_kokoro_engine_singleton_reuse(self):
        """Kokoro model loads once and reuses the singleton instance across calls."""
        engine1 = speech_mod.get_kokoro_engine()
        self.assertIsNotNone(engine1)
        engine2 = speech_mod.get_kokoro_engine()
        self.assertIs(engine1, engine2, "Kokoro engine must be a reused singleton")

    def test_kokoro_voice_configuration(self):
        """Verify default voice configuration matches requirements (bm_fable, en-gb, 1.15 speed)."""
        self.assertEqual(config.KOKORO_VOICE, "bm_fable")
        self.assertEqual(config.KOKORO_LANG, "en-gb")
        self.assertEqual(config.KOKORO_SPEED, 1.15)
        self.assertTrue(config.KOKORO_MODEL_PATH.is_file(), f"Model missing: {config.KOKORO_MODEL_PATH}")
        self.assertTrue(config.KOKORO_VOICES_PATH.is_file(), f"Voices missing: {config.KOKORO_VOICES_PATH}")

    def test_short_sentence_synthesis_kokoro(self):
        """Short sentence synthesizes to valid WAV with 24000 Hz sample rate and expected duration."""
        wav_path, rate, duration = speech_mod._synthesize_to_wav("Hello Sir.")
        try:
            self.assertIsNotNone(wav_path)
            self.assertTrue(os.path.isfile(wav_path))
            self.assertEqual(rate, 24000)
            self.assertGreater(duration, 0.3)
            self.assertLess(duration, 3.0)
        finally:
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)

    def test_long_sentence_synthesis_no_truncation(self):
        """Long sentence synthesizes completely without truncation or dropped frames."""
        long_text = (
            "I have processed your request, Sir. All security protocols are verified, "
            "the system status report indicates complete operational stability, "
            "and all peripheral devices are responding within standard parameters."
        )
        wav_path, rate, duration = speech_mod._synthesize_to_wav(long_text)
        try:
            self.assertIsNotNone(wav_path)
            self.assertTrue(os.path.isfile(wav_path))
            self.assertEqual(rate, 24000)
            # A ~35-word sentence should take ~10-18 seconds with Kokoro at 0.95 speed
            self.assertGreater(duration, 8.0)
            self.assertLess(duration, 25.0)
        finally:
            if wav_path and os.path.exists(wav_path):
                os.unlink(wav_path)

    def test_fallback_to_espeak_when_kokoro_fails(self):
        """If Kokoro synthesis fails, automatically fall back to secondary TTS (espeak-ng at 22050 Hz)."""
        with patch("interfaces.speech._synthesize_kokoro", return_value=False):
            wav_path, rate, duration = speech_mod._synthesize_to_wav("Fallback test sentence.")
            try:
                self.assertIsNotNone(wav_path)
                self.assertTrue(os.path.isfile(wav_path))
                self.assertEqual(rate, 22050)
                self.assertGreater(duration, 0.5)
            finally:
                if wav_path and os.path.exists(wav_path):
                    os.unlink(wav_path)

    def test_total_synthesis_failure_handling(self):
        """If all engines fail, gracefully return (None, 0, 0.0) without crashing."""
        with patch("interfaces.speech._synthesize_kokoro", return_value=False), \
             patch("interfaces.speech._synthesize_piper", return_value=False), \
             patch("interfaces.speech._synthesize_espeak", return_value=False):
            wav_path, rate, duration = speech_mod._synthesize_to_wav("Total failure test.")
            self.assertIsNone(wav_path)
            self.assertEqual(rate, 0)
            self.assertEqual(duration, 0.0)

    def test_sequential_responses_queued_in_order(self):
        """Multiple speak calls must be processed sequentially in exact FIFO order."""
        call_order = []

        def fake_play(path, dur):
            call_order.append(path)
            time.sleep(0.05)
            return True

        with patch("interfaces.speech._synthesize_to_wav") as mock_synth, \
             patch("interfaces.speech._play_wav_file", side_effect=fake_play), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):

            mock_synth.side_effect = [
                ("/tmp/item1.wav", 24000, 0.1),
                ("/tmp/item2.wav", 24000, 0.1),
                ("/tmp/item3.wav", 24000, 0.1),
            ]

            os.environ.pop("JARVIS_TEST_MODE", None)
            try:
                ok1 = speech_mod.speak("Item one", block=True)
                ok2 = speech_mod.speak("Item two", block=True)
                ok3 = speech_mod.speak("Item three", block=True)

                self.assertTrue(ok1)
                self.assertTrue(ok2)
                self.assertTrue(ok3)
                self.assertEqual(call_order, ["/tmp/item1.wav", "/tmp/item2.wav", "/tmp/item3.wav"])
            finally:
                os.environ["JARVIS_TEST_MODE"] = "1"

    def test_playback_error_recovery(self):
        """If player fails with an error, the pipeline recovers and does not hang."""
        with patch("interfaces.speech._synthesize_to_wav", return_value=("/tmp/err.wav", 24000, 1.0)), \
             patch("interfaces.speech._play_wav_file", return_value=False), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"):

            os.environ.pop("JARVIS_TEST_MODE", None)
            try:
                ok = speech_mod.speak("Error test", block=True)
                self.assertFalse(ok)
                self.assertFalse(speech_mod.is_speaking())
                self.assertTrue(speech_mod.is_in_cooldown())
            finally:
                os.environ["JARVIS_TEST_MODE"] = "1"

    def test_feedback_prevention_during_playback_and_cooldown(self):
        """Microphone muting must remain active during speech and subsequent cooldown."""
        speech_mod.set_cooldown(0.5)
        self.assertTrue(speech_mod.is_in_cooldown())
        self.assertTrue(speech_mod.should_mute_mic())
        self.assertGreater(speech_mod.get_cooldown_remaining(), 0.0)

        speech_mod.reset_speech_state()
        self.assertFalse(speech_mod.is_in_cooldown())
        self.assertFalse(speech_mod.should_mute_mic())


if __name__ == "__main__":
    unittest.main()
