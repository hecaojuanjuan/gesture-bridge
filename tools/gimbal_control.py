"""Send one gimbal command and record device-confirmed results."""
import argparse
import datetime
import json
import re
import time
from pathlib import Path


def main():
    import serial

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--seconds", type=float)
    parser.add_argument("words", nargs="+")
    args = parser.parse_args()
    arity = {"status": 1, "probe": 1, "arm": 2, "jog": 3,
             "dir": 3, "start": 1, "stop": 1}
    action = args.words[0]
    if (action not in arity or len(args.words) != arity[action] or
            any(not re.fullmatch(r"[a-z]+|[-+]?\d+", w) for w in args.words)):
        parser.error("Invalid gimbal command")
    limit = args.seconds or (110 if action == "start" else 20)
    stamp = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
    path = Path("artifacts") / f"gimbal-{action}-{stamp}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = args.port, 115200, 0.3
    device.dtr = device.rts = False
    completed = False
    with device, path.open("w", encoding="utf-8") as target:
        device.write(("hv_gimbal " + " ".join(args.words) + "\r\n").encode())
        deadline = time.monotonic() + limit
        try:
            while time.monotonic() < deadline:
                line = device.readline(4096).decode(
                    "utf-8", errors="replace").strip()
                if not line:
                    continue
                if "GIMBAL" not in line and not re.search(
                        r"Guru Meditation|Backtrace|ESP-ROM:|rst:", line):
                    continue
                row = {"host_utc": datetime.datetime.now(
                    datetime.timezone.utc).isoformat(), "line": line}
                start = line.find("GIMBAL {")
                event = None
                if start >= 0:
                    event = json.loads(line[start + 7:])
                    row["device"] = event
                target.write(json.dumps(row) + "\n")
                target.flush()
                print(line, flush=True)
                if re.search(r"GIMBAL ERROR|GIMBAL STOP|Guru Meditation|ESP-ROM:|rst:", line):
                    raise RuntimeError("Device rejected, stopped, or restarted")
                if event:
                    if action == "probe" and event["event"] == "observation":
                        completed = True
                        break
                    if action == "start" and event["event"] == "observation" and not event["active"]:
                        if event["result"] != 2:
                            raise RuntimeError(
                                "Centering stopped before reaching its target")
                        completed = True
                        break
                    if action not in ("probe", "start") and event["event"] == "status":
                        completed = True
                        break
            if not completed:
                raise TimeoutError("No confirmed completion from device")
        finally:
            if not completed and action in ("start", "probe"):
                device.write(b"hv_gimbal stop\r\n")
                device.flush()
    print("Device response log:", path.resolve())


if __name__ == "__main__":
    main()
