# 人脸和手势自动居中功能实现总结

## 📋 任务概述

**任务**：在现有基础上实现在人脸出现和手势时自动让人脸和手居中

**完成状态**：✅ 功能已实现，正在构建固件

---

## ✅ 已完成的工作

### 1. 功能分析和方案确认

**关键发现**：
- ✅ 人脸和手势自动居中功能**已经在代码中实现**
- ✅ 实现位置：`headvoice/firmware/hv_hand_app.c` (第285-304行)
- ✅ 通过 `--vision face-hand` 构建参数启用

**实现原理**：
```c
// 手部优先策略
if (检测到手部) {
    使用手部边界框中心作为目标
    source = HV_GIMBAL_TARGET_HAND
} else if (手部数量 == 0) {
    使用人脸中心作为目标
    source = HV_GIMBAL_TARGET_FACE
}
// 统一调用云台控制
hv_face_gimbal_observe_target(source, ...)
```

### 2. 构建配置优化

**正确的构建命令**：
```bash
python tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90
```

**关键参数说明**：
- `--stage 2`：启用人脸姿态和手势检测
- `--vision face-hand`：**核心参数**，自动启用 `HV_CENTERING=1`
- `--rotate-cw90`：摄像头旋转90度适配硬件

**配置文件**（integration.cmake 第40-46行）：
```cmake
set(hv_centering 0)
if(HEADVOICE_VISION STREQUAL "face-hand")
  set(hv_centering 1)  # 自动启用居中功能
  target_sources(${COMPONENT_LIB} PRIVATE
    "${headvoice_root}/core/hv_gimbal_core.c"
    "${headvoice_root}/firmware/hv_face_gimbal.c")
endif()
```

### 3. 便捷脚本创建

**构建脚本**：
- ✅ `build_face_hand_centering.bat` - 一键构建固件
- ✅ `flash_face_hand_centering.bat` - 一键烧录固件
- ✅ `check_build_progress.bat` - 检查构建进度

**使用方法**：
1. 双击 `build_face_hand_centering.bat` 构建
2. 等待10-15分钟
3. 双击 `flash_face_hand_centering.bat` 烧录
4. 设备自动重启，功能立即生效

### 4. 完整文档编写

**用户文档**：
- ✅ `README_FACE_HAND_CENTERING.md` - 详细使用说明
  - 功能概述和工作原理
  - 构建和烧录步骤
  - 测试方法和预期行为
  - 配置参数说明
  - 故障排除指南
  
- ✅ `QUICK_START.md` - 快速开始指南
  - 简化的操作流程
  - 时间估算
  - 常见问题解答

**技术文档**：
- ✅ 代码实现分析
- ✅ 目标切换逻辑说明
- ✅ 归一化坐标系说明
- ✅ 自动启动条件文档

---

## 🔧 技术实现细节

### 目标检测和选择

**优先级策略**：
1. **手部优先**：当检测到手部 → 跟踪手部中心
2. **人脸回退**：当没有手部（hand.count == 0）→ 跟踪人脸
3. **智能切换**：目标源变化时自动重置居中状态

**代码位置**：`hv_hand_app.c` 第285-304行
```c
HvGimbalTarget source = HV_GIMBAL_TARGET_HAND;
bool targetValid = ret == ESP_OK && hand.valid;
float targetX = (hand.normalized_box[0] + hand.normalized_box[2]) * 0.5f;
float targetY = (hand.normalized_box[1] + hand.normalized_box[3]) * 0.5f;

if (ret == ESP_OK && hand.count == 0) {
  // 切换到人脸
  source = HV_GIMBAL_TARGET_FACE;
  targetValid = faceRet == ESP_OK && faceTarget.valid;
  targetX = faceTarget.x;
  targetY = faceTarget.y;
}
```

### 云台控制算法

**核心文件**：
- `hv_gimbal_core.c` - 云台算法核心
- `hv_face_gimbal.c` - 云台控制器

**居中逻辑**：
- 归一化坐标系：(0, 0) 到 (1, 1)
- 中心点：(0.5, 0.5)
- 偏差计算：`error = target - 0.5`
- 居中容差：±0.08（8%）
- 确认次数：连续3次

**脉宽范围**：
- 最小：1475µs
- 中心：1500µs
- 最大：1525µs
- 单步：最多25µs

### 目标切换处理

**代码位置**：`hv_face_gimbal.c` 第342-348行
```c
bool sourceChanged = source != s_targetSource;
if (sourceChanged) {
  s_acquireCount = 0;           // 重置采集计数
  s_core.previousAxis = -1;      // 清除轴记忆
  s_core.centered = 0;           // 清除居中状态
  s_core.worsening = 0;          // 清除恶化计数
}
```

**目的**：避免目标突然切换时的跳变和振荡

---

## 📂 文件清单

### 核心实现代码
- `headvoice/firmware/hv_hand_app.c` - 主应用，包含目标选择逻辑
- `headvoice/firmware/hv_face_gimbal.c` - 云台控制器
- `headvoice/core/hv_gimbal_core.c` - 云台核心算法
- `headvoice/firmware/hv_face_pose.cpp` - 人脸检测
- `headvoice/firmware/hv_hand_detect.cpp` - 手部检测

### 构建配置
- `headvoice/firmware/integration.cmake` - CMake集成配置
- `tools/build.py` - 构建脚本

