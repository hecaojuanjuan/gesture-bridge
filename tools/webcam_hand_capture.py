"""Capture locally labelled 320x240 webcam or XJWB03 frames.

Run: python tools/webcam_hand_capture.py
Open: http://127.0.0.1:8766/
Samples stay in .local/hand-dataset-webcam. Board frames are proxied from the
local camera preview at 127.0.0.1:8765, without exposing them to another host.
"""

import argparse
import base64
import datetime
import hashlib
import io
import json
import os
import re
import sqlite3
import threading
import uuid
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.error import URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import urlopen

from camera_preview import jpeg_dimensions


PAGE = Path(__file__).with_suffix(".html").read_text(encoding="utf-8")
TARGET_LABELS = {"open_palm", "v_sign", "ok_sign", "six_sign", "thumbs_up",
                 "closed_fist", "one_finger"}
MODEL_LABELS = {
    "palm": "open_palm", "peace": "v_sign", "peace_inverted": "v_sign",
    "two_up": "v_sign", "two_up_inverted": "v_sign", "ok": "ok_sign",
    "call": "six_sign", "middle_finger": "one_finger",
    "like": "thumbs_up", "dislike": "thumbs_up", "fist": "closed_fist",
    "one": "one_finger", "point": "one_finger",
}


def validate(payload):
    if not isinstance(payload, dict):
        raise ValueError("请求格式无效")
    label, split, session = (payload.get(key) for key in ("label", "split", "session"))
    source = payload.get("source", "pc-webcam")
    if label not in TARGET_LABELS | {"other", "no_hand"} or split not in {"train", "val", "test"}:
        raise ValueError("标签或数据集无效")
    if source not in {"pc-webcam", "BF3901-camera"}:
        raise ValueError("摄像头来源无效")
    if not isinstance(session, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,48}", session):
        raise ValueError("会话名称仅能使用字母、数字、下划线和连字符")
    box = payload.get("box")
    if label in TARGET_LABELS and box is None:
        raise ValueError("目标手势必须有手框")
    if label == "no_hand" and box is not None:
        raise ValueError("无手画面不能有手框")
    if box is not None and (not isinstance(box, list) or len(box) != 4 or
                            any(type(v) is not int for v in box) or
                            not (0 <= box[0] < box[2] <= 320 and 0 <= box[1] < box[3] <= 240)):
        raise ValueError("手框坐标无效")
    image = payload.get("image")
    if not isinstance(image, str) or not image.startswith("data:image/jpeg;base64,"):
        raise ValueError("需要 JPEG 照片")
    try:
        raw = base64.b64decode(image.split(",", 1)[1], validate=True)
    except (ValueError, base64.binascii.Error) as exc:
        raise ValueError("照片编码无效") from exc
    if not 1000 <= len(raw) <= 500000 or not raw.startswith(b"\xff\xd8") or not raw.endswith(b"\xff\xd9"):
        raise ValueError("照片内容无效")
    if jpeg_dimensions(raw) != (320, 240):
        raise ValueError("照片必须是 320 × 240 JPEG")
    return label, split, session, source, box, raw


