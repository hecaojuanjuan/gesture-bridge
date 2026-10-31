"""Train/export a small board-side palm/fist/other candidate from labeled sessions.

Example manifest (paths relative to the manifest; box is optional):
{"samples":[{"path":"images/001.png","label":"open_palm","session":"train-a",
             "split":"train","box":[10,20,110,120]}]}
Use separately captured train/val/test sessions. A missing test split is reported,
never silently created by splitting adjacent frames. This tool neither captures
images nor claims that a trained candidate has passed real-device acceptance.
"""
import argparse
import hashlib
import json
import math
import random
import struct
from pathlib import Path

import torch
from PIL import Image
from torch import nn

LABELS = ("open_palm", "closed_fist", "other")
SIZE = 64
WEIGHTS = 54011
PREPROCESS = {
    "version": 1, "input": "RGB888", "box": "integer xyxy, right/bottom exclusive",
    "padding": "floor(box extent / 10) per side, clipped to image",
    "resize": "stretch, source=floor((2*destination+1)*extent/128)",
    "gray": "(77*R+150*G+29*B+128)>>8", "normalize": "gray/255",
    "shape": [1, 64, 64],
}


def preprocess_rgb888(image, box=None):
    """Return 4096 uint8 values using the exact firmware integer operations."""
    image = image.convert("RGB")
    width, height = image.size
    box = [0, 0, width, height] if box is None else box
    if (not isinstance(box, (list, tuple)) or len(box) != 4 or
            any(type(v) is not int for v in box)):
        raise ValueError("box must contain four integer pixel coordinates")
    x1, y1, x2, y2 = box
    if not (0 < width <= 4096 and 0 < height <= 4096 and
            0 <= x1 < x2 <= width and 0 <= y1 < y2 <= height):
        raise ValueError("invalid image size or box")
    pad_x, pad_y = (x2-x1)//10, (y2-y1)//10
    x1, y1, x2, y2 = max(0, x1-pad_x), max(0, y1-pad_y), min(width, x2+pad_x), min(height, y2+pad_y)
    pixels = image.load()
    output = bytearray(SIZE*SIZE)
    for y in range(SIZE):
        sy = y1 + (2*y+1)*(y2-y1)//(2*SIZE)
        for x in range(SIZE):
            sx = x1 + (2*x+1)*(x2-x1)//(2*SIZE)
            r, g, b = pixels[sx, sy]
            output[y*SIZE+x] = (77*r+150*g+29*b+128) >> 8
    return bytes(output)


class HandClassifier(nn.Module):
    def __init__(self):
        super().__init__()
        self.conv1 = nn.Conv2d(1, 8, 3, stride=2, padding=1)
        self.conv2 = nn.Conv2d(8, 16, 3, stride=2, padding=1)
        self.conv3 = nn.Conv2d(16, 24, 3, stride=2, padding=1)
        self.fc1 = nn.Linear(24*8*8, 32)
        self.fc2 = nn.Linear(32, 3)

    def forward(self, x):
        x = torch.relu(self.conv1(x))
        x = torch.relu(self.conv2(x))
        x = torch.relu(self.conv3(x))
        x = torch.relu(self.fc1(x.flatten(1)))
        return self.fc2(x)


