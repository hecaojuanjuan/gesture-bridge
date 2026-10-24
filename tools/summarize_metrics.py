"""Summarize board logs; keep software and audible latency separate."""
import argparse
import json
import statistics
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("log", type=Path)
args = parser.parse_args()
rows = [json.loads(line).get("device", {})
        for line in args.log.read_text(encoding="utf-8").splitlines() if line]


def summary(values):
    if not values:
        return None
    values = sorted(values)
    return dict(count=len(values), median=statistics.median(values),
                p95=values[max(0, (len(values) * 95 + 99) // 100 - 1)],
                maximum=max(values), minimum=min(values))


poses = [row for row in rows if row.get("event") == "pose"]
metrics = [row for row in rows if row.get("event") == "metrics"]
starts = [row for row in rows if row.get("event") == "audio_started_estimate"]
done = [row for row in rows if row.get("event") == "audio_done"]
print(json.dumps(dict(
    pose_inference_ms=summary([r["infer_ms"] for r in poses]),
    pose_age_ms=summary([r["age_ms"] for r in poses]),
    valid_pose_hz=summary([r["valid_hz"] for r in metrics]),
    internal_free_bytes=summary([r["internal_free"] for r in metrics]),
    internal_largest_bytes=summary([r["internal_largest"] for r in metrics]),
    psram_free_bytes=summary([r["psram_free"] for r in metrics]),
    confirm_to_software_start_ms=summary(
        [r["confirm_to_report_ms"] for r in starts]),
    audio_failures=sum(r["result"] != 0 for r in done),
    audio_completed=len(done), audible_latency_ms=None,
    note=("Audible latency requires an external recording "
          "of confirmation and speaker output")
), ensure_ascii=False, indent=2))
