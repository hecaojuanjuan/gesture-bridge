"""Verify snapshot integrity and RGB565 image decoding."""
import struct
import sys
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from camera_preview import Snapshot, checksum  # noqa: E402


class CameraPreviewTest(unittest.TestCase):
    def snapshot(self, data, width=2, height=2, rotation=0):
        result = Snapshot()
        result.feed(f"HVCAM BEGIN {width} {height} {len(data)} 123 {rotation}")
        result.feed(f"HVCAM DATA 0 {data.hex()}")
        result.feed(f"HVCAM END {checksum(data):08x}")
        return result

    def pixels(self, image):
        self.assertEqual(image[:8], b"\x89PNG\r\n\x1a\n")
        width, height = struct.unpack(">II", image[16:24])
        offset, compressed = 8, b""
        while offset < len(image):
            size = struct.unpack(">I", image[offset:offset + 4])[0]
            kind = image[offset + 4:offset + 8]
            data = image[offset + 8:offset + 8 + size]
            expected = struct.unpack(
                ">I", image[offset + 8 + size:offset + 12 + size])[0]
            self.assertEqual(zlib.crc32(kind + data), expected)
            if kind == b"IDAT":
                compressed += data
            offset += size + 12
        return width, height, zlib.decompress(compressed)

    def test_rgb565_channels_and_png_crc(self):
        data = struct.pack("<4H", 0xf800, 0x07e0, 0x001f, 0xffff)
        width, height, rows = self.pixels(self.snapshot(data).png())
        self.assertEqual((width, height), (2, 2))
        self.assertEqual(rows, bytes((
            0, 255, 0, 0, 0, 255, 0, 0, 0, 0, 255, 255, 255, 255)))

    def test_clockwise_rotation_matches_inference(self):
        data = struct.pack("<2H", 0xf800, 0x07e0)
        result = self.snapshot(data, width=2, height=1, rotation=1)
        width, height, rows = self.pixels(result.png())
        self.assertEqual((width, height), (1, 2))
        self.assertEqual(rows, bytes((0, 255, 0, 0, 0, 0, 255, 0)))

    def test_missing_chunk_is_rejected(self):
        result = Snapshot()
        result.feed("HVCAM BEGIN 2 2 8 123 0")
        with self.assertRaises(ValueError):
            result.feed("HVCAM DATA 4 00000000")
        with self.assertRaises(ValueError):
            result.png()

    def test_corrupted_payload_is_rejected(self):
        result = Snapshot()
        result.feed("HVCAM BEGIN 2 2 8 123 0")
        result.feed("HVCAM DATA 0 0000000000000000")
        with self.assertRaises(ValueError):
            result.feed("HVCAM END 00000000")


if __name__ == "__main__":
    unittest.main()
