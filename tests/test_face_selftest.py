"""Check diagnostic build boundaries without preparing an SDK or touching USB."""
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from prepare_sdk import face_selftest_fixture, prepare  # noqa: E402


class FaceSelftestTest(unittest.TestCase):
    def test_missing_fixture_has_fixed_source_and_destination(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "human_face.jpg"
            with self.assertRaisesRegex(ValueError, "dc380d450835d42f92777121a0cd4fc67d7c3a8c") as error:
                face_selftest_fixture(path)
            self.assertIn(str(path), str(error.exception))

    def test_modified_fixture_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "human_face.jpg"
            path.write_bytes(b"not the pinned official JPEG")
            with self.assertRaisesRegex(ValueError, "SHA256 mismatch"):
                face_selftest_fixture(path)

    def test_prepare_rejects_nonisolated_or_nonface_before_sdk_access(self):
        with patch("prepare_sdk.subprocess.check_output") as sdk:
            for mode, vision, workspace in (
                ("headvoice", "coco", "test"),
                ("headvoice", "face", None),
                ("headvoice", "face", "headvoice"),
                ("baseline", "coco", "test"),
            ):
                with self.subTest(mode=mode, vision=vision, workspace=workspace):
                    with self.assertRaisesRegex(ValueError, "isolated workspace"):
                        prepare(mode, vision, workspace, face_selftest=True)
            sdk.assert_not_called()

    def test_cli_rejects_selftest_outside_stage2_face_build(self):
        for arguments in (
            ["headvoice", "build", "--stage", "2", "--work-name", "test"],
            ["headvoice", "build", "--vision", "face", "--stage", "3", "--work-name", "test"],
            ["headvoice", "build", "--vision", "face", "--stage", "2"],
            ["headvoice", "build", "--vision", "face", "--stage", "2", "--work-name", "headvoice"],
            ["headvoice", "flash", "--vision", "face", "--stage", "2", "--work-name", "test"],
        ):
            with self.subTest(arguments=arguments):
                result = subprocess.run(
                    [sys.executable, str(ROOT / "tools/build.py"), *arguments, "--face-selftest"],
                    cwd=ROOT, capture_output=True, text=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn("requires a face stage 2 build", result.stderr)


if __name__ == "__main__":
    unittest.main()
