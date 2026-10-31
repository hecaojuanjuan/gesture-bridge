@echo off
REM 代码完整性检查 (Windows)

echo ==========================================
echo 摄像头居中优化 + 手掌跟踪 - 代码检查
echo ==========================================
echo.

set PASS=0
set FAIL=0

echo === 核心代码文件 ===
call :check_file "headvoice\core\hv_gimbal_core.c"
call :check_file "headvoice\core\hv_gimbal_core.h"
call :check_file "headvoice\core\hv_hand_detector.c"
call :check_file "headvoice\core\hv_hand_detector.h"
call :check_file "headvoice\firmware\hv_gimbal_app.c"
echo.

echo === 文档文件 ===
call :check_file "GIMBAL_OPTIMIZATION.md"
call :check_file "GIMBAL_QUICK_GUIDE.md"
call :check_file "HAND_TRACKING_GUIDE.md"
call :check_file "README_GIMBAL_HAND.md"
echo.

echo === 部署脚本 ===
call :check_file "apply_gimbal_optimization.bat"
call :check_file "apply_gimbal_optimization.sh"
call :check_file "deploy_hand_tracking.bat"
call :check_file "deploy_hand_tracking.sh"
echo.

echo === 参考文件 ===
call :check_file "headvoice\core\hv_gimbal_core_optimized.c"
call :check_file "headvoice\CMakeLists_example.txt"
echo.

echo ==========================================
echo 检查结果: √ %PASS%  × %FAIL%
echo ==========================================
echo.

if %FAIL%==0 (
    echo ✓ 所有文件就绪！
    echo.
    echo 下一步:
    echo 1. 确保在CMakeLists.txt中添加 hv_hand_detector.c
    echo 2. 运行: cd .work\headvoice\apps ^&^& idf.py build
    echo 3. 烧录: idf.py flash monitor
    echo.
    echo 测试命令:
    echo   hv_gimbal mode hand
    echo   hv_gimbal start
    echo.
    pause
    exit /b 0
) else (
    echo × 有 %FAIL% 个文件缺失
    echo 请检查上述文件
    echo.
    pause
    exit /b 1
)

:check_file
if exist %1 (
    echo √ %~1
    set /a PASS+=1
) else (
    echo × 缺少: %~1
    set /a FAIL+=1
)
goto :eof
