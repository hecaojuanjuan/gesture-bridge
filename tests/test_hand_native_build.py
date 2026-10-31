"""Native build CLI boundaries; no SDK preparation, subprocess or USB access."""
import contextlib
import io
import os
from pathlib import Path
import runpy
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch


ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "tools/build.py"


class NativeHandBuildTest(unittest.TestCase):
    def assert_rejected_before_sdk(self, arguments, *, cache=None):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            if cache is not None:
                path = root / ".work/native-test/apps/build/CMakeCache.txt"
                path.parent.mkdir(parents=True)
                path.write_text(cache, encoding="utf-8")
            fake_prepare = types.ModuleType("prepare_sdk")
            fake_prepare.ROOT = root
            fake_prepare.SDK = root / "sdk-must-not-be-accessed"
            fake_prepare.prepare = Mock(side_effect=AssertionError("SDK prepare reached"))
            stderr = io.StringIO()
            with patch.dict(sys.modules, {"prepare_sdk": fake_prepare}), \
                    patch.object(sys, "argv", [str(BUILD), *arguments]), \
                    patch.object(os.environ, "copy", side_effect=AssertionError("SDK environment reached")) as environment, \
                    patch("subprocess.call", side_effect=AssertionError("SDK/USB subprocess reached")) as execute, \
                    contextlib.redirect_stderr(stderr):
                with self.assertRaises(SystemExit) as error:
                    runpy.run_path(str(BUILD), run_name="__main__")
                self.assertEqual(error.exception.code, 2, stderr.getvalue())
                self.assertIn("error:", stderr.getvalue())
                fake_prepare.prepare.assert_not_called()
                environment.assert_not_called()
                execute.assert_not_called()
            return stderr.getvalue()

    def native_build(self, *extra):
        return ["headvoice", "build", "--vision", "hand", "--stage", "2",
                "--work-name", "native-test", "--hand-native-partition", "espdl_model", *extra]

    def test_invalid_action_backend_and_stage_rejected_before_sdk(self):
        cases = [
            ["headvoice", action, "--vision", "hand", "--work-name", "native-test",
             "--port", "/dev/never-open", "--hand-native-partition", "espdl_model"]
            for action in ("flash", "monitor")
        ]
        cases.extend([
            ["baseline", "build", "--vision", "hand", "--stage", "2", "--work-name", "native-test",
             "--hand-native-partition", "espdl_model"],
            self.native_build("--vision", "face"),
            self.native_build("--vision", "coco"),
            self.native_build("--stage", "3"),
            self.native_build("--gimbal"),
        ])
        for arguments in cases:
            with self.subTest(arguments=arguments):
                self.assert_rejected_before_sdk(arguments)

    def test_isolated_workspace_required_before_sdk(self):
        self.assert_rejected_before_sdk([
            "headvoice", "build", "--vision", "hand", "--stage", "2",
            "--hand-native-partition", "espdl_model"])
        for work_name in ("headvoice", "baseline", "../escape", "UPPER", "", "/tmp/work"):
            with self.subTest(work_name=work_name):
                self.assert_rejected_before_sdk(self.native_build("--work-name", work_name))

    def test_invalid_partition_syntax_rejected_before_sdk(self):
        for label in ("../model", "has space", "model;erase", "x" * 16, "-model", "模型"):
            with self.subTest(label=label):
                self.assert_rejected_before_sdk(self.native_build("--hand-native-partition", label))

    def test_custom_weights_cannot_be_combined_with_native(self):
        with tempfile.TemporaryDirectory() as directory:
            weights = Path(directory) / "hv_hand_weights.h"
            self.assert_rejected_before_sdk(self.native_build("--hand-weights", str(weights)))
            weights.write_text("/* existing legacy model header */\n", encoding="utf-8")
            self.assert_rejected_before_sdk(self.native_build("--hand-weights", str(weights)))

    def test_native_cached_workspace_cannot_use_generic_full_flash(self):
        # CMake may preserve an untyped command-line variable in a cache when
        # configuration fails before the owning set(... CACHE STRING) executes.
        # The deployment guard must not depend on successful cache typing.
        for cache_type in ("STRING", "UNINITIALIZED", "INTERNAL"):
            with self.subTest(cache_type=cache_type):
                stderr = self.assert_rejected_before_sdk(
                    ["headvoice", "flash", "--work-name", "native-test", "--port", "/dev/never-open"],
                    cache=f"HEADVOICE_HAND_NATIVE_PARTITION:{cache_type}=espdl_model\n")
                self.assertIn("full SDK flash", stderr)


if __name__ == "__main__":
    unittest.main()
