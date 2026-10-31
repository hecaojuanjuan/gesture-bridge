"""Exercise safety decisions with a fragmented, timed fake serial device."""
from collections import deque
from contextlib import redirect_stdout, redirect_stderr
import io
import json
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from servo_minimal_control import check_stopped, run_test  # noqa: E402


class FakeServo:
    def __init__(self, never_ready=False, wrong_pulse=None, reboot_on_move=False):
        self.now, self.axis, self.pulse, self.expires = 0.0, -1, 0, None
        self.commands, self.chunks = [], deque()
        self.never_ready, self.wrong_pulse = never_ready, wrong_pulse
        self.reboot_on_move = reboot_on_move

    def clock(self):
        return self.now

    @property
    def in_waiting(self):
        return len(self.chunks[0]) if self.chunks else 0

    def event(self, kind, pulse=None):
        line = ("SERVO_MIN " + json.dumps(dict(event=kind, axis=self.axis,
                pulse_us=self.pulse if pulse is None else pulse,
                uptime_ms=int(self.now * 1000))) + "\r\n").encode()
        # A timeout fragment, including a complete JSON object without its
        # newline, must not be treated as a complete acknowledgment.
        self.chunks.extend([line[:9], b"", line[9:37], line[37:-1], line[-1:]])

    def write(self, data):
        command = data.decode().strip()
        self.commands.append(command)
        if command == "status":
            if not self.never_ready:
                self.event("status")
        elif command == "stop":
            self.axis, self.pulse, self.expires = -1, 0, None
            self.event("stopped")
        else:
            axis, pulse = command.split()
            self.axis, self.pulse = (0 if axis == "pan" else 1), int(pulse)
            self.expires = self.now + 2.5
            self.event("set", self.pulse + 5 if self.pulse == self.wrong_pulse else None)
            if self.reboot_on_move:
                self.chunks.append(b"ESP-ROM:esp32s3-20210327\n")
        return len(data)

    def flush(self):
        pass

    def read(self, count):
        self.now += 0.01 if self.chunks else 0.05
        if self.expires is not None and self.now >= self.expires:
            self.axis, self.pulse, self.expires = -1, 0, None
            self.event("lease_expired")
        if not self.chunks:
            return b""
        chunk = self.chunks.popleft()
        if len(chunk) > count:
            self.chunks.appendleft(chunk[count:])
        return chunk[:count]


class ServoMinimalTest(unittest.TestCase):
    def test_status_only_never_sends_motion_or_stop(self):
        device = FakeServo()
        with redirect_stdout(io.StringIO()):
            check_stopped(device, io.StringIO(), clock=device.clock)
        self.assertEqual(device.commands, ["status"])

    def test_status_only_reports_active_output_without_changing_it(self):
        device = FakeServo()
        device.axis, device.pulse = 0, 1500
        with redirect_stdout(io.StringIO()), self.assertRaisesRegex(RuntimeError, "output is active"):
            check_stopped(device, io.StringIO(), clock=device.clock)
        self.assertEqual(device.commands, ["status"])
        self.assertEqual((device.axis, device.pulse), (0, 1500))

    def run_device(self, device, **kwargs):
        log = io.StringIO()
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            run_test(device, log, axis="tilt", clock=device.clock, **kwargs)
        return log.getvalue()

    def test_default_span_stays_small_and_checks_lease_then_stopped_status(self):
        device = FakeServo()
        log = self.run_device(device)
        moves = [line for line in device.commands if line.startswith("tilt ")]
        self.assertEqual(moves, ["tilt 1500", "tilt 1525", "tilt 1500", "tilt 1475", "tilt 1500"])
        self.assertEqual(device.commands[-2:], ["stop", "status"])
        self.assertIn('lease_expired', log)
        self.assertEqual((device.axis, device.pulse), (-1, 0))

    def test_wrong_movement_ack_always_stops_before_another_move(self):
        device = FakeServo(wrong_pulse=1525)
        with self.assertRaisesRegex(RuntimeError, "Acknowledgment does not match"):
            self.run_device(device)
        moves = [line for line in device.commands if line.startswith("tilt ")]
        self.assertEqual(moves, ["tilt 1500", "tilt 1525"])
        self.assertEqual(device.commands[-2:], ["stop", "status"])
        self.assertEqual((device.axis, device.pulse), (-1, 0))

    def test_no_ready_status_never_sends_movement(self):
        device = FakeServo(never_ready=True)
        device.chunks.append(b"ESP-ROM:esp32s3-20210327\n")
        with self.assertRaisesRegex(TimeoutError, "no movement was sent"):
            self.run_device(device)
        self.assertTrue(all(command in ("status", "stop") for command in device.commands))
        self.assertIn("stop", device.commands)
        self.assertGreaterEqual(device.commands.count("status"), 2)

    def test_reboot_while_holding_aborts_before_the_next_jog(self):
        device = FakeServo(reboot_on_move=True)
        with self.assertRaisesRegex(RuntimeError, "restarted"):
            self.run_device(device)
        self.assertEqual([c for c in device.commands if c.startswith("tilt ")], ["tilt 1500"])
        self.assertEqual(device.commands[-2:], ["stop", "status"])

    def test_startup_reset_and_lost_first_status_are_tolerated_before_motion(self):
        class BootingServo(FakeServo):
            def write(self, data):
                if not self.commands:
                    self.commands.append(data.decode().strip())
                    self.chunks.append(b"ESP-ROM:esp32s3-20210327\n")
                    self.event("ready")
                    return len(data)
                return super().write(data)

        device = BootingServo()
        self.run_device(device)
        self.assertEqual(device.commands[:5], ["status", "status", "stop", "status", "tilt 1500"])


if __name__ == "__main__":
    unittest.main()
