# 开机与配网操作图生成记录

- 工具：内置 `image_gen.imagegen`。
- 用途：配合 `docs/device-user-guide.md` 的独立中文使用图。
- 版本：2026-11-01；依据最近一次已确认部署的 native 张掌／V 字手势固件。
- 本图不标示未确认的实体按键位置，不使用旧网络灯色图例。
- 最终图片：`device-startup-guide-20261101.png`。已目视核对名称、联网分支、配网命令、关机及版本限制。

## 基础生成提示词

Use case: infographic-diagram.
Asset type: A finished, highly legible Simplified Chinese portrait quick-start infographic to save and share, approximately 1800 x 2700 pixels, 2:3 portrait. Opaque background.
Primary request: Explain that the Gesture Bridge device automatically begins local gesture recognition after power-on and successful initialization, while Wi-Fi provisioning is a separate optional branch for cloud voice and phone control. The currently deployed firmware does NOT drive the servos or auto-center. Make a polished instruction sheet, not an advertising poster.
Style: Calm cream background, dark forest-green headings, muted sage recognition lane, blue networking lane, restrained amber limitation box. Crisp modern Chinese sans-serif type, very large headline, generous spacing, thin arrows, rounded rectangular cards. Small flat icons for USB cable, open palm, phone Bluetooth, router, speech, unplugging. No speculative realistic hardware, no annotated board pins, no decorative characters or photos. Typography and flow are the primary visual. All text must be exact, complete, readable, correctly spelled Chinese, with no invented text. Do not use color alone for meaning. Avoid tiny footnotes.
Composition: Full-width headline and power-on card, then two independent parallel lanes with separate arrows from the power-on card. Gesture recognition must never appear downstream of Wi-Fi. Below the lanes, full-width change-network instructions, shutdown strip, and a compact current-version limitations box. Every section is readable at full size. Use precisely the following text, preserving commands and punctuation. Layout the short lines across cards as appropriate; no quotation marks around whole text blocks.

Top title:
Gesture Bridge｜开机与配网指南
Main headline, largest type:
上电后，自动启动识别
Supporting line:
正常初始化后运行｜不用输入“开机”或 start
Small version line:
适用：已部署的张掌／V 字手势版 · 2026-11-01

Full-width power card:
01  接通电源
USB Type-C 接底板，另一端接电脑供电
开机音只表示音频有响应，不代表所有功能就绪

Left lane heading:
A  手势识别｜无需联网
Left lane cards, top to bottom:
02  完整手掌入镜
掌心朝向镜头，掌根和指尖都要入镜
03  张掌保持约 3 秒
然后完全移出画面约 2 秒，再做下一次
04  确认识别结果
电脑 USB 面板：分类器已加载，观测持续更新
查看张掌累计次数是否增加
看灯效：选择“状态指示”→“应用到灯板”
Lane note:
关闭网页不停止识别；预览按钮只控制画面显示

Right lane heading:
B  语音与手机控制｜需要联网
Right lane cards, top to bottom:
已配过网
开启原路由器或热点 → 等待设备在线
首次配网（没有保存 Wi-Fi）
手机开启蓝牙 → 配套微信小程序“添加设备”
允许蓝牙等权限 → 选择对应产品
选择 2.4 GHz Wi-Fi → 输入密码 → 完成绑定
确认在线，再说话
小程序显示“在线”后，说“你好，小鹰”
听到唤醒提示，再提问
Lane note:
5 GHz-only 网络不可用；日常开机无需重复配网

Full-width network reset card:
换了 Wi-Fi？需要重新配网
先断开网页 USB，用串口终端连接开发板：115200 / 8N1
确定换网后输入：hv_provision restart
清除已保存的 Wi-Fi、配网环境和本地绑定标记后重启
再按“首次配网”操作；此命令不是普通开机命令

Full-width shutdown strip:
关机：断开供电
只有 USB 供电时拔掉 USB；“熄灯”和网页“断开”都不等于关机

Bottom limitation box, prominent and legible:
当前版本请记住
自动居中未启用：摄像头不会自动转动
张掌已有成功记录；V 字仍未通过实测
当前手势输出为计数和状态灯，未接通手势短句播报

Constraints: No claims of guaranteed V gesture accuracy, no green/blue/yellow network status LEDs, no BLE button position, no promise that a voice wake word starts vision, no gimbal motion arrows. Do not omit the limitations. Do not add a QR code, URL, watermark, platform login, or fake screen UI. Keep the command hv_provision restart exactly with the underscore and single space. Render a final complete infographic image.

## 流程校正提示词

Edit the supplied Chinese infographic with exactly two changes. First, rename the product in the top title to the exact text “Gesture Bridge｜开机与配网指南”. Remove the old Chinese brand name 颔语 entirely; the correct product name is Gesture Bridge. Second, correct the logical layout of the right blue networking lane: “已配过网” and “首次配网（没有保存 Wi-Fi）” are mutually exclusive alternative paths, NOT sequential steps. Remove the arrow from the already-configured card to the first-time setup card. Add a compact clear label “联网方式：二选一”. Show these two alternatives as separate equal-level cards (they may be vertically stacked with a prominent “或” divider and no arrow between them). Give each alternative its own arrow that merges into the final “确认在线，再说话” card. There must be no path from already-configured Wi-Fi to first-time provisioning. You may slightly reflow and rebalance this right lane to fit while preserving legibility and all original right-lane text. Preserve every other text fact, typography, colors, left recognition lane, power card, bottom reset command, shutdown strip and limitations. Keep the two main lanes independent. All Chinese text and the exact command hv_provision restart must remain correct. Generate the corrected full infographic, with no cropping or missing footer text.

## 最终文字校正提示词

Edit this Gesture Bridge instruction infographic. Re-typeset the entire BODY TEXT of the blue right-column card headed 首次配网（没有保存 Wi-Fi）. The current first body line contains a duplicated Chinese word and must be completely removed, not retained. Replace all body text under that heading with these SIX clearly separated lines, exact Chinese text:

```text
打开手机蓝牙
进入配套微信小程序
点“添加设备”并授权
选择对应产品
选择 2.4 GHz Wi-Fi
输入密码，完成绑定
```

These six lines must fit within the card, readable, dark text, left aligned. In particular the new FIRST line is 打开手机蓝牙 (six characters), no repetition of 开启 anywhere. Keep card title, phone icon, two-option networking structure, all arrows, and every other part of the entire infographic unchanged. Do not crop the image. Preserve the Gesture Bridge title and exact command hv_provision restart in the lower section. Output the corrected whole infographic.
