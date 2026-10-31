"""Save one model-input JPEG and strictly same-frame hand diagnostics.

Only sends hv_camera inputjpeg. Capture overhead makes this a framing/crop
diagnostic, not a latency benchmark or a gesture-accuracy measurement.
"""
import argparse
import contextlib
import datetime
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

from camera_preview import JpegSnapshot, SerialLines
from capture_serial import open_device
from collect_hand_samples import hand_message


RESTART = re.compile(r"ESP-ROM:|(?:^|\s)rst:0x|Guru Meditation|Restarting\.\.\.")


def unsigned(value, maximum=2**64 - 1):
    return type(value) is int and 0 <= value <= maximum


def valid_observation(message):
    if not message or message.get("event") != "observation":
        return False
    if (not unsigned(message.get("seq"), 2**32 - 1) or message["seq"] < 1 or
            not unsigned(message.get("captured_ms")) or
            not unsigned(message.get("epoch"), 2**32 - 1) or
            not unsigned(message.get("width"), 320) or message["width"] < 1 or
            not unsigned(message.get("height"), 320) or message["height"] < 1 or
            not unsigned(message.get("hands"), 2**32 - 1) or
            type(message.get("valid")) is not bool or
            (message["valid"] and message["hands"] != 1)):
        return False
    box = message.get("box")
    if not isinstance(box, list) or len(box) != 4 or not all(unsigned(v, 320) for v in box):
        return False
    x1, y1, x2, y2 = box
    bounded = 0 <= x1 < x2 <= message["width"] and 0 <= y1 < y2 <= message["height"]
    return bounded or (not message["valid"] and box == [0, 0, 0, 0])


def panel_boot(line):
    start = line.find("HP {")
    if start < 0:
        return None
    try:
        value = json.loads(line[start + 3:])
    except ValueError:
        return None
    if isinstance(value, dict) and value.get("v") == 1 and unsigned(value.get("boot"), 2**32 - 1):
        return value["boot"]
    return None


