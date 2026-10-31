import io
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from camera_preview import SerialLines
from collect_hand_samples import collect_frame, matching_box, observation
from test_camera_preview import jpeg_lines


class MemorySerial:
    """A deterministic in-memory stream; never opens a physical serial port."""
    def __init__(self, lines):
        self.remaining = ('\n'.join(lines) + '\n').encode('utf-8')
        self.writes = []

    def write(self, data):
        self.writes.append(data)

    def read(self, size):
        if not self.remaining:
            raise AssertionError('collector did not finish or reject the complete fake stream')
        result, self.remaining = self.remaining[:size], self.remaining[size:]
        return result


def hand_row(**patch):
    return dict(v=1, event='observation', seq=500, captured_ms=1000, age_ms=100,
                epoch=0, width=2, height=3, hands=1, box=[0, 0, 2, 3],
                detect_score=0.9, valid=True) | patch


def model_jpeg(captured=1000):
    # Reuse the existing generated 2x3 JPEG; replace only its capture timestamp.
    return [line.replace('4294968000', str(captured)) for line in jpeg_lines('model')]


class SampleEvidenceTests(unittest.TestCase):
    def test_requires_exact_frame_and_valid_single_hand(self):
        snap = SimpleNamespace(captured_ms=100, width=320, height=240)
        row = dict(captured_ms=100, width=320, height=240, hands=1,
                   valid=True, box=[10, 20, 100, 200])
        self.assertEqual(matching_box(row, snap), [10, 20, 100, 200])
        for patch in ({'captured_ms': 101}, {'valid': False}, {'hands': 2},
                      {'width': 240}, {'height': 320}, {'box': [10, 20, 10, 200]},
                      {'box': [-1, 20, 100, 200]}, {'box': [10, 20, 321, 200]},
                      {'box': [True, 20, 100, 200]}, {'box': [10.0, 20, 100, 200]}):
            with self.subTest(patch=patch):
                self.assertIsNone(matching_box(row | patch, snap))

    def test_only_hand_observation_protocol_is_accepted(self):
        row = {'v': 1, 'event': 'observation', 'captured_ms': 100}
        self.assertEqual(observation('prefix HG ' + json.dumps(row)), row)
        self.assertIsNone(observation('HG ' + json.dumps(row | {'v': 2})))
        self.assertIsNone(observation('HG ' + json.dumps(row | {'event': 'ready'})))
        self.assertIsNone(observation('HG {truncated'))
        self.assertIsNone(observation('HV ' + json.dumps(row)))

    def collect(self, lines):
        device = MemorySerial(lines)
        try:
            return collect_frame(device, SerialLines(max_line_bytes=65536, encoding='utf-8'),
                                 io.StringIO(), timeout=1)
        finally:
            self.assertEqual(device.writes, [b'hv_camera inputjpeg\r\n'])

    def test_complete_model_jpeg_matches_its_actual_observation(self):
        row = hand_row()
        snapshot, matched, box = self.collect(['HG ' + json.dumps(row), *model_jpeg()])
        self.assertTrue(snapshot.complete)
        self.assertEqual(snapshot.captured_ms, 1000)
        self.assertEqual(matched, row)
        self.assertEqual(box, [0, 0, 2, 3])

    def test_reboot_cannot_match_old_detection_to_new_same_timestamp_jpeg(self):
        # Both boots can produce captured_ms=1000. Matching that integer alone
        # used to accept seq=500 from the old boot for the new JPEG.
        for marker in (
            'ESP-ROM:esp32s3-20210327',
            'rst:0x1 (POWERON)',
            "Guru Meditation Error: Core 1 panic'ed (LoadProhibited)",
            'Restarting...',
            'HG {"v":1,"event":"ready","backend":"hand"}',
            'HG {"v": 1, "event": "ready", "backend": "hand"}',
            'prefix HG { "event" : "ready", "v": 1 }',
        ):
            with self.subTest(marker=marker):
                with self.assertRaisesRegex(RuntimeError, '重启'):
                    self.collect(['HG ' + json.dumps(hand_row()), marker, *model_jpeg()])

    def test_regressing_or_duplicate_stream_identity_is_rejected(self):
        for patch in (
            {'captured_ms': 999, 'seq': 501},
            {'captured_ms': 1000, 'seq': 501},
            {'captured_ms': 1001, 'seq': 499},
            {'captured_ms': 1001, 'seq': 500},
        ):
            with self.subTest(patch=patch):
                with self.assertRaisesRegex(RuntimeError, '倒退'):
                    self.collect(['HG ' + json.dumps(hand_row()),
                                  'HG ' + json.dumps(hand_row(**patch)), *model_jpeg()])

    def test_invalid_stream_identity_is_rejected(self):
        for patch in ({'captured_ms': -1}, {'captured_ms': True}, {'captured_ms': 1.0},
                      {'seq': 0}, {'seq': -1}, {'seq': True}, {'seq': 1.0}):
            with self.subTest(patch=patch):
                with self.assertRaisesRegex(RuntimeError, '无效'):
                    self.collect(['HG ' + json.dumps(hand_row(**patch)), *model_jpeg()])


if __name__ == '__main__':
    unittest.main()
