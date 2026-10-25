"""Exercise local identity overrides without using real credentials."""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from prepare_sdk import apply_cloud_identity  # noqa: E402


class CloudIdentityTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.config = self.root / "cloud.json"
        self.header = self.root / "main/cloud/ljyd_cloud.h"
        self.header.parent.mkdir(parents=True)
        self.original = (
            '#define CONFIG_XJIANG_CLOUD_PID 1\n'
            '#define CONFIG_XJIANG_CLOUD_SECERT "original"\n')
        self.header.write_text(self.original, encoding="utf-8")

    def write_config(self, value):
        self.config.write_text(json.dumps(value), encoding="utf-8")

    def test_missing_config_preserves_official_identity(self):
        self.assertIsNone(apply_cloud_identity(self.root, self.config))
        self.assertEqual(self.header.read_text(), self.original)

    def test_valid_identity_replaces_both_macros(self):
        secret = "ab" * 16
        self.write_config(dict(pid=11785, secret=secret))
        self.assertEqual(apply_cloud_identity(self.root, self.config), 11785)
        source = self.header.read_text()
        self.assertIn('CONFIG_XJIANG_CLOUD_PID 11785\n', source)
        self.assertIn(f'CONFIG_XJIANG_CLOUD_SECERT "{secret}"', source)

    def test_invalid_identity_does_not_write_or_echo_secret(self):
        cases = [dict(pid=True, secret="a" * 32),
                 dict(pid=0, secret="a" * 32),
                 dict(pid=2**32, secret="a" * 32),
                 dict(pid=2, secret='private"\n#error injected'),
                 dict(pid=2, secret="too-short"), []]
        for value in cases:
            with self.subTest(value=value):
                self.write_config(value)
                with self.assertRaises(ValueError) as caught:
                    apply_cloud_identity(self.root, self.config)
                if isinstance(value, dict):
                    self.assertNotIn(value['secret'], str(caught.exception))
                self.assertEqual(self.header.read_text(), self.original)

    def test_changed_upstream_seam_fails_without_partial_write(self):
        self.write_config(dict(pid=2, secret="a" * 32))
        source = self.original.replace('SECERT', 'DIFFERENT')
        self.header.write_text(source, encoding="utf-8")
        with self.assertRaises(RuntimeError):
            apply_cloud_identity(self.root, self.config)
        self.assertEqual(self.header.read_text(), source)


if __name__ == "__main__":
    unittest.main()
