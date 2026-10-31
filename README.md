# HeadVoice（颔语）第一阶段原型

当前成果总入口：[2026-10-31 GitHub 快照](docs/github-snapshot-2026-10-31.md)。包含手部检测与分类器适配、面板、设计和实测记录，以及远端海报、外壳和历史实验；具体手型分类及自动居中尚未完成验收。快照之后的开发不包含在此次上传中。

当前设备测试请先看 [2026-10-31 下一轮实机测试清单](docs/next-device-tests-2026-10-31.md)。以下保留早期阶段与构建记录；设备当前应用和验收状态以清单为准。

2026-10-31 早期构建记录：新增 [RGB 控制面板与上板验证](docs/control-panel.md)，已接入真实设备指令/回执，并发布到奶龙 PID 11785。修复缓慢回正丢失动作，加入摄像头耗时拆分与时序检查；baseline、stage 2/3 均编译通过。当时灯效、手机云端写操作和真人姿态尚未复测；后续灯效与 face stage 2 结果见上方测试清单。[六轴模块用途与引脚冲突](docs/imu-options.md)已整理，尚未启用采样或融合。

SPI BF3901 摄像头 → 连续 YOLO11n-pose → 有符号眼线倾斜 → 两动作编码 → 新动作确认 → 设备本地 PCM 播放。候选通过串口显示，不需要云端逐句核对。官方联网、配网、语音入口保留，舵机不初始化。

2026-10-30 已完成[最小舵机固件](diagnostics/servo-minimal/README.md)对照并恢复完整云台固件，摄像头预览可用，两路输出已关闭。使用者确认完整固件下水平轴能带动摄像头往返；上方舵盘曾转动但摄像头支架不随动，待断电检查固定连接并复测俯仰轴。自动居中尚未通过实机验收。此前官方 `baseline` 已恢复可听语音回答，本次恢复后尚未复测语音回答；旧 HeadVoice stage 2 崩溃根因尚未修复。详情见[验证记录](docs/validation.md)和[双轴说明](docs/camera-auto-center.md)。

早期验证范围见 [验证记录](docs/validation.md)。基础联网语音及摄像头 stage 1 连续取帧已有实机记录。旧 COCO stage 2 曾测到左右侧倾符号可分及遮挡拒识，但中立读数波动、约 2.68 秒推理耗时尚不满足连续动作输入；后续 face 后端的结果见上方测试清单。动作组合和固定短句播放仍待实测。不把主机测试或固件编译视为实机通过。

| 编码 | 固定短句 |
| --- | --- |
| AA | 我想喝水。 |
| AB | 我想休息一下。 |
| BA | 请过来协助我。 |
| BB | 我想自己来。 |

## 构建与烧录

在本项目根目录打开 PowerShell。本机系统 `python` 是 Store 别名，使用已验证的 Python：

```powershell
Set-Location -LiteralPath 'C:\Users\jiawa\Desktop\gesture-bridge'
$py = 'C:\Users\jiawa\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
$env:PYTHONUTF8 = '1'
# 依赖已安装；新环境首次执行这一行。
# .\tools\bootstrap.ps1 -Python $py
& $py tools/test_core.py
& $py tools/verify_audio.py
& $py tools/build.py baseline build
& $py tools/build.py headvoice build --stage 1
```

先按下文顺序上板验证，再构建下一个阶段：

```powershell
& $py tools/build.py headvoice build --stage 2
& $py tools/build.py headvoice build --stage 3
```

`baseline` 和 `headvoice` 使用独立应用/构建目录。相应固件分别在 `.work/baseline/apps/build/` 和 `.work/headvoice/apps/build/`，应用文件名均为 `vb701n.bin`。构建脚本启用响应文件，避免 Windows 长路径超过命令行长度限制。构建时核对官方 HEAD、固定音频哈希和文本；官方源码始终位于 `vendor/official-sdk`，不直接修改。`artifacts/integration.patch` 记录应用接入差异。

产品身份可通过本机 `.local/cloud.json` 设置，内容为 `pid`（正整数）和 `secret`（32 位十六进制字符串）。此目录由 Git 忽略；每次构建仅修改 `.work` 下的应用副本，官方源码及公开接入补丁不包含个人密钥。缺少该文件时使用官方默认配置。更换身份后先验证动态注册及 AGENT 绑定，不主动清除已保存的 Wi-Fi。

枚举真实端口后再烧录，COM1 是本机 ACPI UART，并非已识别的开发板：

