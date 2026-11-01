"""Run the official HaGRIDv2 YOLOv10n detector on saved hand photos."""

import argparse
import collections
import csv
import hashlib
import io
import json
import os
import sqlite3
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


EXPECTED = {
    "open_palm": {"palm"},
    "v_sign": {"peace", "peace_inverted", "two_up", "two_up_inverted"},
    "ok_sign": {"ok"},
    "six_sign": {"call"},
    "thumbs_up": {"like", "dislike"},
    "closed_fist": {"fist"},
    "one_finger": {"one", "point", "middle_finger"},
}


def iou(a, b):
    x1, y1 = max(a[0], b[0]), max(a[1], b[1])
    x2, y2 = min(a[2], b[2]), min(a[3], b[3])
    intersection = max(0, x2 - x1) * max(0, y2 - y1)
    area_a = (a[2] - a[0]) * (a[3] - a[1])
    area_b = (b[2] - b[0]) * (b[3] - b[1])
    return intersection / (area_a + area_b - intersection) if area_a + area_b > intersection else 0.0


def make_sheet(rows, source, output):
    chosen = []
    for label_index, label in enumerate(EXPECTED):
        group = [row for row in rows if row["source"] == source and row["label"] == label]
        if group:
            count = min(4, len(group))
            chosen.extend((label_index, i, group[round(i * (len(group) - 1) / (count - 1)) if count > 1 else 0])
                          for i in range(count))
    tile_w, tile_h = 320, 280
    sheet = Image.new("RGB", (4 * tile_w, len(EXPECTED) * tile_h), "#202020")
    draw = ImageDraw.Draw(sheet)
    font = ImageFont.load_default(size=15)
    for label_index, column, row in chosen:
        x, y = column * tile_w, label_index * tile_h
        with Image.open(io.BytesIO(row["jpeg"])) as original:
            image = original.convert("RGB")
        pen = ImageDraw.Draw(image)
        pen.rectangle(row["box"], outline="#00ff00", width=2)
        for number, prediction in enumerate(row["predictions"]):
            pen.rectangle(prediction["box"], outline="#ff3030", width=3 if number == 0 else 1)
        sheet.paste(image, (x, y + 40))
        top = row["predictions"][0] if row["predictions"] else None
        predicted = f"{top['label']} {top['score']:.2f}" if top else "NO DETECTION"
        color = "#8aff8a" if row["correct_iou30"] else "#ff9a9a"
        draw.text((x + 4, y + 2), f"#{row['id']} {row['label']}", fill="white", font=font)
        draw.text((x + 4, y + 20), f"pred: {predicted}", fill=color, font=font)
    sheet.save(output, quality=88)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--session", action="append")
    parser.add_argument("--imgsz", type=int, default=640)
    parser.add_argument("--conf", type=float, default=0.25)
    parser.add_argument("--max-id", type=int)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(args.output.resolve()))
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(4)
    with sqlite3.connect(args.database) as db:
        samples = db.execute(
            "SELECT id,path,label,session,source,box_json,jpeg FROM samples ORDER BY id"
        ).fetchall()
    samples = [row for row in samples if row[2] in EXPECTED]
    if args.max_id is not None:
        samples = [row for row in samples if row[0] <= args.max_id]
    if args.session:
        samples = [row for row in samples if row[3] in args.session]
    if args.limit:
        samples = samples[:args.limit]
    model = YOLO(str(args.weights.resolve()))
    rows = []
    for start in range(0, len(samples), 8):
        batch = samples[start:start + 8]
        images = [Image.open(io.BytesIO(row[6])).convert("RGB") for row in batch]
        results = model.predict(images, imgsz=args.imgsz, conf=args.conf, device="cpu", verbose=False)
        for sample, result in zip(batch, results):
            sample_id, path, label, session, source, box_json, jpeg = sample
            box = json.loads(box_json)
            predictions = sorted(({
                "label": model.names[int(cls)], "score": float(score),
                "box": [float(v) for v in xyxy],
            } for cls, score, xyxy in zip(result.boxes.cls.tolist(), result.boxes.conf.tolist(),
                                           result.boxes.xyxy.tolist())),
                key=lambda item: item["score"], reverse=True)
            top = predictions[0] if predictions else None
            overlap = iou(box, top["box"]) if top else 0.0
            rows.append({
                "id": sample_id, "path": path, "label": label, "session": session,
                "source": source, "box": box, "jpeg": jpeg, "predictions": predictions,
                "top_label": top["label"] if top else None,
                "top_score": top["score"] if top else None,
                "top_iou": overlap,
                "correct_class": bool(top and top["label"] in EXPECTED[label]),
                "localized_iou30": bool(top and overlap >= 0.3),
                "correct_iou30": bool(top and overlap >= 0.3 and top["label"] in EXPECTED[label]),
            })
        print(f"processed {len(rows)}/{len(samples)}", flush=True)

    def tally(group):
        count = len(group)
        return {"images": count,
                "detected": sum(bool(row["predictions"]) for row in group),
                "correct_class": sum(row["correct_class"] for row in group),
                "localized_iou30": sum(row["localized_iou30"] for row in group),
                "correct_iou30": sum(row["correct_iou30"] for row in group)}

    report = {
        "weights_sha256": hashlib.sha256(args.weights.read_bytes()).hexdigest(),
        "threshold": {"confidence": args.conf, "iou_for_correct": 0.3, "imgsz": args.imgsz},
        "label_mapping": {key: sorted(value) for key, value in EXPECTED.items()},
        "overall": tally(rows),
        "by_source": {source: tally([r for r in rows if r["source"] == source])
                      for source in sorted({r["source"] for r in rows})},
        "by_source_and_label": {
            source: {label: tally([r for r in rows if r["source"] == source and r["label"] == label])
                     for label in EXPECTED}
            for source in sorted({r["source"] for r in rows})},
        "note": "Photos were previously captured and labeled; this is a retrospective test, not a new-scene or live-board test.",
    }
    (args.output / "report.json").write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    with (args.output / "predictions.csv").open("w", newline="", encoding="utf-8-sig") as file:
        writer = csv.DictWriter(file, fieldnames=["id", "path", "source", "session", "label",
                                                  "top_label", "top_score", "top_iou",
                                                  "correct_class", "localized_iou30", "correct_iou30"])
        writer.writeheader()
        writer.writerows({key: row[key] for key in writer.fieldnames} for row in rows)
    for source in report["by_source"]:
        make_sheet(rows, source, args.output / ("board.jpg" if source == "BF3901-camera" else "webcam.jpg"))
    print(json.dumps(report["by_source_and_label"], ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
