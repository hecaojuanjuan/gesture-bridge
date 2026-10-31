#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""完整的云台固件构建和烧录流程"""
import subprocess
import sys
import time
from pathlib import Path

if sys.platform == 'win32':
    import io
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

ROOT = Path(r"C:\Users\jiawa\Desktop\gesture-bridge")
PYTHON = r"C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe"

def run_command(cmd, desc):
    """运行命令并显示输出"""
    print("\n" + "="*60)
    print(f"  {desc}")
    print("="*60)
    print(f"命令: {' '.join(cmd)}\n")

    result = subprocess.run(cmd, cwd=str(ROOT))

    if result.returncode != 0:
        print(f"\n✗ 失败: {desc}")
        return False

    print(f"\n✓ 成功: {desc}")
    return True

def main():
    print("\n" + "="*60)
    print("  构建并烧录云台固件")
    print("="*60)

    # 1. 构建
    if not run_command(
        [PYTHON, "tools/build.py", "headvoice", "build", "--stage", "2", "--gimbal", "--rotate-cw90"],
        "构建云台固件（需要5-10分钟）"
    ):
        sys.exit(1)

    # 2. 烧录
    if not run_command(
        [PYTHON, "tools/build.py", "headvoice", "flash", "--port", "COM3"],
        "烧录固件到设备"
    ):
        sys.exit(1)

    # 3. 完成
    print("\n" + "="*60)
    print("  ✓✓✓ 完成！")
    print("="*60)
    print("\n设备将自动重启...")
    print("\n测试云台功能:")
    print("  .tools\\espressif\\python_env\\idf5.4_py3.12_env\\Scripts\\python.exe tools\\auto_center_on_boot.py --port COM3")

if __name__ == "__main__":
    main()
