"""Host-only same-frame pairing and CLI safety tests; no real serial ports."""
import contextlib
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
import hand_frame_probe as probe
from test_camera_preview import JPEG, jpeg_lines


CAPTURE = 4294968000


def observation(**changes):
    return {"v": 1, "event": "observation", "seq": 10, "captured_ms": CAPTURE,
            "epoch": 0, "width": 2, "height": 3, "hands": 1,
            "box": [0, 0, 2, 3], "valid": True, "gesture": "two", **changes}


def hg(**changes):
    return "HG " + json.dumps(observation(**changes))


def wire(lines):
    return ("\n".join(lines) + "\n").encode()


class FakeDevice:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.now = 0
        self.timeout = .25
        self.writes = []
        self.opened = False
        self.closed = False

    def open(self):
        assert self.dtr is False and self.rts is False
        self.opened = True

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def write(self, command):
        self.writes.append(command)

    def read(self, _count):
        chunk = next(self.chunks, None)
        self.now += .01 if chunk is not None else self.timeout
        return chunk or b""


class HandFrameProbeTest(unittest.TestCase):
    def collect(self, chunks, timeout=1):
        device = FakeDevice(chunks)
        snapshot, metadata = probe.collect_probe(device, timeout, clock=lambda: device.now)
        self.assertEqual(bytes(snapshot.data), JPEG)
        self.assertTrue(snapshot.complete)
        self.assertTrue(all(command == b"hv_camera inputjpeg\r\n" for command in device.writes))
        self.assertLessEqual(device.now, timeout + 2)
        return metadata

    def test_fragmented_serial_and_hg_before_jpeg_match_exact_frame(self):
        data = wire(["private network message", hg(), *jpeg_lines("model")])
        meta = self.collect([data[i:i + 13] for i in range(0, len(data), 13)], timeout=5)
        self.assertEqual(meta["paired_status"], "matched")
        self.assertEqual(meta["observation"], observation())
        self.assertEqual(meta["box"], [0, 0, 2, 3])
        self.assertNotIn("private network", json.dumps(meta))

    def test_hg_after_jpeg_is_collected_within_pairing_window(self):
        meta = self.collect([wire(jpeg_lines("model")), b"", wire([hg()])])
        self.assertEqual(meta["paired_status"], "matched")
        self.assertEqual(meta["matching_count"], 1)

    def test_missing_and_nearby_timestamp_or_wrong_dimensions_do_not_pair(self):
        for rows in ([], [hg(captured_ms=CAPTURE + 1)], [hg(width=3)], [hg(seq=True)], [hg(box=[0, 0, 9, 9])]):
            with self.subTest(rows=rows):
                meta = self.collect([wire([*rows, *jpeg_lines("model")])])
                self.assertEqual(meta["paired_status"], "missing")
                self.assertIsNone(meta["observation"])
                self.assertIsNone(meta["box"])

    def test_two_exact_observations_are_ambiguous_not_arbitrarily_chosen(self):
        for duplicate in (hg(), hg(seq=11, gesture="five")):
            meta = self.collect([wire([hg(), *jpeg_lines("model"), duplicate])])
            self.assertEqual(meta["paired_status"], "ambiguous")
            self.assertEqual(meta["matching_count"], 2)
            self.assertIsNone(meta["observation"])
            self.assertEqual(len(meta["ambiguous_observations"]), 2)

    def test_boot_boundary_before_export_clears_old_observations(self):
        for marker in ("ESP-ROM:esp32s3", 'HG {"v":1,"event":"ready"}',
                       'HP {"v":1,"boot":2}'):
            meta = self.collect([wire(['HP {"v":1,"boot":1}', hg(), marker, *jpeg_lines("model")])])
            self.assertEqual(meta["paired_status"], "missing")
            self.assertGreater(meta["boot_segment"], 0)

    def test_new_boot_observation_can_pair_only_after_old_cache_cleared(self):
        meta = self.collect([wire([hg(seq=90), "ESP-ROM:esp32s3", hg(seq=1), *jpeg_lines("model")])])
        self.assertEqual(meta["paired_status"], "matched")
        self.assertEqual(meta["observation"]["seq"], 1)

    def test_restart_or_ready_after_authorization_or_begin_rejects_export(self):
        for prefix in (["HVJPEG WAIT"], jpeg_lines("model")[:3]):
            for marker in ("ESP-ROM:esp32s3", "rst:0x1", 'HG {"v":1,"event":"ready"}',
                           'HP {"v":1,"boot":2}'):
                with self.subTest(prefix=prefix, marker=marker):
                    device = FakeDevice([wire(['HP {"v":1,"boot":1}', *prefix, marker])])
                    with self.assertRaisesRegex(RuntimeError, "不跨启动"):
                        probe.collect_probe(device, 1, clock=lambda: device.now)

    def test_regressing_sequence_capture_or_epoch_is_a_boundary(self):
        for changes in ({"seq": 9}, {"captured_ms": CAPTURE - 1}, {"epoch": 1}):
            with self.subTest(changes=changes):
                device = FakeDevice([wire([hg(), "HVJPEG WAIT", hg(**changes)])])
                with self.assertRaisesRegex(RuntimeError, "HG 时间"):
                    probe.collect_probe(device, 1, clock=lambda: device.now)
        meta = self.collect([wire([hg(seq=90), hg(seq=1, captured_ms=1), *jpeg_lines("model")])])
        self.assertEqual(meta["paired_status"], "missing")

    def test_wrong_source_corrupt_checksum_and_dimensions_are_rejected(self):
        broken = jpeg_lines("model")
        broken[-1] = "HVJPEG END 00000000"
        for rows in (jpeg_lines("camera"), broken, jpeg_lines("model", width=3),
                     jpeg_lines("model")[1:]):
            device = FakeDevice([wire(rows)])
            with self.subTest(rows=rows[:2]):
                with self.assertRaises((ValueError, TimeoutError)):
                    probe.collect_probe(device, 1, clock=lambda: device.now)

    def test_cli_saves_original_jpeg_and_explicit_missing_metadata_without_network_logs(self):
        device = FakeDevice([wire(["PRIVATE NETWORK CONTENT", *jpeg_lines("model")])])
        collect = probe.collect_probe
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "v-frame-20261031-203000.jpg"
            printed = io.StringIO()
            with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=lambda: device)}), \
                    patch.object(probe, "collect_probe", side_effect=lambda d, t: collect(d, t, lambda: device.now)), \
                    contextlib.redirect_stdout(printed):
                result = probe.main(["--port", "fake", "--output", str(output), "--timeout", "1"])
            self.assertEqual(result, 0)
            self.assertTrue(device.opened and device.closed)
            self.assertEqual(output.read_bytes(), JPEG)
            metadata = json.loads(output.with_suffix(".json").read_text())
            self.assertEqual(metadata["paired_status"], "missing")
            self.assertNotIn("PRIVATE NETWORK", printed.getvalue())
            self.assertNotIn("PRIVATE NETWORK", json.dumps(metadata))

    def test_existing_either_output_and_invalid_arguments_never_construct_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "new.jpg"
            serial = Mock(side_effect=AssertionError("must not open serial"))
            with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=serial)}), \
                    contextlib.redirect_stderr(io.StringIO()):
                for target in (output, output.with_suffix(".json")):
                    target.write_text("keep")
                    with self.assertRaises(SystemExit) as error:
                        probe.main(["--port", "fake", "--output", str(output)])
                    self.assertEqual(error.exception.code, 2)
                    self.assertEqual(target.read_text(), "keep")
                    target.unlink()
                for tail in (["--timeout", "nan"], ["--timeout", "inf"], ["--timeout", "0"],
                             ["--timeout", "-1"], ["--port", ""], ["--output", str(output.with_suffix(".png"))]):
                    with self.assertRaises(SystemExit) as error:
                        probe.main(["--port", "fake", "--output", str(output), *tail])
                    self.assertEqual(error.exception.code, 2)
                serial.assert_not_called()

    def test_failed_capture_removes_only_its_reserved_outputs(self):
        device = FakeDevice([wire(["HVJPEG WAIT", "ESP-ROM:esp32s3"])])
        collect = probe.collect_probe
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "failed.jpg"
            with patch.dict(sys.modules, {"serial": types.SimpleNamespace(Serial=lambda: device)}), \
                    patch.object(probe, "collect_probe", side_effect=lambda d, t: collect(d, t, lambda: device.now)), \
                    contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(probe.main(["--port", "fake", "--output", str(output)]), 1)
            self.assertFalse(output.exists())
            self.assertFalse(output.with_suffix(".json").exists())
            self.assertTrue(device.closed)

    def test_device_error_does_not_echo_interleaved_network_text(self):
        device = FakeDevice([wire(["HVJPEG ERROR no_input_memory PRIVATE NETWORK CONTENT"])])
        with self.assertRaisesRegex(RuntimeError, "设备报告 JPEG 导出失败") as error:
            probe.collect_probe(device, 1, clock=lambda: device.now)
        self.assertNotIn("PRIVATE NETWORK", str(error.exception))


if __name__ == "__main__":
    unittest.main()
