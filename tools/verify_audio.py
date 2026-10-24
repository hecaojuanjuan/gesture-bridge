"""Verify the fixed dictionary and cached PCM identities before a build."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "headvoice/audio"
EXPECTED = {"AA": "我想喝水。", "AB": "我想休息一下。",
            "BA": "请过来协助我。", "BB": "我想自己来。"}
manifest = json.loads((AUDIO / "manifest.json").read_text(encoding="utf-8"))
if manifest["format"] != "PCM S16LE 16000 Hz mono":
    raise RuntimeError("Unsupported cached audio format")
assets = manifest["assets"]
actual = {row["code"]: row["text"] for row in assets}
if len(assets) != 4 or actual != EXPECTED:
    raise RuntimeError("The cached dictionary does not match phase one")
for row in assets:
    data = (AUDIO / f"{row['code']}.pcm").read_bytes()
    if (len(data) != row["bytes"] or len(data) % 2 or
            hashlib.sha256(data).hexdigest() != row["sha256"]):
        raise RuntimeError(f"PCM integrity check failed: {row['code']}")
print("PASS four cached PCM identities, format and exact dictionary text")
