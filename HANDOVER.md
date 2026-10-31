# 手势/人像自动居中功能开发交接日志

**日期**: 2026-10-31  
**时间**: 20:30  
**开发者**: Claude  
**项目**: gesture-bridge 自动居中功能  

---

## 已完成的工作 ✅

### 1. 代码开发和测试
- ✅ **核心算法验证**
  - 文件: `headvoice/core/hv_gimbal_core.c`
  - 坐标归一化: 像素 → (0-1)范围
  - 偏差计算: target - 0.5
  - 中心容差: ±0.08 (8%)
  - 轴选择逻辑: 优先移动偏差较大的轴
  - **所有算法测试通过** ✓

- ✅ **单元测试**
  - 文件: `tests/test_centering_integration.py`
  - 5个测试全部通过
  - 验证了坐标归一化、偏差计算、脉宽限位

- ✅ **手势居中模拟器**
  - 文件: `tools/hand_center_simulator.py`
  - 已运行167次观察
  - 成功检测到2次居中状态
  - 验证了手部检测和居中判断逻辑

- ✅ **自动居中脚本**
  - 文件: `tools/auto_center_on_boot.py`
  - 检测设备启动
  - 自动验证云台功能
  - 执行人脸自动居中流程

### 2. 文档
- ✅ `docs/hand-centering-test-2026-10-31.md` - 完整测试报告
- ✅ `NEXT_STEPS.md` - 操作指南
- ✅ `tools/build_flash_gimbal.py` - 完整构建和烧录脚本
- ✅ `build_and_flash_gimbal.bat` - Windows批处理脚本

### 3. 问题诊断
- ✅ **确认根本原因**: 当前设备固件**不支持云台功能**
  - 测试命令: `hv_gimbal status` 返回 "command not found"
  - 原因: 烧录的是手势识别固件，不是云台固件
- ✅ **验证方法**: 使用 `auto_center_on_boot.py` 自动检测

---

## 进行中的工作 🔄

### 1. 固件构建（当前正在进行）
**状态**: 🔄 **正在构建中**

**命令**:
```bash
python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90
```

**进度**:
- ✅ 清理了旧的构建目录 `.work/headvoice/apps/build`
- ✅ 删除了旧的配置文件 `.work/headvoice/apps/sdkconfig`
- 🔄 **正在重新编译** (预计需要10-15分钟)
- ⏳ 等待构建完成

**构建参数说明**:
- `--stage 2`: Face pose阶段（人脸姿态检测）
- `--gimbal`: **启用云台功能** ← 关键参数
- `--rotate-cw90`: 摄像头旋转90度（适配当前硬件）

---

## 待完成的工作 ⏳

### 1. 固件烧录（构建完成后）
**步骤**:
```bash
# 1. 确认构建完成
ls -lh .work/headvoice/apps/build/vb701n.bin
# 文件时间应该是最新的（2026-10-31 20:30+）

# 2. 烧录到设备
python tools/build.py headvoice flash --port COM3

# 预计时间: 2-3分钟
```

### 2. 功能验证和测试
**步骤**:
```bash
# 1. 测试云台功能是否可用
.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe tools/auto_center_on_boot.py --port COM3

# 预期输出:
# [启动] ✓ 检测到云台模块
# [检查] ✓ 云台功能已启用
```

**如果成功，应该看到**:
- ✓ `hv_gimbal status` 命令有响应
- ✓ 设备启动时PWM默认关闭
- ✓ 可以手动测试云台命令

### 3. 手动云台测试（验证硬件）
**串口命令**:
```
hv_gimbal status        # 查看状态
hv_gimbal target        # 查看人脸目标
hv_gimbal arm pan       # 启动水平轴（舵机应该转动）
hv_gimbal arm tilt      # 启动俯仰轴（舵机应该转动）
hv_gimbal stop          # 停止（舵机停止）
```

**⚠️ 重要注意事项**:
- 根据文档，之前测试时发现**俯仰轴有机械问题**
- `arm tilt` 后会大幅下移（1500µs位置不对）
- **建议先用只读命令测试，确认机械安装正确**

### 4. 自动居中测试（最终目标）
**前提条件**:
- ✅ 固件支持云台
- ✅ 手动测试云台可以转动
- ✅ 机械校准正确（1500µs对应镜头朝前）

