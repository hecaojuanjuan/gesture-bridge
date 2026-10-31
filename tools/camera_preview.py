"""Request one local camera/model frame, verify it, and save a PNG or full JPEG."""
import argparse
import base64
import binascii
import io
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


class SerialLines:
    """Keep timeout-delimited serial reads until an actual newline arrives."""
    def __init__(self, max_line_bytes=4096, encoding="ascii"):
        self.max_line_bytes = max_line_bytes
        self.encoding = encoding
        self.pending = bytearray()

    def feed(self, data):
        lines, start = [], 0
        while start < len(data):
            end = data.find(b"\n", start)
            part = data[start:] if end < 0 else data[start:end]
            if len(self.pending) + len(part) > self.max_line_bytes:
                self.pending.clear()
                raise ValueError(
                    f"Serial line exceeds {self.max_line_bytes} bytes before newline")
            self.pending.extend(part)
            if end < 0:
                break
            lines.append(self.pending.decode(self.encoding, errors="replace").rstrip("\r"))
            self.pending.clear()
            start = end + 1
        return lines


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
            if len(match[2]) % 2:
                raise ValueError("Invalid snapshot chunk: odd-length hexadecimal payload")
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


def jpeg_dimensions(data):
    """Read JPEG's encoded dimensions without requiring a desktop image library."""
    if not data.startswith(b"\xff\xd8") or not data.endswith(b"\xff\xd9"):
        raise ValueError("Missing JPEG start/end markers")
    offset = 2
    sof = {0xc0, 0xc1, 0xc2, 0xc3, 0xc5, 0xc6, 0xc7,
           0xc9, 0xca, 0xcb, 0xcd, 0xce, 0xcf}
    while offset < len(data):
        if data[offset] != 0xff:
            raise ValueError("Invalid JPEG marker before image scan")
        while offset < len(data) and data[offset] == 0xff:
            offset += 1
        if offset >= len(data):
            break
        marker = data[offset]
        offset += 1
        if marker in (0xda, 0xd9):
            break
        if marker == 0x01 or 0xd0 <= marker <= 0xd7:
            continue
        if offset + 2 > len(data):
            raise ValueError("Truncated JPEG marker length")
        length = int.from_bytes(data[offset:offset + 2], "big")
        if length < 2 or offset + length > len(data):
            raise ValueError("Invalid JPEG marker length")
        if marker in sof:
            if length < 8:
                raise ValueError("Invalid JPEG dimensions segment")
            height = int.from_bytes(data[offset + 3:offset + 5], "big")
            width = int.from_bytes(data[offset + 5:offset + 7], "big")
            return width, height
        offset += length
    raise ValueError("JPEG has no dimensions before image scan")


