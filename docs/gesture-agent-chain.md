# 手势 → prompt → agent → 语音回应

2026-11-01：已实现固件事件接入、固定词典到 prompt、后台请求、服务端转发和语音播放状态处理，152 项主机回归通过。**诊断固件和原生手势模型已上板；设备启动仍有系统 tick 崩溃，中转未部署，真实灵机设备路由和喇叭回应未验收。** 最新应用、构建和实机结果以[验证清单](../artifacts/gesture-agent-validation-20261101.json)为准。本文中的配置例子不能直接作为可用设备配置。

## 路径与接口依据

```text
摄像头 → ESP-DL 分类 → hv_hand_gate 稳定保持与去重
   → 完成事件 → 固定词典 → 中文 prompt
   → 板端后台任务 → HTTPS 中转 → 灵机 event=chat
   → 已启动的 Agora 会话 → 云端语音下行 → 设备喇叭
```

手势含义在建库时确定。模型只负责识别张掌或 V 字；agent 收到的是已经绑定的原句和回应要求。未绑定、低置信度、过期帧及原始逐帧分类不产生对话请求。

官方 SDK 的 Agora `send_text` 与 `request_tts` 均指向返回 `-QM_ENOSYS` 的实现。`agent_app_user_corpus()` 使用 `sendSpeakRequest` 直接合成语音，不能拿它替代 agent 对 prompt 的理解。

本轮核对的官方网页实际使用以下商户接口：

```text
GET https://api.ljyd.cn/agent-merchant/agora/sendEvent
Authorization: <merchant credential>
query: pid=<product>, did=<target>, event=chat, content=<prompt>
response success condition: {"ok": true, ...}
```

依据为 2026-11-01 读取的官方公开脚本：

