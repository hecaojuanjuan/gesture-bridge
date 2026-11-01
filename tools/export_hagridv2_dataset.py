"""Export saved hand boxes to YOLO format without changing the source database."""

import argparse
import csv
import hashlib
import json
import os
import sqlite3
from pathlib import Path

import yaml


LABELS = {
    "open_palm": "palm",
    "v_sign": "peace",
    "ok_sign": "ok",
    "six_sign": "call",
    "middle_finger": "one",
    "thumbs_up": "like",
    "closed_fist": "fist",
    "one_finger": "one",
}
VALIDATION_SESSIONS = {"board_20261031T181358_k5v5", "webcam_20261031T180124_rnt1"}
TEST_SESSIONS = {"board_20261031T201135_efbg"}


def export(database, output, names, all_train=False):
    output.mkdir(parents=True, exist_ok=False)
    with sqlite3.connect(database) as db:
        samples = db.execute(
            "SELECT id,label,session,source,box_json,width,height,sha256,jpeg FROM samples ORDER BY id"
        ).fetchall()
    records, seen = [], {}
    for sample_id, label, session, source, box_json, width, height, digest, jpeg in samples:
        if label not in LABELS:
            continue
        if hashlib.sha256(jpeg).hexdigest() != digest:
            raise ValueError(f"JPEG checksum mismatch at sample {sample_id}")
        split = ("train" if all_train else
                 "test" if session in TEST_SESSIONS else
                 "val" if session in VALIDATION_SESSIONS else "train")
        if digest in seen and seen[digest] != split:
            raise ValueError(f"Duplicate image crosses splits: sample {sample_id}")
        seen[digest] = split
        box = json.loads(box_json)
        if not (isinstance(box, list) and len(box) == 4 and
                0 <= box[0] < box[2] <= width and 0 <= box[1] < box[3] <= height):
            raise ValueError(f"Invalid box at sample {sample_id}")
        image_dir = output / "images" / split
        label_dir = output / "labels" / split
        image_dir.mkdir(parents=True, exist_ok=True)
        label_dir.mkdir(parents=True, exist_ok=True)
        stem = f"sample_{sample_id:04d}"
        (image_dir / f"{stem}.jpg").write_bytes(jpeg)
        x1, y1, x2, y2 = box
        values = ((x1 + x2) / (2 * width), (y1 + y2) / (2 * height),
                  (x2 - x1) / width, (y2 - y1) / height)
        class_id = next(index for index, name in names.items() if name == LABELS[label])
        (label_dir / f"{stem}.txt").write_text(
            f"{class_id} " + " ".join(f"{value:.8f}" for value in values) + "\n", encoding="ascii"
        )
        records.append({"id": sample_id, "split": split, "session": session,
                        "source": source, "label": label, "hagrid_label": LABELS[label]})
    (output / "data.yaml").write_text(yaml.safe_dump({
        "path": output.resolve().as_posix(), "train": "images/train",
        "val": "images/train" if all_train else "images/val",
        **({} if all_train else {"test": "images/test"}),
        "names": names}, sort_keys=False), encoding="utf-8")
    with (output / "manifest.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=list(records[0]))
        writer.writeheader()
        writer.writerows(records)
    return {split: sum(row["split"] == split for row in records) for split in ("train", "val", "test")}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--all-train", action="store_true",
                        help="Use every labelled image for training; validation metrics will be in-sample")
    args = parser.parse_args()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(args.output.parent.resolve()))
    from ultralytics import YOLO

    model = YOLO(str(args.weights.resolve()))
    print(json.dumps(export(args.database, args.output, model.names, args.all_train)), flush=True)
