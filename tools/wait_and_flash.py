#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""等待构建完成并自动烧录"""
import os
import sys
import time
import subprocess
from pathlib import Path

# 设置UTF-8输出
if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# 项目根目录
ROOT = Path(r"C:\Users\jiawa\Desktop\gesture-bridge")
BUILD_DIR = ROOT / ".work" / "headvoice" / "apps" / "build"
FIRMWARE = BUILD_DIR / "vb701n.bin"
PORT = "COM3"

print("等待固件构建完成...")
print(f"监控文件: {FIRMWARE}")

# 记录初始修改时间
initial_mtime = FIRMWARE.stat().st_mtime if FIRMWARE.exists() else 0
print(f"初始修改时间: {time.ctime(initial_mtime)}")

# 等待固件更新
max_wait = 900  # 最多等待15分钟
start = time.time()
last_size = FIRMWARE.stat().st_size if FIRMWARE.exists() else 0

while time.time() - start < max_wait:
    if FIRMWARE.exists():
        current_mtime = FIRMWARE.stat().st_mtime
        current_size = FIRMWARE.stat().st_size

        if current_mtime > initial_mtime and current_size > last_size:
            print(f"\n检测到固件更新: {time.ctime(current_mtime)}")
            print(f"固件大小: {current_size / 1024 / 1024:.2f} MB")

            # 等待几秒确保文件写入完成
            time.sleep(3)

            # 检查大小是否稳定
            if FIRMWARE.stat().st_size == current_size:
                print("\n✓ 固件构建完成！")
                break

        last_size = current_size

    time.sleep(2)
    elapsed = int(time.time() - start)
    print(f"\r等待中... {elapsed}秒", end="", flush=True)
else:
    print("\n✗ 等待超时")
    sys.exit(1)

# 烧录固件
print("\n" + "="*60)
print("  开始烧录固件")
print("="*60)

python_exe = r".tools\espressif\python_env\idf5.4_py3.12_env\Scripts\python.exe"
cmd = [
    python_exe,
    "-m", "esptool",
    "--port", PORT,
    "--baud", "460800",
    "write_flash",
    "0x10000", str(FIRMWARE)
]

print(f"\n执行: {' '.join(cmd)}\n")

try:
    result = subprocess.run(cmd, cwd=str(ROOT), capture_output=False, text=True)

    if result.returncode == 0:
        print("\n" + "="*60)
        print("  ✓ 烧录成功！")
        print("="*60)
        print("\n下一步:")
        print("1. 设备会自动重启")
        print("2. 运行测试脚本:")
        print(f"   python tools/auto_center_on_boot.py --port {PORT}")
    else:
        print(f"\n✗ 烧录失败，返回码: {result.returncode}")
        sys.exit(1)

except Exception as e:
    print(f"\n✗ 烧录出错: {e}")
    sys.exit(1)
