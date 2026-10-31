"""Verify snapshot integrity and RGB565 image decoding."""
import struct
import base64
import sys
import contextlib
import io
import json
import tempfile
import types
import unittest
import zlib
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from camera_preview import SerialLines, Snapshot, JpegSnapshot, jpeg_dimensions, checksum, main  # noqa: E402

# A generated 2x3 JPEG fixture, independent of the device camera and encoder.
JPEG = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAAgGBgcGBQgHBwcJCQgKDBQNDAsLDBkSEw8UHRofHh0aHBwgJC4nICIsIxwcKDcpLDAxNDQ0Hyc5PTgyPC4zNDL/"
    "2wBDAQkJCQwLDBgNDRgyIRwhMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjIyMjL/"
    "wAARCAADAAIDASIAAhEBAxEB/8QAHwAAAQUBAQEBAQEAAAAAAAAAAAECAwQFBgcICQoL/8QAtRAAAgEDAwIEAwUFBAQAAAF9AQIDAAQRBRIhMUEGE1FhByJxFDKBkaEII0KxwRVS0fAkM2JyggkKFhcYGRolJicoKSo0NTY3ODk6Q0RFRkdISUpTVFVWV1hZWmNkZWZnaGlqc3R1dnd4eXqDhIWGh4iJipKTlJWWl5iZmqKjpKWmp6ipqrKztLW2t7i5usLDxMXGx8jJytLT1NXW19jZ2uHi4+Tl5ufo6erx8vP09fb3+Pn6/8QAHwEAAwEBAQEBAQEBAQAAAAAAAAECAwQFBgcICQoL/8QAtREAAgECBAQDBAcFBAQAAQJ3AAECAxEEBSExBhJBUQdhcRMiMoEIFEKRobHBCSMzUvAVYnLRChYkNOEl8RcYGRomJygpKjU2Nzg5OkNERUZHSElKU1RVVldYWVpjZGVmZ2hpanN0dXZ3eHl6goOEhYaHiImKkpOUlZaXmJmaoqOkpaanqKmqsrO0tba3uLm6wsPExcbHyMnK0tPU1dbX2Nna4uPk5ebn6Onq8vP09fb3+Pn6/9oADAMBAAIRAxEAPwCOiiivmj7A/9k=")


