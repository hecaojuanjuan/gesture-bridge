# Gesture Bridge 用户操作图 v2

- 工具：内置 `image_gen.imagegen`，编辑上一版操作图。
- 输出：`gesture-bridge-user-guide-v2.png`。
- 用户要求：仅 A/B 两栏，去掉网页调试、串口与维护步骤；04 改为默认灯板反馈；B 保留小程序联网流程并明确在线后进入控制面板。
- 固件依据：`hv_light_init()` 默认模式为 `HV_LIGHT_STATUS`；`feedback_light_locked()` 在新鲜、已确认目标时输出张掌绿色、V 字蓝色，其余熄灭。没有红色失败灯。保持灰色“未亮灯”提示，不能写成硬件故障或单独的失败事件。
- 验证：已目视检查最终图片，只有 A/B 两栏；04 为三种灯板反馈；联网分支为二选一并进入手机控制面板；保留 V 字调试说明。未修改固件或新增实机灯效验收。

## 编辑提示词

Edit the supplied Gesture Bridge infographic into a much simpler END USER instruction card. Preserve the existing cream, green and blue palette, clear Chinese typography, rounded cards, and friendly small flat icons. Redesign the layout to have ONLY a header and TWO columns A and B. No separate full-width power card, no reset section, no shutdown section, no developer limitations panel below. Fit a portrait canvas about 4:5, with comfortably readable text and generous spacing. Remove ALL references to computer webpages, USB panels, classifiers, counters, diagnostic streams, serial terminals, firmware fields, code commands, applying light settings or technical debugging. Do not show a laptop or board pin labels. User flow is simply power on and perform gestures, or open the phone mini-program, connect Wi-Fi and enter the control panel.

Exact title:
Gesture Bridge｜使用指南
Exact main headline:
上电做手势，看灯知结果
Subtitle:
打开小程序联网，即可进入控制面板

Left column heading:
A  开机与手势操作

Four cards inside A, in order:
01  接通电源
接上 USB 电源，等待启动
手势识别自动开启，无需其他操作

02  完整手掌入镜
掌心朝向镜头，掌根和指尖都要入镜

03  保持手势约 3 秒
张开手掌或摆出 V 字
完成后移出画面约 2 秒，再做下一次

04  看灯板确认结果
上电默认显示手势状态
绿灯｜张掌识别成功
蓝灯｜V 字识别成功
未亮灯｜尚未确认，调整后重试

For the three result rows, add a vivid green dot, a vivid blue dot, and a hollow gray dot. The labels must accompany the colors. Do NOT add a red failure light. Gray represents unlit, not a gray light emitted by hardware. In a compact note INSIDE the A column, use:
手移出画面后，灯板也可能熄灭。
当前 V 字仍在调试；自动居中暂未启用。

Right column heading:
B  小程序联网
Above the choices:
联网方式：二选一

Two distinct alternative cards with NO sequential arrow between them; use a clear 或 label. Both must converge into the same final device-online/control-panel card. The choices may be vertically stacked with a visible 或 divider if this allows larger Chinese text, with separate connector lines to the final card.

First choice:
已经配过网
开启原路由器或热点
设备自动连接，无需重复配网

Second choice:
首次配网
打开手机蓝牙
进入配套微信小程序
点“添加设备”并允许权限
选择对应产品与 2.4 GHz Wi-Fi
输入密码，完成绑定

Final converged card, prominent:
设备在线，打开面板
小程序显示“在线”后
点击设备，进入控制面板

Compact notes INSIDE the B column:
仅支持 2.4 GHz Wi-Fi。
要对话时说“你好，小鹰”，听到提示再提问。

Constraints: Only header plus A/B columns. The 04 card must use LIGHT COLOR only to explain confirmation, no webpage or counter. The B path must end in the phone control panel. Keep the correct product name Gesture Bridge. All Chinese text must be spelled correctly and readable. The first-time pairing card must start 打开手机蓝牙, no duplicated words. Do not promise V gesture accuracy; retain the small V字仍在调试 note. No red failure LED, no pseudo button, no QR code, no developer jargon, no footer beyond these two columns. Generate the finished simplified complete image.
