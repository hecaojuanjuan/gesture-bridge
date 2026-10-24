"""Compile and execute the production C core on the host."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / ".work/host"
out.mkdir(parents=True, exist_ok=True)
zig = ROOT / ".tools/host/ziglang/zig.exe"
compiler = [str(zig), "cc"] if zig.exists() else [
    shutil.which("cc") or "clang"]
env = os.environ.copy()
env["ZIG_GLOBAL_CACHE_DIR"] = str(out / "zig-cache")
env["ZIG_LOCAL_CACHE_DIR"] = str(out / "zig-local")
exe = out / ("test_core.exe" if os.name == "nt" else "test_core")
flags = ["-std=c11", "-Wall", "-Wextra", "-Werror", "-O1", "-UNDEBUG", "-g"]
sources = [str(ROOT / "headvoice/core/hv_core.c"),
           str(ROOT / "tests/test_core.c")]
subprocess.run(compiler + flags + ["-I", str(ROOT / "headvoice/core")] +
               sources + ["-o", str(exe), "-lm"],
               check=True, env=env, cwd=out)
subprocess.run([str(exe)], check=True)
