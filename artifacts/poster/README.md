# Gesture Bridge

当前海报：v7，宽 80 cm × 高 180 cm，比例 4:9。

## 设计概念

按用户最新的手势识别方向重新构图，仅突出手势到语音的转换。
主标题为“把手势，说出来。”，手部关节点连接音频波形与“我想喝水。”
的表达示例。采用米白、炭黑和朱红三色，保留充足留白。
底部只保留“手势识别 → 确认表达 → 语音播报”这一条流程。

## 文件

- `gesture-bridge-poster-v7-80x180cm.pdf`：实际尺寸的矢量 PDF。
- `gesture-bridge-poster-v7.svg`：可编辑矢量源文件。
- `gesture-bridge-poster-v7.html`：浏览器预览，内嵌 SVG，支持原尺寸打印。
- `gesture-bridge-poster-v7-preview.png`：由最终 PDF 渲染的预览。
- `design_gesture_bridge_v7.py`：当前版面的生成代码。
- `gesture-bridge-poster-v7-check.json`：尺寸、关键点和文字边界检查记录。

历史版本保留，当前交付以 v7 为准。所有当前海报标题、元数据和预览名称
统一使用 Gesture Bridge；固件内部已有的构建目标和接口名称保持兼容。

## 生成

沿用 Python、ReportLab、SVG 与系统字体，未引入新的项目依赖。
脚本复用 v4 中的基础矢量绘图方法和 v5 的手部关键点。

```powershell
$posterPython = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $posterPython artifacts/poster/design_gesture_bridge_v7.py
```

字体使用 Arial Bold 与 Microsoft YaHei。
PDF 嵌入所用字体；SVG 保留可编辑文字，按系统字体渲染。

## 关键点和能力范围

手部骨架采用手腕与五指逐节连接的 21 点布局，编号与关节位置对应。
参考：[MediaPipe 官方手部关键点说明](https://developers.google.com/edge/mediapipe/solutions/vision/hand_landmarker)。

手形及关键点均为手工定义的矢量图，不是识别截图，不声明识别结果或性能。
手形只是手势输入示意，不表示开放手掌在所有系统中都对应“我想喝水”。
声波图形取自项目已有的该短句 PCM 音频，并压缩成显示包络。
本次仅更新海报，按用户提供的当前产品方向呈现手势识别，不修改识别固件。

## 检查

生成时检查关键点总数、五指链路完整性和文字是否超出页面。
最终通过 PDF 渲染核查字形、色块边缘与对齐；并检查 PDF 页面尺寸、
字体嵌入、SVG 文档结构和浏览器显示比例。