def load_manifest(path):
    path = Path(path)
    data = json.loads(path.read_text(encoding="utf-8"))
    rows = data.get("samples") if isinstance(data, dict) else None
    if not isinstance(rows, list) or not rows:
        raise ValueError("manifest needs a nonempty samples list")
    session_splits, image_splits, samples = {}, {}, []
    counts = {split: {label: 0 for label in LABELS} for split in ("train", "val", "test")}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("each sample must be an object")
        label, split, session = row.get("label"), row.get("split"), row.get("session")
        if label not in LABELS or split not in counts or not isinstance(session, str) or not session.strip():
            raise ValueError("sample needs a known label/split and a nonempty session")
        if session in session_splits and session_splits[session] != split:
            raise ValueError(f"session {session!r} crosses splits; capture an independent session")
        session_splits[session] = split
        if not isinstance(row.get("path"), str) or not row["path"]:
            raise ValueError("sample path must be a nonempty string")
        source = (path.parent / row["path"]).resolve()
        raw = source.read_bytes()
        digest = hashlib.sha256(raw).hexdigest()
        if digest in image_splits:
            raise ValueError("duplicate image bytes in manifest; do not count copies as independent samples")
        image_splits[digest] = split
        with Image.open(source) as image:
            pixels = preprocess_rgb888(image, row.get("box"))
        # Avoid torch's NumPy bridge: the installed Torch and NumPy may have
        # different ABI versions. Explicit lists also preserve byte semantics.
        tensor = torch.tensor(list(pixels), dtype=torch.float32).reshape(1, SIZE, SIZE) / 255.0
        samples.append({"tensor": tensor, "target": LABELS.index(label), "label": label,
                        "split": split, "session": session, "sha256": digest})
        counts[split][label] += 1
    for split in ("train", "val"):
        if any(count == 0 for count in counts[split].values()):
            raise ValueError(f"{split} needs all three labels, captured in independent sessions")
    if sum(counts["test"].values()) and any(count == 0 for count in counts["test"].values()):
        raise ValueError("a supplied test split needs all three labels")
    return samples, counts, session_splits


def augmentation(batch, generator):
    """Training only: mild contrast/brightness, horizontal flip and ±4px shift."""
    output = batch.clone()
    for i in range(len(output)):
        if generator.random() < 0.5:
            output[i] = output[i].flip(-1)
        dx, dy = generator.randint(-4, 4), generator.randint(-4, 4)
        source = output[i].clone()
        output[i].zero_()
        sx, sy, tx, ty = max(0, -dx), max(0, -dy), max(0, dx), max(0, dy)
        w, h = SIZE-abs(dx), SIZE-abs(dy)
        output[i, :, ty:ty+h, tx:tx+w] = source[:, sy:sy+h, sx:sx+w]
        contrast, brightness = generator.uniform(.85, 1.15), generator.uniform(-.08, .08)
        output[i] = ((output[i]-.5)*contrast+.5+brightness).clamp(0, 1)
    return output


def evaluate(model, samples, split):
    selected = [s for s in samples if s["split"] == split]
    if not selected:
        return None
    confusion = [[0]*3 for _ in range(3)]
    total_loss = 0.0
    model.eval()
    with torch.no_grad():
        for start in range(0, len(selected), 32):
            part = selected[start:start+32]
            inputs = torch.stack([s["tensor"] for s in part])
            targets = torch.tensor([s["target"] for s in part], dtype=torch.long)
            logits = model(inputs)
            total_loss += nn.functional.cross_entropy(logits, targets, reduction="sum").item()
            for actual, predicted in zip(targets.tolist(), logits.argmax(1).tolist()):
                confusion[actual][predicted] += 1
    return {"samples": len(selected), "loss": total_loss/len(selected),
            "accuracy": sum(confusion[i][i] for i in range(3))/len(selected),
            "confusion_rows_actual_columns_predicted": confusion,
            "recall": {LABELS[i]: confusion[i][i]/sum(confusion[i]) for i in range(3)}}


def flattened_weights(model):
    values = []
    for parameter in model.parameters():
        values.extend(parameter.detach().cpu().flatten().tolist())
    if len(values) != WEIGHTS or not all(math.isfinite(v) for v in values):
        raise ValueError("invalid model shape or non-finite weights")
    return values


