@echo off
echo ========================================
echo 构建人脸+手势自动居中固件
echo ========================================
echo.
echo 固件特性:
echo - 人脸检测和自动居中
echo - 手势检测和自动居中
echo - 手部优先，无手时回退到人脸
echo - 摄像头旋转90度
echo.
echo 开始构建...
echo.

set PY=C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe

"%PY%" tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90

if %ERRORLEVEL% EQU 0 (
    echo.
    echo ========================================
    echo 构建成功！
    echo ========================================
    echo.
    echo 固件位置: .work\headvoice\apps\build\vb701n.bin
    echo.
    echo 下一步操作:
    echo 1. 烧录固件: flash_face_hand_centering.bat
    echo 2. 或手动烧录:
    echo    "%PY%" tools/build.py headvoice flash --port COM3
    echo.
) else (
    echo.
    echo ========================================
    echo 构建失败！
    echo ========================================
    echo 请检查错误信息
    echo.
)

pause
