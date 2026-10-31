# 手势识别：采样与测试命令

## 当前状态与本轮范围

**暂停点（2026-10-31）**：用户要求先暂停改进并把当前模型、代码与验证记录推送 GitHub。以下测试步骤保留供恢复时使用，本次归档不继续采样、修改识别策略或烧录。新 `tools/hand_frame_probe.py` 可保存原始 JPEG 及按同一启动内 `captured_ms + width + height` 精确配对的 HG 元数据；13 项主机测试通过，但尚未在设备上运行，同帧裁剪诊断仍未完成。个人照片、原始串口日志及带本机配置的构建镜像保留本地。

2026-10-31，用户最终确认 **张开手掌（five）与 V 字（two）**，必须由开发板独立识别；自动居中与头部姿态优化暂缓。电脑用于查看画面、采集日志和部署，不作为运行时分类器。**不用再做拇指测试，也不用执行第 4–6 节旧张掌／握拳训练路线。**

官方 11 类分类器的离线集成和 ESP-IDF 构建已通过：应用为 `headvoice-hand-palm-v-native-20261031.bin`，3,602,112 bytes，SHA-256 `d14fa9052dabb04bb20f708699811f5fa6c92019ef5f2bb6bde153619a74ce16`。固定模型为 788,608 bytes，SHA-256 `52e18ceb0845121b4c0fa63aa06d69d17068c8c8135f43a7943a11812ac595d0`。应用 hash 与模型 hash 是两个不同值。模型和应用现已分别写入并通过独立校验，分区表与 NVS 未改；原应用和完整 COCO 模型分区已备份。25 秒启动窗口报告 `classifier_ready:true`、固定模型 hash 匹配，66 条观察中实际完成 7 次分类计算，未见匹配崩溃；这 7 帧的总推理中位数 456 ms、结果年龄最大 541 ms。该窗口没有动作标签，**张掌／V 字准确率、实物灯效、语音并行与长期稳定性仍待验收**。见[镜像清单](../artifacts/headvoice-hand-palm-v-native-20261031.json)和[启动检查](../artifacts/hand-native-startup-20261031.json)。用户选择自行运行下面的命令，代理已释放串口。

本轮用户自行完成首次 native 张掌短测：26 条观察，19 条有效分类均为 `five`，15 条保持确认观测、1 次 `open_palm` 完成事件；总推理中位数 460 ms、结果年龄最大 583 ms。7 条未知包括 4 条多候选及 3 条无效单候选，不能按 19/19 宣称整体准确率 100%。这证明本轮张掌触发链路已运行；V 字、无手/非目标对照、重复保持—释放与实物灯效仍待测试。见[张掌 pilot](../artifacts/hand-native-palm-pilot-20261031.json)。

两轮 native V 字短测尚未通过：首轮 23 次有效分类全为 `no_gesture`；第二轮 25 条观测中 18 次 `no_gesture`、1 次 `two`、6 次多候选跳过，均没有 `v_sign` 完成事件。第二轮唯一 `two` 分数 0.957654，其检测框上边界 y=85，其余分类大多 y=134–154；怀疑裁剪遗漏伸出的手指，需同帧 JPEG 与 HG 框核对，不能凭此前照片确认。不要将 `no_gesture` 改名为 V 或降低门槛来制造通过。见[首轮 V 字](../artifacts/hand-native-v-pilot-20261031.json)、[第二轮 V 字](../artifacts/hand-native-v-retest-20261031.json)。

