#!/bin/bash
# 完整构建和烧录face-hand自动居中固件

set -e

PY='/c/Users/jiawa/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/python.exe'
PORT='COM3'

echo "========================================"
echo "人脸和手势自动居中固件 - 完整构建流程"
echo "========================================"
echo ""

# 步骤1：清理
echo "[1/3] 清理旧构建..."
rm -rf .work/headvoice/apps/build .work/headvoice/apps/sdkconfig 2>/dev/null || true
echo "✓ 清理完成"
echo ""

# 步骤2：构建
echo "[2/3] 构建固件（预计10-15分钟）..."
echo "配置: --stage 2 --vision face-hand --rotate-cw90"
echo ""

"$PY" tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90

if [ ! -f .work/headvoice/apps/build/vb701n.bin ]; then
    echo ""
    echo "✗ 构建失败：固件文件未生成"
    exit 1
fi

echo ""
echo "✓ 构建完成"
ls -lh .work/headvoice/apps/build/vb701n.bin
echo ""

# 步骤3：烧录
echo "[3/3] 烧录固件到设备..."
echo "端口: $PORT"
echo ""

"$PY" tools/build.py headvoice flash --port "$PORT"

echo ""
echo "========================================"
echo "✅ 完成！"
echo "========================================"
echo ""
echo "设备正在重启..."
echo ""
echo "功能说明:"
echo "- 伸出手 → 云台跟踪手部居中"
echo "- 收回手 → 云台切换到人脸居中"
echo "- 全自动，无需手动命令"
echo ""
echo "查看串口输出:"
echo "  $PY tools/build.py headvoice monitor --port $PORT"
echo ""
echo "查看详细文档:"
echo "  FINAL_DELIVERY.md"
echo ""
