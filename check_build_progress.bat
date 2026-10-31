@echo off
echo 检查构建进度...
echo.

if not exist ".local\build-face-hand.log" (
    echo 构建日志不存在，构建可能还未开始
    pause
    exit /b 1
)

echo 最新构建日志（最后30行）:
echo ========================================
powershell -Command "Get-Content .local\build-face-hand.log -Tail 30"
echo ========================================
echo.

if exist ".work\headvoice\apps\build\vb701n.bin" (
    echo.
    echo ✓ 固件文件已生成
    powershell -Command "Get-Item .work\headvoice\apps\build\vb701n.bin | Select-Object Name, Length, LastWriteTime | Format-List"
    echo.
    echo 下一步: 运行 flash_face_hand_centering.bat 烧录固件
) else (
    echo.
    echo 固件文件尚未生成，构建仍在进行中...
    echo 请等待几分钟后重新运行此脚本
)

echo.
pause
