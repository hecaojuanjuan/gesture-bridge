# 舵机零位修复说明

## 问题
俯仰轴在 1500µs 启用时会大幅低头

## 原因
舵机零位被设置为 1450µs，而不是标准的 1500µs。当发送 1500µs 信号时，相对于零位偏高了 50µs，导致低头。

## 修复内容
**文件：** `.work/baseline/apps/main/peripheral/bsp_servo.h`

**第 25 行修改：**
```c
// 修改前
#define BSP_SERVO_ZERO_PULSE_US     1450

// 修改后
#define BSP_SERVO_ZERO_PULSE_US     1500
```

**状态：** ✅ 代码已修改完成

## 构建和烧录步骤

由于 Git Bash (MSys/Mingw) 环境与 ESP-IDF 工具链存在兼容性问题，请在 **Windows PowerShell 或 CMD** 中执行：

### 方法一：使用提供的批处理脚本（推荐）

1. 打开 **Windows PowerShell** 或 **CMD**（不是 Git Bash）
2. 切换到项目目录：
   ```cmd
   cd C:\Users\jiawa\Desktop\gesture-bridge
   ```
3. 运行构建脚本：
   ```cmd
   rebuild_baseline_servo_fix_auto.bat
   ```

### 方法二：手动执行命令

在 **Windows PowerShell** 中执行：

```powershell
cd C:\Users\jiawa\Desktop\gesture-bridge

# 清理旧构建
Remove-Item -Recurse -Force .work\baseline\apps\build -ErrorAction SilentlyContinue

# 构建固件
& 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/build.py baseline build

# 检查固件是否生成
Get-Item .work\baseline\apps\build\vb701n.bin

# 烧录到设备
& 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe' tools/build.py baseline flash --port COM3
```

### 方法三：使用 Windows 文件管理器

直接双击 `rebuild_baseline_servo_fix_auto.bat` 文件

## 预计时间
- 构建：12-15 分钟
- 烧录：2-3 分钟
- **总计：约 15-18 分钟**

## 验证
烧录完成后，发送 1500µs 的 PWM 信号，舵机应该保持在中位（水平），而不是低头。

## 技术细节
- 舵机范围：500µs (0°) ~ 2400µs (180°)
- 标准中位：1500µs (90°)
- 之前零位：1450µs（偏低 50µs）
- 修复后零位：1500µs（标准中位）