def connect_database(output):
    db = sqlite3.connect(output / "samples.sqlite3")
    db.execute("""CREATE TABLE IF NOT EXISTS samples (
        id INTEGER PRIMARY KEY, path TEXT NOT NULL UNIQUE, label TEXT NOT NULL,
        split TEXT NOT NULL, session TEXT NOT NULL, source TEXT NOT NULL,
        box_json TEXT, width INTEGER NOT NULL, height INTEGER NOT NULL,
        sha256 TEXT NOT NULL UNIQUE, jpeg BLOB NOT NULL, saved_utc TEXT NOT NULL)""")
    manifest_path = output / "manifest.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        for row in manifest["samples"]:
            if db.execute("SELECT 1 FROM samples WHERE sha256=?", (row["sha256"],)).fetchone():
                continue
            raw = (output / row["path"]).read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise ValueError("已有样本的 JPEG 与清单校验值不符")
            db.execute(
                """INSERT INTO samples
                (path,label,split,session,source,box_json,width,height,sha256,jpeg,saved_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (row["path"], row["label"], row["split"], row["session"],
                 row.get("source", "pc-webcam"), json.dumps(row.get("box")),
                 row.get("width", 320), row.get("height", 240), row["sha256"], raw,
                 row.get("host_utc", datetime.datetime.fromtimestamp(
                     (output / row["path"]).stat().st_mtime,
                     datetime.timezone.utc).isoformat())))
    db.commit()
    return db


def sync_exports(db, output):
    manifest_path = output / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"samples": []}
    known = {row["sha256"] for row in manifest["samples"]}
    changed = False
    for row in db.execute(
            "SELECT path,label,split,session,source,box_json,width,height,sha256,jpeg FROM samples ORDER BY id"):
        path, label, split, session, source, box_json, width, height, digest, jpeg = row
        target = output / path
        if not target.exists():
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(jpeg)
        if digest not in known:
            manifest["samples"].append({
                "path": path, "label": label, "split": split, "session": session,
                "source": source, "box": json.loads(box_json),
                "width": width, "height": height, "sha256": digest})
            known.add(digest)
            changed = True
    if changed:
        temporary = manifest_path.with_suffix(".json.tmp")
        temporary.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        temporary.replace(manifest_path)
    return len(manifest["samples"])


def save_sample(output, payload, lock):
    label, split, session, source, box, raw = validate(payload)
    with lock:
        output.mkdir(parents=True, exist_ok=True)
        with closing(connect_database(output)) as db:
            if db.execute("SELECT 1 FROM samples WHERE session=? AND split<>? LIMIT 1",
                          (session, split)).fetchone():
                raise ValueError("同一会话不能跨训练、验证和测试集")
            digest = hashlib.sha256(raw).hexdigest()
            if db.execute("SELECT 1 FROM samples WHERE sha256=?", (digest,)).fetchone():
                raise ValueError("这张照片已经保存过")
            relative = (Path("images") / f"{session}-{uuid.uuid4().hex[:12]}.jpg").as_posix()
            cursor = db.execute(
                """INSERT INTO samples
                (path,label,split,session,source,box_json,width,height,sha256,jpeg,saved_utc)
                VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (relative, label, split, session, source, json.dumps(box), 320, 240,
                 digest, raw, datetime.datetime.now(datetime.timezone.utc).isoformat()))
            db.commit()
            saved = sync_exports(db, output)
            return {"id": cursor.lastrowid, "saved": saved, "path": relative}


def list_samples(output, before=None):
    with closing(sqlite3.connect(output / "samples.sqlite3")) as db:
        total = db.execute("SELECT COUNT(*) FROM samples").fetchone()[0]
        rows = db.execute(
            "SELECT id,label,split,session,source,box_json,saved_utc FROM samples "
            "WHERE (? IS NULL OR id < ?) ORDER BY id DESC LIMIT 31",
            (before, before)).fetchall()
    samples = [dict(id=row[0], label=row[1], split=row[2], session=row[3],
                    source=row[4], box=json.loads(row[5]), saved_utc=row[6])
               for row in rows[:30]]
    return {"samples": samples, "total": total,
            "next_before": samples[-1]["id"] if len(rows) > 30 else None}


def sample_image(output, sample_id):
    with closing(sqlite3.connect(output / "samples.sqlite3")) as db:
        row = db.execute("SELECT jpeg FROM samples WHERE id=?", (sample_id,)).fetchone()
    return row[0] if row else None


