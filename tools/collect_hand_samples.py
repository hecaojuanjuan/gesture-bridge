"""Collect labelled BF3901 JPEGs with the detector box from the exact same frame.

Only sends hv_camera inputjpeg. No servo, light, provisioning or reboot command.
Keep train/val/test in distinct recording sessions; never split adjacent frames.
"""
import argparse
import datetime
import hashlib
import json
import re
import time
from pathlib import Path

from camera_preview import JpegSnapshot, SerialLines
from capture_serial import open_device, record_line


def hand_message(line):
    start = line.find('HG {')
    if start < 0:
        return None
    try:
        value = json.loads(line[start + 3:])
    except ValueError:
        return None
    if isinstance(value, dict) and value.get('v') == 1:
        return value
    return None


def observation(line):
    value = hand_message(line)
    return value if value and value.get('event') == 'observation' else None


def matching_box(row, snapshot):
    if not row or row.get('captured_ms') != snapshot.captured_ms or row.get('valid') is not True:
        return None
    if row.get('hands') != 1 or row.get('width') != snapshot.width or row.get('height') != snapshot.height:
        return None
    box = row.get('box')
    if not isinstance(box, list) or len(box) != 4 or any(type(v) is not int for v in box):
        return None
    x1, y1, x2, y2 = box
    return box if 0 <= x1 < x2 <= snapshot.width and 0 <= y1 < y2 <= snapshot.height else None


def collect_frame(device, lines, raw_log, timeout=20):
    snapshot = JpegSnapshot(expected_source='model')
    seen = {}
    last_capture, last_sequence = None, None
    device.write(b'hv_camera inputjpeg\r\n')
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        for line in lines.feed(device.read(4096)):
            raw_log.write(json.dumps(record_line(line), ensure_ascii=False) + '\n')
            message = hand_message(line)
            if re.search(r'ESP-ROM:|(?:^|\s)rst:0x|Guru Meditation|Restarting\.\.\.', line) or \
                    (message and message.get('event') == 'ready'):
                raise RuntimeError('取图期间设备重启；丢弃本次图像及检测，重新开始采样会话')
            row = observation(line)
            if row:
                capture, sequence = row.get('captured_ms'), row.get('seq')
                if type(capture) is not int or type(sequence) is not int or capture < 0 or sequence < 1:
                    raise RuntimeError('手部观测时戳或序号无效；本次不保存')
                if (last_capture is not None and capture <= last_capture) or \
                        (last_sequence is not None and sequence <= last_sequence):
                    raise RuntimeError('手部观测时戳或序号倒退；禁止跨重启匹配训练样本')
                last_capture, last_sequence = capture, sequence
                seen[row['captured_ms']] = row
                if len(seen) > 100:
                    del seen[next(iter(seen))]
            start = line.find('HVJPEG ')
            if start >= 0:
                snapshot.feed(line[start:])
        if snapshot.complete and snapshot.captured_ms in seen:
            row = seen[snapshot.captured_ms]
            return snapshot, row, matching_box(row, snapshot)
    raise TimeoutError('未收到完整 JPEG 及同一 captured_ms 的手部检测；本次未保存训练样本')


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', required=True)
    parser.add_argument('--label', required=True, choices=['open_palm', 'closed_fist', 'other'])
    parser.add_argument('--split', required=True, choices=['train', 'val', 'test'])
    parser.add_argument('--session', required=True, help='New identifier for each independent recording session')
    parser.add_argument('--count', type=int, default=20)
    parser.add_argument('--countdown', type=int, default=10)
    parser.add_argument('--output', type=Path, default=Path('.local/hand-dataset'))
    args = parser.parse_args(argv)
    if not 1 <= args.count <= 200 or not 0 <= args.countdown <= 60:
        parser.error('count must be 1..200 and countdown 0..60')
    if not args.session or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-' for c in args.session):
        parser.error('session must use letters, digits, _ or -')
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / 'manifest.json'
    manifest = json.loads(manifest_path.read_text(encoding='utf-8')) if manifest_path.exists() else {'samples': []}
    if any(s['session'] == args.session and s['split'] != args.split for s in manifest['samples']):
        parser.error('同一录制 session 不能跨 train/val/test；请另录独立验证样本')
    import serial
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    log_path = args.output / f'{stamp}-{args.session}-{args.label}.jsonl'
    label_name = {'open_palm': '张开手掌', 'closed_fist': '握拳', 'other': '其他手势（V、指向、拇指等）'}[args.label]
    saved = 0
    with open_device(serial, args.port) as device, log_path.open('w', encoding='utf-8') as raw:
        lines = SerialLines(max_line_bytes=65536, encoding='utf-8')
        # Opening the port may reset this board. Read until its actual hand stream
        # starts; do not repeatedly reopen or send a movement command.
        ready_until = time.monotonic() + 25
        ready = False
        while time.monotonic() < ready_until and not ready:
            for line in lines.feed(device.read(4096)):
                raw.write(json.dumps(record_line(line), ensure_ascii=False) + '\n')
                ready |= observation(line) is not None
        if not ready:
            raise RuntimeError('25 秒内没有 HG 手部诊断流；先确认已运行 hand 固件')
        print(f'准备采集：{label_name}，{args.split}/{args.session}。完整单手入镜，缓慢改变距离和位置。', flush=True)
        for remaining in range(args.countdown, 0, -1):
            print(f'{remaining} 秒后开始', flush=True)
            end = time.monotonic() + 1
            while time.monotonic() < end:
                for line in lines.feed(device.read(4096)):
                    raw.write(json.dumps(record_line(line), ensure_ascii=False) + '\n')
        for attempt in range(args.count * 3):
            snapshot, row, box = collect_frame(device, lines, raw)
            raw.flush()
            if box is None:
                print(f'未保存：手数={row.get("hands")}，有效={row.get("valid")}；请让完整单手进入镜头。', flush=True)
                if attempt >= 4 and saved == 0:
                    break
                continue
            relative = Path('images') / f'{stamp}-{args.session}-{args.label}-{attempt:03d}.jpg'
            path = args.output / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            snapshot.save(path)
            manifest['samples'].append({
                'path': relative.as_posix(), 'label': args.label, 'session': args.session,
                'split': args.split, 'box': box, 'captured_ms': snapshot.captured_ms,
                'width': snapshot.width, 'height': snapshot.height,
                'detect_score': row['detect_score'], 'source': 'BF3901-model-input',
                'sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
                'host_utc': datetime.datetime.now(datetime.timezone.utc).isoformat()})
            # Replace atomically after each complete verified image.
            temporary = manifest_path.with_suffix('.json.tmp')
            temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
            temporary.replace(manifest_path)
            saved += 1
            print(f'已保存 {saved}/{args.count}：{label_name}；手框 {box}', flush=True)
            if saved == args.count:
                break
    print(json.dumps({'saved': saved, 'requested': args.count, 'label': args.label,
                      'split': args.split, 'manifest': str(manifest_path.resolve())}, ensure_ascii=False))
    return 0 if saved == args.count else 2


if __name__ == '__main__':
    raise SystemExit(main())