```powershell
$idfpy = '.tools/espressif/python_env/idf5.4_py3.12_env/Scripts/python.exe'
& $idfpy tools/capture_serial.py --list
$port = 'COMx' # 替换为开发板实际端口
& $py tools/build.py baseline flash --port $port
& $py tools/build.py baseline monitor --port $port
# 基线实机通过后，再烧录对应阶段。
& $py tools/build.py headvoice flash --port $port
& $idfpy tools/capture_serial.py --port $port --seconds 120 --output artifacts/device.jsonl
& $py tools/summarize_metrics.py artifacts/device.jsonl
```

`flash` 使用官方 `idf.py flash`，烧录分区表、应用、引导程序及姿态模型；首次不要只烧应用。不执行整片擦除。串口日志为 115200 8N1；监视器与采集脚本不要同时占用端口。退出 IDF monitor 使用 `Ctrl+]`。

### 单张摄像头预览

HeadVoice 和当前云台固件支持 `hv_camera snapshot`。关闭其他串口程序，在项目根目录执行：

```powershell
& '.\.tools\espressif\python_env\idf5.4_py3.12_env\Scripts\python.exe' tools/camera_preview.py --port COM3 --output .local/camera-preview.png
if ($LASTEXITCODE -eq 0) {
    Invoke-Item -LiteralPath '.local/camera-preview.png'
}
```

端口改变时先重新枚举。每次导出一张低分辨率 PNG，覆盖同名文件；脚本检查数据块顺序和整帧校验和后才保存。图像保存在 Git 忽略的 `.local` 中。原始预览为 120×160 RGB565，脚本依据固件旋转配置显示；当前装配启用顺时针 90°，PNG 为 160×120。导出占用串口带宽，性能采样时不要同时拍照。

当前装配构建命令为 `& $py tools/build.py headvoice build --stage 2 --rotate-cw90`。后续构建其他阶段时也要显式传入当前装配所需的旋转选项。两种构建副本均关闭 nano printf，以正确输出 64 位时间戳和结构化诊断；官方 SDK 原件保持不变。

更换 PID 后，新设备需要重新通过小程序 BLE 配网并绑定账号。串口输入 `hv_provision status` 可核对 PID；输入 `hv_provision restart` 会调用官方复位配网函数，清除已保存的 Wi-Fi、配网环境及本地绑定标记，然后重启进入 BLE 配网。它不会请求删除旧账号设备或整片擦除 Flash。手机在配套小程序内发现蓝牙设备并下发 2.4 GHz Wi-Fi 信息，通常不需要先在系统蓝牙设置里手动配对。

语音链路诊断：`hv_voice stats` 输出自启动以来的麦克风 PCM 包数、字节数、非零采样数、累计峰值、最后一包帧龄，以及真实 Agora 发送成功包数、字节数和失败计数。新构建分为 `HVVOICE`（麦克风）、`HVVOICETX`（上行）和 `HVVOICECTRL`（任务/内存）三行，避免 SDK 的 256 字节输出缓冲截断；后者输出 `control_task_found`、`control_stack_free_min_bytes`（控制任务自启动以来最小剩余栈空间，单位字节）和内部堆空闲/最大连续块；任务不存在时不能把零值当作栈耗尽。间隔 5 秒查询并比较增量；发送成功仅表示 SDK 接收了上行数据，不证明云端收到或识别成功。`hv_voice net` 只读检查 Wi-Fi 关联、RSSI 和是否已获得 IP，不输出热点名称或密码；关联成功不等于云端在线。`hv_voice debug` 打开生命周期、上/下行和计数日志，不开启鉴权载荷打印。统计不保存原始录音，也不改变动作识别或正式短句播放规则。

