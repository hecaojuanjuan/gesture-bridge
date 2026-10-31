# 摄像头居中算法优化 - 快速参考

## 核心改进

### ✅ 问题1：识别要求太苛刻
**优化方案**：
- ✓ 允许 1-2 人（原来只允许恰好1人）
- ✓ 头部检测失败时，如果坐标合理（0.1-0.9）仍尝试居中
- ✓ 不立即停止，给更多等待机会

### ✅ 问题2：时间太久
**优化方案**：
- ✓ 等待时间：450ms → 200ms（**快56%**）
- ✓ 步长范围：10-35 → 12-45（**更大范围**）
- ✓ 步长系数：×100 → ×120（**更快响应**）
- ✓ 循环延迟：30ms → 20ms

## 预期效果

| 指标 | 优化前 | 优化后 | 改进 |
|------|--------|--------|------|
| **识别成功率** | ~60% | ~90% | +50% |
| **平均居中时间** | 9-12秒 | 3-5秒 | **-60%** |
| **侧脸识别** | 经常失败 | 大幅改善 | ✓ |
| **多人场景** | 不支持 | 支持1-2人 | ✓ |

## 快速部署

### Windows用户
```cmd
apply_gimbal_optimization.bat
cd .work\headvoice\apps
idf.py build flash
```

### Linux/Mac用户
```bash
bash apply_gimbal_optimization.sh
cd .work/headvoice/apps
idf.py build flash
```

### 手动部署
```bash
# 1. 备份
cp headvoice/core/hv_gimbal_core.c headvoice/core/hv_gimbal_core.c.backup

# 2. 应用优化
cp headvoice/core/hv_gimbal_core_optimized.c headvoice/core/hv_gimbal_core.c

# 3. 编译
cd .work/headvoice/apps
idf.py build flash
```

## 测试清单

测试完成后打勾：

### 基础功能
- [ ] 正面人像居中（< 5秒）
- [ ] 侧面人像居中（< 7秒）
- [ ] 远距离识别（2-3米）
- [ ] 近距离识别（0.5-1米）

### 边界场景
- [ ] 部分遮挡（戴口罩、手遮脸）
- [ ] 低头/抬头姿势
- [ ] 多人场景（2人）
- [ ] 光线变化（明亮/昏暗）

### 性能指标
- [ ] 首次识别时间：_____ 秒
- [ ] 完整居中时间：_____ 秒
- [ ] 识别失败次数：_____ 次/10次测试

## 参数微调

如果需要进一步调整，编辑 `hv_gimbal_core.c`：

```c
// 调整识别严格度（第45-56行）
// 更宽松：x >= 0.05f && x <= 0.95f
// 更严格：x >= 0.15f && x <= 0.85f

// 调整等待时间（第109行）
core->acceptAfterMs = nowMs + 200;  // 150-300ms

// 调整步长（第97-99行）
int step = (int)(fabsf(error[axis]) * 120);  // 100-150
if (step < 12) step = 12;  // 8-15
if (step > 45) step = 45;  // 35-50
```

## 回滚方法

如果优化效果不好：

```bash
# 恢复备份
cp headvoice/core/hv_gimbal_core.c.backup headvoice/core/hv_gimbal_core.c
# 或从backups目录恢复
cp backups/gimbal_optimization_*/hv_gimbal_core.c headvoice/core/

# 重新编译
cd .work/headvoice/apps
idf.py build flash
```

## 技术细节

详见 `headvoice/core/GIMBAL_OPTIMIZATION.md`

## 反馈

测试后请记录：
- 哪些场景改善明显？
- 哪些场景还有问题？
- 实际居中时间是多少？

这些信息有助于进一步优化！
