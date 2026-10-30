"""Run a bounded single-axis test on the isolated servo diagnostic firmware."""
import argparse
import datetime
import json
import time
from pathlib import Path

import serial


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--axis", choices=["pan", "tilt"])
    args = parser.parse_args()
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    path = Path("artifacts") / f"servo-minimal-{stamp}.jsonl"
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = args.port, 115200, 0.15
    device.dtr = device.rts = False
    with device, path.open("w", encoding="utf-8") as log:
        def receive(expected):
            deadline = time.monotonic() + 1.5
            while time.monotonic() < deadline:
                line = device.readline(2048).decode("utf-8", "replace").strip()
                if not line:
                    continue
                log.write(json.dumps(
                    {"host_time": time.time(), "line": line}) + "\n")
                log.flush()
                if any(word in line for word in ("Guru Meditation", "ESP-ROM:", "rst:")):
                    raise RuntimeError("Device restarted or crashed")
                if line.startswith("SERVO_MIN "):
                    event = json.loads(line[len("SERVO_MIN "):])
                    print(line, flush=True)
                    if event["event"] != expected:
                        raise RuntimeError(f"Unexpected event: {event}")
                    return event
            raise TimeoutError("No diagnostic firmware acknowledgment")

        def send(command, expected):
            device.write((command + "\n").encode("ascii"))
            device.flush()
            return receive(expected)

        try:
            state = send("status", "status")
            if not args.axis:
                return
            if state["axis"] != -1:
                send("stop", "stopped")
            sequence = [1500] + list(range(1550, 1701, 50)) + list(
                range(1650, 1299, -50)) + list(range(1350, 1501, 50))
            for pulse in sequence:
                event = send(f"{args.axis} {pulse}", "set")
                if event["axis"] != (0 if args.axis == "pan" else 1) or event["pulse_us"] != pulse:
                    raise RuntimeError("Acknowledgment does not match command")
                time.sleep(1)
            time.sleep(1.7)
            event = receive("lease_expired")
            if event["axis"] != -1:
                raise RuntimeError("Output lease did not stop the servo")
        finally:
            send("stop", "stopped")
            print("Log:", path.resolve(), flush=True)


if __name__ == "__main__":
    main()