def collect_probe(device, timeout=25, clock=time.monotonic):
    """Return a verified JPEG and metadata; never return across a boot boundary."""
    snapshot = JpegSnapshot("model")
    lines = SerialLines(max_line_bytes=65536, encoding="utf-8")
    observations = []
    last_capture = last_sequence = last_epoch = known_boot = None
    boot_segment = 0
    transfer_started = False
    deadline, next_request, pair_deadline = clock() + timeout, 0, None

    def boundary(reason):
        nonlocal last_capture, last_sequence, last_epoch, known_boot, boot_segment, next_request
        if transfer_started:
            raise RuntimeError(f"取图开始后出现{reason}；不跨启动或采样边界拼接，本次未保存")
        observations.clear()
        last_capture = last_sequence = last_epoch = known_boot = None
        boot_segment += 1
        next_request = 0

    while clock() < (pair_deadline if pair_deadline is not None else deadline):
        now = clock()
        if not transfer_started and now >= next_request:
            device.write(b"hv_camera inputjpeg\r\n")
            next_request = now + 5
        active_deadline = pair_deadline if pair_deadline is not None else deadline
        device.timeout = min(.25, max(0, active_deadline - now))
        data = device.read(4096)
        if clock() > active_deadline:
            break
        for line in lines.feed(data):
            message = hand_message(line)
            if RESTART.search(line):
                boundary("设备重启标记")
            if message and message.get("event") == "ready":
                boundary("新的 HG ready")
            boot = panel_boot(line)
            if boot is not None:
                if known_boot is not None and boot != known_boot:
                    boundary("HP 启动编号变化")
                known_boot = boot
            if valid_observation(message):
                captured, sequence, epoch = message["captured_ms"], message["seq"], message["epoch"]
                if ((last_capture is not None and captured < last_capture) or
                        (last_sequence is not None and sequence < last_sequence) or
                        (last_epoch is not None and epoch != last_epoch)):
                    boundary("HG 时间、序号或采样轮次变化")
                last_capture, last_sequence, last_epoch = captured, sequence, epoch
                if len(observations) >= 256:
                    raise RuntimeError("同帧诊断缓存超过上限；本次未保存")
                observations.append(message)
            start = line.find("HVJPEG ")
            if start >= 0:
                protocol_line = line[start:].strip()
                if protocol_line.startswith("HVJPEG ERROR "):
                    # Do not echo arbitrary serial text (a network log may be
                    # interleaved on the same line) into the terminal.
                    raise RuntimeError("设备报告 JPEG 导出失败；本次未保存")
                snapshot.feed(protocol_line)
                # WAIT can legally arrive after SOURCE/BEGIN. Any of them
                # establishes a transfer that must not survive a boot boundary.
                transfer_started = True
                if snapshot.complete and pair_deadline is None:
                    pair_deadline = clock() + 2
    if not snapshot.complete:
        raise TimeoutError("未收到来源、尺寸及校验均通过的完整模型 JPEG；本次未保存")
    matches = [h for h in observations if
               (h["captured_ms"], h["width"], h["height"]) ==
               (snapshot.captured_ms, snapshot.width, snapshot.height)]
    status = "matched" if len(matches) == 1 else "ambiguous" if matches else "missing"
    observation = matches[0] if status == "matched" else None
    metadata = {
        "v": 1, "source": "inputjpeg", "encoding": "jpeg",
        "captured_ms": snapshot.captured_ms, "width": snapshot.width, "height": snapshot.height,
        "rotate_cw90": False, "jpeg_quality": snapshot.quality,
        "bytes": len(snapshot.data), "sha256": hashlib.sha256(snapshot.data).hexdigest(),
        "checksum_verified": True, "paired_status": status, "matching_count": len(matches),
        "box": observation["box"] if observation else None, "observation": observation,
        "ambiguous_observations": matches if status == "ambiguous" else [],
        "boot_segment": boot_segment, "hp_boot": known_boot,
        "host_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "note": "同帧裁剪诊断；取图有额外开销，不用于性能或手势准确率评估。missing/ambiguous 不提供唯一检测框。",
    }
    return snapshot, metadata


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", required=True, type=Path, help="New timestamped .jpg or .jpeg; never overwrite")
    parser.add_argument("--timeout", type=float, default=25, help="Seconds for JPEG, then at most 2 seconds for pairing")
    args = parser.parse_args(argv)
    if not args.port.strip() or any(c in args.port for c in "\r\n\0"):
        parser.error("--port must name one serial port")
    if not math.isfinite(args.timeout) or not 0 < args.timeout <= 120:
        parser.error("--timeout must be finite and within (0, 120]")
    if args.output.suffix.lower() not in (".jpg", ".jpeg"):
        parser.error("--output must end in .jpg or .jpeg")
    metadata_path = args.output.with_suffix(".json")
    if any(path.exists() or path.is_symlink() for path in (args.output, metadata_path)):
        parser.error("JPEG 或同名 JSON 已存在；未打开串口、未覆盖，请使用新时间戳文件名")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with contextlib.ExitStack() as stack:
            # Exclusive reservation is before even constructing Serial, closing
            # the check/open race without deleting somebody else's files.
            image_file = stack.enter_context(args.output.open("xb"))
            created.append(args.output)
            meta_file = stack.enter_context(metadata_path.open("x", encoding="utf-8"))
            created.append(metadata_path)
            import serial
            with open_device(serial, args.port) as device:
                snapshot, metadata = collect_probe(device, args.timeout)
            image_file.write(snapshot.data)
            meta_file.write(json.dumps(metadata, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    except (OSError, ValueError, RuntimeError) as error:
        for path in created:
            path.unlink(missing_ok=True)
        print(f"取图失败：{error}", file=sys.stderr)
        return 1
    print(json.dumps({"path": str(args.output.resolve()), "metadata": str(metadata_path.resolve()),
                      "paired_status": metadata["paired_status"], "captured_ms": metadata["captured_ms"],
                      "width": metadata["width"], "height": metadata["height"],
                      "checksum_verified": True, "matching_count": metadata["matching_count"]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
