# emotion_rbt6（情绪六类·轻量版）

- 基座 `hfl/rbt6`（6 层），`train_emotion_bert.py --base hfl/rbt6 --epochs 1`，fp16，约 83MB。
- 本机实测（EWECT usual_train，2000 行 official eval）：accuracy 0.7690，macro-F1 **0.7426**；5% 留出 macro-F1 0.7326。
- 对照原 `emotion_ewect_six`（110M，3 epoch）：macro-F1 **0.792**。**低约 5 个百分点**，按“1 分内取最快”的规则不切换默认。
- 训练仅 1 分钟，可作为显存紧张时的快速档与速度对照；要追平原质量需要更多轮次/类权，尚未实测。
- 许可 Apache-2.0。备份在 `ml_train/backups/models/<时间戳>/`。
