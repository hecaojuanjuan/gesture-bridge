"""Exercise one-port startup and corrupted-receipt recovery without hardware."""
import io
import json
import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from face_gimbal_session import DeviceRestarted, FaceGimbalSession, parse_input


def status():
    return dict(event="status", active=False, pan_us=1500, tilt_us=1500,
                pan_armed=False, tilt_armed=False, pan_dir=1, tilt_dir=1,
                directions_ready=False, holding=False, output_fault=False,
                lease_remaining_ms=0, last_stop_reason="none", steps=0,
                limits_us=[1475, 1525], max_step_us=25, max_age_ms=400,
                lost_after_ms=1000)


class FakeSerial:
    def __init__(self, handler):
        self.handler = handler
        self.pending = bytearray()
        self.writes = []

    def write(self, data):
        command = data.decode("ascii").strip()
        self.writes.append(command)
        for line in self.handler(command, len(self.writes)):
            self.pending.extend((line + "\n").encode("utf-8"))

    def flush(self):
        pass

    def read(self, size):
        if not self.pending:
            return b""
        result = self.pending[:size]
        del self.pending[:size]
        return bytes(result)


class FaceGimbalSessionTest(unittest.TestCase):
    def test_waits_through_usb_boot_for_two_safe_statuses(self):
        report = "GIMBAL " + json.dumps(status())

        def handler(command, count):
            self.assertEqual(command, "hv_gimbal status")
            return (["ESP-ROM:esp32s3", "GIMBAL ready pan=17 tilt=18", report]
                    if count == 1 else [report])

        device = FakeSerial(handler)
        session = FaceGimbalSession(device, io.StringIO())
        self.assertEqual(session.startup(timeout=3)["limits_us"], [1475, 1525])
        self.assertEqual(device.writes.count("hv_gimbal status"), 2)

    def test_corrupted_jog_receipt_uses_status_without_replaying_jog(self):
        recovered = status()
        recovered.update(tilt_armed=True)

        def handler(command, count):
            if command == "hv_gimbal jog tilt -25":
                return ['GIMBAL {"event":"stahv_gimbal jog tilt -25']
            if command == "hv_gimbal status":
                return ["GIMBAL " + json.dumps(recovered)]
            self.fail(command)

        device = FakeSerial(handler)
        session = FaceGimbalSession(device, io.StringIO())
        _, report = session.exchange(("jog", "tilt", "-25"))
        self.assertEqual(report["tilt_us"], 1500)
        self.assertEqual(device.writes.count("hv_gimbal jog tilt -25"), 1)
        self.assertEqual(device.writes.count("hv_gimbal status"), 1)

    def test_corrupted_jog_is_confirmed_by_final_pulse(self):
        before = status()
        before.update(tilt_armed=True, tilt_us=1525)
        after = status()
        after.update(tilt_armed=True, tilt_us=1500)

        def handler(command, count):
            if command == "hv_gimbal jog tilt -25":
                return ['GIMBAL {"event":"stahv_gimbal jog tilt -25']
            if command == "hv_gimbal status":
                return ["GIMBAL " + json.dumps(before if count == 1 else after)]
            self.fail(command)

        device = FakeSerial(handler)
        session = FaceGimbalSession(device, io.StringIO())
        session.status = before
        self.assertEqual(session.move_command(["jog", "tilt", "-25"])["tilt_us"], 1500)
        self.assertEqual(device.writes.count("hv_gimbal jog tilt -25"), 1)
        self.assertEqual(device.writes.count("hv_gimbal status"), 2)

    def test_corrupted_jog_with_wrong_pulse_aborts_without_retry(self):
        before = status()
        before.update(tilt_armed=True, tilt_us=1525)

        def handler(command, count):
            if command == "hv_gimbal jog tilt -25":
                return ['GIMBAL {"event":"stahv_gimbal jog tilt -25']
            return ["GIMBAL " + json.dumps(before)]

        device = FakeSerial(handler)
        session = FaceGimbalSession(device, io.StringIO())
        session.status = before
        with self.assertRaisesRegex(RuntimeError, "脉宽变化不符"):
            session.move_command(["jog", "tilt", "-25"])
        self.assertEqual(device.writes.count("hv_gimbal jog tilt -25"), 1)

    def test_corrupted_target_retries_only_read_only_target_after_status(self):
        fresh = dict(event="target", valid=True, people=1, x=0.4, y=0.6,
                     captured_ms=100, age_ms=100)

        def handler(command, count):
            if command == "hv_gimbal target":
                if count == 1:
                    return ['GIMBAL {"event":"targ hv_gimbal target']
                return ["GIMBAL " + json.dumps(fresh),
                        "GIMBAL " + json.dumps(status())]
            if command == "hv_gimbal status":
                return ["GIMBAL " + json.dumps(status())]
            self.fail(f"unexpected motion command: {command}")

        device = FakeSerial(handler)
        session = FaceGimbalSession(device, io.StringIO())
        self.assertEqual(session.target()["x"], 0.4)
        self.assertEqual(device.writes, ["hv_gimbal target", "hv_gimbal status",
                                         "hv_gimbal target"])
        self.assertFalse(session.motion_sent)

    def test_corrupted_target_retry_is_bounded(self):
        def handler(command, count):
            if command == "hv_gimbal target":
                return ['GIMBAL {"event":"targ hv_gimbal target']
            if command == "hv_gimbal status":
                return ["GIMBAL " + json.dumps(status())]
            self.fail(f"unexpected motion command: {command}")

        device = FakeSerial(handler)
        session = FaceGimbalSession(device, io.StringIO())
        with self.assertRaisesRegex(RuntimeError, "连续损坏"):
            session.target()
        self.assertEqual(device.writes.count("hv_gimbal target"), 3)
        self.assertEqual(device.writes.count("hv_gimbal status"), 3)
        self.assertFalse(session.motion_sent)

    def test_restart_during_command_blocks_followup(self):
        device = FakeSerial(lambda command, count: ["ESP-ROM:esp32s3"])
        session = FaceGimbalSession(device, io.StringIO())
        with self.assertRaises(DeviceRestarted):
            session.exchange(("arm", "tilt"))
        self.assertTrue(session.restarted)
        self.assertEqual(device.writes, ["hv_gimbal arm tilt"])

    def test_input_bounds(self):
        self.assertEqual(parse_input("jog tilt -25"), ["jog", "tilt", "-25"])
        self.assertEqual(parse_input("jog pan +25"), ["jog", "pan", "+25"])
        self.assertEqual(parse_input("dir +1 -1"), ["dir", "+1", "-1"])
        for text in ("jog tilt 26", "jog pan 0", "arm p18", "dir 0 1", "start now", "'oops"):
            self.assertIsNone(parse_input(text))


if __name__ == "__main__":
    unittest.main()
