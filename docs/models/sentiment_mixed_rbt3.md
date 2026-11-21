# sentiment_mixed_rbt3（情感极性·多语料版）

- 清单：`tools/model_manifests/sentiment_mixed_rbt3.json`;权重：`ml_train/models/sentiment_mixed_rbt3`。
- 基座与训练：`hfl/rbt3`，3 epoch，fp16 batch 32，max_len 128，seed 42；脚本 `ml_train/scripts/train_sentiment_mixed.py`。
- 语料：weibo_senti_100k（119,988）+ ChnSentiCorp（7,766）+ JDReview（3,729）+ OnlineShopping（8,000）+ waimai（8,000），
  每个来源单独留 5% 做留出，不混到训练集里。标签映射在脚本里显式写出（JD 的 0=POS 因此取反）。
- 原始报告：`ml_train/logs/mixed_train/sentiment_mixed.json`;训练 stdout：`ml_train/logs/train_sentiment_mixed_rbt3_20261121.log`（清理时删除，数字已落本报告与下方表格）。

| 数据集 | 新模型 accuracy / macro-F1 | 旧默认 `sentiment_rbt3` |
|---|---|---|
| 混合留出（6,374 行） | **0.9597 / 0.9587** | 0.9321 / 0.9304 |
| JDReview test（533） | **0.8987 / 0.8375** | 0.7880 / 0.7270 |
| OnlineShopping test（1000） | **0.9230 / 0.9228** | 0.7990 / 0.7985 |
| waimai test（1000） | **0.8990 / 0.8825** | 0.7430 / 0.7326 |

四个集合全胜，且外部测试集是旧模型没见过的新域，所以 2026-11-21 起 `default_for=['sentiment']` 指向本模型。
旧模型仍在 `ml_train/models/sentiment_rbt3` 与 `ml_train/backups/models/20261121_102504/`，可随时回退。
