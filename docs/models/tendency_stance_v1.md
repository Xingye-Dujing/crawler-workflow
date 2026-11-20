# tendency_stance_v1（立场蒸馏基线）

- **任务**：`operation=tendency`，`mode=bert`，用于与 v2 做模型对比。
- **标签**：与 v2 相同的六类传播立场。
- **输出列**：`tendency`、`tendency_confidence`。
- **权重**：`ml_train/models/tendency_stance_v1`，约 391MB。
- **实测**（`tendency_distilled.csv`，5% 留出）：accuracy 0.731，macro-F1 0.681。
- **适用**：蒸馏基线对照、模型对比图。
- **不适用**：作为默认立场模型（v2 是推荐项）。
- **许可**：Apache-2.0。
- **训练**：`ml_train/scripts/train_tendency_bert_v1.py`。