def jpeg_lines(source="camera", data=JPEG, width=2, height=3):
    lines = ["HVJPEG WAIT", f"HVJPEG SOURCE {source}",
             f"HVJPEG BEGIN 1 {width} {height} {len(data)} 4294968000 0 75"]
    for offset in range(0, len(data), 192):
        lines.append(f"HVJPEG DATA {offset} " + base64.b64encode(data[offset:offset + 192]).decode())
    return lines + [f"HVJPEG END {checksum(data):08x}"]


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

    def test_serial_partial_reads_keep_odd_hex_fragment_until_newline(self):
        data = struct.pack("<4H", 0xf800, 0x07e0, 0x001f, 0xffff)
        result, lines = Snapshot(), SerialLines()
        chunks = [b"HVCAM BE", b"GIN 2 2 8 123 0\r", b"\nHVCAM DATA 0 00f",
                  b"", data.hex()[3:].encode() + b"\r", b"\nHVCAM END ",
                  f"{checksum(data):08x}".encode(), b"\n"]
        for chunk in chunks[:-1]:
            for line in lines.feed(chunk):
                result.feed(line)
            self.assertFalse(result.complete)
        for line in lines.feed(chunks[-1]):
            result.feed(line)
        self.assertTrue(result.complete)
        self.assertEqual(result.data, data)

    def test_serial_multiple_lines_and_empty_timeout(self):
        lines = SerialLines()
        self.assertEqual(lines.feed(b"noise\nHVCAM WAIT\r\nHVC"),
                         ["noise", "HVCAM WAIT"])
        self.assertEqual(lines.feed(b""), [])
        self.assertEqual(lines.feed(b"AM ERROR no_complete_frame\n"),
                         ["HVCAM ERROR no_complete_frame"])
        self.assertEqual(lines.pending, b"")

    def test_serial_line_limit_accepts_boundary_and_rejects_overflow(self):
        lines = SerialLines(max_line_bytes=8)
        self.assertEqual(lines.feed(b"1234"), [])
        self.assertEqual(lines.feed(b"5678\n"), ["12345678"])
        self.assertEqual(lines.feed(b"12345678"), [])
        with self.assertRaisesRegex(ValueError, "exceeds 8 bytes"):
            lines.feed(b"9")
        self.assertEqual(lines.pending, b"")
        with self.assertRaisesRegex(ValueError, "exceeds 8 bytes"):
            lines.feed(b"123456789\n")
        self.assertEqual(lines.pending, b"")

    def test_odd_hex_payload_has_clear_error_without_partial_data(self):
        result = Snapshot()
        result.feed("HVCAM BEGIN 2 2 8 123 0")
        with self.assertRaisesRegex(ValueError, "odd-length hexadecimal payload"):
            result.feed("HVCAM DATA 0 00f")
        self.assertEqual(result.data, b"")

    def run_cli(self, response, *arguments, extension=".png"):
        class Device:
            writes = []
            def __enter__(self):
                self.assert_control_lines = self.dtr is False and self.rts is False
                return self
            def __exit__(self, *args):
                pass
            def write(self, data):
                self.writes.append(data)
            def read(self, count):
                return response

        device = Device()
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / ("preview" + extension)
            printed = io.StringIO()
            with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=lambda: device)}):
                with contextlib.redirect_stdout(printed):
                    main(["--port", "test", "--output", str(output), *arguments])
            result = json.loads(printed.getvalue().splitlines()[-1])
            self.assertTrue(output.read_bytes().startswith(b"\xff\xd8" if extension == ".jpg" else b"\x89PNG"))
        self.assertTrue(device.assert_control_lines)
        return device.writes, result

    def response(self, source=""):
        data = bytes.fromhex("00f8")
        return ("HVCAM WAIT\n" + source + "HVCAM BEGIN 1 1 2 789 0\n"
                "HVCAM DATA 0 00f8\n" + f"HVCAM END {checksum(data):08x}\n").encode()

    def test_cli_default_keeps_camera_command(self):
        writes, result = self.run_cli(self.response())
        self.assertEqual(writes, [b"hv_camera snapshot\r\n"])
        self.assertEqual(result["source"], "camera")

    def test_cli_model_source_and_capture_timestamp(self):
        writes, result = self.run_cli(self.response("HVCAM SOURCE model\n"), "--source", "model")
        self.assertEqual(writes, [b"hv_camera input\r\n"])
        self.assertEqual(result["source"], "model")
        self.assertEqual(result["captured_ms"], 789)
        self.assertFalse(result["rotate_cw90"])

    def test_cli_model_rejects_existing_export_and_missing_source(self):
        with self.assertRaisesRegex(RuntimeError, "another export"):
            self.run_cli(b"HVCAM BUSY\n", "--source", "model")
        with self.assertRaisesRegex(RuntimeError, "Unverified model source"):
            self.run_cli(self.response(), "--source", "model")

    def test_cli_model_reports_stage1_error(self):
        with self.assertRaisesRegex(RuntimeError, "model_input_requires_stage2"):
            self.run_cli(b"HVCAM ERROR model_input_requires_stage2\n", "--source", "model")

    def test_cli_full_camera_and_model_jpeg_preserve_provenance(self):
        for source, expected in (("jpeg", "camera"), ("inputjpeg", "model")):
            with self.subTest(source=source):
                response = ("\n".join(jpeg_lines(expected)) + "\n").encode()
                writes, report = self.run_cli(response, "--source", source, extension=".jpg")
                self.assertEqual(writes, [f"hv_camera {source}\r\n".encode()])
                self.assertEqual(report["captured_ms"], 4294968000)
                self.assertEqual((report["source_width"], report["source_height"]), (2, 3))
                self.assertEqual(report["bytes"], len(JPEG))
                self.assertEqual(report["encoding"], "jpeg")
                self.assertTrue(report["checksum_verified"])

    def test_cli_jpeg_busy_and_wrong_source_are_not_an_existing_frame(self):
        with self.assertRaisesRegex(RuntimeError, "another export"):
            self.run_cli(b"HVJPEG BUSY\n", "--source", "jpeg")
        with self.assertRaisesRegex(ValueError, "Unverified JPEG source"):
            self.run_cli(("\n".join(jpeg_lines("camera")) + "\n").encode(), "--source", "inputjpeg")


