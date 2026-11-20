# sentiment_weibosenti_bin（情感极性）

- **任务**：process 节点 `operation=sentiment`，`mode=bert`（默认）。
- **标签**：negative / positive；中性由 `label_for_score` 按 0.6/0.4 阈值产生，不是模型输出。
- **输出列**：`sentiment`、`score`（正面概率）。
- **权重**：`ml_train/models/sentiment_weibosenti_bin`，基座 `hfl/chinese-roberta-wwm-ext`，fp32，约 391MB。
- **实测**（weibo_senti_100k，5% 留出）：accuracy = macro-F1 = 0.9785。
- **吞吐**：同机约 240 行/秒。
- **适用**：舆情正负统计、大批量确定性打分。
- **不适用**：六类情绪、立场/网暴判断、要生成解释的场景。
- **许可**：Apache-2.0。
- **训练**：`ml_train/scripts/train_sentiment_bert.py`；备份在 `ml_train/backups/models/<时间戳>/`。
