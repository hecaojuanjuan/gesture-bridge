"""Check local sample metadata and split isolation with a generated image."""

import base64
import hashlib
import io
import json
import sqlite3
import tempfile
import threading
import unittest
from contextlib import closing
from pathlib import Path

from PIL import Image

from webcam_hand_capture import MODEL_LABELS, connect_database, list_samples, sample_image, save_sample, validate


class CaptureTest(unittest.TestCase):
    def test_save_and_reject_wrong_split(self):
        image = io.BytesIO()
        Image.new("RGB", (320, 240), "green").save(image, format="JPEG")
        payload = {"label": "v_sign", "split": "train", "session": "session1",
                   "source": "BF3901-camera",
                   "box": [20, 30, 100, 180],
                   "image": "data:image/jpeg;base64," + base64.b64encode(image.getvalue()).decode()}
        for new_label in ("ok_sign", "six_sign", "thumbs_up",
                          "closed_fist", "one_finger"):
            self.assertEqual(validate(dict(payload, label=new_label))[0], new_label)
            with self.assertRaisesRegex(ValueError, "必须有手框"):
                validate(dict(payload, label=new_label, box=None))
        self.assertEqual(MODEL_LABELS["dislike"], "thumbs_up")
        self.assertEqual(MODEL_LABELS["two_up"], "v_sign")
        self.assertEqual(MODEL_LABELS["middle_finger"], "one_finger")
        with self.assertRaisesRegex(ValueError, "标签或数据集无效"):
            validate(dict(payload, label="middle_finger"))
        self.assertNotIn("three", MODEL_LABELS)
        self.assertNotIn("four", MODEL_LABELS)
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".local") as temporary:
            output = Path(temporary)
            lock = threading.Lock()
            result = save_sample(output, payload, lock)
            self.assertEqual(result["saved"], 1)
            self.assertTrue((output / result["path"]).exists())
            with closing(sqlite3.connect(output / "samples.sqlite3")) as database:
                saved = database.execute(
                    "SELECT label,source,box_json,jpeg FROM samples WHERE id=?", (result["id"],)).fetchone()
            self.assertEqual(saved[:3], ("v_sign", "BF3901-camera", "[20, 30, 100, 180]"))
            self.assertEqual(saved[3], image.getvalue())
            listed = list_samples(output)
            self.assertEqual((listed["total"], listed["samples"][0]["id"], listed["samples"][0]["box"]),
                             (1, result["id"], payload["box"]))
            self.assertEqual(sample_image(output, result["id"]), image.getvalue())
            manifest = json.loads((output / "manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["samples"][0]["source"], "BF3901-camera")
            with self.assertRaisesRegex(ValueError, "同一会话"):
                save_sample(output, dict(payload, split="val"), lock)
            with self.assertRaisesRegex(ValueError, "已经保存"):
                save_sample(output, payload, lock)
            with self.assertRaisesRegex(ValueError, "必须有手框"):
                save_sample(output, dict(payload, box=None), lock)
            with self.assertRaisesRegex(ValueError, "摄像头来源无效"):
                save_sample(output, dict(payload, source="unknown"), lock)

    def test_existing_manifest_is_migrated(self):
        image = io.BytesIO()
        Image.new("RGB", (320, 240), "blue").save(image, format="JPEG")
        with tempfile.TemporaryDirectory(dir=Path(__file__).resolve().parents[1] / ".local") as temporary:
            output = Path(temporary)
            (output / "images").mkdir()
            (output / "images/old.jpg").write_bytes(image.getvalue())
            digest = hashlib.sha256(image.getvalue()).hexdigest()
            (output / "manifest.json").write_text(json.dumps({"samples": [{
                "path": "images/old.jpg", "label": "open_palm", "split": "train",
                "session": "old", "source": "pc-webcam", "box": [1, 2, 30, 40],
                "width": 320, "height": 240, "sha256": digest}]}), encoding="utf-8")
            with closing(connect_database(output)) as database:
                migrated = database.execute("SELECT jpeg,box_json FROM samples WHERE sha256=?",
                                            (digest,)).fetchone()
            self.assertEqual(migrated, (image.getvalue(), "[1, 2, 30, 40]"))


if __name__ == "__main__":
    unittest.main()
