# Gesture Bridge

当前海报：v9，宽 80 cm × 高 180 cm，比例 4:9。

## 设计概念

完整采用用户最新上传的炭灰、暖黄及三个气泡的模板。
原始 JPEG 原样嵌入，标题、拳头、背景、气泡及声波装饰不重绘、不改动。

- 中间黄色区域：项目已有设备外观的矢量示意图。
- 最大橙色气泡：手势组合、候选句、本人确认、原句播报的四步流程。
- 浅黄色气泡：家人协助定义手势与表达内容，保留使用者确认。
- 蓝色气泡：“无需精细操作，降低表达门槛”。
- 气泡下方：“让表达被听见”。

标题区域及左上手部区域禁止增加内容；新增设备和文字在授权区域内排版。

## 文件

- `gesture-bridge-poster-v9-80x180cm.pdf`：实际尺寸的排版 PDF。
- `gesture-bridge-poster-v9.svg`：嵌入原始底图，新增图形与文字可编辑。
- `gesture-bridge-poster-v9-background.jpg`：用户原始 JPEG 的完整副本。
- `gesture-bridge-poster-v9.html`：浏览器预览，内嵌 SVG，支持原尺寸打印。
- `gesture-bridge-poster-v9-preview.png`：由最终 PDF 渲染的预览。
- `gesture-bridge-device-concept.svg`：可单独使用或替换的设备示意图。
- `design_gesture_bridge_v9.py`：当前版面的生成代码。
- `gesture-bridge-poster-v9-check.json`：底图哈希、保护区域和文字边界记录。

历史版本保留，当前交付以 v9 为准。项目与导出元数据使用 Gesture Bridge；
参考图原有标题的字形、大小写和位置完全保留。

## 生成

沿用 Python、ReportLab、SVG 与系统字体，未引入新的项目依赖。
脚本复用 v4 中的基础矢量绘图方法，将底图作为未修改的图片资源引用。

```powershell
$posterPython = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $posterPython artifacts/poster/design_gesture_bridge_v9.py
```

新增字体使用 KaiTi 与 Microsoft YaHei。PDF 嵌入字体，SVG 保留可编辑文字。
底图为 800×1800 像素的 JPEG，整张海报并非纯矢量；导出尺寸不会增加
底图细节。正式 80×180 cm 大幅印刷时，应提供相同布局的高清底稿。

## 能力范围

原图手形不修改，不表示该手形在所有系统中都对应“我想喝水”。
设备图采用已有外观设计的矢量示意，不是设备实拍照片。
本次仅更新海报，按用户提供的当前产品方向呈现手势识别，不修改识别固件。

## 检查

生成时检查新增文字不进入保护区域，且文字不超出页面。
检查嵌入 JPEG 与用户原图的 SHA-256 一致。通过 PDF 和浏览器渲染核查
字形、对齐、尺寸、字体嵌入及原图保留情况。
