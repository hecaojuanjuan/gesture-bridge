"""Verify actual C/PyTorch inference and dataset isolation, not gesture accuracy."""
import ctypes
import importlib.util
import json
import math
import random
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

import torch
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("train_hand_classifier", ROOT/"tools/train_hand_classifier.py")
trainer = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trainer)
FLOAT = ctypes.c_float
BYTE = ctypes.c_uint8
WORK_FLOATS = 4096+8192+4096+1536+32


class Model(ctypes.Structure):
    _fields_ = [("weights", ctypes.POINTER(FLOAT)), ("count", ctypes.c_size_t),
                ("version", ctypes.c_uint32)]


class ClassifierTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.directory = tempfile.TemporaryDirectory(prefix="hand-classifier-test-")
        cls.library_path = Path(cls.directory.name)/"classifier.so"
        subprocess.run([shutil.which("cc") or "clang", "-std=c11", "-O2", "-Wall", "-Wextra", "-Werror",
                        "-fPIC", "-shared", "-I", str(ROOT/"headvoice/core"),
                        str(ROOT/"headvoice/core/hv_hand_classifier.c"), "-o", str(cls.library_path), "-lm"], check=True)
        cls.library = ctypes.CDLL(str(cls.library_path))
        cls.library.hv_hand_classifier_preprocess_rgb888.argtypes = [ctypes.POINTER(BYTE), ctypes.c_size_t,
            ctypes.c_uint, ctypes.c_uint, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
            ctypes.POINTER(BYTE)]
        cls.library.hv_hand_classifier_preprocess_rgb888.restype = ctypes.c_int
        cls.library.hv_hand_classifier_predict.argtypes = [ctypes.POINTER(Model), ctypes.POINTER(BYTE),
            ctypes.POINTER(FLOAT), ctypes.c_size_t, ctypes.POINTER(FLOAT)]
        cls.library.hv_hand_classifier_predict.restype = ctypes.c_int
        torch.set_num_threads(2)

    @classmethod
    def tearDownClass(cls):
        cls.directory.cleanup()

    def preprocess(self, image, box):
        raw = image.tobytes()
        source = (BYTE*len(raw)).from_buffer_copy(raw)
        out = (BYTE*4096)()
        result = self.library.hv_hand_classifier_preprocess_rgb888(source, len(raw), *image.size, *box, out)
        return result, bytes(out)

    def test_pixel_preprocessing_matches_exactly_including_clipped_padding(self):
        rng = random.Random(37)
        for shape, box in (((320, 240), (70, 40, 190, 230)), ((13, 9), (0, 0, 13, 9)),
                           ((10, 12), (8, 10, 10, 12)), ((1, 1), (0, 0, 1, 1))):
            image = Image.frombytes("RGB", shape, bytes(rng.randrange(256) for _ in range(shape[0]*shape[1]*3)))
            status, got = self.preprocess(image, box)
            self.assertEqual(status, 0)
            self.assertEqual(got, trainer.preprocess_rgb888(image, list(box)))

    def test_crop_and_source_boundaries_are_rejected(self):
        image = Image.new("RGB", (8, 8), (255, 127, 0))
        for box in ((0, 0, 0, 8), (-1, 0, 7, 8), (0, 0, 9, 8), (0, 0, 8, 9)):
            self.assertEqual(self.preprocess(image, box)[0], 2)
        raw = (BYTE*192)()
        out = (BYTE*4096)()
        self.assertEqual(self.library.hv_hand_classifier_preprocess_rgb888(raw, 191, 8, 8, 0, 0, 8, 8, out), 2)
        with self.assertRaises(ValueError):
            trainer.preprocess_rgb888(image, [0.0, 0, 8, 8])

    def test_c_matches_torch_on_varied_synthetic_pixels(self):
        # Random weights test implementation equivalence only. They never leave
        # this test as a deployed or accuracy-validated gesture model.
        torch.manual_seed(871)
        network = trainer.HandClassifier().eval()
        values = trainer.flattened_weights(network)
        weights = (FLOAT*len(values))(*values)
        model = Model(weights, len(values), 1)
        workspace = (FLOAT*WORK_FLOATS)()
        rng = random.Random(871)
        for pixels in (bytes(4096), bytes([255])*4096,
                       bytes(rng.randrange(256) for _ in range(4096)),
                       bytes((i//64)*4 for i in range(4096))):
            gray = (BYTE*4096).from_buffer_copy(pixels)
            scores = (FLOAT*3)()
            self.assertEqual(self.library.hv_hand_classifier_predict(
                ctypes.byref(model), gray, workspace, WORK_FLOATS, scores), 0)
            with torch.no_grad():
                reference = network(torch.tensor(list(pixels), dtype=torch.float32).reshape(1, 1, 64, 64)/255).softmax(1)[0].tolist()
            for actual, expected in zip(scores, reference):
                self.assertAlmostEqual(actual, expected, delta=2e-6)
            self.assertAlmostEqual(sum(scores), 1.0, delta=2e-6)

    def test_missing_corrupt_model_and_small_workspace_never_produce_scores(self):
        gray, workspace, scores = (BYTE*4096)(), (FLOAT*WORK_FLOATS)(), (FLOAT*3)(1, 1, 1)
        predict = self.library.hv_hand_classifier_predict
        self.assertEqual(predict(None, gray, workspace, WORK_FLOATS, scores), 1)
        self.assertEqual(list(scores), [0, 0, 0])
        weights = (FLOAT*trainer.WEIGHTS)()
        wrong = Model(weights, trainer.WEIGHTS-1, 1)
        self.assertEqual(predict(ctypes.byref(wrong), gray, workspace, WORK_FLOATS, scores), 3)
        wrong = Model(weights, trainer.WEIGHTS, 2)
        self.assertEqual(predict(ctypes.byref(wrong), gray, workspace, WORK_FLOATS, scores), 3)
        model = Model(weights, trainer.WEIGHTS, 1)
        self.assertEqual(predict(ctypes.byref(model), gray, workspace, WORK_FLOATS-1, scores), 2)
        weights[trainer.WEIGHTS-1] = float("nan")
        self.assertEqual(predict(ctypes.byref(model), gray, workspace, WORK_FLOATS, scores), 3)
        self.assertEqual(list(scores), [0, 0, 0])

    @staticmethod
    def manifest_at(directory):
        rows = []
        for split_index, split in enumerate(("train", "val", "test")):
            for label_index, label in enumerate(trainer.LABELS):
                name = f"{split}-{label}.png"
                # Synthetic images are used only to exercise training/export.
                Image.new("RGB", (71, 67), (30+label_index*80, 30+split_index*60, 40+label_index)).save(directory/name)
                rows.append({"path": name, "label": label, "session": split+"-capture",
                             "split": split, "box": [3, 2, 65, 61]})
        manifest = directory/"manifest.json"
        manifest.write_text(json.dumps({"samples": rows}), encoding="utf-8")
        return manifest, rows

    def test_session_leakage_and_duplicate_frames_are_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest, rows = self.manifest_at(directory)
            samples, counts, sessions = trainer.load_manifest(manifest)
            self.assertEqual(len(samples), 9)
            self.assertEqual(len(sessions), 3)
            self.assertEqual(counts["val"], dict.fromkeys(trainer.LABELS, 1))
            rows[3]["session"] = rows[0]["session"]
            manifest.write_text(json.dumps({"samples": rows}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "crosses splits"):
                trainer.load_manifest(manifest)
            rows[3]["session"] = "val-capture"
            rows[3]["path"] = rows[0]["path"]
            manifest.write_text(json.dumps({"samples": rows}), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "duplicate image"):
                trainer.load_manifest(manifest)

    def test_train_export_and_generated_c_header(self):
        with tempfile.TemporaryDirectory() as temp:
            directory = Path(temp)
            manifest, _ = self.manifest_at(directory)
            output = directory/"export"
            result = trainer.train(manifest, output, epochs=1, batch_size=3)
            self.assertEqual(result["weights"], trainer.WEIGHTS)
            self.assertEqual(result["weight_bytes"], trainer.WEIGHTS*4)
            self.assertEqual(result["test"]["samples"], 3)
            self.assertFalse(result["hardware_accuracy_verified"])
            self.assertEqual(result["status"], "candidate_not_hardware_validated")
            harness = directory/"header.c"
            harness.write_text('#include "hv_hand_weights.h"\nint main(void) { return hv_hand_model.count != 54011; }\n', encoding="utf-8")
            binary = directory/"header-check"
            subprocess.run([shutil.which("cc") or "clang", "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", str(ROOT/"headvoice/core"), "-I", str(output), str(harness),
                            "-o", str(binary)], check=True)
            subprocess.run([str(binary)], check=True)

    def test_training_augmentation_does_not_mutate_validation_source(self):
        original = torch.full((2, 1, 64, 64), .5)
        augmented = trainer.augmentation(original, random.Random(23))
        self.assertTrue(torch.all(original == .5))
        self.assertFalse(torch.equal(original, augmented))
        self.assertTrue(torch.all(augmented >= 0) and torch.all(augmented <= 1))


if __name__ == "__main__":
    unittest.main()
