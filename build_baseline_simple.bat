@echo off
setlocal enabledelayedexpansion

echo ========================================
echo 构建 baseline 固件（修复舵机零位）
echo ========================================
echo.

set PYTHON=C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe

echo [1/2] 清理旧构建...
if exist .work\baseline\apps\build rmdir /s /q .work\baseline\apps\build
echo.

echo [2/2] 开始构建...
echo 这可能需要 10-15 分钟，请耐心等待...
echo.

"%PYTHON%" tools\build.py baseline build

echo.
if exist .work\baseline\apps\build\vb701n.bin (
    echo ========================================
    echo 构建成功！
    echo ========================================
    dir .work\baseline\apps\build\vb701n.bin
    echo.
    echo 请运行 flash_baseline_simple.bat 来烧录固件
) else (
    echo ========================================
    echo 构建失败！
    echo ========================================
    echo 请检查上面的错误信息
)

echo.
pause
