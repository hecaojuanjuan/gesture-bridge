import io
import json
from pathlib import Path
import sys
import queue
import unittest
from contextlib import redirect_stdout
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from probe_gesture_agent import Evidence, challenge, main, run_probe
from gesture_agent_bridge import BridgeError, Device


class ProbeTests(unittest.TestCase):
    def test_echo_and_asr_cannot_pass_as_model_reply(self):
        evidence = Evidence("GB12345678")
        evidence.feed("asr final=1 text=编号 GB12345678，答案是42。")
        self.assertFalse(evidence.matched)
        evidence.feed("tts final=1 text=" + challenge("GB12345678"))
        self.assertFalse(evidence.matched)
        evidence.feed("agent text final=1 text=编号 GB87654321，答案是42。")
        self.assertFalse(evidence.matched)

    def test_reply_and_completion_must_match_current_generation(self):
        evidence = Evidence("GB12345678")
        evidence.feed("tts playback started generation=7")
        evidence.feed("tts final=0 text=编号 GB1234")
        evidence.feed("tts final=0 text=5678，答案是42。")
        self.assertTrue(evidence.matched)
        evidence.feed("tts playback complete generation=6")
        self.assertFalse(evidence.complete)
        evidence.feed("tts playback complete generation=7")
        self.assertTrue(evidence.complete)
        self.assertFalse(evidence.result()["physical_audio_verified"])

    def test_restart_and_overlapping_audio_remain_failures(self):
        evidence = Evidence("GB12345678")
        evidence.feed("tts playback started generation=7")
        evidence.feed("tts playback started generation=8")
        self.assertEqual(evidence.failure, "multiple_playback_generations")
        evidence.feed("***ERROR*** A stack overflow in task prov_rst has been detected.")
        self.assertEqual(evidence.failure, "multiple_playback_generations")

    def test_answer_requires_exact_numeric_boundary(self):
        for answer in ("420", "42.5", "42．5", "425", "-42", "142"):
            with self.subTest(answer=answer):
                evidence = Evidence("GB12345678")
                evidence.feed("tts final=1 text=编号 GB12345678，答案是" + answer + "。")
                self.assertFalse(evidence.matched)
        evidence = Evidence("GB12345678")
        evidence.feed("tts final=1 text=编号 GB12345678，答案不是42。")
        self.assertFalse(evidence.matched)
        for tail in ("0。", ".5。"):
            evidence = Evidence("GB12345678")
            evidence.feed("tts final=0 text=编号 GB12345678，答案是42")
            self.assertFalse(evidence.matched)
            evidence.feed("tts final=1 text=" + tail)
            self.assertFalse(evidence.matched)

    def test_real_agora_chunks_finish_at_silent_without_final_flag(self):
        # Sanitized response/lifecycle excerpt from route-local-wdt.jsonl,
        # 2026-11-01. Neither response chunk had final=1 or final punctuation.
        evidence = Evidence("GB8D2F07C3", require_ready=True)
        for line in (
            '[029828]<I> dialog=silent',
            'HG_PROBE {"v":1,"marker":"GB8D2F07C3","state":"ready","code":0}',
            '[047612]<I> tts playback started generation=2',
            'HG_PROBE {"v":1,"marker":"GB8D2F07C3","state":"speaking","code":0}',
            '[047942]<I> tts final=0 text=编号 GB8D2F07C3，',
            '[048567]<I> tts final=0 text=答案是42',
        ):
            evidence.feed(line)
        self.assertFalse(evidence.matched)
        evidence.feed('[052567]<I> dialog=silent')
        evidence.feed('HG_PROBE {"v":1,"marker":"GB8D2F07C3","state":"failed","code":-8}')
        evidence.feed('HG_PROBE {"v":1,"marker":"GB8D2F07C3","state":"ended","code":0}')
        result = evidence.result()
        self.assertTrue(result["matching_agent_reply_observed"])
        self.assertTrue(result["matching_tts_reply_observed"])
        self.assertTrue(result["playback_started_observed"])
        self.assertFalse(result["playback_generation_completed_observed"])
        self.assertEqual(result["failure"], "probe_failed")
        self.assertFalse(result["physical_audio_verified"])

    def test_answer_first_accepts_exact_marker_and_turn_boundary(self):
        for prefix in ("计算结果是42，编号 ", "答案为42，本次编号为 "):
            for channel in ("tts", "agent text"):
                with self.subTest(prefix=prefix, channel=channel):
                    evidence = Evidence("GB12345678")
                    evidence.feed(channel + " final=0 text=" + prefix + "GB1234")
                    evidence.feed(channel + " final=0 text=5678")
                    self.assertFalse(evidence.matched)
                    evidence.feed("dialog=silent")
                    self.assertTrue(evidence.matched)
                    self.assertEqual(evidence.tts_matched, channel == "tts")
                    self.assertFalse(evidence.complete)
        for text in ("计算结果是420，编号 GB12345678",
                     "计算结果是42.5，编号 GB12345678",
                     "计算结果是42．5，编号 GB12345678",
                     "计算结果是-42，编号 GB12345678",
                     "计算结果不是42，编号 GB12345678",
                     "计算结果是42，编号 GB123456789",
                     "计算结果是42，编号 XGB12345678"):
            with self.subTest(text=text):
                evidence = Evidence("GB12345678")
                evidence.feed("tts final=0 text=" + text)
                evidence.feed("dialog=silent")
                self.assertFalse(evidence.matched)

    def test_later_chunks_revoke_numeric_or_marker_prefix_matches(self):
        for boundary in ("final", "silent"):
            for tail in ("0", ".5", "．5"):
                with self.subTest(boundary=boundary, tail=tail):
                    evidence = Evidence("GB12345678")
                    evidence.feed("tts final=" + ("1" if boundary == "final" else "0") +
                                  " text=编号 GB12345678，答案是42")
                    if boundary == "silent":
                        evidence.feed("dialog=silent")
                    self.assertTrue(evidence.matched)
                    evidence.feed("tts final=1 text=" + tail)
                    evidence.feed("dialog=silent")
                    self.assertFalse(evidence.matched)
                    self.assertFalse(evidence.tts_matched)
        evidence = Evidence("GB12345678")
        evidence.feed("tts final=1 text=计算结果是42，编号 GB12345678")
        self.assertTrue(evidence.matched)
        evidence.feed("tts final=1 text=9")
        self.assertFalse(evidence.matched)

    def test_playback_completion_is_independent_of_transcript(self):
        evidence = Evidence("GB12345678")
        evidence.feed("tts playback started generation=7")
        evidence.feed("agent text final=1 text=编号 GB12345678，答案是42。")
        evidence.feed("tts playback complete generation=7")
        result = evidence.result()
        self.assertTrue(result["matching_agent_reply_observed"])
        self.assertFalse(result["matching_tts_reply_observed"])
        self.assertTrue(result["playback_generation_completed_observed"])
        self.assertNotIn("matching_generation_completed_observed", result)

    def test_unrelated_ready_and_greeting_cannot_unlock_request(self):
        serial = FakeSerial(ready_marker="GB87654321")
        calls = []
        result = run_probe(lambda *_: calls.append(1), Device("unused", 1, "2"),
                           "GB12345678", serial, seconds=0, ready_seconds=0.03,
                           cleanup_seconds=0.03)
        self.assertEqual(calls, [])
        self.assertFalse(result["request_sent"])
        self.assertEqual(result["failure"], "probe_readiness_timeout")
        self.assertEqual(serial.commands, ["hg_agent probe GB12345678", "hg_agent abort GB12345678"])

    def test_no_http_until_matching_diagnostic_ready_then_one_request(self):
        serial = FakeSerial()
        calls = []
        def send(*_):
            self.assertEqual(serial.commands, ["hg_agent probe GB12345678"])
            calls.append(1)
            serial.enqueue("tts playback started generation=7")
            serial.enqueue("tts final=1 text=编号 GB12345678，答案是42。")
            serial.enqueue("tts playback complete generation=7")
            serial.enqueue('HG_PROBE {"v":1,"marker":"GB12345678","state":"ended","code":0}')
        result = run_probe(send, Device("unused", 1, "2"), "GB12345678", serial,
                           seconds=0.1, ready_seconds=0.1, cleanup_seconds=0.03)
        self.assertEqual(calls, [1])
        self.assertTrue(result["diagnostic_session_ready"])
        self.assertTrue(result["diagnostic_session_ended"])
        self.assertTrue(result["matching_tts_reply_observed"])
        self.assertIsNone(result["failure"])
        self.assertEqual(len(serial.commands), 1)

    def test_busy_session_prevents_http_and_abort_is_marker_scoped(self):
        serial = FakeSerial(state="busy")
        calls = []
        result = run_probe(lambda *_: calls.append(1), Device("unused", 1, "2"),
                           "GB12345678", serial, seconds=0, ready_seconds=0.1,
                           cleanup_seconds=0.03)
        self.assertEqual(calls, [])
        self.assertEqual(result["failure"], "probe_busy")

    def test_failed_request_never_retries_or_claims_audio(self):
        calls = []
        def send(device, prompt):
            calls.append(prompt)
            raise BridgeError(502, "upstream_unconfirmed")
        result = run_probe(send, Device("unused", 11785, "100000766"), "GB12345678")
        self.assertEqual(len(calls), 1)
        self.assertFalse(result["http_accepted"])
        self.assertFalse(result["matching_agent_reply_observed"])
        self.assertFalse(result["physical_audio_verified"])

    def test_default_preflight_has_no_network_or_secret_output(self):
        output = io.StringIO()
        with patch.dict("os.environ", {"LJYD_MERCHANT_TOKEN": "private-test-value"}), \
             patch("probe_gesture_agent.LjydChat") as chat, redirect_stdout(output):
            self.assertEqual(main(["--pid", "11785", "--did", "100000766"]), 0)
        chat.assert_not_called()
        self.assertNotIn("private-test-value", output.getvalue())
        self.assertFalse(json.loads(output.getvalue())["request_sent"])


class FakeSerial:
    def __init__(self, ready_marker="GB12345678", state="ready"):
        self.pending = queue.Queue()
        self.commands = []
        self.marker, self.state = ready_marker, state

    def reset_input_buffer(self): pass
    def flush(self): pass
    def enqueue(self, line): self.pending.put((line + "\n").encode())
    def read(self, _size):
        try: return self.pending.get(timeout=0.005)
        except queue.Empty: return b""
    def write(self, data):
        command = data.decode().strip()
        self.commands.append(command)
        if command.startswith("hg_agent probe"):
            # Greeting belongs to the connect phase and must not poison the
            # eventual reply's generation or satisfy its transcript evidence.
            self.enqueue("tts playback started generation=1")
            self.enqueue("tts playback complete generation=1")
            self.enqueue("HG_PROBE " + json.dumps({"v": 1, "marker": self.marker,
                                                   "state": self.state, "code": 0}))
        else:
            self.enqueue('HG_PROBE {"v":1,"marker":"GB12345678","state":"ended","code":0}')
        return len(data)


if __name__ == "__main__":
    unittest.main()
