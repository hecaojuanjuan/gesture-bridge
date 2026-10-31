"""Build production RGB policy on the host; this is not an electrical test."""
import os
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
out = ROOT / '.work/host'
out.mkdir(parents=True, exist_ok=True)
zig = ROOT / '.tools/host/ziglang/zig.exe'
compiler = [str(zig), 'cc'] if zig.exists() else [shutil.which('cc') or 'clang']
exe = out / ('test_light.exe' if os.name == 'nt' else 'test_light')
subprocess.run(compiler + ['-std=c11', '-Wall', '-Wextra', '-Werror', '-UNDEBUG',
    '-I', str(ROOT / 'headvoice/core'), str(ROOT / 'headvoice/core/hv_light.c'),
    str(ROOT / 'tests/test_light.c'), '-o', str(exe)], check=True)
subprocess.run([str(exe)], check=True)
