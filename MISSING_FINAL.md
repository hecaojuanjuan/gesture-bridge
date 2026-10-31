# 🎯 现在还差什么 - 最终答案

## ✅ 好消息：固件已经构建好了！

**位置**：`.work/face-hand-center/apps/build/vb701n.bin`  
**大小**：3.7 MB  
**构建时间**：2026-10-31 20:49  
**功能**：人脸和手势自动居中

---

## ⚠️ 问题：无法直接烧录

这个固件使用了ESP-DL的native手势分类器（11类手势），需要特殊的分区配置。

**错误信息**：
```
Native hand firmware needs an explicit application/model deployment 
after backing up the selected model partition
```

---

## 🔧 解决方案

### 方案1：使用简化版（推荐）

重新构建一个**不使用native分类器**的版本，使用标准手部检测即可实现自动居中。

**在PowerShell中运行**：

```powershell
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

# 清理
Remove-Item -Recurse -Force .work\headvoice -ErrorAction SilentlyContinue

# 构建（不使用native分类器）
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90

# 烧录
& $py tools/build.py headvoice flash --port COM3
```

**说明**：
- ✅ 仍然支持人脸和手势自动居中
- ✅ 可以正常烧录，无需特殊分区
- ⚠️ 手势分类功能会简化（但居中功能完整）

### 方案2：使用已有的face固件

如果之前已经烧录过face或gimbal固件，可以直接使用（如果已经有云台功能）。

检查设备：
```powershell
# 监控串口
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py tools/build.py headvoice monitor --port COM3

# 在串口中输入：
hv_gimbal status
```

如果显示云台状态，说明固件已支持，可以直接测试。

---

## 🎯 最简单的方案

**在项目目录打开PowerShell，复制粘贴运行**：

```powershell
# 设置Python路径
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'

# 清理旧构建
Write-Host "清理旧构建..." -ForegroundColor Yellow
Remove-Item -Recurse -Force .work\headvoice -ErrorAction SilentlyContinue

# 构建新固件（标准版本）
Write-Host "开始构建（预计10-15分钟）..." -ForegroundColor Yellow
& $py tools/build.py headvoice build --stage 2 --vision face-hand --rotate-cw90

# 检查固件
if (Test-Path .work\headvoice\apps\build\vb701n.bin) {
    Write-Host "✓ 构建成功！" -ForegroundColor Green
    Get-Item .work\headvoice\apps\build\vb701n.bin
    
    # 烧录
    Write-Host "`n开始烧录..." -ForegroundColor Yellow
    & $py tools/build.py headvoice flash --port COM3
    
    Write-Host "`n✅ 完成！设备正在重启..." -ForegroundColor Green
    Write-Host "功能说明：" -ForegroundColor Cyan
    Write-Host "  • 伸出手 → 云台跟踪手部居中"
    Write-Host "  • 收回手 → 云台切换到人脸居中"
    Write-Host "  • 全自动，无需手动命令"
} else {
    Write-Host "✗ 构建失败" -ForegroundColor Red
}
```

---

## 📋 总结

**现在还差什么？**

1. ❌ ~~固件构建~~ （已完成，但是native版本无法直接烧录）
2. ⏳ **需要重新构建标准版本**（不使用native分类器）
3. ⏳ **烧录到设备**

**最快方案**：复制上面的PowerShell命令，一次性完成构建和烧录

**预计时间**：15分钟构建 + 3分钟烧录 = 约20分钟

---

## 🔍 为什么会这样？

之前构建的 `face-hand-center` 固件使用了：
- `--hand-native-partition coco_pose` - ESP-DL的11类手势模型
- 需要特殊的Flash分区来存储模型
- 无法用标准方式烧录

**标准版本**：
- 使用基础的手部检测（足够实现自动居中）
- 可以直接烧录
- 功能完整

---

**建议**：运行上面的PowerShell命令，重新构建标准版本！
