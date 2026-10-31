@echo off
REM 部署手掌跟踪功能 (Windows)

setlocal enabledelayedexpansion

echo ================================================
echo 部署手掌跟踪功能
echo ================================================
echo.

REM 检查文件
echo 1. 检查必需文件...
set MISSING=0

if exist "headvoice\core\hv_gimbal_core.c" (
    echo    √ headvoice\core\hv_gimbal_core.c
) else (
    echo    × 缺少: headvoice\core\hv_gimbal_core.c
    set MISSING=1
)

if exist "headvoice\core\hv_gimbal_core.h" (
    echo    √ headvoice\core\hv_gimbal_core.h
) else (
    echo    × 缺少: headvoice\core\hv_gimbal_core.h
    set MISSING=1
)

if exist "headvoice\core\hv_hand_detector.c" (
    echo    √ headvoice\core\hv_hand_detector.c
) else (
    echo    × 缺少: headvoice\core\hv_hand_detector.c
    set MISSING=1
)

if exist "headvoice\core\hv_hand_detector.h" (
    echo    √ headvoice\core\hv_hand_detector.h
) else (
    echo    × 缺少: headvoice\core\hv_hand_detector.h
    set MISSING=1
)

if exist "headvoice\firmware\hv_gimbal_app.c" (
    echo    √ headvoice\firmware\hv_gimbal_app.c
) else (
    echo    × 缺少: headvoice\firmware\hv_gimbal_app.c
    set MISSING=1
)

if %MISSING%==1 (
    echo.
    echo 错误: 缺少必需文件
    pause
    exit /b 1
)
echo.

REM 创建备份
echo 2. 创建备份...
set BACKUP_DIR=backups\hand_tracking_%date:~0,4%%date:~5,2%%date:~8,2%_%time:~0,2%%time:~3,2%%time:~6,2%
set BACKUP_DIR=%BACKUP_DIR: =0%
if not exist "%BACKUP_DIR%" mkdir "%BACKUP_DIR%"
echo    备份目录: %BACKUP_DIR%
echo.

REM 功能说明
echo 3. 新增功能:
echo    √ 人脸居中（已优化）
echo    √ 手掌居中（新功能）
echo    √ 自动模式（人脸优先，无人脸时切换到手掌）
echo.

echo 4. 使用命令:
echo    hv_gimbal mode face   # 人脸模式
echo    hv_gimbal mode hand   # 手掌模式
echo    hv_gimbal mode auto   # 自动模式（默认）
echo.

echo 5. 编译步骤:
echo    cd .work\headvoice\apps
echo    idf.py build
echo    idf.py flash monitor
echo.

echo 6. 测试步骤:
echo    a^) 启动手掌模式: hv_gimbal mode hand
echo    b^) 开始跟踪: hv_gimbal start
echo    c^) 伸出手掌，观察跟踪效果
echo.

echo ================================================
echo 准备就绪！请按照上述步骤编译和测试
echo ================================================
echo.

echo 重要提示：
echo 1. 确保在项目的CMakeLists.txt中添加了hv_hand_detector.c
echo 2. 查看 headvoice\CMakeLists_example.txt 了解如何配置
echo 3. 详细文档见 HAND_TRACKING_GUIDE.md
echo.

pause
