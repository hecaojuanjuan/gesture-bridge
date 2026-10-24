# HeadVoice（颔语）第一阶段原型

SPI BF3901 摄像头 → 连续 YOLO11n-pose → 有符号眼线倾斜 → 两动作编码 → 新动作确认 → 设备本地 PCM 播放。候选通过串口显示，不需要云端逐句核对。官方联网、配网、语音入口保留，舵机不初始化。

当前验证范围见 [验证记录](docs/validation.md)。没有连接 ESP32 开发板，不把主机测试或固件编译视为实机通过。

| 编码 | 固定短句 |
| --- | --- |
| AA | 我想喝水。 |
| AB | 我想休息一下。 |
| BA | 请过来协助我。 |
| BB | 我想自己来。 |

## 构建与烧录

在本项目根目录打开 PowerShell。本机系统 `python` 是 Store 别名，使用已验证的 Python：

```powershell
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

代码入口：`headvoice/core/` 为无设备依赖的生产 C 核心；`headvoice/firmware/` 为 FreeRTOS、摄像头、模型、音频、RGB 适配；`tools/prepare_sdk.py` 为核对官方源码后的确定性接入。没有实现大型前端、舵机、学习、自主设置或复杂平台工作流，也不代表完整赛事验收通过。
