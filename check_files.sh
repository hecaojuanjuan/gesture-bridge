#!/bin/bash
# 代码完整性检查

echo "=========================================="
echo "摄像头居中优化 + 手掌跟踪 - 代码检查"
echo "=========================================="
echo ""

PASS=0
FAIL=0

check_file() {
    if [ -f "$1" ]; then
        echo "✓ $1"
        ((PASS++))
        return 0
    else
        echo "✗ 缺少: $1"
        ((FAIL++))
        return 1
    fi
}

echo "=== 核心代码文件 ==="
check_file "headvoice/core/hv_gimbal_core.c"
check_file "headvoice/core/hv_gimbal_core.h"
check_file "headvoice/core/hv_hand_detector.c"
check_file "headvoice/core/hv_hand_detector.h"
check_file "headvoice/firmware/hv_gimbal_app.c"
echo ""

echo "=== 文档文件 ==="
check_file "GIMBAL_OPTIMIZATION.md"
check_file "GIMBAL_QUICK_GUIDE.md"
check_file "HAND_TRACKING_GUIDE.md"
check_file "README_GIMBAL_HAND.md"
echo ""

echo "=== 部署脚本 ==="
check_file "apply_gimbal_optimization.bat"
check_file "apply_gimbal_optimization.sh"
check_file "deploy_hand_tracking.bat"
check_file "deploy_hand_tracking.sh"
echo ""

echo "=== 参考文件 ==="
check_file "headvoice/core/hv_gimbal_core_optimized.c"
check_file "headvoice/CMakeLists_example.txt"
echo ""

echo "=========================================="
echo "检查结果: ✓ $PASS  ✗ $FAIL"
echo "=========================================="
echo ""

if [ $FAIL -eq 0 ]; then
    echo "✅ 所有文件就绪！"
    echo ""
    echo "下一步:"
    echo "1. 确保在CMakeLists.txt中添加 hv_hand_detector.c"
    echo "2. 运行: cd .work/headvoice/apps && idf.py build"
    echo "3. 烧录: idf.py flash monitor"
    echo ""
    echo "测试命令:"
    echo "  hv_gimbal mode hand"
    echo "  hv_gimbal start"
    exit 0
else
    echo "❌ 有 $FAIL 个文件缺失"
    echo "请检查上述文件"
    exit 1
fi
