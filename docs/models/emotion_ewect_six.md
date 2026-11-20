# emotion_ewect_six（情绪六类）

- **任务**：process 节点 `operation=emotion`，`mode=bert`（默认）。
- **标签**：Anger / Fear / Joy / Neutral / Sadness / Surprise，顺序与 `config.json` 的 `id2label` 一致。
- **输出列**：`emotion`（标签）、`confidence`（该标签概率）。
- **权重**：`ml_train/models/emotion_ewect_six`，基座 `hfl/chinese-roberta-wwm-ext`，fp32，约 391MB。
- **实测**（SMP2020-EWECT usual_train，5% 留出）：accuracy 0.811，macro-F1 0.792。
- **吞吐**：RTX 4060 Laptop，batch 32 / max_len 512，约 236 行/秒（同一机器 8,208 行基准，见 `docs/why_finetuned_bert.md`）。
- **适用**：封闭六类标签、大批量逐行标注、需要结构化概率。
- **不适用**：讽刺/反语细分、跨行结论、开放标签的临时情绪。
- **许可**：Apache-2.0（基座与本项目权重）。
- **训练**：`ml_train/scripts/train_emotion_bert.py`；备份在 `ml_train/backups/models/<时间戳>/`。
