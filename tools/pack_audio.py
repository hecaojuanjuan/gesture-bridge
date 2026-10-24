"""Validate synthesized WAVs and cache PCM with provenance."""
import hashlib
import json
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
AUDIO = ROOT / "headvoice/audio"
PHRASES = dict(zip(("AA", "AB", "BA", "BB"),
                   ("我想喝水。", "我想休息一下。", "请过来协助我。", "我想自己来。")))
assets = []
for code, text in PHRASES.items():
    with wave.open(str(AUDIO / f"{code}.wav"), "rb") as source:
        geometry = (source.getnchannels(), source.getsampwidth(),
                    source.getframerate(), source.getcomptype())
        if geometry != (1, 2, 16000, "NONE"):
            raise RuntimeError(f"Unsupported WAV format: {code}: {geometry}")
        pcm = source.readframes(source.getnframes())
    if not 3200 <= len(pcm) <= 320000 or len(pcm) % 2:
        raise RuntimeError(f"Invalid audio size: {code}")
    (AUDIO / f"{code}.pcm").write_bytes(pcm)
    assets.append(dict(code=code, text=text, bytes=len(pcm),
                       duration_ms=len(pcm) // 32,
                       sha256=hashlib.sha256(pcm).hexdigest()))
manifest = dict(source="Windows SAPI Microsoft Huihui Desktop, rate 0",
                format="PCM S16LE 16000 Hz mono", listening_verified=False,
                note=("Synthesized exact text offline; human listening "
                      "and board playback pending"),
                assets=assets)
(AUDIO / "manifest.json").write_text(
    json.dumps(manifest, ensure_ascii=False, indent=2) + "\n",
    encoding="utf-8")
print(json.dumps(manifest, ensure_ascii=False, indent=2))
