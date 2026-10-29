"""Compile and run the production gimbal controller on the host."""
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
output = ROOT / ".work/host"
output.mkdir(parents=True, exist_ok=True)
env = os.environ.copy()
env["ZIG_GLOBAL_CACHE_DIR"] = str(output / "zig-cache")
env["ZIG_LOCAL_CACHE_DIR"] = str(output / "zig-local")
binary = output / "test_gimbal.exe"
subprocess.run([
    str(ROOT / ".tools/host/ziglang/zig.exe"), "cc", "-std=c11",
    "-Wall", "-Wextra", "-Werror", "-O1", "-UNDEBUG",
    "-I", str(ROOT / "headvoice/core"),
    str(ROOT / "headvoice/core/hv_gimbal_core.c"),
    str(ROOT / "tests/test_gimbal.c"), "-o", str(binary), "-lm"],
    check=True, env=env, cwd=output)
subprocess.run([str(binary)], check=True)
