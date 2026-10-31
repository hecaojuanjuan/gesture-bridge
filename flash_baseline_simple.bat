@echo off
setlocal enabledelayedexpansion

echo ========================================
echo 烧录 baseline 固件
echo ========================================
echo.

set PYTHON=C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe

if not exist .work\baseline\apps\build\vb701n.bin (
    echo 错误：固件文件不存在！
    echo 请先运行 build_baseline_simple.bat 构建固件
    pause
    exit /b 1
)

echo 固件信息：
dir .work\baseline\apps\build\vb701n.bin
echo.

echo 开始烧录到 COM3...
echo.

"%PYTHON%" tools\build.py baseline flash --port COM3

echo.
if errorlevel 1 (
    echo ========================================
    echo 烧录失败！
    echo ========================================
) else (
    echo ========================================
    echo 烧录成功！
    echo ========================================
    echo 舵机零位已修复为 1500us
)

echo.
pause
