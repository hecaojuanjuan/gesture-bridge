"""Serial capture must preserve real lines and keep cloud payloads off stdout."""
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from capture_serial import capture, diagnostic_summary, main, open_device, record_line  # noqa: E402


class FakeDevice:
    def __init__(self, chunks):
        self.chunks = iter(chunks)
        self.now = 0

    def read(self, size):
        self.now += 1
        chunk = next(self.chunks, b"")
        if isinstance(chunk, Exception):
            raise chunk
        return chunk

    def __enter__(self):
        self.closed = False
        return self

    def __exit__(self, *args):
        self.closed = True


class FakeSerialException(Exception):
    pass


class CaptureSerialTest(unittest.TestCase):
    def run_capture(self, chunks, quiet=False):
        device, output, stdout = FakeDevice(chunks), io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(stdout):
            capture(device, output, len(chunks), quiet=quiet, clock=lambda: device.now)
        return [json.loads(line) for line in output.getvalue().splitlines()], stdout.getvalue()

    def test_timeout_and_split_newline_do_not_drop_pose(self):
        chunks = [b'I (9) HV {"event":"po', b'', b'se","age_ms":90}\r',
                  b'\nHP {"v":1,"boot":7,"id":9}\n']
        rows, stdout = self.run_capture(chunks)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["device"], {"event": "pose", "age_ms": 90})
        self.assertEqual(rows[1]["panel"]["boot"], 7)
        self.assertEqual(stdout.count('"event": "pose"'), 1)

    def test_utf8_cloud_message_is_preserved_only_in_file(self):
        wire = 'cloud password=secret-token transcript=你好\n'.encode()
        split = wire.index('好'.encode()) + 1
        rows, stdout = self.run_capture([wire[:split], b'', wire[split:]])
        self.assertEqual(rows[0]["line"], wire.decode().rstrip('\n'))
        self.assertEqual(stdout, '')

    def test_final_fragment_is_saved_but_not_parsed_or_printed(self):
        rows, stdout = self.run_capture([b'HV {"event":"pose","age_ms":10}'])
        self.assertTrue(rows[0]["partial_line"])
        self.assertNotIn('device', rows[0])
        self.assertEqual(stdout, '')

    def test_quiet_keeps_all_records(self):
        rows, stdout = self.run_capture([b'ESP-ROM:esp32s3-20210327\n'
                                         b'HV {"event":"metrics","captured":30}\n'], quiet=True)
        self.assertEqual(len(rows), 2)
        self.assertEqual(stdout, '')

    def test_summary_omits_cloud_prefix_and_snapshot_pixels(self):
        line = ('cloud token=secret bsp_camera: got 30 frames good=30 empty=0 '
                'last_bytes=153600 dt=1000 ms')
        self.assertEqual(diagnostic_summary(record_line(line)), line[line.index('bsp_camera:'):])
        self.assertIsNone(diagnostic_summary(record_line('HVCAM DATA 0 00ff00ff')))
        self.assertEqual(diagnostic_summary(record_line('HVCAM END deadbeef')), 'HVCAM END deadbeef')
        row = record_line('cloud token=secret HP {"v":1,"boot":7,"secret":"hidden"}')
        self.assertNotIn('secret', diagnostic_summary(row))

    def test_boot_and_panic_summary(self):
        for line in ['rst:0xc (RTC_SW_CPU_RST),boot:0x8',
                     "Guru Meditation Error: Core  0 panic'ed (IllegalInstruction).",
                     'Brownout detector was triggered',
                     'CORRUPT HEAP: bad tail', 'Restarting...']:
            self.assertIsNotNone(diagnostic_summary(record_line(line)))
        self.assertIsNone(diagnostic_summary(record_line('wifi: connected with private-ssid')))

    def test_bad_json_is_raw_evidence_not_structured_pose(self):
        for line in ['HV {broken}', 'HV {"event":', 'unrelated line']:
            self.assertNotIn('device', record_line(line))

    def test_control_lines_are_set_before_open(self):
        class Port:
            dtr = rts = True

            def open(self):
                self.opened = (self.port, self.baudrate, self.timeout, self.dtr, self.rts)

        port = open_device(SimpleNamespace(Serial=Port), 'test-only')
        self.assertEqual(port.opened, ('test-only', 115200, 0.5, False, False))

    def run_main(self, output, chunks):
        device = FakeDevice(chunks)
        stderr = io.StringIO()
        serial_module = SimpleNamespace(SerialException=FakeSerialException)

        def timed_capture(device, target, seconds, quiet=False):
            return capture(device, target, seconds, quiet=quiet, clock=lambda: device.now)

        with mock.patch.dict(sys.modules, {'serial': serial_module}), \
                mock.patch('capture_serial.open_device', return_value=device) as opened, \
                mock.patch('capture_serial.capture', side_effect=timed_capture), \
                contextlib.redirect_stderr(stderr):
            status = main(['--port', 'test-only', '--seconds', str(max(1, len(chunks))),
                           '--quiet', '--output', str(output)])
        return status, stderr.getvalue(), device, opened

    def test_existing_log_is_preserved_before_opening_serial(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'fault.jsonl'
            original = b'earlier fault evidence\n'
            output.write_bytes(original)
            with mock.patch.dict(sys.modules, {'serial': SimpleNamespace()}), \
                    mock.patch('capture_serial.open_device') as opened, \
                    contextlib.redirect_stderr(io.StringIO()) as stderr:
                with self.assertRaises(SystemExit) as raised:
                    main(['--port', 'test-only', '--output', str(output)])
            self.assertEqual(raised.exception.code, 2)
            opened.assert_not_called()
            self.assertEqual(output.read_bytes(), original)
            self.assertIn('--output', stderr.getvalue())

    def test_serial_disconnect_returns_failure_and_keeps_pending_fragment(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'fault.jsonl'
            chunks = [b'ESP-ROM:esp32s3-20210327\nHG {"event":',
                      FakeSerialException('device disconnected')]
            status, stderr, device, _ = self.run_main(output, chunks)
            rows = [json.loads(line) for line in output.read_text().splitlines()]
            self.assertNotEqual(status, 0)
            self.assertTrue(device.closed)
            self.assertEqual(rows[0]['line'], 'ESP-ROM:esp32s3-20210327')
            self.assertEqual(rows[1]['line'], 'HG {"event":')
            self.assertTrue(rows[1]['partial_line'])
            self.assertIn('device disconnected', stderr)
            self.assertIn(str(output), stderr)

    def test_no_complete_lines_returns_failure_including_partial_only(self):
        for wire in (b'', b'\x00\xff\x00'):
            with self.subTest(wire=wire), tempfile.TemporaryDirectory() as directory:
                output = Path(directory) / 'empty.jsonl'
                status, stderr, device, _ = self.run_main(output, [wire])
                self.assertNotEqual(status, 0)
                self.assertTrue(device.closed)
                self.assertIn('未收到完整日志行', stderr)
                if wire:
                    self.assertTrue(json.loads(output.read_text())['partial_line'])
                else:
                    self.assertEqual(output.read_text(), '')

    def test_complete_line_capture_returns_success(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'capture.jsonl'
            status, stderr, device, _ = self.run_main(output, [b'HG {"v":1,"event":"observation","hands":0}\n'])
            self.assertEqual(status, 0)
            self.assertEqual(stderr, '')
            self.assertTrue(device.closed)
            self.assertNotIn('partial_line', json.loads(output.read_text()))


if __name__ == '__main__':
    unittest.main()