**步骤**:
```bash
# 自动居中测试
.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe tools/auto_center_on_boot.py --port COM3

# 或手动执行：
hv_gimbal target        # 确认检测到人脸
hv_gimbal arm pan       # 启动水平轴
hv_gimbal arm tilt      # 启动俯仰轴
hv_gimbal dir 1 1       # 设置方向（需要实测校准）
hv_gimbal start         # 开始自动居中（舵机会自动转动）
```

**预期结果**:
- 舵机自动转动来居中人脸
- 最多20步、90秒内完成
- 连续3次确认居中后停止
- 控制台显示进度

---

## 文件清单 📁

### 核心代码
- `headvoice/core/hv_gimbal_core.c/h` - 云台控制核心算法
- `headvoice/firmware/hv_face_gimbal.c/h` - 固件层云台接口
- `headvoice/firmware/hv_face_pose.cpp/h` - 人脸检测

### 测试工具
- `tests/test_centering_integration.py` - 单元测试
- `tools/hand_center_simulator.py` - 手势居中模拟器
- `tools/auto_center_on_boot.py` - 自动居中启动脚本
- `tools/build_flash_gimbal.py` - 完整构建烧录脚本

### 文档
- `docs/hand-centering-test-2026-10-31.md` - 测试报告
- `docs/camera-auto-center.md` - 云台功能文档
- `NEXT_STEPS.md` - 后续步骤指南

### 配置和脚本
- `build_and_flash_gimbal.bat` - Windows批处理
- `flash_firmware.bat` - 简化烧录脚本
- `tools/wait_and_flash.py` - 自动等待构建完成并烧录

---

## 下一步操作指南 🎯

### 立即执行（构建完成后）:

1. **检查构建是否完成**:
```bash
ls -lh .work/headvoice/apps/build/vb701n.bin
# 确认文件时间是最新的
```

2. **烧录固件**:
```bash
python tools/build.py headvoice flash --port COM3
```

3. **测试云台功能**:
```bash
.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe tools/auto_center_on_boot.py --port COM3
```

### 如果构建卡住:
```bash
# 检查构建进程
ps aux | grep -E "idf.py|ninja|cmake"

# 如果卡住，强制终止并重新开始
pkill -9 -f "idf.py"
rm -rf .work/headvoice/apps/build
python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90
```

---

## 已知问题和限制 ⚠️

### 1. 机械问题
- 俯仰轴（tilt）在 `arm tilt` 后会大幅下移
- 原因: 1500µs位置与实际机械中位不匹配
- **解决方案**: 需要断电后检查舵盘安装，重新校准

### 2. 检测稳定性
- 人脸检测间歇性强（约18%帧有效）
- 手部检测也不连续
- 影响连续居中判断（需要连续3次）

### 3. 供电
- 两只SG90舵机共用主板5V/VBUS
- 舵机端电压未实测
- 可能影响舵机稳定性

---

## 快速命令参考 📋

### 构建和烧录
```bash
# 完整流程
python tools/build_flash_gimbal.py

# 或分步执行
python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90
python tools/build.py headvoice flash --port COM3
```

### 测试
```bash
# 自动测试
.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe tools/auto_center_on_boot.py --port COM3

# 手势模拟器
.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe tools/hand_center_simulator.py --port COM3

# 串口监控
python tools/build.py headvoice monitor --port COM3
```

### 云台串口命令
```
hv_gimbal status       # 状态
hv_gimbal target       # 目标
hv_gimbal arm pan      # 启动水平
hv_gimbal arm tilt     # 启动俯仰
hv_gimbal dir 1 1      # 方向
hv_gimbal start        # 开始
hv_gimbal stop         # 停止
```

---

## 成功标准 🎯

自动居中功能**完全成功**的标志:
1. ✅ 固件烧录成功
2. ✅ `hv_gimbal status` 有响应
3. ✅ 手动 `arm pan/tilt` 舵机能转动
4. ✅ 检测到人脸目标
5. ✅ `hv_gimbal start` 后舵机自动转动
6. ✅ 成功居中人脸
7. ✅ 设备重启后自动执行居中

---

**当前状态**: 🔄 **等待固件构建完成**  
**估计完成时间**: 10-15分钟  
**下一步**: 烧录固件并测试