class JpegSnapshot:
    """HVJPEG v1: bounded base64 chunks; authorization, source and hash required."""
    def __init__(self, expected_source="camera"):
        self.expected_source = expected_source
        self.source = None
        self.width = self.height = self.length = self.captured_ms = self.quality = 0
        self.rotate_cw90 = False
        self.authorized = self.verified = False
        self.data = bytearray()

    @property
    def complete(self):
        return self.authorized and self.verified

    def feed(self, line):
        if line == "HVJPEG WAIT":
            if self.authorized:
                raise ValueError("Duplicate JPEG request authorization")
            self.authorized = True
        elif line.startswith("HVJPEG SOURCE "):
            if self.source is not None or line[14:] != self.expected_source:
                raise ValueError("Unverified JPEG source")
            self.source = line[14:]
        elif line.startswith("HVJPEG BEGIN "):
            match = re.fullmatch(r"HVJPEG BEGIN 1 (\d+) (\d+) (\d+) (\d+) 0 (\d+)", line)
            if self.length or not match or self.source != self.expected_source:
                raise ValueError("Invalid JPEG header, orientation, or source")
            width, height, length, captured, quality = map(int, match.groups())
            if not (0 < width <= 320 and 0 < height <= 320 and
                    0 < length <= 240 * 320 * 2 + 4096 and
                    captured <= 2**64 - 1 and 1 <= quality <= 100):
                raise ValueError("Invalid JPEG dimensions, length, time, or quality")
            self.width, self.height, self.length = width, height, length
            self.captured_ms, self.quality = captured, quality
        elif line.startswith("HVJPEG DATA "):
            match = re.fullmatch(r"HVJPEG DATA (\d+) ([A-Za-z0-9+/]+={0,2})", line)
            if not self.length or self.verified or not match or len(match[2]) > 256:
                raise ValueError("Invalid JPEG data chunk")
            try:
                chunk = base64.b64decode(match[2], validate=True)
            except (binascii.Error, ValueError) as error:
                raise ValueError("Invalid JPEG base64 data") from error
            offset = int(match[1])
            if not chunk or offset != len(self.data) or offset + len(chunk) > self.length:
                raise ValueError("Missing, repeated, or oversized JPEG chunk")
            self.data.extend(chunk)
        elif line.startswith("HVJPEG END "):
            match = re.fullmatch(r"HVJPEG END ([0-9a-fA-F]{8})", line)
            if (not match or self.verified or not self.length or
                    len(self.data) != self.length or checksum(self.data) != int(match[1], 16)):
                raise ValueError("Incomplete JPEG or checksum mismatch")
            if jpeg_dimensions(self.data) != (self.width, self.height):
                raise ValueError("JPEG pixels do not match advertised dimensions")
            self.verified = True
        elif line == "HVJPEG BUSY":
            raise RuntimeError("HVJPEG BUSY: another export is active; wait and retry")
        elif line.startswith("HVJPEG ERROR "):
            raise RuntimeError(line)
        elif line.startswith("HVJPEG "):
            raise ValueError("Unknown JPEG protocol message")

    def save(self, target):
        if not self.complete:
            raise ValueError("JPEG has not passed authorization and integrity checks")
        if target.suffix.lower() in (".jpg", ".jpeg"):
            target.write_bytes(self.data)
        elif target.suffix.lower() == ".png":
            try:
                from PIL import Image
            except ImportError as error:
                raise RuntimeError("Saving JPEG as PNG requires Pillow; use a .jpg output") from error
            with Image.open(io.BytesIO(self.data)) as image:
                image.load()
                if image.size != (self.width, self.height):
                    raise ValueError("Decoded JPEG dimensions mismatch")
                image.convert("RGB").save(target, format="PNG")
        else:
            raise ValueError("JPEG source output must end in .jpg, .jpeg, or .png")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", required=True)
    parser.add_argument("--source", choices=("camera", "model", "jpeg", "inputjpeg"), default="camera",
                        help="camera/model RGB565 preview, or full jpeg/inputjpeg (model requires stage >= 2)")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--timeout", type=float, default=60)
    args = parser.parse_args(argv)
    import serial

    jpeg = args.source in ("jpeg", "inputjpeg")
    args.output = args.output or Path(".local/camera-preview.jpg" if jpeg else ".local/camera-preview.png")
    if jpeg and args.output.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        parser.error("JPEG source output must end in .jpg, .jpeg, or .png")
    verb = {"camera": "snapshot", "model": "input", "jpeg": "jpeg", "inputjpeg": "inputjpeg"}[args.source]
    command = f"hv_camera {verb}\r\n".encode("ascii")
    snapshot = JpegSnapshot("model" if args.source == "inputjpeg" else "camera") if jpeg else Snapshot()
    protocol = "HVJPEG" if jpeg else "HVCAM"
    lines = SerialLines()
    device = serial.Serial()
    device.port, device.baudrate, device.timeout = args.port, 115200, 0.5
    device.dtr = device.rts = False
    with device:
        deadline, next_request = time.monotonic() + args.timeout, 0
        accepted = False
        model_source = False
        while time.monotonic() < deadline and not snapshot.complete:
            if not accepted and time.monotonic() >= next_request:
                device.write(command)
                next_request = time.monotonic() + 5
            for line in lines.feed(device.read(4096)):
                prefix = line.find(protocol + " ")
                if prefix < 0:
                    continue
                line = line[prefix:].strip()
                if args.source == "model" and line == "HVCAM BUSY":
                    raise RuntimeError("HVCAM BUSY: another export is active; wait and retry model input")
                if line == "HVCAM SOURCE model":
                    model_source = True
                if args.source == "model" and line.startswith("HVCAM BEGIN ") and not model_source:
                    raise RuntimeError("Unverified model source: received an ordinary camera export")
                if line in (protocol + " WAIT", protocol + " BUSY"):
                    accepted = True
                if jpeg and line.startswith(("HVJPEG SOURCE ", "HVJPEG BEGIN ")):
                    # WAIT may be scheduled after the frame header. Do not send
                    # a second request during that export; publishing still
                    # requires the original WAIT in JpegSnapshot.complete.
                    accepted = True
                if not line.startswith(protocol + " DATA "):
                    print(line, flush=True)
                snapshot.feed(line)
                if snapshot.complete:
                    break
        if not snapshot.complete:
            raise TimeoutError("No complete snapshot; check stage and camera")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if jpeg:
        snapshot.save(args.output)
    else:
        args.output.write_bytes(snapshot.png())
    print(json.dumps(dict(path=str(args.output.resolve()),
                          source=args.source,
                          source_width=snapshot.width,
                          source_height=snapshot.height,
                          rotate_cw90=snapshot.rotate_cw90,
                          captured_ms=snapshot.captured_ms,
                          bytes=len(snapshot.data),
                          encoding="jpeg" if jpeg else "rgb565le",
                          jpeg_quality=snapshot.quality if jpeg else None,
                          checksum_verified=True)))


if __name__ == "__main__":
    main()
