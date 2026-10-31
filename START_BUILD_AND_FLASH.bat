@echo off
echo.
echo ========================================
echo 启动自动居中固件完整构建流程
echo ========================================
echo.
echo 这将执行:
echo   1. 清理旧构建
echo   2. 构建 face-hand 固件 (10-15分钟)
echo   3. 烧录到设备
echo.
echo 按任意键开始，或关闭窗口取消...
pause >nul

powershell -ExecutionPolicy Bypass -File "%~dp0Build-And-Flash-Complete.ps1"

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo 全部完成！
    echo ========================================
) else (
    echo.
    echo ========================================
    echo 过程中出现错误
    echo ========================================
)

echo.
pause
