# 人脸和手势自动居中功能 - 最终交付

## 🎉 功能实现状态

**功能**：人脸出现和手势时自动居中  
**实现状态**：✅ **已完成**（代码已存在，只需正确构建）

---

## 📋 核心发现

### 功能已经实现！

在代码审查后发现，**人脸和手势自动居中功能已经在现有代码中完整实现**：

**实现位置**：`headvoice/firmware/hv_hand_app.c` 第285-304行

**工作原理**：
1. **手部优先**：检测到手部时，云台跟踪手部中心
2. **人脸回退**：没有手部时，云台自动切换到跟踪人脸
3. **智能切换**：目标源变化时重置状态，避免跳变

**启用方法**：使用 `--vision face-hand` 构建参数

---

## 🚀 使用方法

### 方法1：使用批处理脚本（推荐）

**步骤1：构建固件**
```cmd
双击运行：build_face_hand_centering.bat
```
或在PowerShell中：
```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90
```

**步骤2：检查进度**
```cmd
双击运行：check_build_progress.bat
```
或手动检查：
```powershell
# 查看固件文件
Get-Item .work\headvoice\apps\build\vb701n.bin
```

**步骤3：烧录固件**
```cmd
双击运行：flash_face_hand_centering.bat
```
或手动烧录：
```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice flash --port COM3
```

### 方法2：PowerShell 一键命令

```powershell
# 设置Python路径
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

# 构建
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90

# 烧录（构建完成后）
& $py tools/build.py headvoice flash --port COM3

# 监控（烧录完成后）
& $py tools/build.py headvoice monitor --port COM3
```

---

## ✨ 功能说明

### 自动居中行为

**场景1：检测到手部**
1. 伸出手掌在摄像头前
2. 设备检测到手部（2-3秒内）
3. 云台自动转动，将手部移动到画面中心
4. 居中完成后停止

**场景2：只有人脸**
1. 不显示手部，只露出脸
2. 设备检测到人脸（2-3秒内）
3. 云台自动转动，将人脸移动到画面中心
4. 居中完成后停止

**场景3：手部和人脸切换**
1. 初始状态：只有人脸，云台跟踪人脸
2. 伸出手：云台**立即切换**到跟踪手部
3. 收回手：云台**自动切换回**跟踪人脸
4. 整个过程无需任何手动操作

### 串口输出示例

```json
# 启动时
GIMBAL ready pan=17 tilt=18 PWM=off limits=1475..1525us age<=400ms

# 检测到手部，开始跟踪
GIMBAL {"event":"auto_started","source":"hand"}
GIMBAL {"event":"observation","source":"hand","people":1,"face":true,"x":0.62,"y":0.45,...}

# 手部居中
GIMBAL {"event":"observation","source":"hand","people":1,"face":true,"x":0.50,"y":0.50,...}

# 手部消失，切换到人脸
GIMBAL {"event":"auto_started","source":"face"}
GIMBAL {"event":"observation","source":"face","people":1,"face":true,"x":0.48,"y":0.52,...}
```

---

## 📂 已创建的文件

### 便捷脚本
1. ✅ `build_face_hand_centering.bat` - 构建固件
2. ✅ `flash_face_hand_centering.bat` - 烧录固件
3. ✅ `check_build_progress.bat` - 检查构建进度

### 文档
1. ✅ `README_FACE_HAND_CENTERING.md` - 完整功能说明（技术细节）
2. ✅ `QUICK_START.md` - 快速开始指南（简化版）
3. ✅ `SUMMARY_IMPLEMENTATION.md` - 实现总结（代码分析）
4. ✅ `FINAL_DELIVERY.md` - 本文件（最终交付）

### 现有文档（参考）
- `docs/camera-auto-center.md` - 云台功能原理
- `docs/hand-centering-test-2026-10-31.md` - 历史测试记录
- `HANDOVER.md` - 之前的开发交接记录

---

## 🔧 技术要点

### 构建参数详解

```bash
python tools/build.py headvoice build \
  --stage 2              # 启用人脸姿态和手势检测
  --vision face-hand     # 关键：同时启用人脸和手势，自动启用HV_CENTERING
  --rotate-cw90          # 摄像头旋转90度适配硬件
```

### CMake配置（自动处理）

当使用 `--vision face-hand` 时：
```cmake
# headvoice/firmware/integration.cmake 第40-46行
if(HEADVOICE_VISION STREQUAL "face-hand")
  set(hv_centering 1)  # ✅ 自动启用
  target_sources(${COMPONENT_LIB} PRIVATE
    "${headvoice_root}/core/hv_gimbal_core.c"
    "${headvoice_root}/firmware/hv_face_gimbal.c")
endif()
```

### 关键代码段

**目标选择**（hv_hand_app.c 第285-304行）：
```c
#if HV_CENTERING
    HvGimbalTarget source = HV_GIMBAL_TARGET_HAND;
    unsigned targets = hand.count;
    bool targetValid = ret == ESP_OK && hand.valid;
    float targetX = (hand.normalized_box[0] + hand.normalized_box[2]) * 0.5f;
    float targetY = (hand.normalized_box[1] + hand.normalized_box[3]) * 0.5f;
    
    // 无手时回退到人脸
    if (ret == ESP_OK && hand.count == 0) {
      esp_err_t faceRet = hv_face_pose_analyze_rgb888(rgb, width, height, &face, &faceTarget);
      source = HV_GIMBAL_TARGET_FACE;
      targets = face.person_count;
      targetValid = faceRet == ESP_OK && faceTarget.valid;
      targetX = faceTarget.x;
      targetY = faceTarget.y;
    }
    
    // 统一控制
    hv_face_gimbal_observe_target(source, targets, targetValid, targetX, targetY, captured, now_ms());
#endif
```

