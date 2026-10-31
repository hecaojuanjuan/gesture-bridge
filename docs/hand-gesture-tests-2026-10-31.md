# 手势识别：采样与测试命令

## 当前状态与本轮范围

2026-10-31，用户确定：暂缓自动居中和头部姿态，先识别 **张开手掌 / 握拳**，且必须由开发板独立运行。电脑仅用于采样、训练、烧录及查看日志，不作为运行时识别器。

随后用户要求尝试其他手势，并最终确认 **手掌张开（five）与 V 字（two）**，仍要求板端独立运行。两种手型已分别完成检测短测，分类验收尚未开始。下面第 4–6 节保留为原张掌/握拳自训练路线，暂不按其中标签采集新手势；当前固件尚未接入这两类的官方分类器。

当前板上为 `headvoice-hand-voice-restored-20261031.bin`，SHA-256 `b4175a0c09ce6f27517a05cb1f5afffbe724185cd5b7a701b9b9b4dee85faa6f`，已于 18:34 完成恢复并通过烧录哈希校验。该镜像支持手部检测和同帧 JPEG，**尚未加载张掌/握拳分类权重**；`classifier_ready:false`、`gesture:"untrained"` 是预期状态。用户已在同一镜像上确认摄像头运行时唤醒提示音与回答均可听到。恢复后约 36 秒观察有 35 条相机批次记录、113 条手检测记录，热点和云端已连接，未观察到新崩溃；串口监视已退出，可继续摄像头取景和短时测试。此前启动崩溃仍待定位，短窗不等于长期稳定或分类准确率通过；有重启的采样必须分段。该应用不初始化舵机，也不运行头部动作或手势播报流程。详见[最新上板清单](../artifacts/headvoice-hand-voice-restored-20261031.json)及[语音验证记录](validation.md#后续实机听测通过启动稳定性仍未通过)。

此前检测采样版已验证：应用分区烧录 hash 正确；15 秒启动日志有 43 次手检测，推理中位数 280 ms，摄像头取帧没有空帧；三张 320×240 模型输入 JPEG 均通过校验，文件大小约 7.6–8.3 KB。该窗口不是有标签的准确率测试。三张画面均缺少完整掌心/掌根，因此未纳入训练，当前尚无有效训练集。

软件验证：14 项手势相关主机测试、21 项相机测试、6 项采样测试通过。最新源码的无权重版本与带临时测试权重的版本均完成 ESP-IDF 编译；后者大小 3,811,184 B，仍有 317,584 B 应用区余量。临时权重仅用于链接检查，未烧录、不是训练模型，构建配置已恢复无权重。当时板上仍为原采样版；当前运行版本以后续握拳日志为准。记录见[构建检查](/Users/emt/Workspace/hackathon/gesture-bridge/artifacts/hand-implementation-check-20261031.json)。分类器真实板端耗时尚未测量。

用户表示位置受限，先自行调整后测试。完整单手入镜之前，不继续长时间采样。不要强拧舵机轴；本轮不执行 `arm`、`jog` 或 `start` 云台命令。

## 2026-10-31 采样中断与恢复

张掌短测之后的握拳尝试没有检测记录，不能计算握拳漏检率。只读诊断确认 12 秒内出现 40 次启动，bootloader 报应用段长度无效、没有可启动应用；原采样版的 flash 摘要校验失败，`0x104000` 起 4096 字节读出全为 `0xFF`。用户确认期间另有窗口或聊天烧录／升级；具体写入中断过程未观测，不能将这次失败归因于握拳动作。

已仅恢复原 `56d3b8c2…` 采样应用，写入校验和独立 `verify_flash` 均通过。随后 30 秒只读观察有 91 条 HG observation、1 条 ready、一次正常启动，相机持续完整取帧；这轮没有动作标签，不作识别准确率或长期稳定性结论。详情见[恢复证据](../artifacts/hand-boot-recovery-20261031.json)。

继续测试时，一次只由一个窗口操作开发板：暂停其他窗口的烧录／升级并断开网页 USB。重新采集握拳短测，使用下面带时间戳的新日志名；当前仍无分类权重。

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

## 2. 先确认完整手部入镜

张开一只手，掌心朝镜头，掌根、掌心、五指都放入画面中央，避免手遮到镜头或与亮灯重叠。准备好后执行：

```sh
"$PY" tools/camera_preview.py --port "$PORT" --source inputjpeg \
  --output .local/hand-tests/framing.jpg --timeout 25 && open .local/hand-tests/framing.jpg
```

应看到 `source: inputjpeg`、`320×240`、`checksum_verified: true` 和一只完整的手。JPEG 已按当前安装方向旋转，不要再次手工旋转后当作同一训练图。

如果只看到手指、掌根出画、手很小或亮部细节消失，先改变整套装置摆放、手的位置或照明，再取一张图。**不要把不完整的手标为合格张掌。** 当前低分辨率与光照下的适用距离需要实测，不预先承诺固定厘米数。

## 3. 短测“能否找到手”，不等于识别手型

先保持张掌再运行以下命令；结束后可以放下手休息：

```sh
LOG=".local/hand-tests/open-detection-$(date +%Y%m%d-%H%M%S).jsonl"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 15 --quiet --output "$LOG" && "${PY}" tools/hand_readiness.py "$LOG"
```

然后换成握拳，拳头与手腕完整入镜，再运行：

```sh
LOG=".local/hand-tests/fist-detection-$(date +%Y%m%d-%H%M%S).jsonl"
"$PY" tools/capture_serial.py --port "$PORT" --seconds 15 --quiet --output "$LOG" && "${PY}" tools/hand_readiness.py "$LOG"
```

每次采集使用带时间戳的新文件，工具会在打开串口前拒绝覆盖旧日志。串口报错或只有不完整数据时返回失败；`&&` 会阻止继续生成摘要。`recording_status:no_observations` 表示没有检测日志，不能解释成握拳漏检或无手画面；正常无手时也应有 observation，只是 `hands=0`。

重点看 `observations`、`hand_counts`、`valid_single_hand`、`inference_ms`。当前检测版出现 `gesture_events:0` 是正常的，**不能把检测到一只手算成张掌或握拳已识别**。如果一侧大部分时间 `hands=0` 或 `valid_single_hand` 很少，先反馈本步骤，不进入训练采集。

2026-10-31 用户已完成张掌短测：43 次观察中 33 次有效单手（76.7%），35 次单候选、6 次双候选、2 次无候选；推理中位数 281 ms，结果年龄中位数 298 ms。原始日志只见一次 POWERON 启动，预览已看到完整手掌。该比例是有效检测覆盖率，不是张掌识别准确率；下一步先补握拳与无手短测，尚不进入训练采集。详见[本轮摘要](../artifacts/hand-open-detection-20261031.json)。

恢复后用户就绪的握拳短测得到 42 条观察、11 条有效单手（26.2%），20 条无候选、20 条单候选、2 条双候选；推理中位数 269 ms。一次同帧 JPEG 确认拳头和手腕完整入镜，检测框宽占画面约 22%，分数 0.50。运行日志显示当前已被另一窗口更换为 18:16:20 编译的手检测版（ELF 前缀 `87d44b90b`），仍未训练，不能把与早先张掌的百分比差异当成严格同版本对照。用户选择自行运行下一轮“稍靠近镜头”的握拳短测；使用新日志名前缀 `fist-close`，不改门槛。见[握拳证据](../artifacts/hand-fist-detection-20261031.json)。

随后用户近距离握拳短测：39 条观察中 18 条有效单手（46.2%），19 条单候选、20 条双候选、没有零候选。两次握拳的编译时间与 ELF 前缀一致；有效覆盖率提高，但仍不稳定。18 个有效框全部贴近画面下边缘，尚无本轮配对 JPEG，不能断言手出画或第二候选来源。下一步只拍一张近距离握拳画面核对取景，暂不采训练集或放宽门槛。见[近距离摘要](../artifacts/hand-fist-close-detection-20261031.json)。

也可将手移开后采 15 秒，日志名前缀改为 `no-hand`，保留时间戳，核查背景是否被误检成手。日志里的 `startup_or_fault_lines` 同时包含正常打开串口引起的启动文字，不能仅凭它非零认定反复重启；反馈时附短摘要，由我核对。

## 3.1 当前两种目标：手掌张开与 V 字

最近一次握拳对照为 13/40 条有效单手（32.5%）；取景照片前两张拳头在上边缘之外，第三张手部靠近上下边界，未作为训练图。之后用户自行进行 V 字短测：42 条观察，39 条单候选、3 条无候选、没有双候选；26 条有效单手（61.9%），最长连续有效 7 条、首尾采集跨度 1902 ms。推理中位数 272.5 ms，结果年龄最大 355 ms。只有一次正常启动，运行指纹仍为 18:16:20 / `87d44b90b`。两轮取景不同，不能把比例变化当成受控的手势优劣或分类准确率。见[V 字摘要](../artifacts/hand-v-detection-20261031.json)与[握拳取景复测](../artifacts/hand-fist-framing-retest-20261031.json)。

V 字四张预览中，18:56:08 的两根指尖完整入镜且留白较好，18:56:25 又靠近上边缘。预览与长采集并非逐帧配对；26 个有效检测框中 20 个距底边不超过 10 px，尚不能确认每帧框都完整覆盖手型。当前所有原始类别仍为 `untrained`。

用户已确认最终采用张开手掌与 V 字，不再安排拇指测试。当前检测短测已足够用于选择接入路线，下一步先完成官方 11 类模型的离线集成；raw `five` 对应张掌，raw `two` 对应 V 字，其余类别不触发这两种动作。不要把 `untrained` 或 `valid_single_hand` 当作手势分类结果。

目前仍可用下面的命令检查取景；图片名根据实际手势写 `palm-view` 或 `v-view`，不要把图片名当成设备预测类别：

```sh
IMG=".local/hand-tests/v-view-$(date +%Y%m%d-%H%M%S).jpg"
"$PY" tools/camera_preview.py --port "$PORT" --source inputjpeg --output "$IMG" --timeout 25 && open "$IMG"
```

正式分类验收将在模型上板、报告 `classifier_ready:true` 后进行。V 字和张掌分别做保持、放下、重复动作，并补其他手型与无手背景；现在不需要重复采集长时间 `untrained` 日志。

## 4. 原张掌/握拳路线：采集训练、验证和测试样本（暂不执行）

两种手型都能被稳定找到后再进行本步骤。每个命令连接后等待手部日志，并有 **10 秒倒计时**；过程中保持指定类别，缓慢改变手的位置、距离和朝向。只放一只手，避免大幅运动模糊。按 `Ctrl+C` 可结束采集并释放串口。

采样工具只发送 `hv_camera inputjpeg`。每张图必须通过 JPEG 校验，且与同一个 `captured_ms` 的有效单手检测框匹配，才会保存。重启、时戳倒退或图框不匹配会拒绝保存。连续尝试 5 次仍没有合格图时会停止，不会把失败帧凑进样本数。

### 4.1 训练组：每类先采 20 张

依次执行，每次先换好对应手势。`other` 要轮换 V 字、拇指、单指、半握等非目标手势，不要一直保持张掌或握拳。

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

## 5. 样本齐全后由我继续训练与上板

这一步先不需要你执行。训练代码已实现三类分类器（张掌、握拳、其他），导出约 216 KB 的 float 权重。训练运行在 Mac，最终权重会编入开发板应用；运行时无需电脑。尚未训练的版本不会输出假分类。

训练入口供复现：

```sh
.tools/hand-training/bin/python tools/train_hand_classifier.py .local/hand-dataset/manifest.json \
  --output .local/hand-model --epochs 40
```

已准备项目独立环境 `.tools/hand-training`（Python 3.9.6、Torch 1.12.0、NumPy 1.26.4、Pillow 11.3.0），依赖见 `tools/requirements-hand-training.txt`；`pip check`、NumPy/Torch 往返及 7 项分类器主机测试通过。测试中的合成数据只验证训练/导出代码，尚无真实数据集或真实训练权重；全局 Python 和 IDF 环境未改。输出 `model.json` 会分别记录训练/验证/测试数量、混淆矩阵和权重哈希；即使离线准确率较好，也仍标为未实机验收。

训练后的构建入口为 `tools/build.py headvoice build --stage 2 --vision hand --rotate-cw90 --work-name hand-trained --hand-weights .local/hand-model/hv_hand_weights.h`。**现阶段没有真实权重，不能执行这条命令来获得已识别的固件，也不需要重新烧录当前检测版。** 我会先检查模型、固件大小和运行耗时，再完成应用分区更新。

## 6. 训练版上板后的验收方法

仅在固件明确报告 `classifier_ready:true` 后进行。张掌和握拳各做 10 次：保持约 2 秒，将手移出画面约 1 秒再做下一次；记录每次是否只有一个对应的 `HG gesture` 完成事件。长时间保持不能重复计数，两类不能互相混淆。再测试无手背景、其他手势、半只手和遮挡后的恢复。

采集命令仍用第 3 步的 `capture_serial.py` 与 `hand_readiness.py`，按实际轮次延长 `--seconds` 并更换文件名。摘要中的原始类别次数和完成事件次数是两回事，准确率需结合你实际做的动作逐次核对。

候选确认规则为分数至少 0.80、领先第二类至少 0.20，至少 3 个新帧且持续 600 ms；过期、多人和未知结果取消未完成进度。参数还需实测，不能为让结果“通过”而直接放宽。训练版在 RGB“状态指示”模式下，已确认张掌显示绿色、握拳显示蓝色，结果过期则清除状态灯；当前采样版没有这些分类灯效。手势完成、灯效和脱离电脑后的识别需分别确认。

## 反馈模板

```text
1. USB 端口：
2. framing.jpg 是否能看到完整掌根、掌心和五指：
3. 张掌检测摘要（observations / hand_counts / valid_single_hand / inference_ms）：
4. 握拳检测摘要：
5. 无手背景有没有误检：
6. 训练/验证/测试各类实际保存数；有无错标或失败：
7. 若报错，最后几行错误文字：
```

反馈摘要即可；原始串口日志可能夹带云端消息，不要整份复制。图片保留在本机，我可继续读取核查。

实现与来源：[官方手检测模型及固定版本](../headvoice/third_party/hand_detect/UPSTREAM.json)、[采样工具](../tools/collect_hand_samples.py)、[训练工具](../tools/train_hand_classifier.py)、[板端应用](../headvoice/firmware/hv_hand_app.c)。