def recognize(image_data, model_path, cache, lock, output):
    if model_path is None:
        raise ValueError("未配置识别模型")
    raw = validate({"label": "no_hand", "split": "train", "session": "predict",
                    "source": "pc-webcam", "box": None, "image": image_data})[-1]
    with lock:
        if cache["model"] is None:
            config_dir = output / ".yolo"
            config_dir.mkdir(parents=True, exist_ok=True)
            os.environ.setdefault("YOLO_CONFIG_DIR", str(config_dir.resolve()))
            import torch
            from ultralytics import YOLO

            torch.set_num_threads(4)
            cache["model"] = YOLO(str(model_path.resolve(strict=True)))
        from PIL import Image

        image = Image.open(io.BytesIO(raw)).convert("RGB")
        result = cache["model"].predict(image, imgsz=320, conf=0.10,
                                        device="cpu", verbose=False)[0]
        boxes = sorted(zip(result.boxes.cls.tolist(), result.boxes.conf.tolist(),
                           result.boxes.xyxy.tolist()), key=lambda row: row[1], reverse=True)
        if boxes:
            class_id, score, box = boxes[0]
            label = MODEL_LABELS.get(cache["model"].names[int(class_id)])
            if label:
                return {"label": label, "score": score, "box": box}
    return {"label": None, "score": None, "box": None}


def serve(port, output, model_path=None):
    lock = threading.Lock()
    inference_lock = threading.Lock()
    model_cache = {"model": None}
    output.mkdir(parents=True, exist_ok=True)
    with closing(connect_database(output)) as db:
        sync_exports(db, output)

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            request = urlsplit(self.path)
            path = request.path
            if path == "/":
                body, mime, code = PAGE.encode("utf-8"), "text/html; charset=utf-8", 200
            elif path == "/samples":
                cursor = parse_qs(request.query).get("before", [None])[0]
                if cursor is not None and (not cursor.isdecimal() or int(cursor) < 1):
                    self.send_error(400, "Invalid sample cursor")
                    return
                body = json.dumps(list_samples(output, int(cursor) if cursor else None),
                                  ensure_ascii=False).encode("utf-8")
                mime, code = "application/json; charset=utf-8", 200
            elif match := re.fullmatch(r"/samples/(\d+)\.jpg", path):
                body = sample_image(output, int(match.group(1)))
                if body is None:
                    self.send_error(404)
                    return
                mime, code = "image/jpeg", 200
            elif path in {"/board/status", "/board/frame.jpg"}:
                try:
                    upstream_path = "/status" if path == "/board/status" else "/frame.jpg"
                    with urlopen("http://127.0.0.1:8765" + upstream_path, timeout=5) as upstream:
                        body = upstream.read(500001)
                    if len(body) > 500000:
                        raise ValueError("开发板画面过大")
                    mime = "application/json; charset=utf-8" if path == "/board/status" else "image/jpeg"
                    code = 200
                except (URLError, TimeoutError, ValueError) as exc:
                    body = json.dumps({"error": str(exc)}, ensure_ascii=False).encode("utf-8")
                    mime, code = "application/json; charset=utf-8", 503
            else:
                self.send_error(404)
                return
            self.send_response(code)
            self.send_header("Content-Type", mime)
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self):
            if self.path not in {"/sample", "/predict"}:
                self.send_error(404)
                return
            try:
                size = int(self.headers.get("Content-Length", "0"))
                if not 0 < size <= 800000:
                    raise ValueError("照片过大或为空")
                payload = json.loads(self.rfile.read(size))
                if not isinstance(payload, dict):
                    raise ValueError("请求格式无效")
                if self.path == "/sample":
                    result = save_sample(output, payload, lock)
                else:
                    result = recognize(payload.get("image"), model_path, model_cache,
                                       inference_lock, output)
                code = 200
            except (ValueError, OSError, json.JSONDecodeError) as exc:
                result, code = {"error": str(exc)}, 400
            body = json.dumps(result, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    print(f"Webcam hand capture: http://127.0.0.1:{port}/", flush=True)
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8766)
    parser.add_argument("--output", type=Path, default=Path(".local/hand-dataset-webcam"))
    parser.add_argument("--model", type=Path)
    args = parser.parse_args()
    serve(args.port, args.output, args.model)
