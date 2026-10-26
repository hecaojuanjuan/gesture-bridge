"""Request one local camera frame, verify it, and save a dependency-free PNG."""
import argparse
import json
import re
import struct
import time
import zlib
from pathlib import Path


def checksum(data):
    value = 2166136261
    for byte in data:
        value = ((value ^ byte) * 16777619) & 0xffffffff
    return value


class Snapshot:
    def __init__(self):
        self.width = self.height = self.length = self.captured_ms = 0
        self.rotate_cw90 = False
        self.data = bytearray()
        self.complete = False

    def feed(self, line):
        if line.startswith("HVCAM BEGIN "):
            if self.length:
                raise ValueError("Unexpected second snapshot header")
            values = list(map(int, line.split()[2:]))
            if len(values) != 5:
                raise ValueError("Invalid snapshot header")
            width, height, length, captured, rotation = values
            if not (0 < width <= 320 and 0 < height <= 320 and
                    length == width * height * 2 and rotation in (0, 1)):
                raise ValueError("Invalid snapshot dimensions or format")
            self.width, self.height, self.length = width, height, length
            self.captured_ms, self.rotate_cw90 = captured, bool(rotation)
        elif line.startswith("HVCAM DATA "):
            match = re.fullmatch(r"HVCAM DATA (\d+) ([0-9a-f]+)", line)
            if not self.length or not match:
                raise ValueError("Invalid snapshot chunk")
            offset, chunk = int(match[1]), bytes.fromhex(match[2])
            if offset != len(self.data) or offset + len(chunk) > self.length:
                raise ValueError("Missing, repeated, or oversized chunk")
            self.data.extend(chunk)
        elif line.startswith("HVCAM END "):
            expected = int(line.split()[2], 16)
            if (not self.length or len(self.data) != self.length or
                    checksum(self.data) != expected):
                raise ValueError("Incomplete snapshot or checksum mismatch")
            self.complete = True
        elif line.startswith("HVCAM ERROR "):
            raise RuntimeError(line)

    def png(self):
        if not self.complete:
            raise ValueError("Snapshot has not passed integrity checks")
        width, height = self.width, self.height
        if self.rotate_cw90:
            width, height = height, width
        pixels = bytearray(width * height * 3)
        for y in range(self.height):
            for x in range(self.width):
                offset = (y * self.width + x) * 2
                value = int.from_bytes(self.data[offset:offset + 2], "little")
                dx, dy = (self.height - 1 - y,
                          x) if self.rotate_cw90 else (x, y)
                dest = (dy * width + dx) * 3
                pixels[dest:dest + 3] = bytes((
                    ((value >> 11) & 31) * 255 // 31,
                    ((value >> 5) & 63) * 255 // 63,
                    (value & 31) * 255 // 31))

        def chunk(kind, data):
            return (struct.pack(">I", len(data)) + kind + data +
                    struct.pack(">I", zlib.crc32(kind + data)))

        rows = b"".join(b"\0" + pixels[y * width * 3:(y + 1) * width * 3]
                        for y in range(height))
        header = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
        return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) +
                chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


def main():
    import serial

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--output", type=Path,
                        default=Path(".local/camera-preview.png"))
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args()
    snapshot = Snapshot()
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = args.port, 115200, 0.5
    device.dtr = device.rts = False
    with device:
        deadline, next_request = time.monotonic() + args.timeout, 0
        accepted = False
        while time.monotonic() < deadline and not snapshot.complete:
            if not accepted and time.monotonic() >= next_request:
                device.write(b"hv_camera snapshot\r\n")
                next_request = time.monotonic() + 5
            line = device.readline(4096).decode("ascii", errors="replace")
            prefix = line.find("HVCAM ")
            if prefix < 0:
                continue
            line = line[prefix:].strip()
            if line in ("HVCAM WAIT", "HVCAM BUSY"):
                accepted = True
            if not line.startswith("HVCAM DATA "):
                print(line, flush=True)
            snapshot.feed(line)
        if not snapshot.complete:
            raise TimeoutError("No complete snapshot; check stage and camera")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(snapshot.png())
    print(json.dumps(dict(path=str(args.output.resolve()),
                          source_width=snapshot.width,
                          source_height=snapshot.height,
                          rotate_cw90=snapshot.rotate_cw90,
                          captured_ms=snapshot.captured_ms,
                          checksum_verified=True)))


if __name__ == "__main__":
    main()
