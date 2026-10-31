"""Compile the production MNP landmark adapter and shared tilt math."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / ".work/host"
out.mkdir(parents=True, exist_ok=True)
zig = ROOT / ".tools/host/ziglang/zig.exe"
compiler = [str(zig), "cc"] if zig.exists() else [shutil.which("cc") or "clang"]
env = os.environ.copy()
env["ZIG_GLOBAL_CACHE_DIR"] = str(out / "zig-cache")
env["ZIG_LOCAL_CACHE_DIR"] = str(out / "zig-local")
exe = out / ("test_face_landmarks.exe" if os.name == "nt" else "test_face_landmarks")
sources = [ROOT / "headvoice/core/hv_face_landmarks.c",
           ROOT / "headvoice/core/hv_core.c", ROOT / "tests/test_face_landmarks.c"]
subprocess.run(compiler + ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-UNDEBUG",
    "-I", str(ROOT / "headvoice/core")] + list(map(str, sources)) + ["-o", str(exe), "-lm"],
    check=True, env=env, cwd=out)
subprocess.run([str(exe)], check=True)