def export_model(model, directory, metadata):
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    values = flattened_weights(model)
    binary = struct.pack("<" + "f"*len(values), *values)
    digest = hashlib.sha256(binary).hexdigest()
    (directory/"hand_classifier.f32le").write_bytes(binary)
    # Hex floats preserve the exact float32 weights, including tiny exponents.
    lines = ["/* Generated candidate. See model.json; real-device acceptance is separate. */",
             "#ifndef HV_GENERATED_HAND_WEIGHTS_H", "#define HV_GENERATED_HAND_WEIGHTS_H",
             '#include "hv_hand_classifier.h"',
             f'#define HV_HAND_MODEL_SHA256 "{digest}"',
             "static const float hv_hand_weights[HV_HAND_CLASSIFIER_WEIGHTS] = {"]
    for start in range(0, len(values), 6):
        lines.append("  " + ", ".join(float(v).hex()+"f" for v in values[start:start+6]) + ",")
    lines += ["};", "static const hv_hand_classifier_model_t hv_hand_model = {",
              "  hv_hand_weights, HV_HAND_CLASSIFIER_WEIGHTS, HV_HAND_CLASSIFIER_VERSION", "};", "#endif", ""]
    (directory/"hv_hand_weights.h").write_text("\n".join(lines), encoding="utf-8")
    result = dict(metadata, format_version=1, architecture="gray64_conv8_16_24_fc32_3",
                  labels=list(LABELS), preprocessing=PREPROCESS, weights=WEIGHTS,
                  weight_bytes=len(binary), sha256=digest,
                  status="candidate_not_hardware_validated", hardware_accuracy_verified=False)
    (directory/"model.json").write_text(json.dumps(result, ensure_ascii=False, indent=2)+"\n", encoding="utf-8")
    return result


def train(manifest, output, epochs=40, batch_size=24, seed=11785, learning_rate=0.001):
    if epochs < 1 or batch_size < 1 or not 0 < learning_rate < 1:
        raise ValueError("invalid training settings")
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    generator = random.Random(seed)
    samples, counts, sessions = load_manifest(manifest)
    model = HandClassifier()
    optimizer = torch.optim.Adam(model.parameters(), lr=learning_rate)
    selected = [s for s in samples if s["split"] == "train"]
    class_weights = torch.tensor([len(selected)/(3*counts["train"][label]) for label in LABELS])
    history, best_loss, best_state, best_epoch = [], float("inf"), None, 0
    for epoch in range(1, epochs+1):
        model.train()
        order = list(range(len(selected)))
        generator.shuffle(order)
        for start in range(0, len(order), batch_size):
            batch = [selected[i] for i in order[start:start+batch_size]]
            inputs = augmentation(torch.stack([s["tensor"] for s in batch]), generator)
            targets = torch.tensor([s["target"] for s in batch], dtype=torch.long)
            optimizer.zero_grad()
            loss = nn.functional.cross_entropy(model(inputs), targets, weight=class_weights)
            if not torch.isfinite(loss):
                raise ValueError("training produced a non-finite loss")
            loss.backward()
            optimizer.step()
        validation = evaluate(model, samples, "val")
        history.append({"epoch": epoch, "validation": validation})
        print(json.dumps(history[-1]), flush=True)
        if validation["loss"] < best_loss:
            best_loss, best_epoch = validation["loss"], epoch
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
    model.load_state_dict(best_state)
    result = export_model(model, output, {
        "manifest_sha256": hashlib.sha256(Path(manifest).read_bytes()).hexdigest(),
        "sample_counts": counts, "sessions": sessions, "seed": seed,
        "epochs": epochs, "selected_epoch": best_epoch, "learning_rate": learning_rate,
        "selection": "lowest independent validation-session cross-entropy",
        "validation": evaluate(model, samples, "val"), "test": evaluate(model, samples, "test"),
        "history": history, "torch_version": torch.__version__,
        "note": "Validation selects the candidate. Missing independent test sessions are not a pass."
    })
    torch.save(model.state_dict(), Path(output)/"checkpoint.pt")
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=40)
    parser.add_argument("--batch-size", type=int, default=24)
    parser.add_argument("--seed", type=int, default=11785)
    parser.add_argument("--learning-rate", type=float, default=.001)
    args = parser.parse_args()
    result = train(args.manifest, args.output, args.epochs, args.batch_size, args.seed, args.learning_rate)
    print(json.dumps({k: result[k] for k in ("status", "sha256", "validation", "test",
                                            "hardware_accuracy_verified")}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
