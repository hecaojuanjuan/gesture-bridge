"""Read serial diagnostics; never write gesture or confirmation events."""
import argparse
import datetime
import json
import time
from pathlib import Path

import serial
from serial.tools import list_ports

parser = argparse.ArgumentParser()
parser.add_argument("--port")
parser.add_argument("--seconds", type=int, default=120)
parser.add_argument("--output", type=Path,
                    default=Path("artifacts/device.jsonl"))
parser.add_argument("--list", action="store_true")
args = parser.parse_args()
if args.list:
    for port in list_ports.comports():
        print(json.dumps(dict(port=port.device, description=port.description,
                              hwid=port.hwid), ensure_ascii=False))
    raise SystemExit()
if not args.port:
    parser.error("--port is required")
args.output.parent.mkdir(parents=True, exist_ok=True)
with serial.Serial(args.port, 115200, timeout=0.5) as device, \
        args.output.open("w", encoding="utf-8") as target:
    deadline = time.monotonic() + args.seconds
    while time.monotonic() < deadline:
        line = device.readline(2048).decode("utf-8", errors="replace").strip()
        if not line:
            continue
        timestamp = datetime.datetime.now(datetime.timezone.utc).isoformat()
        row = dict(host_utc=timestamp, line=line)
        prefix = line.find("HV {")
        if prefix >= 0:
            try:
                row["device"] = json.loads(line[prefix + 3:])
            except json.JSONDecodeError:
                pass
        target.write(json.dumps(row, ensure_ascii=False) + "\n")
        target.flush()
        print(line, flush=True)