---

## ⏱️ 构建和测试时间

| 步骤 | 预计时间 | 说明 |
|------|----------|------|
| 构建固件 | 10-15分钟 | 首次构建或完全重建 |
| 烧录固件 | 2-3分钟 | 包括擦除和写入 |
| 首次测试 | 5-10分钟 | 手部/人脸切换测试 |
| **总计** | **约20-30分钟** | 从构建到验证完成 |

---

## ✅ 验证清单

构建完成后，按以下步骤验证：

### 1. 固件文件检查
```powershell
Get-Item .work\headvoice\apps\build\vb701n.bin
# 应该显示文件大小约2-3MB，时间戳是最新的
```

### 2. 烧录成功检查
```
# 串口输出应包含：
GIMBAL ready pan=17 tilt=18 PWM=off limits=1475..1525us age<=400ms
```

### 3. 手部跟踪测试
- [ ] 伸出手掌，云台开始转动
- [ ] 串口显示 `"source":"hand"`
- [ ] 手部居中后云台停止
- [ ] 移动手，云台跟随

### 4. 人脸回退测试
- [ ] 收回手（不让摄像头看到）
- [ ] 云台切换到跟踪人脸
- [ ] 串口显示 `"source":"face"`
- [ ] 人脸居中后云台停止

### 5. 切换测试
- [ ] 反复伸手/收手
- [ ] 云台在手部和人脸之间正确切换
- [ ] 没有异常抖动或卡死

---

## 🐛 故障排除

### 构建问题

**问题1：构建时间过长或无输出**
```powershell
# 1. 检查进程
Get-Process | Where-Object {$_.ProcessName -like "*python*" -or $_.ProcessName -like "*ninja*"}

# 2. 如果卡住，终止并重试
Stop-Process -Name python -Force
Remove-Item -Recurse -Force .work\headvoice\apps\build

# 3. 重新构建
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90
```

**问题2：构建错误**
```powershell
# 查看完整错误日志
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90 2>&1 | Tee-Object -FilePath build-error.log
```

### 烧录问题

**问题：找不到端口**
```powershell
# 列出所有串口
$py = '.tools\espressif\python_env\idf5.4_py3.12_env\Scripts\python.exe'
& $py tools/capture_serial.py --list

# 使用正确的端口烧录
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice flash --port COMx  # 替换为实际端口
```

### 功能问题

**问题：云台不动**
1. 检查串口是否有 `GIMBAL ready` 消息
2. 检查舵机连接（GPIO17=pan, GPIO18=tilt）
3. 检查舵机供电（5V）
4. 查看串口是否有 `"source":"hand"` 或 `"source":"face"`

**问题：目标不切换**
1. 确保手部完全进入或离开视野
2. 检查光照（太暗影响检测）
3. 查看串口的手部和人脸检测消息
4. 确认 `hand.count` 是否正确变化

---

## 📖 文档阅读顺序

### 快速上手（5分钟）
1. 阅读本文件（FINAL_DELIVERY.md）
2. 运行 `build_face_hand_centering.bat`
3. 等待构建，然后运行 `flash_face_hand_centering.bat`

### 详细了解（20分钟）
1. `QUICK_START.md` - 快速开始指南
2. `README_FACE_HAND_CENTERING.md` - 完整功能说明
3. `SUMMARY_IMPLEMENTATION.md` - 技术实现总结

### 深入研究（1小时+）
1. `headvoice/firmware/hv_hand_app.c` - 主应用代码
2. `headvoice/firmware/hv_face_gimbal.c` - 云台控制器
3. `headvoice/core/hv_gimbal_core.c` - 云台算法
4. `docs/camera-auto-center.md` - 原理文档

---

## 🎯 成功标准

功能**完全成功**需要满足：

1. ✅ 固件构建无错误
2. ✅ 固件烧录成功，设备重启
3. ✅ 串口输出包含 `GIMBAL ready`
4. ✅ 伸出手后云台转动
5. ✅ 串口显示 `"source":"hand"`
6. ✅ 收回手后云台切换到人脸
7. ✅ 串口显示 `"source":"face"`
8. ✅ 目标居中后云台停止
9. ✅ 反复切换工作正常

---

## 📞 后续支持

如果遇到问题：

1. **查看串口输出**：所有诊断信息都在串口中
2. **检查文档**：上述文档涵盖了常见问题
3. **记录现象**：保存完整的串口日志
4. **检查硬件**：确认舵机和摄像头工作正常

---

## 🎓 总结

**功能已实现**：代码中已包含完整的人脸和手势自动居中功能

**关键参数**：`--vision face-hand`（自动启用 `HV_CENTERING=1`）

**工作原理**：手部优先，无手时回退到人脸，自动切换

**用户体验**：全自动，无需手动命令，智能切换

**下一步**：构建固件 → 烧录 → 测试验证

---

**交付日期**：2026-10-31  
**功能状态**：✅ 代码完成，等待构建和验证  
**文档状态**：✅ 完整，包含使用说明和技术细节