- [AssistantList-Y9y655oE.js](https://platform.ljyd.cn/assets/AssistantList-Y9y655oE.js)：网页聊天的 `pid/did/event/content` 参数。
- [agent-7cahtG5T.js](https://platform.ljyd.cn/assets/agent-7cahtG5T.js)：`/agora/sendEvent` 路径及 GET 方法。
- [request-BnVUanJf.js](https://platform.ljyd.cn/assets/request-BnVUanJf.js)：`agent-merchant` 基地址。

这属于**官方网页实现证据，不是设备侧公开 API 的兼容性承诺**。网页使用的是调试会话目标，真实硬件的 PID/DID 是否可以通过同一路径路由，必须用实际凭据与在线设备验证。未猜造 `sendTextRequest`，也未将浏览器登录凭据放入固件。若平台拒绝物理设备路由，需要替换服务端 `LjydChat` 适配器；板端事件、prompt 和音频状态代码可保留。

### 后续文档核查：文本命令与 `think`（2026-11-01）

用户进一步要求按“识别结果映射成文本命令”核查开发文档。**这种交互有明确的官方接口依据；当前未确认的是灵机是否向设备开放该入口。** 自建 HTTPS 中转是现有候选实现的选择，不是手势输入的必然要求。

声网[发送自定义指令](https://doc.shengwang.cn/doc/convoai/restful/convoai/operations/agent-think)定义了以下服务端接口，将 `text` 作为用户输入送入正在运行的智能体，由模型推理并响应：

```text
POST https://api.agora.io/cn/api/conversational-ai-agent/v2/projects/{appid}/agents/{agentId}/think
```

以下是按当前“空闲时触发，忙碌时丢弃”策略准备的请求示例，尚未发送：

```json
{
  "text": "我想喝水。请用一句简短的中文回应。",
  "on_listening_action": "interrupt",
  "on_thinking_action": "ignore",
  "on_speaking_action": "ignore",
  "interruptable": true
}
```

`agentId` 是创建该次声网智能体会话时返回的**实例 ID**，不是灵机智能体页面编号、设备 DID 或 RTC 用户 UID。接口需要声网规定的 HTTP Token 或 Basic Auth，不能假设灵机商户凭据、设备 token 或 RTC token 可以直接替用。当前 SDK 的 Agora 鉴权解析只保存 RTC 的 `appid/token/uid/channelName` 等字段，没有保存此实例 ID。

官方[发版说明](https://doc.shengwang.cn/doc/convoai/restful/overview/release-notes)也说明客户端 `think` 通过 RTM 注入用户文本；`speak` 则直接播报。板载 Agora 头文件虽有 RTM API，但当前适配器未接入该能力；现有 RTC 鉴权信息不能证明 RTM 登录与目标会话可用。本轮没有改动鉴权或尝试复用凭据。

继续检查灵机文档和固定版本 SDK（`89020f5e0`）后，各通道边界如下：

| 通道 | 已核实行为 | 对本项目的含义 |
| --- | --- | --- |
| `ljyd_method_up()` → `qm_iot_up_report_ex()` | 能经 `device/up` 上报带 `method/subMethod/params` 的 JSON | 可以承载手势文本；尚未找到云端将指定命令转交 agent 的 method、参数和回执契约，不能自造 `chat/text` 并宣称可用 |
| [设备 IoT 控制](https://xjiangiot.yuque.com/afahpl/qrhct7/dc7i3ia268k44vl1) | 云端将设备控制结果下发为 `siid/piid/属性值`，由设备执行 | 主要是 agent → 硬件动作，不能据此认定属性上报会触发 agent 推理 |
| [智能场景](https://xjiangiot.yuque.com/afahpl/qrhct7/zh4dl0gxtv2pni66) | 用户触发语料匹配执行项，并配置回复 | 可处理已进入平台的用户意图；文档没有给出设备主动提交任意文本的协议 |
| [平台能力接入与集成](https://xjiangiot.yuque.com/afahpl/qrhct7/kmyfep56ybuhsdpf) | 提到插件事件上报后可推送到模型会话 | 支持继续核查事件直达方案，但本文未定义通用手势文本事件的请求契约 |
| `QM_AGENT_TRANSPORT_AGORA` 的 `send_text` | 返回 `-QM_ENOSYS` | 当前板上所选适配器需要补接文本入口 |
| `QM_AGENT_TRANSPORT_LGEINE` 的 `send_text` | 实际调用 `lgeine_agent_send_speak()` | 虽然函数名为发送文本，实际是 TTS；直接切换传输也不能完成模型理解 |
| LGEINE 协议的 `listen/detect/text` | 协议明确限定为唤醒词上报 | 不能将它当作已支持任意 prompt 的接口 |

SDK 核对位置：`apps/main/cloud/ljyd_method.c:339`、`qumios-dev/components/qm_cloud/api/qm_iot_api.h:673`、`qumios-dev/components/qm_agent/src/transport/qm_agent_transport_agora.c:1082`、`qumios-dev/components/qm_agent/src/transport/qm_agent_transport_lgeine.c:488`、`qumios-dev/components/lgeine_agent/LGEINE_PROTOCOL_V2_CN.md:268`、`qumios-dev/components/qm_agent/src/auth/qm_agent_auth.c:1004`。

下一步所需的平台信息已缩小为：**是否支持将设备上行文本转为用户消息／`think`；若支持，提供准确的 MQTT method 或设备 HTTP 接口，以及会话定位、鉴权和回执规则。** 如果提供设备直达接口，板端可以复用设备鉴权并去掉自建中转；若仅提供服务端接口，再保留中转。声网原生接口可用不等于我们有权限调用灵机所创建的声网会话。

上述文档核查阶段只读取文档和源码，没有发送设备命令、请求真实智能体、变更平台配置或烧录。原有测试结果不构成上述新路线的运行验证；后续实机操作单列于下文。

## 代码与行为

| 位置 | 职责 |
| --- | --- |
| `headvoice/core/hv_gesture_prompt.*` | 将明确绑定的完成事件转换为有长度限制的中文 prompt |
| `headvoice/core/hv_gesture_reply.*` | 判断文本、speaking/silent 与同代播放事件，关闭输入并等待本地音频排空 |
| `headvoice/firmware/hv_gesture_agent.c` | 单任务、单请求；HTTPS、超时、回执校验、状态日志 |
| `headvoice/firmware/hv_gesture_agent_port.inc` | 通过构建补丁接入官方 `agent_app.c`，管理会话与播放通知 |
| `server/gesture_agent_bridge.py` | 鉴权、固定设备路由、事件去重、调用灵机商户聊天接口 |
| `tools/gesture_agent_config.py` | 验证本地配置并生成私有固件头文件，拒绝 HTTP 和非法绑定 |
| `headvoice/firmware/hv_gesture_probe.*` | 显式启用的无凭据诊断入口；独占会话、关闭麦克风上传并观察播放结束 |
| `tools/probe_gesture_agent.py` | 等待诊断会话 ready，再发送一次带随机标记的计算问题，分别记录回答和音频证据 |

固件不在视觉任务中请求网络。一个手势事务未结束时，新事件报告 `busy` 并丢弃；不排队播报旧需求。断网、HTTP 失败、空回执、回执 ID 不匹配、播放错误或超时均报告失败，不自动重试。同一手势持续保持时仍沿用原 gate 去重规则；失败后需要释放并重新完成动作才会再次发送。

手势只在没有已有语音会话和资源播放占用时启动自己的 Agora 会话，期间关闭麦克风上传。唤醒词、资源播放或云端退出可以接管，旧任务清理不会关闭接管后的会话。正常完成或超时由任务关闭自己启动的会话；停止失败保留占用，后续请求拒绝，显式退出成功后可恢复。

启动等待最长约 15 秒，其中要求远端加入、SDK 为 RUNNING、音频空闲并稳定 600 ms；网络单次收发超时为 15 秒；请求接受后等待语音完成最多 45 秒。SDK 的 HTTP 超时是单次收发上限，不是整个 TLS 请求的严格总期限。

服务端只按私有配置选定物理设备，客户端不能提交另一台设备的 PID/DID。商户凭据从环境变量读取；固件只保存单设备中转 token。服务端不记录 prompt、鉴权头或含 prompt 的上游 URL；HTTPS 校验证书并拒绝重定向。配置了中转的固件在隔离 SDK 副本中启用 TLS 主机名校验，保留原有 CA bundle；连接各平台域名的兼容性仍需实测。去重缓存最多 1024 项、保留 1 小时；失败或超时的同一事件也不重试。缓存仅在当前进程中有效，重启不保留；设备本身不会重发旧请求。

## 配置与运行

运行当前候选中转实现需要一个可被设备访问的 HTTPS 服务。可在服务器运行 Python 3.9+ 中转，前面配置 HTTPS 反向代理；正常工作时开发板不需要连接 Mac。中转依赖标准库，无需安装 Python 包。部署前应限制代理连接数及请求速率，并避免记录请求体或 Authorization。

1. 将 `server/config.example.json` 复制到服务器私有位置，填写已绑定产品的真实 PID 和物理设备 DID。**`2703` 是历史智能体设置页 ID，不能当作物理设备 DID。** 设置 `LJYD_MERCHANT_TOKEN` 和每台设备的 `GESTURE_DEVICE_TOKEN` 环境变量。商户凭据需按平台有效期维护；本实现不自动登录或续期。
2. 启动中转：

   ```sh
   python3 server/gesture_agent_bridge.py --config /private/path/bridge.json
   ```

   默认仅监听 `127.0.0.1:8787`。代理 `/v1/gesture` 到此服务，保留 Authorization。`GET /healthz` 仅证明服务进程就绪，不证明灵机鉴权或设备在线。
3. 将 `docs/gesture-agent-config.example.json` 复制到 `.local/gesture-agent.json`，填写 HTTPS 地址和相同的单设备 token。示例中的两句仅供说明，需要按用户确认的词义配置。可以只绑定一种手势；空缺的手势不会发送。
4. 构建手势固件：

   ```sh
   HEADVOICE_SDK=/Users/emt/Workspace/hackathon/ljyd_xjwb03_agent_public_developer \
   python3 tools/build.py headvoice build \
     --stage 2 --vision hand --rotate-cw90 \
     --hand-native-partition coco_pose --work-name gesture-agent \
     --gesture-agent-config .local/gesture-agent.json
   ```

   私有头文件仅写入 `.work/gesture-agent/apps/main/hv_config/`，不进入公开补丁。省略 `--gesture-agent-config` 时编译出的固件保持原识别行为并报告 `not_configured`，不会隐式沿用上次配置。固件二进制含设备 token，应按私有部署产物处理。
5. 原生分类模型占用了现有数据分区。遵循 [原生分类器部署边界](hand-gesture-tests-2026-10-31.md)，核对分区和备份后部署应用；不要直接执行构建日志给出的整套 `idf.py flash`，否则可能覆盖模型。实际诊断部署与生产中转配置分开记录。

控制面板的 localStorage 演示词典不会自动同步到这里。当前绑定通过私有构建配置进入固件；运行时词典编辑、真实建库采集和面板同步仍未接入。

### 不部署中转时的最小路由诊断

构建时显式添加 `--gesture-agent-probe`，即可启用 `hg_agent probe GB<8位大写十六进制>` 和同 marker 的 `hg_agent abort`。该选项不需要中转地址或凭据；省略时诊断 CLI 关闭。会话确认没有已有语音／手势所有者后启动，等待远端加入和连续 600 ms 空闲，再发出带同一 marker 的 `HG_PROBE ready`。最长等待回复 90 秒，随后清理自己拥有的会话。

配置了私有环境变量 `LJYD_MERCHANT_TOKEN` 后，可运行：

```sh
python3 tools/probe_gesture_agent.py --pid 11785 --did 100000766 \
  --port /dev/cu.usbmodem5CE41521721 --send \
  --output .local/gesture-route-result.json
```

省略 `--send` 只检查配置，不联网。带串口时，工具必须收到本次 marker 的 ready 才发送一次请求；失败不重试。测试问题要求计算 17+25，prompt 本身不含答案。严格匹配答案数字，拒绝 `420`、`42.5` 和未结束的数字分片，避免直接朗读 prompt 被当成模型理解。

结果分别记录 `matching_agent_reply_observed`、`matching_tts_reply_observed`、`playback_generation_completed_observed`、`diagnostic_session_ready/ended`。文本通知没有音频 generation，不能把它们强行关联；`physical_audio_verified` 始终为 false，实际听测另行确认。没有平台凭据时，也可以保持诊断会话并由已登录网页发送相同的单次测试，HTTP 结果与串口结果分别留证。

### 2026-11-01 实机接入记录

平台只读核对确认 PID 11785 的默认绑定为 `gesture_bridge`、agentId 2703、版本 1，开场白字段为空。这里的 agentId 是平台配置 ID，仍不能替代物理 DID 或声网会话实例 ID。

首次采样发现板上实际是 `89020f5e04bf-baseline`（2026-10-31 22:10:51 构建），并持续报告 `prov_rst` 栈溢出；Flash 中也已恢复成原 COCO 模型，不能沿用“原生手势固件仍在板上”的旧记录。先完成 16 MiB 全 Flash 私有备份，再核对现有分区；应用区为 `0x20000`，模型区为 `0x810000`。随后仅写入诊断应用和固定版本手势模型，并校验应用、模型和未改动的分区表。

`tools/prepare_sdk.py` 将隔离 SDK 副本中的 `prov_rst` 栈由 2048 增至 4096 字节；`hv_voice stats` 增加其最小剩余栈报告。70 秒采样中读取到剩余 1960 字节，未再见该任务栈溢出，原生分类器成功加载并产生 140 条手部观察。但同一窗口有两次 `StoreProhibited` 和一次 `IllegalInstruction`，回溯位于系统 tick／ROM 路径，不能宣称设备已稳定。正在以此前语音会话采用的 `--wdt-rom off` 做单变量对照；这会保留看门狗保护，历史上也曾出现异常，不能先称为修复。

## 验收

先确认物理设备关联的是所需的 `gesture_bridge` 智能体，并关闭会话开场白及自主插话。SDK 的播放通知没有本次 prompt 的业务 request ID；实现通过独占会话和播放 generation 限定归属，仍须避免平台自行发送其他语音。

完整成功日志应包含同一次请求的状态：

```text
HG gesture
HG_AGENT connecting → sending → accepted → speaking → playback_complete
```

- `accepted`：中转已收到灵机 `ok:true`，不代表 agent 已理解或出声。
- `speaking`：本地 SDK 发出播放开始通知，不替代实际听测。
- `playback_complete`：同代本地音频队列与设备播放结束通知，不替代对回答内容的核对。

实际验收要核对：张掌/已可稳定识别的目标动作触发一次、回答保留绑定原意、持续保持不重复；再测释放重做、断网、凭据失效、忙碌、唤醒词接管和超时。已有 V 字识别尚未通过实机验收，本次没有调整模型或降低门槛。

2026-11-01 初次代码检查阶段：141 项 Python unittest 通过，生产 C 核心合成测试通过，中转启用版和未配置版均完成 ESP32-S3 完整编译。补入诊断入口后，主机回归增至 152 项并全部通过，诊断版完整编译通过。主机测试包含真实本机 HTTP 往返，灵机、RTOS 和音频硬件由 stub 模拟。启用版编译使用 `.invalid` 地址与测试 token，仅用于编译检查，不能部署为可用链路。构建大小、哈希及最新实机边界见[验证清单](../artifacts/gesture-agent-validation-20261101.json)。未听测、未发布 H5、未推送 GitHub。
