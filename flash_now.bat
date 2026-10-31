@echo off
echo ========================================
echo 检查烧录状态并执行烧录
echo ========================================
echo.

set PYTHON=C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe

if not exist .work\baseline\apps\build\vb701n.bin (
    echo 错误：固件文件不存在！
    pause
    exit /b 1
)

echo 固件已准备就绪：
dir .work\baseline\apps\build\vb701n.bin
echo.
echo 开始烧录到 COM3...
echo 预计需要 2-3 分钟
echo.

"%PYTHON%" tools\build.py baseline flash --port COM3

echo.
echo ========================================
if errorlevel 1 (
    echo 烧录过程中出现错误
) else (
    echo 烧录完成！
    echo.
    echo 修复内容：舵机零位从 1450us 改为 1500us
    echo 效果：发送 1500us 信号时，舵机保持中位（水平），不再低头
)
echo ========================================
echo.
pause
