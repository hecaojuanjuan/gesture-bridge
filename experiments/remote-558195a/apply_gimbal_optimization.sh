#!/bin/bash
# 应用摄像头居中算法优化

set -e

echo "================================================"
echo "应用摄像头居中算法优化"
echo "================================================"
echo ""

# 检查是否在项目根目录
if [ ! -f "headvoice/core/hv_gimbal_core.c" ]; then
    echo "错误: 请在项目根目录运行此脚本"
    exit 1
fi

# 备份原文件
echo "1. 备份原始文件..."
BACKUP_DIR="backups/gimbal_optimization_$(date +%Y%m%d_%H%M%S)"
mkdir -p "$BACKUP_DIR"
cp headvoice/core/hv_gimbal_core.c "$BACKUP_DIR/"
cp headvoice/firmware/hv_gimbal_app.c "$BACKUP_DIR/"
echo "   备份保存到: $BACKUP_DIR"
echo ""

# 应用优化
echo "2. 应用优化版本..."
cp headvoice/core/hv_gimbal_core_optimized.c headvoice/core/hv_gimbal_core.c
echo "   ✓ 已更新 hv_gimbal_core.c"
echo "   ✓ 已更新 hv_gimbal_app.c (已在之前修改)"
echo ""

# 显示优化内容
echo "3. 优化内容摘要:"
echo "   • 识别条件: 允许1-2人，放宽头部检测要求"
echo "   • 响应速度: 等待时间从450ms降到200ms (-56%)"
echo "   • 步长调整: 最小12→最大45 (更快收敛)"
echo "   • 最大步数: 20步→30步"
echo "   • 容错性: 更宽松的误差判断"
echo ""

echo "4. 下一步操作:"
echo "   cd .work/headvoice/apps"
echo "   idf.py build"
echo "   idf.py flash"
echo ""

echo "5. 测试建议:"
echo "   • 测试正面、侧面识别"
echo "   • 测试多人场景"
echo "   • 记录实际居中时间"
echo ""

echo "6. 如需回滚:"
echo "   cp $BACKUP_DIR/hv_gimbal_core.c headvoice/core/"
echo "   cp $BACKUP_DIR/hv_gimbal_app.c headvoice/firmware/"
echo ""

echo "================================================"
echo "优化已应用！请重新编译和烧录固件"
echo "================================================"
