# sentiment_rbt3（情感极性·蒸馏轻量版）

- **任务**：process 节点 `operation=sentiment`，`mode=bert`。
- **基座**：`hfl/rbt3`（3 层中文 RoBERTa），`ml_train/scripts/train_sentiment_bert.py --base hfl/rbt3` 微调 1 轮，fp16。
- **标签 / 输出列**：与 110M 极性模型相同（`negative/positive` → `sentiment/score`）。
- **本机实测**（RTX 4060 Laptop，batch 32 / max_len 512，2,000 行）：
  - accuracy **0.9845**，**743 行/秒**，峰值显存 719MB。
  - 对照 `sentiment_weibosenti_bin`：accuracy **0.9845**，**134.7 行/秒**，峰值显存 570MB。
  - 同准情况下吞吐约为 **5.5 倍**；训练脚本自己的 5% 留出为 0.9778（macro-F1 同）。
- **口径说明**：2,000 行基准从 `weibo_senti_100k.csv` 抽样，两个模型都在这份语料上训练过，所以 0.9845 是**同机对照值，不是干净泛化估计**；干净留出请看训练脚本的 0.9778 与原模型的 0.9785。
- **适用**：量大、要快、封闭二分类标签；显存紧张时与别的模型同时跑。
- **不适用**：未见过的新事件域名的零样本判断；要生成解释的场景。
- **备份**：`ml_train/backups/models/<时间戳>/sentiment_rbt3`，带 SHA-256 清单。
