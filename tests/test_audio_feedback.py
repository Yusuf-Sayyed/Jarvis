"""
Tests for Half-Duplex Audio Feedback Prevention and Speech Engine:
1. Microphone input being ignored during TTS playback and cooldown.
2. Listening resuming normally after playback completes or fails.
3. No overlapping TTS playback (concurrency lock).
4. Audio buffers and pre-buffers being cleared safely.
5. Existing time/date commands working without web search or self-feedback.
6. Spoken responses not being processed as new user commands.
"""

import os
import time
import unittest
from unittest.mock import MagicMock, patch

from core.context import get_conversation_context
from core.intent import detect_intent, is_current_info_query
from core.listener import SpeechRecognizer
from core.router import route_command
import interfaces.speech as speech_mod


class TestAudioFeedback(unittest.TestCase):

    def setUp(self):
        os.environ["JARVIS_TEST_MODE"] = "1"
        self.context = get_conversation_context()
        self.context.clear_pending()
        speech_mod.reset_speech_state()

    def tearDown(self):
        speech_mod.reset_speech_state()
        self.context.clear_pending()

    def test_microphone_ignored_during_tts_playback(self):
        """Microphone input must be completely suppressed while JARVIS is speaking."""
        listener = SpeechRecognizer(engine="whisper")
        listener.vad_model = None  # Force energy VAD for predictable test
        dummy_audio = b"\x50\x20" * 1024  # High amplitude audio chunk (simulating speaker output)

        # 1. Normal state: audio is processed
        speech_mod._IS_SPEAKING = False
        speech_mod._COOLDOWN_UNTIL = 0.0
        self.assertFalse(speech_mod.should_mute_mic())

        # 2. Activate TTS playback: mic should be muted
        speech_mod._IS_SPEAKING = True
        self.assertTrue(speech_mod.should_mute_mic())

        # Any audio frame received during speech must return None and keep buffers clean
        result = listener.process_audio(dummy_audio, session_active=True)
        self.assertIsNone(result)
        self.assertEqual(len(listener.speech_frames), 0)
        self.assertFalse(listener.speech_active)

    def test_microphone_ignored_during_cooldown(self):
        """Microphone input must be suppressed during post-speech cooldown to eliminate room reverb."""
        listener = SpeechRecognizer(engine="whisper")
        dummy_audio = b"\x50\x20" * 1024

        speech_mod._IS_SPEAKING = False
        speech_mod.set_cooldown(0.5)  # 500ms cooldown
        self.assertTrue(speech_mod.is_in_cooldown())
        self.assertTrue(speech_mod.should_mute_mic())

        result = listener.process_audio(dummy_audio, session_active=True)
        self.assertIsNone(result)
        self.assertEqual(len(listener.speech_frames), 0)

    def test_listening_resumes_after_cooldown_expires(self):
        """Once cooldown elapses, listener smoothly transitions back to processing speech."""
        listener = SpeechRecognizer(engine="whisper")
        dummy_audio = b"\x00\x00" * 1024

        # Set very brief cooldown (10ms)
        speech_mod._IS_SPEAKING = False
        speech_mod.set_cooldown(0.01)
        time.sleep(0.02)
        self.assertFalse(speech_mod.should_mute_mic())

        # Listener should now process frames without dropping
        listener.process_audio(dummy_audio, session_active=True)
        self.assertEqual(len(listener.pre_buffer), 1)

    def test_safe_state_restoration_on_playback_failure(self):
        """If TTS synthesis or audio playback throws an exception, is_speaking must be restored to False."""
        speech_mod._IS_SPEAKING = True
        try:
            # Simulate crash inside speech execution
            with patch("subprocess.Popen", side_effect=RuntimeError("Audio hardware failure")):
                os.environ.pop("JARVIS_TEST_MODE", None)
                speech_mod.speak("Test speech error recovery", block=True)
        except Exception:
            pass
        finally:
            os.environ["JARVIS_TEST_MODE"] = "1"

        # Even after failure, is_speaking MUST be False so JARVIS is not permanently silenced
        self.assertFalse(speech_mod.is_speaking())
        self.assertTrue(speech_mod.is_in_cooldown())  # Safe cooldown applied

    def test_no_overlapping_tts_playback(self):
        """Concurrent or rapid speak calls must be serialized via the queue and not overlap."""
        mock_proc1 = MagicMock()
        mock_proc1.communicate.return_value = ("", "")
        mock_proc1.returncode = 0
        mock_proc1.pid = 99991

        mock_proc2 = MagicMock()
        mock_proc2.communicate.return_value = ("", "")
        mock_proc2.returncode = 0
        mock_proc2.pid = 99992

        with patch("shutil.which", return_value="/usr/bin/pw-play"), \
             patch("interfaces.speech._synthesize_to_wav", side_effect=[
                 ("/tmp/mock1.wav", 22050, 1.5),
                 ("/tmp/mock2.wav", 22050, 2.0),
             ]), \
             patch("os.path.isfile", return_value=True), \
             patch("os.path.exists", return_value=True), \
             patch("os.unlink"), \
             patch("subprocess.Popen", side_effect=[mock_proc1, mock_proc2]) as mock_popen:
            os.environ.pop("JARVIS_TEST_MODE", None)
            try:
                # Enqueue two statements in rapid succession
                ok1 = speech_mod.speak("First statement", block=True)
                ok2 = speech_mod.speak("Second statement", block=True)

                self.assertTrue(ok1)
                self.assertTrue(ok2)
                # Both processes were invoked sequentially via the queue
                self.assertEqual(mock_popen.call_count, 2)
            finally:
                os.environ["JARVIS_TEST_MODE"] = "1"
                speech_mod.reset_speech_state()

    def test_stop_speech_halts_active_playback_and_clears_queue(self):
        """stop_speech must terminate any active player and drain pending queue items."""
        mock_proc = MagicMock()
        mock_proc.poll.return_value = None

        with speech_mod._STATE_LOCK:
            speech_mod._ACTIVE_PROC = mock_proc
            speech_mod._IS_SPEAKING = True
            speech_mod._SPEECH_QUEUE.put(speech_mod._SpeechJob("q1", "q1", False))
            speech_mod._SPEECH_QUEUE.put(speech_mod._SpeechJob("q2", "q2", False))

        speech_mod.stop_speech()

        mock_proc.terminate.assert_called_once()
        self.assertTrue(speech_mod._SPEECH_QUEUE.empty())
        self.assertFalse(speech_mod.is_speaking())
        self.assertTrue(speech_mod.is_in_cooldown())

    def test_buffer_clearing_integrity(self):
        """SpeechRecognizer.reset_buffers cleanly wipes speech frames and pre-buffers."""
        listener = SpeechRecognizer(engine="whisper")
        listener.speech_frames = [b"chunk1", b"chunk2"]
        listener.pre_buffer.append(b"pre1")
        listener.speech_active = True
        listener.silence_start_time = 12345.0

        listener.reset_buffers()
        self.assertEqual(len(listener.speech_frames), 0)
        self.assertEqual(len(listener.pre_buffer), 0)
        self.assertFalse(listener.speech_active)
        self.assertIsNone(listener.silence_start_time)

    def test_spoken_response_not_sent_to_web_search(self):
        """
        Regression test: When JARVIS answers 'What time is it?', the spoken answer
        must not loop back into the listener or trigger web search.
        """
        # 1. User asks time
        intent, params = detect_intent("What time is it?")
        self.assertEqual(intent, "TIME_DATE_QUERY")

        # 2. Router generates answer and calls speak()
        with patch("intelligence.web_search.handle_current_info_query") as mock_web:
            cont, pending = route_command("What time is it?")
            self.assertTrue(cont)
            self.assertIsNone(pending)
            spoken = speech_mod.get_last_spoken()
            self.assertIn("The current time is", spoken)

            # Ensure web search was NOT called for original question
            mock_web.assert_not_called()

        # 3. Simulate microphone picking up the spoken answer ("The current time is 8:26 PM, Sir.")
        # If mic is muted during speech, process_audio drops it
        listener = SpeechRecognizer(engine="whisper")
        speech_mod._IS_SPEAKING = True
        mic_pickup = listener.process_audio(b"\x50\x20" * 1024, session_active=True)
        self.assertIsNone(mic_pickup)

    def test_clean_text_for_speech_formatting(self):
        """Markdown, URLs, and formatting characters must be cleaned before vocalization."""
        raw = "Here is **bold text** with a [link](https://example.com) and `code`!"
        cleaned = speech_mod.clean_text_for_speech(raw)
        self.assertEqual(cleaned, "Here is bold text with a link and code!")


if __name__ == "__main__":
    unittest.main()
