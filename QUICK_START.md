# 人脸和手势自动居中 - 快速开始

> 日常开关机、配网和打开面板，请看[独立使用说明](docs/device-user-guide.md)。下文为早期自动居中构建记录，不代表当前构建进度或设备状态，也不是日常开机步骤。

## 当前状态：正在构建固件

构建命令已启动，预计需要 10-15 分钟。

## 1️⃣ 等待构建完成

### 检查构建进度：
```cmd
check_build_progress.bat
```

或手动检查：
```powershell
# 查看构建日志
Get-Content .local\build-face-hand.log -Tail 30

# 检查固件文件是否生成
Get-Item .work\headvoice\apps\build\vb701n.bin
```

### 构建完成标志：
- ✅ 日志中出现 "Project build complete"
- ✅ 固件文件存在：`.work\headvoice\apps\build\vb701n.bin`
- ✅ 文件大小约 2-3 MB

## 2️⃣ 烧录固件

构建完成后，运行：
```cmd
flash_face_hand_centering.bat
```

**预期过程**：
1. 检查固件文件
2. 连接设备（COM3）
3. 擦除并写入固件（约2-3分钟）
4. 自动重启设备

## 3️⃣ 测试功能

设备重启后，自动居中功能会立即生效：

### 测试步骤：

**步骤1：测试手部跟踪**
1. 站在摄像头前
2. 伸出手掌
3. **观察**：云台应该转动，跟踪你的手部并尝试居中
4. 左右移动手 → 云台应跟随

**步骤2：测试人脸回退**
1. 收回手（不让摄像头看到手）
2. **观察**：云台应该切换到跟踪你的脸部
3. 左右移动头部 → 云台应跟随

**步骤3：测试切换**
1. 再次伸出手
2. **观察**：云台应立即切换回跟踪手部
3. 反复伸手/收手，确认云台能正确切换

### 查看详细日志：

```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice monitor --port COM3
```

在串口输出中查找：
- `GIMBAL {"event":"auto_started","source":"hand"}` - 开始跟踪手部
- `GIMBAL {"event":"auto_started","source":"face"}` - 切换到跟踪人脸
- `GIMBAL {"event":"observation",...}` - 云台运动状态

## 4️⃣ 预期行为

### ✅ 正常工作时：
- 伸出手 → 云台2-3秒内开始转动，跟踪手部
- 手部居中后 → 云台停止
- 收回手 → 云台切换到跟踪人脸
- 人脸居中后 → 云台停止
- 目标移动 → 云台自动调整

### ⚠️ 可能的问题：

**云台不动**：
- 检查舵机连接（GPIO17=pan, GPIO18=tilt）
- 检查舵机供电（5V）
- 查看串口是否有 `GIMBAL` 消息

**目标不切换**：
- 确保手部完全进入或离开视野
- 检查光照条件（太暗会影响检测）
- 观察串口的 `"source"` 字段

**舵机抖动**：
- 机械中位未校准（1500µs应对应正前方）
- 供电不稳定
- 检测不稳定（光照、距离）

## 📋 完整文档

详细信息请查看：
- **功能说明**：`README_FACE_HAND_CENTERING.md`
- **云台原理**：`docs/camera-auto-center.md`
- **开发记录**：`HANDOVER.md`

## 🔧 故障排除

### 构建失败
```cmd
# 清理后重新构建
rmdir /s /q .work\headvoice\apps\build
build_face_hand_centering.bat
```

### 烧录失败
1. 检查设备连接（设备管理器中确认COM端口）
2. 关闭其他串口程序
3. 尝试更换USB端口或线缆

### 云台不响应
```powershell
# 测试串口连接
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice monitor --port COM3

# 查看设备启动信息
# 应该看到 "GIMBAL ready pan=17 tilt=18 PWM=off limits=1475..1525us age<=400ms"
```

---

## ⏱️ 时间估算

| 步骤 | 预计时间 |
|------|----------|
| 构建固件 | 10-15 分钟 |
| 烧录固件 | 2-3 分钟 |
| 首次测试 | 5-10 分钟 |
| **总计** | **约 20-30 分钟** |

---

**当前进度**：🔄 正在构建固件...  
**下一步**：运行 `check_build_progress.bat` 检查进度
