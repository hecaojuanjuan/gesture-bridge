"""Probe the candidate physical-device text route without deploying a bridge.

Default: check credential presence only. --send sends exactly one synthetic
prompt. With --port, first open an owned diagnostic session and wait for its
matching ready record. Never retries. Serial evidence is not physical hearing.
"""
import argparse
import datetime
import json
import os
from pathlib import Path
import re
import secrets
import sys
import threading
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "server"))
from gesture_agent_bridge import BridgeError, Device, LjydChat
from camera_preview import SerialLines
from capture_serial import open_device


def challenge(marker):
    # The answer is deliberately absent: merely reading this prompt as TTS
    # cannot satisfy the response check.
    return (f"这是一次设备文本输入测试，编号 {marker}。请计算 17 加 25。"
            f"只回答：编号 {marker}，答案是计算结果的阿拉伯数字。不要复述问题。")


class Evidence:
    def __init__(self, marker, require_ready=False):
        self.marker = marker.lower()
        self.text = {"tts": "", "agent text": ""}
        self.text_ended = {"tts": False, "agent text": False}
        self.matched = False
        self.tts_matched = False
        self.generation = None
        self.complete = False
        self.failure = None
        self.ready = False
        self.ended = False
        self.require_ready = require_ready

    def fail(self, reason):
        if self.failure is None:
            self.failure = reason

    def refresh_reply_matches(self):
        marker = r"(?<![a-z0-9])" + re.escape(self.marker) + r"(?![a-z0-9])"
        matches = {}
        for key, text in self.text.items():
            clean = re.sub(r"\x1b\[[0-9;]*m", "", text.lower())
            # Without a turn boundary, a final chunk '42' or marker could
            # still grow into '420', '42.5' or another marker.
            ending = (r"(?=$|[\s，,。！!？?；;])" if self.text_ended[key]
                      else r"(?=[，,。！!？?；;])")
            marker_first = (marker + r"[\s，,：:。]*"
                            r"(?:答案(?:是|为)?[\s，,：:]*)?"
                            r"42(?![0-9.．])" + ending)
            answer_first = (r"(?:计算结果|答案)(?:是|为)?[\s：:]*"
                            r"42(?![0-9.．])[\s，,。；;]+"
                            r"(?:本次)?编号(?:为|是)?[\s：:]*" + marker + ending)
            matches[key] = bool(re.search(marker_first, clean) or
                                re.search(answer_first, clean))
        # Recompute rather than latch a numeric prefix: later chunks can
        # invalidate even a previously final-marked transcript.
        self.matched = any(matches.values())
        self.tts_matched = matches["tts"]

    def feed(self, line):
        # Do not retain or print unrelated ASR, credentials or raw logs.
        if "ESP-ROM:" in line or "stack overflow" in line or "Guru Meditation" in line:
            self.fail("device_restarted_or_panicked")
        if "agora disconnected" in line and not self.complete and not self.ended:
            self.fail("session_disconnected")
        record = re.search(r'HG_PROBE (\{[^\r\n]*\})', line)
        if record:
            try:
                status = json.loads(record[1])
            except ValueError:
                status = {}
            if (isinstance(status, dict) and isinstance(status.get("marker"), str) and
                    status["marker"].lower() == self.marker and status.get("v") == 1):
                state = status.get("state")
                if state == "ready" and status.get("code") == 0:
                    self.ready = True
                elif state == "ended" and status.get("code") == 0:
                    self.ended = True
                elif state in ("failed", "cleanup_failed", "unavailable", "busy"):
                    self.fail("probe_" + state)
        if self.require_ready and not self.ready:
            return
        match = re.search(r"\b(tts|agent text) final=([01]) text=(.*)$", line)
        if match:
            key, final, text = match.groups()
            self.text[key] = (self.text[key] + text)[-4096:]
            self.text_ended[key] = final == "1"
            self.refresh_reply_matches()
        elif re.search(r"\bdialog=silent\s*$", line):
            # Agora can finish with final=0 chunks and no punctuation. Its
            # silent notice supplies the missing textual turn boundary; it
            # does not establish that local playback completed.
            self.text_ended = {key: True for key in self.text}
            self.refresh_reply_matches()
        match = re.search(r"tts playback (started|complete|failed) generation=(\d+)", line)
        if match:
            state, generation = match[1], int(match[2])
            if state == "started":
                if self.generation is not None and self.generation != generation:
                    self.fail("multiple_playback_generations")
                self.generation = generation
            elif self.generation == generation:
                if state == "failed":
                    self.fail("playback_failed")
                else:
                    self.complete = True

    def result(self):
        return {
            "matching_agent_reply_observed": self.matched,
            "matching_tts_reply_observed": self.tts_matched,
            "playback_started_observed": self.generation is not None,
            # Text notices have no generation ID. These are independent facts,
            # even though the diagnostic session reserves an idle transaction.
            "playback_generation_completed_observed": self.complete,
            "diagnostic_session_ready": self.ready,
            "diagnostic_session_ended": self.ended,
            "failure": self.failure,
            "physical_audio_verified": False,
        }


