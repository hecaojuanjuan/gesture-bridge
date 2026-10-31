# 人脸关键点候选后端

`--vision face` 用 Espressif MSR/MNP 检测可见人脸，再计算双眼连线倾斜角。默认仍是 `--vision coco`；该后端不估计完整 3D 头部姿态。当前 face stage 2 还向集成云台模块提供脸框中心；云台上电 PWM 关闭，需要显式启用和方向标定，面板没有运动入口。自动居中尚未通过实物验收，当前试验限制见[双轴说明](camera-auto-center.md)。

## 构建与范围

```sh
HEADVOICE_SDK=/path/to/pinned-sdk python3 tools/build.py headvoice build \
  --stage 2 --vision face --rotate-cw90 --work-name face-candidate
```

`--work-name` 将应用与构建结果放到 `.work/face-candidate/apps`，生成补丁放到 `.work/face-candidate/integration.patch`，可与默认 `.work/headvoice` 并行使用。省略该参数保持原有目录。`--vision face --gimbal` 和 baseline + face 会直接拒绝；`--gimbal` 指旧的独立 COCO 云台应用，不是 face stage 2 的集成模块。

`flash` / `monitor` 复用指定 workspace 的构建；如果同时给出 `--vision`，工具会核对缓存配置，不匹配时要求先重新 build，不会静默使用另一个 backend。

启动日志包含 `vision=face`。stage 1 不初始化视觉模型；stage 2/3 的 face 路径只初始化 MSR/MNP。UYVY → RGB888 与可选顺时针 90° 旋转复用原转换函数，不调用 COCO 初始化或推理。

模型使用应用 rodata，沿用原有分区表。SDK 中的 COCO 组件仍是 RGB 转换代码的编译依赖；保留该组件不代表 face 路径会实例化它。

## 有效性约束

- 检测结果必须恰好有 1 张可见人脸；零张或多张均无效，不挑选其中一张继续操作。
- 检测分数至少 0.5，双眼与鼻点必须在图像内部。共用 `hv_eye_tilt` 继续检查眼距。
- 共用原有帧时间戳、epoch 失效、400 ms 新鲜度上限与确认状态机；耗时超限不能通过增加上限绕过。
- `person_count` / `people` 字段为接口兼容保留，但 face 后端的值是**检测到的可见人脸数**，不是场景内完整人数。背向镜头或被遮挡的人可能不会计入，使用者必须了解此限制。

