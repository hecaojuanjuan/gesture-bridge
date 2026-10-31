@echo off
echo ========================================
echo 构建并烧录云台固件
echo ========================================
cd /d C:\Users\jiawa\Desktop\gesture-bridge

echo.
echo [1/3] 清理旧构建...
if exist .work\headvoice\apps\build rmdir /s /q .work\headvoice\apps\build
if exist .work\headvoice\apps\sdkconfig del /q .work\headvoice\apps\sdkconfig

echo.
echo [2/3] 构建云台固件（需要5-10分钟）...
C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools\build.py headvoice build --stage 2 --gimbal --rotate-cw90

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 构建失败
    pause
    exit /b 1
)

echo.
echo [3/3] 烧录固件到设备...
C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe tools\build.py headvoice flash --port COM3

if %ERRORLEVEL% NEQ 0 (
    echo.
    echo [错误] 烧录失败
    pause
    exit /b 1
)

echo.
echo ========================================
echo 完成！设备将自动重启
echo ========================================
echo.
echo 测试云台功能:
echo   .tools\espressif\python_env\idf5.4_py3.12_env\Scripts\python.exe tools\auto_center_on_boot.py --port COM3
echo.
pause
