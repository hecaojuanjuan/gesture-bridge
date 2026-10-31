# 人脸和手势自动居中功能使用说明

## 功能概述

本固件实现了**人脸和手势的自动居中**功能，云台会根据检测到的目标自动调整摄像头位置：

### 目标优先级
1. **手部优先**：当检测到手部时，云台会跟踪手部中心并自动居中
2. **人脸回退**：当没有检测到手部（hand.count == 0）时，云台会自动切换到跟踪人脸
3. **智能切换**：目标源变化时会重置居中状态，避免突变

### 核心特性
- ✅ 手势检测（张掌、V字等）
- ✅ 人脸检测和姿态识别
- ✅ 云台自动居中控制
- ✅ 手部/人脸智能切换
- ✅ 摄像头旋转90度适配

## 构建固件

### 方法1：使用批处理脚本（推荐）
```cmd
build_face_hand_centering.bat
```

### 方法2：手动命令
```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90
```

**构建参数说明**：
- `--stage 2`：启用人脸姿态和手势检测
- `--vision face-hand`：**关键参数**，同时启用人脸和手势检测，并自动启用 `HV_CENTERING`
- `--rotate-cw90`：摄像头顺时针旋转90度

## 烧录固件

### 方法1：使用批处理脚本（推荐）
```cmd
flash_face_hand_centering.bat
```

### 方法2：手动命令
```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice flash --port COM3
```

## 工作原理

### 代码位置
主要实现在 `headvoice/firmware/hv_hand_app.c` 的 `process_frame()` 函数（第285-304行）：

```c
#if HV_CENTERING
    /* Center before gesture classification. Only a successful zero-hand
     * detection allows face fallback; ambiguous hands veto background faces. */
    hv_face_target_t faceTarget = {0};
    yolo11_pose_frame_result_t face = {0};
    HvGimbalTarget source = HV_GIMBAL_TARGET_HAND;
    unsigned targets = hand.count;
    bool targetValid = ret == ESP_OK && hand.valid;
    float targetX = (hand.normalized_box[0] + hand.normalized_box[2]) * 0.5f;
    float targetY = (hand.normalized_box[1] + hand.normalized_box[3]) * 0.5f;
    if (ret == ESP_OK && hand.count == 0) {
      esp_err_t faceRet = hv_face_pose_analyze_rgb888(rgb, width, height, &face, &faceTarget);
      source = HV_GIMBAL_TARGET_FACE;
      targets = face.person_count;
      targetValid = faceRet == ESP_OK && faceTarget.valid;
      targetX = faceTarget.x;
      targetY = faceTarget.y;
    }
    hv_face_gimbal_observe_target(source, targets,
      targetValid && epoch == stream_epoch(false), targetX, targetY, captured, now_ms());
#endif
```

### 工作流程
1. **每帧处理**：从摄像头获取图像
2. **手部检测**：首先尝试检测手部
   - 如果检测到手部 → 使用手部边界框中心作为目标
   - 目标源标记为 `HV_GIMBAL_TARGET_HAND`
3. **人脸回退**：如果手部数量为0
   - 运行人脸检测
   - 使用人脸中心作为目标
   - 目标源标记为 `HV_GIMBAL_TARGET_FACE`
4. **云台控制**：调用 `hv_face_gimbal_observe_target()` 统一处理
   - 自动启动云台（需要3次连续有效观察）
   - 计算偏差并控制舵机
   - 连续3次居中后停止

### 目标切换处理
在 `hv_face_gimbal.c` 的 `hv_face_gimbal_observe_target()` 函数（第337-348行）：

```c
bool sourceChanged = source != s_targetSource;
s_targetSource = source;
if (sourceChanged) {
  s_acquireCount = 0;  // 重置采集计数
  s_core.previousAxis = -1;  // 清除轴记忆
  s_core.centered = s_core.worsening = 0;  // 清除居中状态
}
```

## 测试方法

### 1. 串口监控
```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice monitor --port COM3
```

### 2. 观察输出
查找包含 `GIMBAL` 的行：

```json
GIMBAL {"event":"auto_started","source":"hand"}
GIMBAL {"event":"observation","source":"hand","people":1,"face":true,...}
GIMBAL {"event":"auto_started","source":"face"}
GIMBAL {"event":"observation","source":"face","people":1,"face":true,...}
```

