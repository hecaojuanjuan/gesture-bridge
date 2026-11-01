"""Fine-tune the HaGRIDv2 detector on exported local hand photos."""

import argparse
import os
from pathlib import Path


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--weights", type=Path, required=True)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--epochs", type=int, default=12)
    parser.add_argument("--no-val", action="store_true",
                        help="Train all images for the requested epochs without a held-out validation set")
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()
    args.project.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("YOLO_CONFIG_DIR", str(args.project.resolve()))
    import torch
    from ultralytics import YOLO

    torch.set_num_threads(4)
    YOLO(str(args.weights.resolve())).train(
        data=str(args.data.resolve()), project=str(args.project.resolve()), name="pilot",
        epochs=args.epochs, imgsz=320, batch=8, device=args.device, workers=0,
        freeze=10, optimizer="AdamW", lr0=0.0005, lrf=0.1,
        patience=args.epochs + 1 if args.no_val else 5, val=not args.no_val,
        mosaic=0.0, mixup=0.0, degrees=30.0, translate=0.1, scale=0.2,
        hsv_s=0.3, hsv_v=0.4, fliplr=0.5, seed=11930, amp=False,
        plots=False, save=True,
    )
