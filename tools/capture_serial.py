"""Capture full local serial logs; print only device diagnostics, never commands."""
import argparse
import datetime
import json
import re
import sys
import time
from pathlib import Path

from camera_preview import SerialLines


HV_FIELDS = ("event", "captured_ms", "age_ms", "tilt", "people", "tracking_valid",
             "valid", "infer_ms", "conversion_ms", "model_ms", "eye_span_px",
             "window_ms", "valid_hz", "inferred", "infer_mean_ms", "infer_max_ms",
             "captured", "dropped", "internal_free", "internal_largest", "psram_free",
             "code", "at_ms", "ticket", "result", "confirm_to_report_ms")
HP_FIELDS = ("v", "boot", "reset_reason", "id", "ok", "uptime_ms", "mode",
             "brightness", "rgb", "output", "test_ms", "stage")
# Match only the diagnostic itself: unrelated cloud messages can share a line.
DIAGNOSTICS = re.compile(
    r"bsp_camera: got \d+ frames good=\d+ empty=\d+ last_bytes=\d+ dt=\d+ ms"
    r"|HV stage=\d+ vision=\w+"
    r"|HV reset reason=invalid_frame_or_pose epoch=\d+"
    r"|HVCAM (?:BEGIN [\d ]+|END [0-9a-fA-F]+|WAIT\b|BUSY\b|ERROR [a-z_]+)"
    r"|ESP-ROM:[\w.-]+"
    r"|rst:0x[0-9a-fA-F]+"
    r"|ELF file SHA256:\s*[0-9a-fA-F.]+"
    r"|Guru Meditation Error: Core\s+\S+ panic'ed \([\w /-]+\)"
    r"|Brownout detector was triggered|CORRUPT HEAP|assert failed"
    r"|(?:Interrupt|Task) watchdog[^\r\n]*?(?:CPU[01]|triggered)"
    r"|Restarting\.\.\."
)


def utc_now():
    return datetime.datetime.now(datetime.timezone.utc).isoformat()


def record_line(line, partial=False):
    row = dict(host_utc=utc_now(), line=line)
    if partial:
        row["partial_line"] = True
        return row
    for prefix, key in (("HV {", "device"), ("HP {", "panel")):
        start = line.find(prefix)
        if start < 0:
            continue
        try:
            payload = json.loads(line[start + 3:])
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            row[key] = payload
    return row


def diagnostic_summary(row):
    if row.get("partial_line"):
        return None
    for key, prefix, fields in (("device", "HV", HV_FIELDS),
                                 ("panel", "HP", HP_FIELDS)):
        payload = row.get(key)
        if payload is not None:
            summary = {k: payload[k] for k in fields if k in payload}
            if summary:
                return prefix + " " + json.dumps(summary, ensure_ascii=False)
    matches = [match.group() for match in DIAGNOSTICS.finditer(row["line"])]
    return " | ".join(matches) if matches else None


def capture(device, target, seconds, quiet=False, clock=time.monotonic):
    lines = SerialLines(max_line_bytes=65536, encoding="utf-8")
    count = 0

    def save(row):
        target.write(json.dumps(row, ensure_ascii=False) + "\n")
        target.flush()
        if not quiet:
            summary = diagnostic_summary(row)
            if summary:
                print(summary, flush=True)

    deadline = clock() + seconds
    try:
        while clock() < deadline:
            for line in lines.feed(device.read(4096)):
                if not line.strip():
                    continue
                save(record_line(line))
                count += 1
    finally:
        # Keep a final fragment as evidence, but never treat it as a pose record.
        if lines.pending:
            save(record_line(lines.pending.decode("utf-8", errors="replace"), partial=True))
    return count


def open_device(serial_module, port):
    device = serial_module.Serial()
    device.port, device.baudrate, device.timeout = port, 115200, 0.5
    device.dtr = device.rts = False
    device.open()
    return device


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port")
    parser.add_argument("--seconds", type=int, default=120)
    parser.add_argument("--output", type=Path, default=Path(".local/device.jsonl"),
                        help="New raw log file; existing files are never overwritten. Keep it local")
    parser.add_argument("--quiet", action="store_true", help="Do not print captured diagnostics")
    parser.add_argument("--list", action="store_true")
    args = parser.parse_args(argv)
    if args.list:
        from serial.tools import list_ports
        for port in list_ports.comports():
            print(json.dumps(dict(port=port.device, description=port.description,
                                 hwid=port.hwid), ensure_ascii=False))
        return 0
    if not args.port:
        parser.error("--port is required")
    if args.seconds <= 0:
        parser.error("--seconds must be positive")
    import serial
    args.output.parent.mkdir(parents=True, exist_ok=True)
    # Reserve the new file before opening the port: even opening this board's
    # serial port can reset it, and a retry must not erase earlier fault evidence.
    try:
        target = args.output.open("x", encoding="utf-8")
    except FileExistsError:
        parser.error(f"日志已存在，未打开串口、未覆盖文件：{args.output}；请更换 --output 文件名")
    with target:
        try:
            with open_device(serial, args.port) as device:
                count = capture(device, target, args.seconds, quiet=args.quiet)
        except serial.SerialException as exc:
            print(f"串口采集失败：{exc}；已收到的日志和末尾片段保留在 {args.output}", file=sys.stderr)
            return 1
    if count == 0:
        print(f"未收到完整日志行，本轮采集不可用；已有片段保留在 {args.output}。"
              "请检查设备连接与运行状态，并使用新文件名重试。", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