旧版恢复记录：`headvoice-hand-voice-restored-20261031.bin`，SHA-256 `b4175a0c09ce6f27517a05cb1f5afffbe724185cd5b7a701b9b9b4dee85faa6f`，于 18:34 完成恢复并通过烧录哈希校验。它支持手部检测和同帧 JPEG，**没有分类权重**，`classifier_ready:false`、`gesture:"untrained"` 是旧版预期状态。用户曾确认该镜像在摄像头运行时能听到唤醒提示音与回答；约 36 秒观察有 35 条相机批次记录、113 条手检测记录，热点和云端已连接，未观察到新崩溃。这些结论不自动继承到新 native 镜像，也不代表长期稳定性。详见[旧版恢复清单](../artifacts/headvoice-hand-voice-restored-20261031.json)及[语音验证记录](validation.md#后续实机听测通过启动稳定性仍未通过)。

此前检测采样版已验证：应用分区烧录 hash 正确；15 秒启动日志有 43 次手检测，推理中位数 280 ms，摄像头取帧没有空帧；三张 320×240 模型输入 JPEG 均通过校验，文件大小约 7.6–8.3 KB。该窗口不是有标签的准确率测试。三张画面均缺少完整掌心/掌根，因此未纳入训练；旧路线未形成有效训练集。

旧三分类路线的软件验证：14 项手势相关主机测试、21 项相机测试、6 项采样测试通过。无权重版本与带临时测试权重的版本均完成 ESP-IDF 编译；后者大小 3,811,184 B，应用区余量 317,584 B。临时权重仅用于链接检查，未烧录、不是训练模型，见[历史构建检查](/Users/emt/Workspace/hackathon/gesture-bridge/artifacts/hand-implementation-check-20261031.json)。不要把旧路线的编译或检测比例当成新 native 分类准确率。

用户表示位置受限，先自行调整后测试。完整单手入镜之前，不继续长时间采样。不要强拧舵机轴；本轮不执行 `arm`、`jog` 或 `start` 云台命令。

## 2026-10-31 采样中断与恢复

张掌短测之后的握拳尝试没有检测记录，不能计算握拳漏检率。只读诊断确认 12 秒内出现 40 次启动，bootloader 报应用段长度无效、没有可启动应用；原采样版的 flash 摘要校验失败，`0x104000` 起 4096 字节读出全为 `0xFF`。用户确认期间另有窗口或聊天烧录／升级；具体写入中断过程未观测，不能将这次失败归因于握拳动作。

已仅恢复原 `56d3b8c2…` 采样应用，写入校验和独立 `verify_flash` 均通过。随后 30 秒只读观察有 91 条 HG observation、1 条 ready、一次正常启动，相机持续完整取帧；这轮没有动作标签，不作识别准确率或长期稳定性结论。详情见[恢复证据](../artifacts/hand-boot-recovery-20261031.json)。

继续测试时，一次只由一个窗口操作开发板：部署完成后暂停其他窗口的烧录／升级，并断开网页 USB。使用带时间戳的新日志名，不覆盖发生故障的记录；当前测试目标按张掌／V 字执行。

## 1. 准备目录与 USB 端口

先在 Chrome 面板点击 **断开**，关闭其他串口程序；网页与终端不能同时读取这块板。

```sh
cd /Users/emt/Workspace/hackathon/gesture-bridge
PY="$PWD/.tools/espressif/python_env/idf5.4_py3.9_env/bin/python"
"$PY" tools/capture_serial.py --list
PORT="/dev/cu.usbmodem5CE41521721"
mkdir -p .local/hand-tests
```

上面已填入 2026-10-31 本轮确认的真实端口；更换 USB 插口后，若 `--list` 的 USB Single Serial 路径变化，只替换 `PORT` 引号内的值。后文在同一个终端执行，沿用 `PY` 和 `PORT`。复制时只复制代码内容，不要复制围栏标记；如果出现 `bquote>`，按 Control+C 退出后重新粘贴。

### 1.1 先确认新分类器确实就绪

部署完成后先录 10 秒身份日志，此时不要求做手势：

```sh
LOG=".local/hand-tests/native-ready-$(date +%Y%m%d-%H%M%S).jsonl"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 10 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
"$PY" -c 'import json,sys; sys.path.insert(0,"tools"); from collect_hand_samples import hand_message; rows=[json.loads(s) for s in open(sys.argv[1]) if s.strip()]; msgs=[hand_message(r.get("line","")) for r in rows if not r.get("partial_line")]; keys=("event","classifier","classifier_ready","classifier_status","model_sha256"); print(json.dumps([{k:m[k] for k in keys if k in m} for m in msgs if m and m.get("event") in ("ready","classifier_init")],ensure_ascii=False,indent=2))' "$LOG"
```

应核对同一启动日志的 `HG ready`：`classifier:"espdl_gesture11"`、`classifier_ready:true`，且 `model_sha256` 完整等于上方 `52e18ceb…ac595d0`。摘要应有 `observations>0`，`classifier_names:["espdl_gesture11"]`、`classifier_ready_values:[true]`。如果只看到 `untrained`，仍是旧检测版；如果 native 报 `classifier_ready:false`、`gesture:"unavailable"` 或模型 hash 为 `unavailable`，停止分类验收并反馈 `classifier_init` 状态，不要用反复摆手代替部署检查。

末条命令只提取身份诊断，不打印原始云端消息。它输出 `[]` 可能是没有捕获到启动时的一次性 ready，不等于模型坏了；此时保留日志，结合本轮部署启动记录核对完整模型 hash，确认前不把分类验收记为通过。不要为了取 ready 同时打开第二个串口窗口。

## 2. 先确认完整手部入镜

张开一只手，掌心朝镜头，掌根、掌心、五指都放入画面中央，避免手遮到镜头或与亮灯重叠。准备好后执行：

```sh
IMG=".local/hand-tests/palm-view-$(date +%Y%m%d-%H%M%S).jpg"
"$PY" tools/camera_preview.py --port "$PORT" --source inputjpeg --output "$IMG" --timeout 25 && open "$IMG"
```

应看到 `source: inputjpeg`、`checksum_verified: true` 和一只完整的手；当前旋转配置预期为 320×240，实际尺寸以报文为准。JPEG 已按模型输入方向旋转。再换成 V 字，让两根指尖、掌根和手腕都留在画面内，执行：

```sh
IMG=".local/hand-tests/v-view-$(date +%Y%m%d-%H%M%S).jpg"
"$PY" tools/camera_preview.py --port "$PORT" --source inputjpeg --output "$IMG" --timeout 25 && open "$IMG"
```

如果只看到手指、掌根出画、手很小或亮部细节消失，先改变整套装置摆放、手的位置或照明，再取一张图。**不要把不完整的手标为合格张掌。** 当前低分辨率与光照下的适用距离需要实测，不预先承诺固定厘米数。

## 3. Native 张掌／V 字测试（部署和身份核对后执行）

### 3.1 各做一轮独立 15 秒 pilot

每条命令都有 5 秒倒计时。看到“开始”后保持指定状态，直到终端显示摘要；一次只录一种手型。输出文件名是人工标注的真实动作，不是设备预测。`--quiet` 期间终端安静属于正常情况。

先张掌，掌心朝镜头、五指自然张开：

```sh
LOG=".local/hand-tests/native-palm-pilot-$(date +%Y%m%d-%H%M%S).jsonl"
for N in 5 4 3 2 1; do echo "张掌测试 $N 秒后开始"; sleep 1; done
echo "开始：保持张掌，等待 15 秒采集结束"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 15 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
```

放下手休息，再举 V 字；食指与中指分开，其余手指收起，掌心朝镜头：

```sh
LOG=".local/hand-tests/native-v-pilot-$(date +%Y%m%d-%H%M%S).jsonl"
for N in 5 4 3 2 1; do echo "V 字测试 $N 秒后开始"; sleep 1; done
echo "开始：保持 V 字，等待 15 秒采集结束"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 15 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
```

再做一轮非目标手型，例如只伸食指；**不用再做拇指测试**：

```sh
LOG=".local/hand-tests/native-other-pilot-$(date +%Y%m%d-%H%M%S).jsonl"
for N in 5 4 3 2 1; do echo "非目标单指测试 $N 秒后开始"; sleep 1; done
echo "开始：保持单指，不能出现张掌或 V 字完成事件"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 15 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
```

最后把两只手都移出画面，保持原背景：

```sh
LOG=".local/hand-tests/native-no-hand-pilot-$(date +%Y%m%d-%H%M%S).jsonl"
for N in 5 4 3 2 1; do echo "无手背景测试 $N 秒后开始"; sleep 1; done
echo "开始：双手保持在画面外，等待 15 秒采集结束"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 15 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
```

每次使用带时间戳的新文件；工具会在打开串口前拒绝覆盖旧日志。串口报错或只有不完整数据时返回失败，`&&` 阻止生成正常摘要。`recording_status:no_observations` 表示没有 HG 观测，不能解释成漏检或无手；正常无手也应持续有 observation，且 `hands=0`。`startup_or_fault_lines` 同时可能包含正常打开串口引起的启动文字，非零本身不证明重启循环；有重启的测试应分段，不能合并算准确率。

按下面区分三层结果：

| 真实动作 | 分类原始候选（`raw_classes`） | 完成事件（`gestures`） | 状态模式灯效 |
| --- | --- | --- | --- |
| 张掌 | `five` | `open_palm` | 稳定确认后绿色 |
| V 字 | `two` | `v_sign` | 稳定确认后蓝色 |
| 其他手型或无手 | 可为其他原类，或检测为零手 | 不应新增上述两类事件 | 失效或非目标时清除状态输出 |

`valid_single_hand` 只表示手框有效；`classification_valid` 表示分类输出有效；`confirmed_observations` 是处于已确认状态的帧数，**不是动作次数**。只用 `HG gesture` / `gesture_events` 统计完成事件。原始 `no_hand` 也可能是“检测到手，但分类模型判为无手”；它与检测器 `hands=0` 不相同，都不能触发目标动作。pilot 用于找取景、误分类和帧龄问题，不能仅凭一次 `five` / `two` 宣称验收通过。若 `classifier_ready` 变 false、日志断流、反复重启，先停止后续轮次并反馈。

### 3.2 每类 10 次保持—放下重复验收

先在本地面板切换到“状态指示”，点击“应用到灯板”并等设备回执，再**断开网页 USB**后运行终端命令。若仍是自选颜色或熄灯模式，识别事件可能正常，但灯圈不会显示对应状态颜色；不能据此判为分类失败。手势测试不发送舵机动作，也不承诺手势语音播报。

每轮录 60 秒。倒计时结束后先将手放在画面外约 5 秒，再做 10 次：**保持目标手型约 3 秒 → 完全移出画面约 2 秒**。最后保持无手，等待摘要出现。自己按顺序记下第 1–10 次结果；不需要为了凑满 10 个事件而反复补做。若设备重启或明显卡住，结束本轮，保留失败记录。

张掌 10 次：

```sh
LOG=".local/hand-tests/native-palm-repeat10-$(date +%Y%m%d-%H%M%S).jsonl"
for N in 5 4 3 2 1; do echo "张掌重复验收 $N 秒后开始"; sleep 1; done
echo "开始：先无手 5 秒，再做 10 次张掌；每次保持 3 秒、放下 2 秒"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 60 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
```

V 字 10 次：

```sh
LOG=".local/hand-tests/native-v-repeat10-$(date +%Y%m%d-%H%M%S).jsonl"
for N in 5 4 3 2 1; do echo "V 字重复验收 $N 秒后开始"; sleep 1; done
echo "开始：先无手 5 秒，再做 10 次 V 字；每次保持 3 秒、放下 2 秒"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 60 --quiet --output "$LOG" && "$PY" tools/hand_readiness.py "$LOG"
```

每次保持最多产生一个对应完成事件，持续保持不能重复计数；有效放下后才开始下一次。两类各记录“正确完成／漏触发／错类／重复”，另记灯色与放下后是否熄灭。验收目标是每类 10 次均有唯一正确完成事件，非目标和无手 pilot 没有目标事件；这只是本次使用者、取景和环境的短测试，不证明换人或长期准确率。日志总计 10 次仍需与逐次观察对应，不能掩盖“一次漏报、另一次重复”。

固件保持规则为分类分数 ≥0.80、领先第二类 ≥0.20、至少 3 个新帧且持续 ≥600 ms；有效放下／非目标释放需持续 ≥500 ms。本帧年龄超过 600 ms、连续帧间隔超过 800 ms、复数手候选或未知结果会取消未完成进度。不要为通过测试直接放宽门槛。记录 `inference_ms` 与 `result_age_ms`，由我结合原始时间戳核查持续性。

### 3.3 断开电脑后的独立运行确认

完成日志对照后，再做一次“停止全部串口／网页程序，只保留开发板原有供电”的张掌、放下、V 字观察。预期仍由板端分类并显示绿／蓝状态灯；Mac 不运行识别程序。若 USB 同时是唯一供电，不要直接拔线后把掉电当失败；改为独立 USB 电源的测试留到供电方式确认后进行。该项、摄像头运行时唤醒／回答和长期稳定性分别反馈，不能用串口摘要代替。

## 历史证据：旧检测版张掌／握拳短测（不重新执行）

2026-10-31 用户已完成张掌短测：43 次观察中 33 次有效单手（76.7%），35 次单候选、6 次双候选、2 次无候选；推理中位数 281 ms，结果年龄中位数 298 ms。原始日志只见一次 POWERON 启动，预览已看到完整手掌。该比例是有效检测覆盖率，不是张掌识别准确率；当时尚未进入训练采集。详见[本轮摘要](../artifacts/hand-open-detection-20261031.json)。

恢复后用户就绪的握拳短测得到 42 条观察、11 条有效单手（26.2%），20 条无候选、20 条单候选、2 条双候选；推理中位数 269 ms。一次同帧 JPEG 确认拳头和手腕完整入镜，检测框宽占画面约 22%，分数 0.50。运行日志显示当时已被另一窗口更换为 18:16:20 编译的手检测版（ELF 前缀 `87d44b90b`），仍未训练，不能把与早先张掌的百分比差异当成严格同版本对照。用户随后自行运行“稍靠近镜头”的握拳短测，日志名前缀为 `fist-close`，未改门槛。见[握拳证据](../artifacts/hand-fist-detection-20261031.json)。

随后用户近距离握拳短测：39 条观察中 18 条有效单手（46.2%），19 条单候选、20 条双候选、没有零候选。两次握拳的编译时间与 ELF 前缀一致；有效覆盖率提高，但仍不稳定。18 个有效框全部贴近画面下边缘，当时没有配对 JPEG，不能断言手出画或第二候选来源；未据此采训练集或放宽门槛。见[近距离摘要](../artifacts/hand-fist-close-detection-20261031.json)。

## 历史证据：V 字检测与目标确定（分类器接入前）

当时最后一次握拳对照为 13/40 条有效单手（32.5%）；取景照片前两张拳头在上边缘之外，第三张手部靠近上下边界，未作为训练图。之后用户自行进行 V 字短测：42 条观察，39 条单候选、3 条无候选、没有双候选；26 条有效单手（61.9%），最长连续有效 7 条、首尾采集跨度 1902 ms。推理中位数 272.5 ms，结果年龄最大 355 ms。只有一次正常启动，运行指纹仍为 18:16:20 / `87d44b90b`。两轮取景不同，不能把比例变化当成受控的手势优劣或分类准确率。见[V 字摘要](../artifacts/hand-v-detection-20261031.json)与[握拳取景复测](../artifacts/hand-fist-framing-retest-20261031.json)。

V 字四张预览中，18:56:08 的两根指尖完整入镜且留白较好，18:56:25 又靠近上边缘。预览与长采集并非逐帧配对；26 个有效检测框中 20 个距底边不超过 10 px，不能确认每帧框都完整覆盖手型。该轮所有原始类别均为 `untrained`。

这些历史检测短测支持了接入路线的选择，但不是分类验收。后续用户确定张掌／V 字，native 离线集成已经完成；正式测试按上方第 1–3 节执行，不再重复长时间 `untrained` 日志。

## 4. 原张掌/握拳路线：采集训练、验证和测试样本（暂不执行）

**历史方案存档：第 4–6 节均不属于当前张掌／V 字路线，不执行其中命令，也不按旧标签收集新数据。** 以下保留当时的设计和工具用法以便追溯。

旧方案要求两种手型都能被稳定找到后才采训练图。每个命令连接后等待手部日志，并有 **10 秒倒计时**；过程中保持指定类别，缓慢改变手的位置、距离和朝向。只放一只手，避免大幅运动模糊。按 `Ctrl+C` 可结束采集并释放串口。

采样工具只发送 `hv_camera inputjpeg`。每张图必须通过 JPEG 校验，且与同一个 `captured_ms` 的有效单手检测框匹配，才会保存。重启、时戳倒退或图框不匹配会拒绝保存。连续尝试 5 次仍没有合格图时会停止，不会把失败帧凑进样本数。

### 4.1 训练组：每类先采 20 张

以下是旧方案的命令记录，当前不执行。其 `other` 曾包含 V 字、拇指、单指、半握等；**V 字现在是目标，不能再按这里标成 other**。

```sh
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label open_palm --split train --session train01 --count 20
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label closed_fist --split train --session train01 --count 20
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label other --split train --session train01 --count 20
```

这是首批个人原型数据，不足以证明换人、换环境也可靠。工具按命令赋标签，不会替你确认动作；完成后查看 `.local/hand-dataset/images/`，反馈错标、遮挡或未入镜图，不要只看保存数量。

### 4.2 验证组：放下手，重新摆姿势再采

用新 session，每类 10 张。验证组用于选择模型，不能从训练组相邻帧随机拆出来，也不能复制训练图充数。

```sh
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label open_palm --split val --session val01 --count 10
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label closed_fist --split val --session val01 --count 10
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label other --split val --session val01 --count 10
```

### 4.3 独立测试组：再重新摆姿势，每类 10 张

测试组不参与训练和模型选择；不要为了让结果变好而把失败图片删掉。再次变换位置或在稍后另一次会话采集：

```sh
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label open_palm --split test --session test01 --count 10
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label closed_fist --split test --session test01 --count 10
"$PY" tools/collect_hand_samples.py --port "$PORT" \
  --label other --split test --session test01 --count 10
```

所有图片与清单都在 Git 忽略的 `.local/hand-dataset/`。训练、验证和测试需要不同 session；工具会拒绝同 session 跨集合，训练工具还会拒绝重复图片。

## 5. 历史三分类训练与上板路线（不执行）

此路线已暂缓，不需要用户执行。旧训练代码实现三类分类器（张掌、握拳、其他），导出约 216 KB 的 float 权重。训练运行在 Mac，最终权重编入开发板应用；运行时无需电脑。尚未训练的版本不会输出假分类。

训练入口供复现：

```sh
.tools/hand-training/bin/python tools/train_hand_classifier.py .local/hand-dataset/manifest.json \
  --output .local/hand-model --epochs 40
```

已准备项目独立环境 `.tools/hand-training`（Python 3.9.6、Torch 1.12.0、NumPy 1.26.4、Pillow 11.3.0），依赖见 `tools/requirements-hand-training.txt`；`pip check`、NumPy/Torch 往返及 7 项分类器主机测试通过。测试中的合成数据只验证训练/导出代码，尚无真实数据集或真实训练权重；全局 Python 和 IDF 环境未改。输出 `model.json` 会分别记录训练/验证/测试数量、混淆矩阵和权重哈希；即使离线准确率较好，也仍标为未实机验收。

旧训练后的构建入口为 `tools/build.py headvoice build --stage 2 --vision hand --rotate-cw90 --work-name hand-trained --hand-weights .local/hand-model/hv_hand_weights.h`。**没有真实三分类权重；此命令不能构建当前官方 11 类 native 版本，不执行。**

## 6. 历史张掌／握拳训练版验收方法（不执行）

此处保留旧三分类验收设计，当前使用第 3 节张掌／V 字流程。旧设计要求固件明确报告 `classifier_ready:true` 后，张掌和握拳各做 10 次：保持约 2 秒，将手移出画面约 1 秒再做下一次；记录每次是否只有一个对应的 `HG gesture` 完成事件。长时间保持不能重复计数，两类不能互相混淆，再测试无手背景、其他手势、半只手和遮挡后的恢复。

历史方案同样使用 `capture_serial.py` 与 `hand_readiness.py`。摘要中的原始类别次数和完成事件次数是两回事，准确率需结合实际动作逐次核对。

旧方案的候选确认规则为分数至少 0.80、领先第二类至少 0.20，至少 3 个新帧且持续 600 ms；过期、复数手候选和未知结果取消未完成进度。旧三分类版在 RGB“状态指示”模式下为张掌绿色、握拳蓝色；**native 蓝色目标已经改为 V 字**。手势完成、灯效和脱离电脑后的识别仍须分别确认。

## 反馈模板

```text
1. USB 端口：
2. 身份核对：classifier / classifier_ready / model_sha256：
3. palm-view 与 v-view 是否完整入镜；本地图片路径：
4. 张掌 15 秒摘要：observations / valid_single_hand / classification_valid / raw_classes / gestures / result_age_ms：
5. V 字 15 秒摘要：
6. 非目标、无手 pilot 是否出现 open_palm 或 v_sign 完成事件：
7. 张掌 10 次：第 1–10 次分别为 正确/漏触发/错类/重复；绿色灯及放下熄灭情况：
8. V 字 10 次：第 1–10 次分别为 正确/漏触发/错类/重复；蓝色灯及放下熄灭情况：
9. 无串口/网页程序时是否仍能板端识别；供电方式：
10. 是否有重启、声音异常、报错；对应日志路径和最后几行错误文字：
```

反馈摘要即可；原始串口日志可能夹带云端消息，不要整份复制。图片保留在本机，我可继续读取核查。

实现与来源：[官方手检测模型及固定版本](../headvoice/third_party/hand_detect/UPSTREAM.json)、[官方 11 类分类模型固定版本](../headvoice/third_party/hand_gesture_recognition/UPSTREAM.json)、[native 镜像清单](../artifacts/headvoice-hand-palm-v-native-20261031.json)、[日志摘要工具](../tools/hand_readiness.py)、[旧训练采样工具](../tools/collect_hand_samples.py)、[旧训练工具](../tools/train_hand_classifier.py)、[板端应用](../headvoice/firmware/hv_hand_app.c)。
