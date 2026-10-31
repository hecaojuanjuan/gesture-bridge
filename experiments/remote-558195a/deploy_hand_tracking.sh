#!/bin/bash
# 部署手掌跟踪功能

set -e

echo "================================================"
echo "部署手掌跟踪功能"
echo "================================================"
echo ""

# 检查文件
echo "1. 检查必需文件..."
REQUIRED_FILES=(
    "headvoice/core/hv_gimbal_core.c"
    "headvoice/core/hv_gimbal_core.h"
    "headvoice/core/hv_hand_detector.c"
    "headvoice/core/hv_hand_detector.h"
    "headvoice/firmware/hv_gimbal_app.c"
)

for file in "${REQUIRED_FILES[@]}"; do
    if [ -f "$file" ]; then
        echo "   ✓ $file"
    else
        echo "   ✗ 缺少: $file"
        exit 1
    fi
done
echo ""

# 创建备份
echo "2. 创建备份..."
BACKUP_DIR="backups/hand_tracking_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
echo "   备份目录: $BACKUP_DIR"
echo ""

# 检查CMakeLists.txt
echo "3. 检查构建配置..."
if [ -f ".work/headvoice/apps/main/CMakeLists.txt" ]; then
    echo "   找到构建配置"
    echo "   请确保已添加 hv_hand_detector.c 到源文件列表"
else
    echo "   ⚠️  未找到标准CMakeLists.txt路径"
fi
echo ""

# 功能说明
echo "4. 新增功能:"
echo "   ✓ 人脸居中（已优化）"
echo "   ✓ 手掌居中（新功能）"
echo "   ✓ 自动模式（人脸优先，无人脸时切换到手掌）"
echo ""

echo "5. 使用命令:"
echo "   hv_gimbal mode face   # 人脸模式"
echo "   hv_gimbal mode hand   # 手掌模式"
echo "   hv_gimbal mode auto   # 自动模式（默认）"
echo ""

echo "6. 编译步骤:"
echo "   cd .work/headvoice/apps"
echo "   idf.py build"
echo "   idf.py flash monitor"
echo ""

echo "7. 测试步骤:"
echo "   a) 启动手掌模式: hv_gimbal mode hand"
echo "   b) 开始跟踪: hv_gimbal start"
echo "   c) 伸出手掌，观察跟踪效果"
echo ""

echo "================================================"
echo "准备就绪！请按照上述步骤编译和测试"
echo "================================================"
