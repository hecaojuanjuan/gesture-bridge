"""Run a bounded single-axis test on the isolated servo diagnostic firmware."""
import argparse
from collections import deque
import datetime
import json
import sys
import time
from pathlib import Path

from camera_preview import SerialLines


class DiagnosticSession:
    def __init__(self, device, log, clock=time.monotonic):
        self.device, self.log, self.clock = device, log, clock
        self.framing, self.lines = SerialLines(), deque()
        self.ready, self.last_uptime = False, 0

    def write(self, command):
        if command not in ("status", "stop") and not self.ready:
            raise RuntimeError("Movement requires a confirmed startup status")
        self.device.write((command + "\n").encode("ascii"))
        self.device.flush()

    def read_event(self, deadline, startup=False):
        while self.clock() < deadline:
            if not self.lines:
                count = min(max(self.device.in_waiting, 1), 4096)
                self.lines.extend(self.framing.feed(self.device.read(count)))
                continue
            line = self.lines.popleft()
            self.log.write(json.dumps({"host_time": time.time(), "line": line}) + "\n")
            self.log.flush()
            if any(word in line for word in ("Guru Meditation", "ESP-ROM:", "rst:")):
                if startup:
                    continue
                raise RuntimeError("Device restarted or crashed")
            start = line.find("SERVO_MIN ")
            if start < 0:
                continue
            event = json.loads(line[start + len("SERVO_MIN "):])
            if (not isinstance(event, dict) or not isinstance(event.get("event"), str)
                    or type(event.get("axis")) is not int or event["axis"] not in (-1, 0, 1)
                    or type(event.get("pulse_us")) is not int
                    or type(event.get("uptime_ms")) is not int or event["uptime_ms"] < 0
                    or (event["axis"] == -1 and event["pulse_us"] != 0)
                    or (event["axis"] != -1 and not 1300 <= event["pulse_us"] <= 1700)):
                raise RuntimeError(f"Invalid diagnostic acknowledgment: {event}")
            print(line, flush=True)
            if not startup and (event["event"] == "ready" or event["uptime_ms"] < self.last_uptime):
                raise RuntimeError("Device restarted during the test")
            self.last_uptime = event["uptime_ms"]
            if startup and event["event"] == "ready":
                continue
            return event
        return None

    def startup(self, timeout=20):
        deadline, next_request = self.clock() + timeout, self.clock()
        while self.clock() < deadline:
            if self.clock() >= next_request:
                self.write("status")  # Only this read-only command may be retried.
                next_request = self.clock() + 1
            event = self.read_event(min(deadline, next_request), startup=True)
            if event and event["event"] == "status":
                self.ready = True
                return event
        raise TimeoutError("No confirmed diagnostic status; no movement was sent")

    def expect(self, expected, axis, pulse, timeout=1.5):
        event = self.read_event(self.clock() + timeout)
        if event is None:
            raise TimeoutError(f"No diagnostic acknowledgment for {expected}")
        if event["event"] != expected or event["axis"] != axis or event["pulse_us"] != pulse:
            raise RuntimeError(f"Acknowledgment does not match {expected}/{axis}/{pulse}: {event}")
        return event

    def send(self, command, expected, axis, pulse):
        self.write(command)
        return self.expect(expected, axis, pulse)

    def stop_confirmed(self):
        self.send("stop", "stopped", -1, 0)
        self.send("status", "status", -1, 0)

    def hold(self, duration):
        # Read while observing the servo so a restart aborts before the next jog.
        event = self.read_event(self.clock() + duration)
        if event is not None:
            raise RuntimeError(f"Unexpected event while holding position: {event}")


def run_test(device, log, axis=None, span_us=25, hold_seconds=0.8, clock=time.monotonic):
    if axis not in (None, "pan", "tilt") or span_us not in (25, 50, 100, 200):
        raise ValueError("Invalid axis or pulse span")
    if not 0.1 <= hold_seconds <= 1.0:
        raise ValueError("Hold must be between 0.1 and 1.0 seconds")
    session, failure = DiagnosticSession(device, log, clock), None
    try:
        session.startup()
        session.stop_confirmed()
        if axis is None:
            return
        current, sequence = 1500, [1500]
        for target in (1500 + span_us, 1500, 1500 - span_us, 1500):
            while current != target:
                current += min(50, abs(target-current)) * (1 if target > current else -1)
                sequence.append(current)
        for pulse in sequence:
            session.send(f"{axis} {pulse}", "set", 0 if axis == "pan" else 1, pulse)
            session.hold(hold_seconds)
        session.expect("lease_expired", -1, 0, timeout=3.5)
    except BaseException as exc:
        failure = exc
        raise
    finally:
        try:
            session.stop_confirmed()
        except Exception as exc:
            if failure is None:
                raise
            # Preserve the original failure and report whether shutdown could
            # also be confirmed; sending stop alone is not an acknowledgment.
            message = f"Stop/status verification also failed: {exc}"
            log.write(json.dumps({"cleanup_error": message}) + "\n")
            log.flush()
            print(message, file=sys.stderr, flush=True)


def check_stopped(device, log, clock=time.monotonic):
    """Send only read-only status queries; never stop, arm, or jog an axis."""
    report = DiagnosticSession(device, log, clock).startup()
    if report["axis"] != -1 or report["pulse_us"] != 0:
        raise RuntimeError("Servo output is active; status-only check made no changes")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    action = parser.add_mutually_exclusive_group()
    action.add_argument("--axis", choices=["pan", "tilt"])
    action.add_argument("--status-only", action="store_true",
                        help="Only query status and verify outputs are off; never send motion or stop")
    parser.add_argument("--span-us", type=int, choices=[25, 50, 100, 200], default=25)
    parser.add_argument("--hold-seconds", type=float, default=0.8)
    args = parser.parse_args()
    if not 0.1 <= args.hold_seconds <= 1.0:
        parser.error("--hold-seconds must be between 0.1 and 1.0")
    import serial

    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = Path("artifacts") / f"servo-minimal-{stamp}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = args.port, 115200, 0.05
    device.dtr = device.rts = False
    try:
        with device, path.open("w", encoding="utf-8") as log:
            if args.status_only:
                check_stopped(device, log)
            else:
                run_test(device, log, args.axis, args.span_us, args.hold_seconds)
    finally:
        print("Log:", path.resolve(), flush=True)


if __name__ == "__main__":
    main()