### 便捷脚本
- `build_face_hand_centering.bat` - 构建固件
- `flash_face_hand_centering.bat` - 烧录固件
- `check_build_progress.bat` - 检查进度

### 文档
- `README_FACE_HAND_CENTERING.md` - 完整使用说明
- `QUICK_START.md` - 快速开始指南
- `SUMMARY_IMPLEMENTATION.md` - 本文件（实现总结）

---

## 🚀 下一步操作

### 1. 等待构建完成（约10-15分钟）

**检查方法**：
```cmd
check_build_progress.bat
```

或手动检查：
```bash
ls -lh .work/headvoice/apps/build/vb701n.bin
```

### 2. 烧录固件（约2-3分钟）

```cmd
flash_face_hand_centering.bat
```

### 3. 测试功能

**基本测试**：
1. 伸出手掌 → 云台跟踪手部
2. 收回手 → 云台切换到跟踪人脸
3. 再伸出手 → 云台切换回跟踪手部

**串口监控**：
```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice monitor --port COM3
```

**关键输出**：
```json
GIMBAL {"event":"auto_started","source":"hand"}
GIMBAL {"event":"observation","source":"hand",...}
GIMBAL {"event":"auto_started","source":"face"}
GIMBAL {"event":"observation","source":"face",...}
```

---

## ✨ 功能特性

### 自动居中
- ✅ 无需手动命令，设备启动后自动工作
- ✅ 检测到目标后2-3秒内开始调整
- ✅ 连续3次确认居中后停止
- ✅ 目标移动时自动重新调整

### 智能切换
- ✅ 手部检测优先级高于人脸
- ✅ 无手时自动回退到人脸
- ✅ 切换时重置状态，避免跳变
- ✅ 支持反复切换

### 稳定控制
- ✅ 归一化坐标系，与分辨率无关
- ✅ 单步移动限制，避免突变
- ✅ 脉宽限位保护，防止过度转动
- ✅ 超时和丢失目标保护

---

## 🎯 成功标准

功能**完全成功**的标志：

1. ✅ 固件构建成功（vb701n.bin 文件生成）
2. ✅ 固件烧录成功（设备重启）
3. ✅ 设备启动时输出 `GIMBAL ready pan=17 tilt=18 PWM=off`
4. ✅ 伸出手后云台开始转动（2-3秒内）
5. ✅ 串口输出显示 `"source":"hand"`
6. ✅ 收回手后云台切换到跟踪人脸
7. ✅ 串口输出显示 `"source":"face"`
8. ✅ 目标居中后云台停止
9. ✅ 目标移动时云台自动跟随

---

## ⚠️ 注意事项

### 硬件要求
- ✅ 舵机已连接（GPIO17=pan, GPIO18=tilt）
- ✅ 舵机供电正常（5V）
- ✅ 摄像头工作正常
- ⚠️ 舵机中位校准（1500µs应对应正前方）

### 环境要求
- ✅ 光照充足（利于检测）
- ✅ 目标清晰可见
- ✅ 距离适中（0.5-2米）

### 已知限制
- ⚠️ 检测不稳定时可能频繁切换
- ⚠️ 俯仰轴可能有机械问题（之前测试发现）
- ⚠️ 多人或多手时行为未定义

---

## 📊 与之前方案的对比

### 旧方案（--gimbal）
```bash
# 只支持COCO后端
python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90
```
**问题**：
- ❌ 只支持COCO身体姿态检测
- ❌ 不支持手势检测
- ❌ 无法区分手部和人脸
- ❌ 构建系统限制（第13-15行检查）

### 新方案（--vision face-hand）
```bash
# 同时支持人脸和手势
python tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90
```
**优势**：
- ✅ 同时支持人脸和手势检测
- ✅ 智能目标切换（手部优先）
- ✅ 自动启用云台控制（HV_CENTERING=1）
- ✅ 代码已经实现，无需修改

---

## 🔍 代码审查要点

### 1. 目标选择逻辑正确
- ✅ 手部检测有效时使用手部
- ✅ hand.count == 0 时才切换到人脸
- ✅ 避免检测不确定时频繁切换

### 2. 坐标归一化正确
- ✅ 手部：`(box[0]+box[2])/2` 和 `(box[1]+box[3])/2`
- ✅ 人脸：`faceTarget.x` 和 `faceTarget.y`
- ✅ 范围检查：0-1

### 3. 目标切换处理正确
- ✅ 检测到源变化时重置状态
- ✅ 清除采集计数和居中状态
- ✅ 避免历史数据污染

### 4. 构建配置正确
- ✅ `face-hand` 后端自动启用 `HV_CENTERING`
- ✅ 包含所有必要的源文件
- ✅ 编译定义正确传递

---

## 📝 总结

**核心发现**：自动居中功能已经在代码中实现，只需要使用正确的构建参数 `--vision face-hand` 启用即可。

**实现质量**：
- ✅ 代码结构清晰，逻辑正确
- ✅ 目标切换策略合理（手部优先）
- ✅ 状态管理完善（重置、超时、限位）
- ✅ 配置灵活（脉宽、容差、超时可调）

**用户体验**：
- ✅ 全自动工作，无需手动命令
- ✅ 智能切换，体验流畅
- ✅ 一键构建和烧录
- ✅ 详细文档和故障排除

---

**当前状态**：🔄 正在构建固件（预计10-15分钟）  
**完成度**：95%（等待构建完成并测试验证）  
**下一步**：构建完成后烧录并测试功能
