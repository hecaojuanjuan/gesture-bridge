"""Exercise the serial protocol without opening hardware ports."""
from control_panel import exchange, parse_reply, validate_action
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))


def reply(request_id=1, **fields):
    row = dict(id=request_id, ok=True, state="online", mode="auto",
               brightness=20, ready=True, render_ok=True, rgb=[0, 9, 0],
               uptime=12)
    row.update(fields)
    return "PANEL " + json.dumps(row)


class FakeSerial:
    def __init__(self, lines):
        self.lines = iter(lines)
        self.written = []

    def write(self, data):
        self.written.append(data)

    def flush(self):
        pass

    def read_until(self, *args):
        return next(self.lines, b"")


class PanelProtocolTests(unittest.TestCase):
    def test_ignores_noise_stale_and_partial_replies(self):
        self.assertIsNone(parse_reply("cloud connected", 1))
        self.assertIsNone(parse_reply(reply(2), 1))
        self.assertIsNone(parse_reply('PANEL {"id":1', 1))
        self.assertEqual(parse_reply("\x1b[0m" + reply(), 1)["state"],
                         "online")

    def test_rejects_errors_and_invalid_fields(self):
        for fields in ({"ok": False}, {"brightness": 101},
                       {"state": "invented"}, {"rgb": [0, -1, 0]},
                       {"ready": "true"}):
            with self.subTest(fields=fields), self.assertRaises(RuntimeError):
                parse_reply(reply(**fields), 1)

    def test_command_allowlist_prevents_arbitrary_serial_commands(self):
        for action in ("status", "auto", "off", "restart",
                       "brightness 100", "color 255 0 20"):
            validate_action(action)
        for action in ("hv_gimbal start", "color 256 0 0",
                       "brightness -1", "auto;reboot", "off\r\nreboot"):
            with self.subTest(action=action), self.assertRaises(ValueError):
                validate_action(action)

    def test_fragmented_reply_is_reassembled_and_correlated(self):
        body = reply().encode()
        device = FakeSerial([b"noise\n", (reply(2) + "\n").encode(),
                             body[:30], body[30:] + b"\n"])
        self.assertEqual(exchange(device, 1, "status")["uptime"], 12)
        self.assertEqual(device.written, [b"hv_panel 1 status\r\n"])

    def test_timeout_never_reports_success(self):
        device = FakeSerial([])
        with patch("control_panel.time.monotonic", side_effect=[0, 5]):
            with self.assertRaises(TimeoutError):
                exchange(device, 1, "status")

    def test_reboot_invalidates_response(self):
        device = FakeSerial([b"ESP-ROM:esp32s3\n"])
        with self.assertRaises(RuntimeError):
            exchange(device, 1, "status")


if __name__ == "__main__":
    unittest.main()