def run_probe(send_chat, target, marker, serial_device=None, seconds=45,
              ready_seconds=20, cleanup_seconds=5):
    evidence = Evidence(marker, require_ready=serial_device is not None)
    stop = threading.Event()
    reader = None

    def observe():
        lines = SerialLines(max_line_bytes=65536, encoding="utf-8")
        try:
            while not stop.is_set():
                for line in lines.feed(serial_device.read(4096)):
                    evidence.feed(line)
        except Exception:
            evidence.fail("serial_observation_failed")

    if serial_device is not None:
        # Every diagnostic lifecycle record must echo our unique marker.
        serial_device.reset_input_buffer()
        reader = threading.Thread(target=observe, daemon=True)
        reader.start()
    accepted, sent, error = False, False, None
    def command(action):
        serial_device.write(f"hg_agent {action} {marker}\r\n".encode("ascii"))
        serial_device.flush()
    try:
        if reader:
            command("probe")
            deadline = time.monotonic() + ready_seconds
            while not evidence.ready and not evidence.failure and time.monotonic() < deadline:
                stop.wait(0.01)
            if not evidence.ready and not evidence.failure:
                evidence.fail("probe_readiness_timeout")
            if evidence.ended and not evidence.failure:
                evidence.fail("probe_ended_before_request")
        if not evidence.failure:
            try:
                sent = True
                send_chat(target, challenge(marker))
                accepted = True
            except BridgeError as exc:
                error = exc.code
            except Exception:
                error = "upstream_unconfirmed"
        # A timeout can occur after the service accepted a request. Keep
        # observing, without retrying or claiming the HTTP result was success.
        deadline = time.monotonic() + seconds
        while reader and time.monotonic() < deadline:
            if evidence.failure or evidence.ended:
                break
            stop.wait(0.05)
        if reader and sent and not evidence.failure and not evidence.ended:
            evidence.fail("probe_observation_timeout")
    except (OSError, ValueError):
        evidence.fail("serial_command_failed")
    finally:
        if reader and not evidence.ended:
            # Marker-scoped abort cannot close another probe or ordinary voice.
            try:
                command("abort")
                deadline = time.monotonic() + cleanup_seconds
                while not evidence.ended and time.monotonic() < deadline:
                    stop.wait(0.01)
            except (OSError, ValueError):
                evidence.fail("serial_cleanup_failed")
        stop.set()
        if reader:
            reader.join(2)
            if reader.is_alive():
                evidence.fail("serial_observer_did_not_stop")
    return {
        "utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "test_marker": marker,
        "pid": target.pid,
        "did": target.did,
        "http_accepted": accepted,
        "request_sent": sent,
        "http_error": error,
        "serial_observed": serial_device is not None,
        **evidence.result(),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--did", required=True)
    parser.add_argument("--environment", choices=("prod", "test", "dev"), default="prod")
    parser.add_argument("--send", action="store_true")
    parser.add_argument("--port", help="Optional physical-device serial port (115200)")
    parser.add_argument("--seconds", type=int, default=45)
    parser.add_argument("--output", type=Path, help="New private JSON evidence file")
    args = parser.parse_args(argv)
    if args.pid <= 0 or not re.fullmatch(r"[0-9]+", args.did) or int(args.did) <= 0:
        parser.error("Use the physical device's positive numeric PID/DID")
    if not 1 <= args.seconds <= 120:
        parser.error("--seconds must be 1..120")
    token = os.environ.get("LJYD_MERCHANT_TOKEN", "")
    if not args.send:
        print(json.dumps({"pid": args.pid, "did": args.did,
                          "merchant_credential_present": bool(token), "request_sent": False}))
        return 0 if token else 2
    if not token:
        parser.error("Set LJYD_MERCHANT_TOKEN privately before --send")
    chat = LjydChat(token, args.environment)
    marker = "GB" + secrets.token_hex(4).upper()
    output = None
    device = None
    try:
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            fd = os.open(args.output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            output = os.fdopen(fd, "w", encoding="utf-8")
        if args.port:
            import serial
            device = open_device(serial, args.port)
            device.write_timeout = 2
        print(f"Preparing one device text test; marker={marker}", flush=True)
        result = run_probe(chat, Device("unused", args.pid, args.did), marker, device, args.seconds)
        encoded = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
        if output:
            output.write(encoded)
        print(encoded, end="")
        # This exit status only means HTTP acceptance; the JSON carries the
        # independently observed device stages. It never certifies hearing.
        return 0 if result["http_accepted"] else 1
    except (OSError, ValueError, ImportError):
        print("Probe setup failed; check port, pyserial, or output path. No automatic retry.", file=sys.stderr)
        return 2
    finally:
        if device:
            device.close()
        if output:
            output.close()


if __name__ == "__main__":
    raise SystemExit(main())
