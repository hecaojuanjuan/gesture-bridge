@echo off
echo ========================================
echo 烧录人脸+手势自动居中固件
echo ========================================
echo.

set PY=C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe
set PORT=COM3

echo 检查固件文件...
if not exist ".work\headvoice\apps\build\vb701n.bin" (
    echo 错误: 固件文件不存在
    echo 请先运行 build_face_hand_centering.bat 构建固件
    pause
    exit /b 1
)

echo 固件文件: .work\headvoice\apps\build\vb701n.bin
echo 端口: %PORT%
echo.
echo 开始烧录...
echo.

"%PY%" tools/build.py headvoice flash --port %PORT%

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo 烧录成功！
    echo ========================================
    echo.
    echo 设备会自动重启
    echo.
    echo 功能说明:
    echo - 设备启动后会自动检测人脸和手势
    echo - 当检测到手部时，云台会自动跟踪手部居中
    echo - 当没有检测到手部时，云台会回退到人脸居中
    echo - 手部检测优先级高于人脸检测
    echo.
    echo 测试方法:
    echo 1. 伸出手掌在摄像头前 → 云台跟踪手部
    echo 2. 收回手 → 云台自动切换到跟踪人脸
    echo 3. 观察串口输出查看目标切换信息
    echo.
    echo 串口监控命令:
    echo "%PY%" tools/build.py headvoice monitor --port %PORT%
    echo.
) else (
    echo.
    echo ========================================
    echo 烧录失败！
    echo ========================================
    echo 请检查:
    echo 1. 设备是否连接到 %PORT%
    echo 2. 是否有其他程序占用串口
    echo 3. USB线缆是否正常
    echo.
)

pause