MNP 五点顺序是左眼、左嘴角、鼻、右眼、右嘴角，双眼坐标使用 `[0,1]` 与 `[6,7]`。固定版本的 [官方示例](https://github.com/espressif/esp-dl/blob/dc380d450835d42f92777121a0cd4fc67d7c3a8c/examples/human_face_detect/main/app_main.cpp) 明确给出此顺序；不能沿用 COCO 的 `[2,3]` / `[4,5]`。

## 固定来源

`headvoice/third_party/human_face_detect` 保留官方 `espressif/human_face_detect` 0.3.0 原始文件与 MIT LICENSE。`UPSTREAM.json` 记录下载地址、固定 commit、归档 SHA-256 与逐文件 SHA-256；准备构建时核验逐文件摘要，仅在隔离的 SDK 副本中添加 ESP-DL 本地 override。它要求 ESP-DL `~3.2.0`，当前固定 SDK 私有副本是 3.2.4。

## 验证状态（2026-10-31）

`python3 tools/test_face_landmarks.py` 已通过：中性与倾斜眼线、MNP 嘴角/眼睛索引区别、零/多目标、低分数、NaN、短数组与边界坐标拒绝。

原生产 core 的合成观察测试已通过，包括过时帧、遮挡、动作取消与确认屏障。ESP-IDF 5.4.1 / ESP-DL 3.2.4 的 face stage 2 交叉编译通过。本轮候选按当前摄像头安装方式启用 CW90，应用大小为 `0x31bb50`（3,259,216 bytes），现有 `0x3f0000` 应用分区剩余 21%。配置明确采用 rodata；分区表与当前 stage 1 构建及原板备份一致。

固定产物为 `artifacts/headvoice-face-stage2-cw90-20261031.bin`，SHA-256 为 `223a9e1993713006f540d05aedf1303239286b5786df67c1b27211f8376c8419`，同名 `.json` 保存配置和源文件摘要，`.elf/.map` 用于定位异常。它适合仅更新 `0x20000` 应用区，不需要更改 bootloader、分区表、NVS 或模型区。镜像 checksum 和 validation hash 检查通过。该产物包含空帧 100 ms 退避、相机日志 1 秒节流、Wi-Fi 断线去重连接和 `reset_reason` 回执字段。

ELF 符号表保留 `hv_face_pose_init`、`HumanFaceDetect` 与 CW90 RGB 转换函数，不包含 `yolo11_pose_init`、`yolo11_pose_analyze_rgb888` 或 `COCOPose`。构建选项检查也已验证 face + gimbal 和 flash 时显式 backend 与缓存不符会提前失败。

本轮已完成下述应用烧录、设备查询与图像预览验证；正式姿态时序、拒绝行为和动作输入验收尚未完成。官方 benchmark 仅用于选择候选，不代表本板帧率或可用性。

### stage 1 对照与 face stage 2 上板（同日后续）

先恢复旧 stage 1 应用 `aa1769ed6f5ef8995ce157d6b15667805fcd81fb382f6ff1414b51d598382053`，应用写入及哈希校验通过。两次真实 HP 查询回执的 boot 一致；两次摄像头快照均通过整帧校验并已查看。60 秒被动采样包含 1 个启动标记，未检出 panic/watchdog 标记；57 条相机记录中 good 从 30 增至 1710、empty 始终为 0、`last_bytes=153600`，计数单调增加。这只证明该 stage 1 窗口完整取帧，不能推出姿态识别或长期稳定性通过。汇总见 `artifacts/camera-stage1-retest-20261031.json`，原始日志和画面仅保存在 `.local/camera-retest-20261031/`。

随后仅在 `0x20000` 写入本页所列 `223a9e…6c8419` face stage 2 CW90 应用，烧录校验通过，未改分区、NVS 或模型区。真实 Chrome USB 查询显示 stage 2；160×120 快照通过校验并显示，页面记录获取用时 8.9 秒。面板出现过 107 ms、136 ms 的推理耗时读数，但它们只是初步界面读数，不能充当正式 median/p95/max 分布、400 ms 连续性验收或稳定性结果。证据见 `artifacts/face-stage2-runtime-20261031.json`；含拍摄内容的原始截图仅留在 `.local`，不公开。

取景调整后已完成两轮各约 60 秒正脸采样。第一轮 425 条 `HV pose` 全部检出 0 张脸；第二轮 399 条中 191 条检出单脸，其中 167 条 `valid=true`，208 条检出 0 张。第二轮最长连续段约 18.8 秒，未达到 30 秒时序门槛；该窗口未见 panic，但不代表长期稳定或真人动作通过。下一轮按[实机测试清单](next-device-tests-2026-10-31.md)改变取景或光照条件、先采集连续正脸，再测试侧倾和遮挡。两轮原始日志保存在 `.local/camera-retest-20261031/`。

## 本轮时序与稳定性验收口径

单脸稳定段至少覆盖 30 秒、30 个 tracked 结果；测时暂停 HVCAM 图像导出，避免其串口带宽和额外 PSRAM 拷贝干扰。分别报告转换、模型调用、整体推理、结果帧龄的 median / p95 / max，以及相邻采集时间间隔。`model_ms` 包含 MSR/MNP 的预处理、逐候选二阶段检测与后处理；多脸拒绝发生在检测结束之后，因此空场、单脸、多脸应分别统计。

stage 2 的 `tracking_valid` 表示单张可见脸及眼点检查通过；串口 `valid` 另外要求 epoch 一致和 `age_ms <= 400`，但 stage 2 不执行手势状态机。stage 3 的 `hv_tick` 还会检查距上一帧采集时间的空窗，所以要同时检查连续单脸结果的 `captured_ms[i] - captured_ms[i-1] + age_ms[i] <= 400`。不能仅凭单帧 age、采集间隔分别小于 400 ms 或 `valid_hz > 2.5` 宣称动作链连续。旧固件的 HP 快照 valid 曾遗漏 epoch 拒绝；该修复已随下述自检固件上板，真实失效/恢复边界仍待验收。USB 被动 `HV pose` 包含核心 valid。

采集工具 `tools/capture_serial.py` 已按真实换行缓冲串口片段；结束时未完成的尾行以 `partial_line` 保存，不解析为姿态证据。原始完整日志默认写入 `.local`，终端只输出筛选后的诊断；`--quiet` 关闭终端输出但保留日志，打开串口前明确关闭 DTR/RTS。`tools/pose_readiness.py` 已加入上述连续性量，并按启动/崩溃、boot 变化、时间倒退和显式失效划分片段，不跨段计算间隔或合并短窗口时长；未追踪/被拒绝的观察、负数或非有限时间、未换行尾行均不能制造通过。该工具的 10 项主机测试通过，仍只验证观察到的时序，不能代替真实手势准确率测试。

`captured` / `dropped` 是累计计数，计算帧率时取窗口差值；`inferred` 是 core 消费到的结果数，单槽结果队列可以覆盖中间结果。`age_ms` 从 BSP dequeue 后记时，尚未包含传感器曝光到 dequeue 的完整延迟。

推理任务使用 16 KiB PSRAM 栈，core 使用 6 KiB；模型构造仍发生于 4 KiB main 栈。当前只有栈 canary、PSRAM 启动自检和轻度 heap 检查，未记录栈高水位，heap 空闲量不能证明栈余量。顶层 `nothrow` 也不覆盖官方模型内部的所有分配失败路径；出现分配失败日志时应区分启动加载失败与推理期异常。现配置启用 PSRAM XIP，不能未经定位就将崩溃归因于普通 NVS 写入使 PSRAM 栈失效。


## HP 姿态快照有效性修复（2026-10-31）

重新分析 `.local/camera-retest-20261031/face-neutral-02.jsonl`：399 条观察中，208 条模型返回零脸，167 条追踪且被核心接受，另 24 条 `tracking_valid=true` 但 `valid=false`，其帧龄均为 129–231 ms。后者与 epoch 不一致相符，但日志未逐条输出 epoch，不能把推断当作每帧已证实的原因。见[日志审计](../artifacts/face-pose-rejection-audit-20261031.json)。这两类失败应分开：放宽眼点或帧龄门限不会让零脸结果变成人脸。

源码确认了独立缺口：旧 HP `pose.valid` 仅检查 tracking 和帧龄，没有沿用核心的 epoch/fresh 决策。已将 `tracking`（眼点质量）与 `eligible`（核心接受）分开保存；报告时还核对当前 epoch 与 400 ms 帧龄。epoch 递增时按固定 app→panel 锁顺序发布，旧结果即使迟到也不能恢复有效；核心收到观察后也重新核对 epoch。HP 仍是设备侧诊断快照，不能保证手机到达时仍处于相同状态。

`python3 tests/test_panel_firmware.py` 通过 16 个真实 HP/cloud 报告场景，涵盖失效与序列化交错、旧 epoch 迟到、新帧恢复、400/401 ms 边界、baseline/stage 1；RGB 与生产核心回归通过。ESP-IDF 完整编译与镜像 checksum/validation hash 检查通过，分区表未变。[合并候选](../artifacts/headvoice-face-panel-eligibility-candidate-20261031.json)同时包含前一版目标缓存失效修复，**未烧录、未做运行时验收**。它不解决零脸掉检或俯仰启动位置，也不表示自动居中已通过。


## 固定样例自检与相机采集恢复（2026-10-31）

[当前自检候选](../artifacts/headvoice-face-selftest-eligibility-20261031.json)已合并 HP 有效性与云台目标缓存修复，替代早期诊断镜像作为下一轮模型核查入口。完整构建及镜像校验通过，SHA-256 `df8b63d652bd500d610444db6749ed4431bae716618ee2eddde356096f50bf3b`，3,380,352 字节，分区表不变。固定官方 JPEG 仅在启动时推理一次并输出独立 `HV_SELFTEST`，不进入真人 pose 或云台目标通道；上电两轴 PWM 关闭。

自检已在本板执行：`begin/result/face/end` 各一次，检出 1 张脸，score 0.899121，`head_valid=true`，解码 29 ms、模型调用 54 ms。固定样例没有混入真人 pose，6 个独立 get 与 6 个云台 status 正常，双轴 PWM 关闭。首次真实采集 430 个空帧；断电检查重连后 935 个完整帧、空帧 0，已有实际模型输入快照。不能由这次先后关系确定空帧根因，也不能将固定样例通过视作真人识别通过。证据见[实机报告](../artifacts/face-selftest-runtime-20261031.json)。

重连后首次 60 秒用户标记正视采样为 473 条零脸；同位置后续模型图只见额头/眼镜，不能作为正脸准确性试验。后续调整时先在 Chrome 获取新画面确认完整脸入镜，再释放网页 USB 记录日志；曾有一次终端图像分块损坏，重试时发现 Chrome 已持有串口，故改用已连接的网页获取画面，未强行抢占。后续完整正脸截图只保留在 `.local`，不写入版本化报告。
