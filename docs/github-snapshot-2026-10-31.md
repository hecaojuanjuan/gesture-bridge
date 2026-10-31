# 2026-10-31 GitHub 成果快照

本次保存本地 `8426810` 快照，并合并远端 `558195a` 及其前序提交。用户明确选择“先推已保存的快照”；快照之后另一窗口的修改不包含在本次上传中。

## 成果入口

| 内容 | 位置与状态 |
| --- | --- |
| 板端手部检测、同帧 JPEG、采样与分类训练工具 | [手势测试记录](hand-gesture-tests-2026-10-31.md)、`headvoice/firmware/hv_hand_*`、`headvoice/core/hv_hand_*`、`tools/collect_hand_samples.py`、`tools/train_hand_classifier.py` |
| 官方模型与适配代码 | `headvoice/third_party/hand_detect/`、`hand_gesture_recognition/`、`human_face_detect/`，保留上游来源、许可证和哈希 |
| H5 / USB 灯光与摄像头控制台 | [面板文档](control-panel.md)、`panel/`、`hv_panel.c` |
| 人脸后端、头部动作与云台 | [人脸后端](face-backend.md)、[双轴说明](camera-auto-center.md)、`headvoice/` |
| 实机过程及负结果 | [验证记录](validation.md)、`artifacts/*.json` 与面板截图 |
| 设计方案 | [双方案实现方案](design/AI硬件黑客松-双方案完整实现方案.md)、[HeadVoice](design/HeadVoice_软件开发文档.md)、[ExitCoach](design/ExitCoach_软件开发文档.md)，保留原设计状态 |
| 摄像头偏色排查文档 | [Word 文档](HeadVoice_摄像头画面偏色排查与修复方案.docx) |
| 海报与外壳模型 | [海报](../artifacts/poster/README.md)、[外壳](../artifacts/enclosure-v1/README.md)、`tools/generate_enclosure.py` |
| 远端另一版手掌／云台和旧面板 | [实验归档](../experiments/remote-558195a/ARCHIVE.md)，原文件逐字节保留，完整提交历史保留 |

## 算法进度边界

已有实机证据支持板端手部检测和同帧取图；张掌、握拳、V 字短测中的有效单手比例是检测覆盖率，不能当作手型分类准确率。快照附带自训练 CNN 的实现与训练／导出工具，但没有真实训练好的张掌／握拳权重。

官方 11 类分类器的模型、适配器、构建选项与部分门控／面板代码也保存了下来。冻结快照时完整应用接入仍在进行，`--hand-native-partition` 路径未在本次验证中完成固件编译或上板，不能把源码和模型已入库理解为 V 字／拇指／张掌识别已经可用。后续修改留待下一次提交。

自动居中继续暂缓。旧肤色检测云台与旧 `PANEL` 面板接口同当前 ESP-DL 检测及 `HP` 面板不兼容，因此原样移至实验目录，不参与主构建；海报、外壳与其他结果保留原目录。本次没有把旧实验的性能描述当作已确认结果。

## 本次实际验证

- 独立副本中 Python unittest **97 项通过**；面板 Node 测试 **81 项通过**，Vite 生产构建通过。
- 头部动作核心、云台核心、人脸关键点、灯光策略、MQTT 分词回归及四句 PCM 身份检查通过。
- 27 个固定上游文件的 SHA-256 核对通过；远端 74 个改动文件均在原位置或归档位置按字节保留。
- 初次快照测试有两项因未使用的 `second_count` 函数被 `-Werror` 拒绝；只移除该未引用函数后，全套 97 项复测通过。其原文仍保留在父提交 `8426810` 中。
- 候选文件扫描未发现已知本机云密钥、GitHub token 或私钥；命中的凭据字面量仅为测试夹具。`.local/`、原始串口日志、训练照片、编译固件、依赖和缓存继续由 Git 忽略。

机器可读结果见[验证摘要](../artifacts/github-snapshot-validation-20261031.json)。本次未重新编译整机固件、烧录、训练真实模型或测试设备；既有实机记录保留原日期与限制，不因上传而改变验收状态。