### 3. 手动测试步骤
1. **伸出手掌**：观察串口输出 `"source":"hand"`，云台应跟踪手部
2. **移动手**：云台应跟随手部移动
3. **收回手**：观察串口输出切换到 `"source":"face"`，云台应跟踪人脸
4. **移动头部**：云台应跟随人脸移动
5. **再次伸出手**：云台应立即切换回跟踪手部

## 配置参数

### 云台范围（hv_face_gimbal.c 第18-22行）
```c
enum {
  PULSE_MIN_US = 1475,      // 最小脉宽
  PULSE_MID_US = 1500,      // 中心位置
  PULSE_MAX_US = 1525,      // 最大脉宽
  MAX_STEP_US = 25,         // 单步最大移动
  MAX_FRAME_AGE_MS = 400,   // 帧有效期
  LOST_TARGET_MS = 2000,    // 目标丢失超时
}
```

### 居中容差（hv_gimbal_core.c 第56行）
```c
if (fabsf(error[0]) <= 0.08f && fabsf(error[1]) <= 0.08f) {
  if (++core->centered >= 3) return stop(core, HV_GIMBAL_CENTERED);
```
- 容差：±0.08（归一化坐标系，即±8%）
- 需要连续3次确认

## 串口命令

虽然固件会自动控制云台，但也可以手动测试：

```
hv_gimbal status        # 查看云台状态
hv_gimbal target        # 查看当前目标（手部或人脸）
hv_gimbal auto on       # 启用自动模式（默认已启用）
hv_gimbal auto off      # 禁用自动模式
hv_gimbal stop          # 停止云台
```

## 构建配置对比

### face-hand 后端（当前方案）
```cmake
if(HEADVOICE_VISION STREQUAL "face-hand")
  set(hv_centering 1)  # ✅ 自动启用居中
  # 编译云台控制和人脸检测模块
endif()
```

### 旧的 gimbal 方案（已弃用）
```cmake
if(HEADVOICE_GIMBAL AND NOT HEADVOICE_VISION STREQUAL "coco")
  message(FATAL_ERROR "The gimbal requires the COCO body pose backend")
endif()
```
- ⚠️ `--gimbal` 参数只支持 `coco` 后端
- ⚠️ 不包含手势检测
- ⚠️ 已被 `face-hand` 方案替代

## 故障排除

### 1. 云台不动
- 检查串口输出是否有 `GIMBAL` 消息
- 确认固件是用 `--vision face-hand` 构建的
- 检查舵机电源连接（GPIO17=pan, GPIO18=tilt）

### 2. 目标不切换
- 确认手部检测工作正常（查看 `HG` 消息）
- 确认人脸检测工作正常（查看 `observation` 消息）
- 检查 `"source"` 字段是否在 `hand` 和 `face` 之间切换

### 3. 频繁切换
- 检测不稳定，手部时有时无
- 调整光照条件
- 保持手部在摄像头视野内

### 4. 云台漂移
- 检查机械中位校准（1500µs应对应镜头朝前）
- 检查舵盘固定是否松动
- 检查供电是否稳定

## 技术细节

### 归一化坐标系
- 目标坐标范围：(0, 0) 到 (1, 1)
- 中心点：(0.5, 0.5)
- 偏差计算：`error = target - 0.5`

### 目标选择逻辑
```c
// 手部优先
if (hand.count > 0 && hand.valid) {
  使用手部中心
} else if (hand.count == 0) {  // 明确无手
  使用人脸中心
} else {
  // hand.count 不确定，不切换
}
```

### 自动启动条件
1. 自动模式已启用（`s_autoEnabled = true`）
2. 目标有效且连续3次观察
3. 目标偏离中心超过±0.12（12%）
4. 云台未在运行中

## 相关文件

### 核心代码
- `headvoice/firmware/hv_hand_app.c` - 主应用，包含目标选择逻辑
- `headvoice/firmware/hv_face_gimbal.c` - 云台控制器
- `headvoice/core/hv_gimbal_core.c` - 云台核心算法
- `headvoice/firmware/hv_face_pose.cpp` - 人脸检测
- `headvoice/firmware/hv_hand_detect.cpp` - 手部检测

### 构建配置
- `headvoice/firmware/integration.cmake` - CMake集成
- `tools/build.py` - 构建脚本

### 文档
- `docs/camera-auto-center.md` - 云台功能原理
- `docs/hand-centering-test-2026-10-31.md` - 测试记录
- `HANDOVER.md` - 开发交接日志

---

**构建时间**: 预计10-15分钟  
**测试准备**: 确保舵机已连接，机械安装正确  
**问题反馈**: 查看串口输出，记录完整的 `GIMBAL` 和 `HG` 消息