class JpegSnapshotTests(unittest.TestCase):
    def parse(self, lines):
        snapshot = JpegSnapshot()
        for line in lines:
            snapshot.feed(line)
        return snapshot

    def test_integrity_orientation_and_late_wait(self):
        lines = jpeg_lines()
        snapshot = self.parse(lines[1:])
        self.assertFalse(snapshot.complete)
        snapshot.feed(lines[0])
        self.assertTrue(snapshot.complete)
        self.assertFalse(snapshot.rotate_cw90)
        self.assertEqual(snapshot.data, JPEG)
        self.assertEqual(jpeg_dimensions(JPEG), (2, 3))
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "capture.jpg"
            snapshot.save(output)
            self.assertEqual(output.read_bytes(), JPEG)

    def test_corruption_and_incomplete_data_reject(self):
        lines = jpeg_lines()
        with self.assertRaisesRegex(ValueError, "checksum mismatch"):
            self.parse(lines[:-1] + ["HVJPEG END 00000000"])
        with self.assertRaisesRegex(ValueError, "Missing, repeated"):
            self.parse(lines[:4] + lines[3:])
        with self.assertRaisesRegex(ValueError, "Missing, repeated"):
            self.parse(lines[:3] + lines[4:])
        snapshot = self.parse(lines[:-1])
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaisesRegex(ValueError, "authorization and integrity"):
                snapshot.save(Path(folder) / "no.jpg")

    def test_base64_line_dimensions_and_orientation_bounds(self):
        for payload in ("A", "AA=", "A" * 260, "@@@@"):
            with self.subTest(payload=payload[:10]):
                with self.assertRaises(ValueError):
                    self.parse(jpeg_lines()[:3] + ["HVJPEG DATA 0 " + payload])
        for header in ("HVJPEG BEGIN 1 321 3 20 1 0 75",
                       "HVJPEG BEGIN 1 2 3 200000 1 0 75",
                       "HVJPEG BEGIN 1 2 3 20 1 1 75",
                       "HVJPEG BEGIN 2 2 3 20 1 0 75"):
            with self.subTest(header=header), self.assertRaises(ValueError):
                self.parse(["HVJPEG SOURCE camera", header])
        with self.assertRaisesRegex(ValueError, "advertised dimensions"):
            self.parse(jpeg_lines(width=3, height=2))

    def test_non_jpeg_bytes_cannot_pass_only_a_matching_checksum(self):
        for data in (b"arbitrary bytes", b"\xff\xd8\xff\xda\x00\x02\xff\xd9",
                     b"\xff\xd8\xff\xc0\x00\x01\xff\xd9"):
            with self.subTest(data=data), self.assertRaises(ValueError):
                self.parse(jpeg_lines(data=data))

    def test_duplicate_source_and_authorization_reject(self):
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            self.parse(["HVJPEG WAIT", "HVJPEG WAIT"])
        with self.assertRaisesRegex(ValueError, "Unverified"):
            self.parse(["HVJPEG SOURCE camera", "HVJPEG SOURCE camera"])

    def test_jpeg_png_decode_keeps_encoded_orientation(self):
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Optional Pillow is not installed")
        with tempfile.TemporaryDirectory() as folder:
            output = Path(folder) / "capture.png"
            self.parse(jpeg_lines()).save(output)
            with Image.open(output) as image:
                self.assertEqual(image.size, (2, 3))
                self.assertEqual(image.mode, "RGB")


if __name__ == "__main__":
    unittest.main()
