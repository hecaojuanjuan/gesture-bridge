"""Check real serial command/receipt behavior; never claim optical LED output."""
import argparse
import datetime
import json
import secrets
import time
from pathlib import Path

import serial


def run(port):
    events = []
    boot = None
    last_uptime = -1
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = port, 115200, 0.3
    device.dtr = device.rts = False

    def request(verb, request_id=None, startup=False):
        nonlocal boot, last_uptime
        request_id = request_id or secrets.randbelow(999999999) + 1
        wire = f"hv_panel {request_id} {verb}\r\n".encode("ascii")
        device.write(wire)
        started = time.monotonic()
        next_probe = started + 1
        while time.monotonic() - started < (20 if startup else 10):
            # Some USB/UART drivers pulse reset on open, even with DTR/RTS
            # configured false. Only the initial read-only query is retried.
            if startup and time.monotonic() >= next_probe:
                device.write(wire)
                next_probe = time.monotonic() + 1
            line = device.readline(4096).decode("utf-8", errors="replace")
            prefix = line.find("HP {")
            if prefix < 0:
                continue
            try:
                report = json.loads(line[prefix + 3:].strip())
            except ValueError:
                continue
            if report.get("v") != 1 or report.get("id") != request_id:
                continue
            if boot is None:
                boot = report["boot"]
            assert report["boot"] == boot, "Device rebooted during protocol check"
            assert report["uptime_ms"] > last_uptime, "Non-monotonic receipt"
            assert report["ok"] is True, "RGB driver returned failure"
            last_uptime = report["uptime_ms"]
            events.append({"command": verb, "report": report,
                           "round_trip_ms": round((time.monotonic()-started)*1000)})
            return report
        raise TimeoutError(f"No matching report for {request_id} {verb}")

    with device:
        initial = request("get", startup=True)
        restore = "set {} {} {}".format(
            initial["mode"], initial["brightness"],
            " ".join(map(str, initial["rgb"])))
        try:
            manual = request("set 1 20 80 190 255")
            assert (manual["mode"], manual["brightness"], manual["rgb"],
                    manual["output"]) == (1, 20, [80, 190, 255], [3, 7, 9])
            test_id = secrets.randbelow(999999999) + 1
            trial = request("test", test_id)
            assert 4000 < trial["test_ms"] <= 5000
            assert trial["output"] == [32, 0, 0]
            time.sleep(1.2)
            request("get")  # A second browser's polling must not defeat deduplication.
            duplicate = request("test", test_id)
            assert duplicate["test_ms"] < trial["test_ms"] - 800, "Duplicate restarted test"
            assert duplicate["output"] == [0, 32, 0]
            time.sleep(duplicate["test_ms"] / 1000 + 0.3)
            restored = request("get")
            assert restored["test_ms"] == 0
            assert restored["mode"] == 1 and restored["output"] == [3, 7, 9]
            off = request("set 2 20 80 190 255")
            assert off["mode"] == 2 and off["output"] == [0, 0, 0]
        finally:
            restored = request(restore)
            assert (restored["mode"], restored["brightness"], restored["rgb"]) == (
                initial["mode"], initial["brightness"], initial["rgb"])
    return {"host_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
            "serial_protocol_verified": True, "driver_receipts_verified": True,
            "optical_led_output_verified": False,
            "cloud_round_trip_verified": False, "events": events}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = run(args.port)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n",
                           encoding="utf-8")
    print("PASS serial requests, driver receipts, duplicate suppression, expiry and restoration")
    print("Not verified: physical LEDs, cloud transport, camera accuracy")
