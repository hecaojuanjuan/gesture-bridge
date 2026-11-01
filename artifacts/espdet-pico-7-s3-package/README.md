# ESPDet-Pico 手势模型（ESP32-S3）

## 文件

`espdet-pico-7-s3-int8-20261101.espdl` 是面向 ESP-DL 的 EDL2 部署模型，文件头为 `EDL2`。它适用于 ESP32-S3；文件大小为 501,952 字节，SHA-256 为：

```text
4c1005d8fd73021c9b70007211dfb825cbd4c4f983bb8e64ae712fcdcf88ecca
```

同批的 `.pt` 是 PyTorch 训练检查点，不能直接写入 ESP32-S3 模型分区。本包只包含可由设备端 ESP-DL 加载的 `.espdl` 文件。

模型输入为 224×224 RGB，三个输出尺度为 28×28、14×14、7×7。板端预处理接收 320×240 RGB，并以 RGB(114,114,114) 补边。类别索引固定如下：

| 索引 | 类别 |
| --- | --- |
| 0 | `closed_fist` |
| 1 | `ok_sign` |
| 2 | `one_finger` |
| 3 | `open_palm` |
| 4 | `six_sign` |
| 5 | `thumbs_up` |
| 6 | `v_sign` |

## 设备与分区

目标设备为灵机 XJWB03（ESP32-S3、8 MB PSRAM、16 MB Flash），当前构建使用 ESP-IDF 5.4.1 和 ESP-DL 3.2.4。现有分区表中 `coco_pose` 数据分区从 `0x810000` 开始，大小为 `0x320000`；模型应写入该分区。此分区原先用于 COCO 姿态模型，替换前应先备份。应用分区 `ota_0` 从 `0x20000` 开始，大小为 `0x3f0000`。本流程不改写分区表。

## 部署

以下命令在仓库根目录的 PowerShell 中执行。先确认 USB 串口号，再设置文件路径并核验模型摘要：

```powershell
$PY = ".\.tools\espressif\python_env\idf5.4_py3.12_env\Scripts\python.exe"
$PORT = "COM5"
$MODEL = ".\artifacts\espdet-pico-7-s3-package\espdet-pico-7-s3-int8-20261101.espdl"
$BACKUP = ".\.local\coco_pose-before-espdet-$(Get-Date -Format yyyyMMdd-HHmmss).bin"

if (Test-Path $BACKUP) { throw "Backup file already exists: $BACKUP" }
if ((Get-FileHash $MODEL -Algorithm SHA256).Hash.ToLowerInvariant() -ne `
    "4c1005d8fd73021c9b70007211dfb825cbd4c4f983bb8e64ae712fcdcf88ecca") {
    throw "Model SHA-256 mismatch"
}
```

备份整个 `coco_pose` 分区，再写入模型文件。保留备份，便于恢复原 COCO 模型：

```powershell
& $PY -m esptool --chip esp32s3 --port $PORT --baud 460800 `
  read_flash 0x810000 0x320000 $BACKUP

& $PY -m esptool --chip esp32s3 --port $PORT --baud 460800 `
  --before default_reset --after no_reset write_flash `
  --flash_mode dio --flash_freq 80m --flash_size detect `
  0x810000 $MODEL
```

构建隔离的 ESPDet 摄像头测试应用。CMake 会从 `$MODEL` 计算模型大小和 SHA-256；固件按 `coco_pose` 标签查找分区，并在加载前校验摘要：

```powershell
& $PY tools\build.py headvoice build --stage 2 --vision coco `
  --work-name espdet-gesture-test `
  --hand-espdet-model $MODEL `
  --hand-espdet-partition coco_pose
```

只把生成的应用镜像写到 `ota_0`，不要对这个配置运行整片 `idf.py flash`，以免覆盖刚写入的模型分区：

```powershell
$APP = ".\.work\espdet-gesture-test\apps\build\vb701n.bin"
& $PY -m esptool --chip esp32s3 --port $PORT --baud 460800 `
  --before default_reset --after hard_reset write_flash `
  --flash_mode dio --flash_freq 80m --flash_size detect `
  0x20000 $APP
```

## 运行检查

只读采集串口日志即可检查模型与识别结果，不需要请求或传输 JPEG：

```powershell
$LOG = ".\.local\espdet-probe-$(Get-Date -Format yyyyMMdd-HHmmss).jsonl"
& $PY tools\capture_serial.py --port $PORT --seconds 20 --quiet --output $LOG
```

`HG {"event":"ready","backend":"espdet_pico_7","model_ready":true}` 表示模型分区摘要匹配且模型初始化成功。每个有效相机帧的 `HG` `espdet` 事件包含 `gesture`、`model_ms`、`total_ms`、分数和框；没有 `espdet` 事件时，不应把摄像头帧数或启动自检当作实时检测结果。

## 当前验证状态

2026-11-01 的板端启动自检对合成 RGB 输入预热 3 次、计时 20 次：模型耗时中位数 134.669 ms，含预处理和后处理的合计中位数 141.999 ms。该自检不使用摄像头图像，也不代表实时识别准确率。

最近一次重启日志识别到 BF3901，摄像头计数为 631 个有效帧、0 个空帧；但没有产生 `HG espdet` 实时检测事件，并出现两次任务看门狗告警。因此当前只能确认模型可加载和摄像头帧流恢复，不能确认端到端手势识别已验收。对应串口记录位于 `.local/espdet-gestures/retry-probe-20261101.jsonl`。
