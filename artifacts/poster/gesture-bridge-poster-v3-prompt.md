# Gesture Bridge 海报草案 v3

- 日期：2026-10-31
- 方法：内置 image_gen 工具，基于 v2 修改
- 调整重点：简化人物，将设备和姿态到语言的转换过程作为主视觉
- 用途：视觉构图讨论，尚未制作印刷交付文件
- 比例：4:9，对应宽 80 × 高 180 cm
- 图片：`gesture-bridge-poster-v3.png`

## 实际生成提示词

```text
Use case: style-transfer + infographic-diagram.
Edit the supplied poster into a radically simpler, process-led graphic design. The user's specific feedback is that the painterly people and decorative illustration look too AI-generated. Eliminate that illustration style completely. Create one flat, front-on poster artwork, no surrounding mockup. Exact portrait width:height 4:9, for an 80 cm wide × 180 cm tall display board.

PRESERVE THESE INVARIANTS:
- Exact brand, lower case: "gesture bridge".
- The compositional route: muted upper-left head/posture input -> a large central DEVICE -> larger colourful lower-right LANGUAGE OUTPUT.
- A hardware aid converts deliberate head movements into selected sentences and speaks only after a fresh user confirmation.
- The device is a low rectangular desktop enclosure, front speaker holes, status dot, and a small exposed camera lens on a simple gimbal.
- No claim that this restores a person's biological speech.

CHANGE THE ENTIRE VISUAL LANGUAGE:
Clean contemporary Swiss graphic design / museum exhibition infographic / cut-paper shapes. Crisp solid vector-style silhouettes, consistent simple outlines, flat ink fills, carefully typeset Chinese and English, deliberate negative space. No painterly rendering, no paper grain, no textures, no gradients, no fake light beams, no glows, no shadows, no photoreal faces, no hair details, no fabric, no kitchen, no lifestyle scene, no 3D glossy device. Use simple neutral oval head-and-shoulder symbols in place of people, with tiny eye/nose landmark dots and short head tilt arcs. No detailed human figures anywhere. The visual story must be about a machine translating head posture into words.

LAYOUT AND HIERARCHY:
Top approximately 15%: brand "gesture bridge" in large black modern sans-serif, two lines allowed. Smaller exact Chinese slogan "让动作，拥有声音". A tiny supporting descriptor "头部姿态辅助沟通设备".
Upper-left input zone approximately y=18%–36%, 55% width: large pale grey organic field, three simple head outlines: neutral, left tilt, right tilt. The tilted heads are naturally connected to a neck and shoulders. Each head is just a few geometric strokes, with 3–5 facial landmark dots, no facial expressions. Labels, exact: "中立", "动作 A", "动作 B". A clear heading "01 采集头部姿态". Make camera-based posture recognition legible without showing a realistic person.
From input, carry ONE clear thick path down and right through the poster, with discrete arrowheads. Do not create disconnected pill-button rows. The path turns A/A into code AA at the device.
Centre approximately y=36%–60%: the central device is the largest single object, occupying approximately half the poster's width. Draw it in simple flat oblique/isometric schematic style, not a beauty render. Cream-grey enclosure, dark geometric camera on exposed bracket/gimbal, clear lens, front speaker grille, tiny status dot, minimal 2–3 solid flat colours. Nearby label "设备概念示意".
Near the input-to-device path place the exact large coding example "A + A → AA" and heading "02 识别动作组合".
After the device, a clean arrow points to the candidate phrase inside a restrained outline speech box with exact heading "03 选择表达", and exact phrase "我想喝水。". This is a CANDIDATE stage, not yet spoken.
Next on the SAME connected path, show a small new-head-movement/check symbol and exact heading "04 本人再次确认". Make it obvious confirmation is a separate NEW action after the combination.
Lower-right, approximately y=63%–94%: make this the largest area, with broad intersecting flat cobalt blue, warm yellow and vermilion speech-bubble shapes. Brightness here comes from solid colour and space, not beams or decorative swirls. Use dark near-black lettering on yellow, white on cobalt. Exact heading "05 设备语音播报". The main large output bubble repeats the exact phrase "我想喝水。". Add two smaller independent sample-expression bubbles, exact: "我想自己来。" and "请过来协助我。". Clearly group smaller samples with the understated label "更多自定义表达". No conversational crowd or realistic people. Small abstract speaker bars can extend from the device toward output bubbles, but no huge random decorative waveform. The vivid WORDS are the main protagonist of the lower half.
Bottom small aligned text: "自定义表达 · 自主选句 · 个体适应"
And one modest status line: "完整产品设计 · 部分功能开发验证中"

ART DIRECTION:
Strong editorial layout, substantial clean light/off-white negative space, upper-left neutral greys and near-black ink, central low-colour schematic, lower-right three carefully placed bright colours. Honour the diagonal flow while making the sequential five-step story effortless to follow. Do not cover the entire upper half in dark navy. No cards, no web UI dashboard, no rounded app buttons, no stock icon collage, no glowing computer vision mesh. Render precise type with comfortable print margins, very few words outside the exact specified labels, no invented metrics, QR codes, extra logos or watermark.
The resulting poster should feel like a human designer built a clear, bold, flat information graphic, with the DEVICE and the conversion PROCESS dominant.
```
