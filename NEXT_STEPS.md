# 烧录完成后的测试步骤

## 1. 烧录状态
正在烧录当前的HeadVoice固件...

## 2. 烧录完成后的操作

### 立即测试云台功能：
```powershell
# 运行自动居中脚本
python tools/auto_center_on_boot.py --port COM3
```

如果脚本显示"当前固件不支持云台"，说明需要重新构建云台固件：

### 重新构建云台固件（如果需要）：
```powershell
# 1. 清理旧构建
rm -rf .work/headvoice/apps/build

# 2. 重新构建（带--gimbal参数）
python tools/build.py headvoice build --stage 2 --gimbal --rotate-cw90

# 3. 烧录
python tools/build.py headvoice flash --port COM3

# 4. 测试
python tools/auto_center_on_boot.py --port COM3
```

## 3. 预期结果

如果固件支持云台，你会看到：
- ✓ 检测到云台模块
- ✓ 云台功能已启用
- 设备启动后，舵机会根据人脸位置自动转动
- 控制台显示居中进度

## 4. 手动测试命令

如果自动脚本不工作，可以手动测试：

连接串口监控：
```powershell
python tools/build.py headvoice monitor --port COM3
```

在串口中输入命令：
```
hv_gimbal status      # 查看云台状态
hv_gimbal target      # 查看人脸目标
hv_gimbal arm pan     # 启动水平轴
hv_gimbal arm tilt    # 启动俯仰轴
hv_gimbal dir 1 1     # 设置方向
hv_gimbal start       # 开始自动居中
```

## 5. 注意事项

⚠️ 根据文档，之前测试时发现俯仰轴有机械问题
⚠️ 建议先用只读命令（status, target）测试
⚠️ 确认舵机机械安装正确后再执行完整居中

## 6. 如果一切正常

当固件正确且舵机工作时：
1. 设备启动后会自动检测人脸
2. 舵机会自动转动来居中人脸
3. 达到居中位置后停止
4. 连续3次确认居中后完成

---

**当前状态**: 等待烧录完成...
**下一步**: 运行 `python tools/auto_center_on_boot.py --port COM3`
