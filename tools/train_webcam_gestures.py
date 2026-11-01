"""Train a six-gesture candidate from a consistent SQLite capture snapshot."""

import argparse
import collections
import hashlib
import io
import json
import random
import sqlite3
from contextlib import closing
from pathlib import Path

import torch
from PIL import Image
from torch import nn

from train_hand_classifier import HandClassifier, augmentation, preprocess_rgb888


LABELS = ("open_palm", "v_sign", "ok_sign", "six_sign", "middle_finger", "thumbs_up")


def evaluate(model, samples, split):
    chosen = [sample for sample in samples if sample["split"] == split]
    confusion = [[0] * len(LABELS) for _ in LABELS]
    source_counts = collections.defaultdict(lambda: [0, 0])
    loss = 0.0
    model.eval()
    with torch.no_grad():
        for start in range(0, len(chosen), 32):
            batch = chosen[start:start + 32]
            inputs = torch.stack([sample["tensor"] for sample in batch])
            targets = torch.tensor([sample["target"] for sample in batch])
            scores = model(inputs)
            loss += nn.functional.cross_entropy(scores, targets, reduction="sum").item()
            for sample, predicted in zip(batch, scores.argmax(1).tolist()):
                actual = sample["target"]
                confusion[actual][predicted] += 1
                source_counts[sample["source"]][1] += 1
                source_counts[sample["source"]][0] += actual == predicted
    recall = {label: confusion[i][i] / sum(confusion[i]) if sum(confusion[i]) else None
              for i, label in enumerate(LABELS)}
    return {"samples": len(chosen), "loss": loss / len(chosen),
            "accuracy": sum(confusion[i][i] for i in range(len(LABELS))) / len(chosen),
            "macro_recall": sum(recall.values()) / len(LABELS),
            "recall": recall, "confusion_rows_actual_columns_predicted": confusion,
            "source_accuracy": {source: {"correct": counts[0], "samples": counts[1]}
                                for source, counts in source_counts.items()}}


def train(database, output, validation_sessions, epochs=40, seed=11930):
    if not validation_sessions or epochs < 1:
        raise ValueError("Need validation sessions and at least one epoch")
    output.mkdir(parents=True, exist_ok=False)
    snapshot = output / "samples.sqlite3"
    with closing(sqlite3.connect(database)) as source, closing(sqlite3.connect(snapshot)) as target:
        source.backup(target)
    with closing(sqlite3.connect(snapshot)) as db:
        rows = db.execute("SELECT id,label,session,source,box_json,jpeg FROM samples ORDER BY id").fetchall()
    torch.set_num_threads(2)
    torch.manual_seed(seed)
    generator = random.Random(seed)
    samples, excluded = [], collections.Counter()
    counts = {split: collections.Counter() for split in ("train", "val")}
    for sample_id, label, session, source, box_json, jpeg in rows:
        if label not in LABELS:
            excluded[label] += 1
            continue
        box = json.loads(box_json)
        if box is None:
            raise ValueError(f"Sample {sample_id} has no hand box")
        with Image.open(io.BytesIO(jpeg)) as image:
            if image.size != (320, 240):
                raise ValueError(f"Sample {sample_id} has the wrong image size")
            pixels = preprocess_rgb888(image, box)
        split = "val" if session in validation_sessions else "train"
        samples.append({"tensor": torch.tensor(list(pixels), dtype=torch.float32).reshape(1, 64, 64) / 255,
                        "target": LABELS.index(label), "split": split, "source": source})
        counts[split][label] += 1
    if any(counts[split][label] == 0 for split in counts for label in LABELS):
        raise ValueError(f"Every gesture needs train and validation samples: {counts}")
    selected = [sample for sample in samples if sample["split"] == "train"]
    weights = torch.tensor([len(selected) / (len(LABELS) * counts["train"][label])
                            for label in LABELS])
    model = HandClassifier()
    model.fc2 = nn.Linear(32, len(LABELS))
    optimizer = torch.optim.Adam(model.parameters(), lr=.001)
    best_loss, best_epoch, best_state, history = float("inf"), 0, None, []
    for epoch in range(1, epochs + 1):
        model.train()
        order = list(range(len(selected)))
        generator.shuffle(order)
        for start in range(0, len(order), 24):
            batch = [selected[i] for i in order[start:start + 24]]
            inputs = augmentation(torch.stack([sample["tensor"] for sample in batch]), generator)
            targets = torch.tensor([sample["target"] for sample in batch])
            optimizer.zero_grad()
            loss = nn.functional.cross_entropy(model(inputs), targets, weight=weights)
            loss.backward()
            optimizer.step()
        validation = evaluate(model, samples, "val")
        history.append({"epoch": epoch, "validation_loss": validation["loss"],
                        "validation_accuracy": validation["accuracy"]})
        if validation["loss"] < best_loss:
            best_loss, best_epoch = validation["loss"], epoch
            best_state = {key: value.detach().clone() for key, value in model.state_dict().items()}
        print(json.dumps(history[-1]), flush=True)
    model.load_state_dict(best_state)
    torch.save(model.state_dict(), output / "checkpoint.pt")
    report = {"status": "exploratory_not_deployable", "labels": list(LABELS),
              "architecture": "gray64_conv8_16_24_fc32_6", "input": "boxed_hand_RGB_to_gray64",
              "snapshot_sha256": hashlib.sha256(snapshot.read_bytes()).hexdigest(),
              "snapshot_samples": len(rows), "excluded": dict(excluded),
              "validation_sessions": sorted(validation_sessions),
              "counts": {split: dict(counts[split]) for split in counts},
              "seed": seed, "epochs": epochs, "selected_epoch": best_epoch,
              "train": evaluate(model, samples, "train"),
              "validation": evaluate(model, samples, "val"),
              "independent_test": None, "history": history,
              "note": "Validation sessions were carved from train-tagged captures; no independent test or board deployment."}
    (output / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("database", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--validation-session", action="append", required=True)
    parser.add_argument("--epochs", type=int, default=40)
    args = parser.parse_args()
    report = train(args.database, args.output, set(args.validation_session), args.epochs)
    print(json.dumps({key: report[key] for key in ("snapshot_samples", "selected_epoch", "train", "validation")},
                     ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
