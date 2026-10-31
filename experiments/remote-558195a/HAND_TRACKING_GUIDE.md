# 手掌识别居中功能 - 使用指南

## 功能概述

在原有人脸居中的基础上，新增了**手掌自动居中**功能，支持三种模式：

1. **人脸模式** (`face`) - 仅跟踪人脸
2. **手掌模式** (`hand`) - 仅跟踪手掌
3. **自动模式** (`auto`) - 优先人脸，无人脸时自动切换到手掌

## 核心特性

### ✅ 已实现
- ✓ 基于肤色的手掌检测算法
- ✓ 三种跟踪模式切换
- ✓ 手掌置信度评估
- ✓ 自动目标选择（人脸/手掌）
- ✓ 更快的响应速度（手掌模式 180ms vs 人脸模式 200ms）
- ✓ 连续丢失容错（最多3帧）

### 📊 性能参数对比

| 特性 | 人脸模式 | 手掌模式 |
|------|----------|----------|
| 等待时间 | 200ms | 180ms |
| 步长范围 | 12-45 | 15-50 |
| 居中阈值 | 0.06 | 0.08 (更宽松) |
| 最小置信度 | 1.0 | 0.3 |

## 使用方法

### 1. 编译代码

需要确保以下文件已添加到编译系统：

```
headvoice/core/hv_gimbal_core.c
headvoice/core/hv_gimbal_core.h
headvoice/core/hv_hand_detector.c
headvoice/core/hv_hand_detector.h
headvoice/firmware/hv_gimbal_app.c
```

### 2. 命令行控制

通过串口发送以下命令：

```bash
# 查看当前状态
hv_gimbal status

# 设置目标模式
hv_gimbal mode face   # 人脸模式
hv_gimbal mode hand   # 手掌模式  
hv_gimbal mode auto   # 自动模式（默认）

# 启动居中（先arm两个轴并设置方向）
hv_gimbal arm pan
hv_gimbal arm tilt
hv_gimbal dir 1 1
hv_gimbal start

# 停止
hv_gimbal stop
```

### 3. 状态输出

系统会输出JSON格式的状态信息：

```json
{
  "event": "observation",
  "people": 1,
  "face": true,
  "face_x": 0.5123,
  "face_y": 0.4876,
  "hand": true,
  "hand_x": 0.3245,
  "hand_y": 0.6543,
  "hand_conf": 0.756,
  "result": 1,
  "tracking": "face"
}
```

## 测试场景

### 场景1：人脸居中（默认）
```bash
hv_gimbal mode auto
hv_gimbal start
# 站在摄像头前，系统会自动跟踪你的脸
```

### 场景2：手掌居中
```bash
hv_gimbal mode hand
hv_gimbal start
# 伸出手掌，系统会跟踪手掌中心
```

### 场景3：自动切换
```bash
hv_gimbal mode auto
hv_gimbal start
# 先用脸测试，然后遮住脸，伸出手掌
# 系统会自动从人脸切换到手掌跟踪
```

### 场景4：手势演示准备
```bash
hv_gimbal mode hand
hv_gimbal start
# 适合手势识别前的定位
# 手掌自动居中后，方便后续手势检测
```

## 检测原理

### 手掌检测方法

**方法1：基于手腕关键点（预留）**
- 利用YOLO11姿态估计的手腕关键点
- 在手腕周围搜索肤色区域
- 计算手掌中心

**方法2：基于肤色检测（当前实现）**
- YCbCr色彩空间肤色检测
- 分块扫描（16x16块）
- 选择肤色像素最多的区域

### 肤色检测参数

```c
Y:  80-255
Cb: 77-127
Cr: 133-173
```

这些参数适用于多种肤色，可根据实际情况调整。

## 优化建议

### 提高手掌检测准确度

1. **光照条件**：确保良好照明，避免强逆光
2. **背景选择**：避免与肤色相似的背景
3. **手掌姿势**：张开手掌效果最好
4. **距离范围**：0.5-2米为最佳检测距离

### 调整检测参数

编辑 `hv_hand_detector.c`：

```c
// 调整肤色范围（更宽松/更严格）
#define SKIN_CB_MIN 70    // 降低提高检出率
#define SKIN_CR_MIN 130

// 调整最小像素阈值
int min_pixels = 30;  // 降低提高灵敏度

// 调整置信度计算
out->confidence = fminf(1.0f, skin_pixels / 150.0f);
```

## 已知限制

### 当前版本
1. ⚠️ 手掌检测基于颜色，可能受背景干扰
2. ⚠️ 暂未使用YOLO手腕关键点（预留接口）
3. ⚠️ 不支持手势分类（仅检测位置）

### 未来改进
- [ ] 集成手腕关键点定位
- [ ] 添加手势形状识别
- [ ] 支持多手检测
- [ ] 优化肤色检测算法

## 与手势识别集成

手掌居中功能为手势识别提供基础：

```
手掌居中 (本功能) 
    ↓
手掌定位完成
    ↓
手势识别 (下一步)
    ↓
手势命令执行
```

### 建议工作流程

1. **启动手掌跟踪**
   ```bash
   hv_gimbal mode hand
   hv_gimbal start
   ```

2. **等待居中完成**
   - 观察串口输出 `"tracking": "hand"`
   - `result: 2` 表示居中成功

3. **开始手势识别**
   - 手掌已在画面中心
   - 此时进行手势检测准确度最高

## 调试技巧

### 查看检测日志

```bash
# 观察实时检测状态
hv_gimbal probe

# 每帧都会输出：
# - face: 是否检测到人脸
# - hand: 是否检测到手掌
# - hand_conf: 手掌置信度
# - tracking: 当前跟踪目标
```

### 常见问题

**Q: 手掌检测不稳定？**
A: 
- 检查光照是否充足
- 确保背景不是肤色
- 尝试张开手掌
- 降低 `min_pixels` 阈值

**Q: 从人脸切换到手掌太慢？**
A:
- 使用 `mode hand` 直接切换到手掌模式
- 确保人脸完全离开画面

**Q: 手掌居中不够精确？**
A:
- 手掌模式使用较宽松的阈值(0.08)
- 可在 `hv_gimbal_core.c` 中调整

## 文件清单

### 核心算法
- `headvoice/core/hv_gimbal_core.c` - 居中控制核心（已优化+手掌支持）
- `headvoice/core/hv_gimbal_core.h` - 核心API定义
- `headvoice/core/hv_hand_detector.c` - 手掌检测算法
- `headvoice/core/hv_hand_detector.h` - 手掌检测API

### 应用层
- `headvoice/firmware/hv_gimbal_app.c` - 应用集成和命令行接口

### 文档
- `HAND_TRACKING_GUIDE.md` - 本文档
- `GIMBAL_QUICK_GUIDE.md` - 快速参考
- `GIMBAL_OPTIMIZATION.md` - 优化说明

## 下一步工作

完成手掌居中后，可以开始：

1. **手势分类**：识别不同手势（OK、点赞等）
2. **手势命令映射**：手势→控制指令
3. **动态跟踪**：连续跟踪手势运动轨迹
4. **多手支持**：同时识别左右手

这些功能的基础（手掌定位）已经就绪！