2026-10-31 实机确认本板唤醒事件为 **`wakeup: 你好小鹰`**，使用“你好，小鹰”。官方使用文档第 8 页写的是默认“你好，小灵”，不能用该默认值覆盖实际语音芯片上报。先确保原热点开启并连云；唤醒提示音也不代表对话成功。本轮曾在启动 Agora 时触发 `qm_agent_ctl` 栈溢出，修复及实机范围见[语音诊断记录](docs/validation.md#2026-10-31-语音唤醒热点恢复与控制任务栈溢出)。

## 上板操作顺序

1. **官方基线**：使用官方配网方式完成 Wi-Fi/平台连接，观察 `cloud connected`，唤醒并完成真实语音对话。产品身份配置仍由官方 `cloud/ljyd_cloud.h` 管理。本仓库没有创建或核实平台账号。
2. **stage 1**：只取连续摄像头帧，不初始化模型。确认 `bsp_camera` 的有效帧计数稳定增长且 `empty` 不增长；确认数据格式为 240×320 UYVY。接线见官方 `apps/main/peripheral/bsp_camera.h`：3.3V、GND、SDA21、SCL47、CS4、SCLK13、D0=8、PWDN41。
3. **stage 2**：启用真实图像转换与推理，保持联网并同时进行语音对话。串口 `HV pose` 显示人数、眼线倾斜、有效性、帧龄和推理耗时，`HV metrics` 每 5 秒显示有效频率与内存。此阶段不会输入编码或播放表达。
4. 确认画面竖直、单人时关键点有效，左右侧倾符号相反。默认正眼线倾斜为 A、负倾斜为 B；这只是图像空间倾斜，并非 yaw/roll 三维角度。装配方向需要时使用 `--rotate-cw90`，A/B 相反时使用 `--invert-tilt`；每次构建显式传入需要的选项。
5. **stage 3**：启动后保持个人舒适中立姿态，连续观察至少 2 秒且至少 10 帧，波动不超过 5°；校准后再观察中立约 350 ms。校准本阶段仅存在 RAM，重启重新采样。
6. 做 A：侧倾并保持至少 600 ms，再回正并稳定至少 350 ms。每段至少 3 个不同时间戳的有效观察。先完成 AA，串口出现候选“我想喝水。”且亮黄灯；未确认不会播放表达。
7. 候选出现后先重新稳定中立，再做一次完整 A 确认或 B 取消。最后一个编码动作不能充当确认。确认后结束当前语音对话、临时关闭上传、使用设备音频控制器播放缓存，播放时亮蓝灯，完成后恢复官方语音入口。以后仍可唤醒对话；忙、抢占或播放失败不会自动重播。
8. 播放后重新回正，再验证 AB、BA、BB。分别测试一直保持不回正、候选取消、遮挡、多人、缺帧和恢复；恢复后从新组合开始。

RGB 使用官方 GPIO1 WS2812 驱动。灯带按官方要求 5V 供电并共地，摄像头使用 3.3V。白色为校准，黄色为待确认，蓝色为音频控制器报告正在播放，其余熄灭；串口同时提供状态。灯带未接不代表喇叭已通过。

## 参数与边界

默认中立 ±5°，动作 ±14°，回落阈值 ±9°，最大相对倾斜 45°；动作最长 5 秒，组合期限 8 秒，确认期限 10 秒。有效观察最大间隔、最大帧龄均为 400 ms。参数在 `headvoice/core/hv_core.c` 的 `hv_default_config()` 中集中定义，必须根据 stage 2 的实际分布调整并重测；推理慢时会拒绝输入，不会靠延时补出“连续观察”。

帧链路为驱动 2 个 MMAP 缓冲 + 应用 2 个原始帧槽 + 1 个最新观察邮箱。摄像头回调只复制，返回后驱动立即 `VIDIOC_QBUF`；推理完成 RGB 转换即归还原始槽。RGB 常驻缓冲只归推理任务使用。无效帧/多人/无效关键点会增加失效代数，邮箱覆盖不会吞掉失效；核心另有独立 20 ms 看门狗和时间戳检查。

驱动未提供实际曝光时间戳，记录的是出队时刻；摄像头任务持续排空，底层仍最多保留两帧。不能把该时间称为曝光时间。模型人数和遮挡判定仍须真人验证，未检测到的第二个人不能由状态机补救。

四句音频是 Windows 离线慧慧语音生成的 16 kHz/单声道/S16LE PCM，共 268480 字节，嵌入只读固件，不占用 SPIFFS；文本和 SHA-256 见 `headvoice/audio/manifest.json`。尚未人工听测或在设备喇叭播放验证。重新生成可执行 `tools/generate_audio.ps1`、`tools/pack_audio.py`，随后重新听测。

`audio_started_estimate` 是音频控制器状态轮询的估计，不能替代实际出声延迟。使用同一外部录音/视频记录确认动作完成、候选显示与喇叭起声，再计算实际延迟。`tools/summarize_metrics.py` 对采集日志输出中位数、P95、最大值和失败数，实际可听延迟保留为空。

代码入口：`headvoice/core/` 为无设备依赖的生产 C 核心；`headvoice/firmware/` 为 FreeRTOS、摄像头、模型、音频、RGB 适配；`panel/` 为 H5 灯光与诊断面板；`tools/prepare_sdk.py` 为核对官方源码后的确定性接入。云台独立入口见双轴说明。尚未实现学习、自主设置或 IMU 融合，也不代表完整赛事验收通过。
