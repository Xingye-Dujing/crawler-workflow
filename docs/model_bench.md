# 本机模型基准（RTX 4060 Laptop 8GB / i7-14650HX / 16GB）

`ml_train/scripts/bench.py` 顺序测每个模型：固定 2,000 行、固定种子 42、同一 analyze 路径，记录准确率、rows/s 与峰值显存。原始回执在 `ml_train/logs/model_bench/*.json`。

## 情感极性（2026-11-20）

| 模型 | accuracy | rows/s | 峰值显存 | 备注 |
|---|---:|---:|---:|---|
| `sentiment_weibosenti_bin`（110M） | 0.9845 | 134.7 | 570MB | 原有默认 |
| `sentiment_rbt3`（3 层蒸馏） | **0.9845** | **743.0** | 719MB | 同准，快 5.5 倍 |

**结论**：按“最优指标 1 个百分点内取最快”的规则，rbt3 成为 `sentiment` 任务的推荐模型（`default_for: ["sentiment"]`）。

**口径**：这 2,000 行从 `weibo_senti_100k.csv` 抽出，两个模型都用它训练过，所以表中的 accuracy 是同机对照而非干净泛化；训练脚本自己的 5% 留出分别是 rbt3 0.9778、110M 0.9785，差距在 0.1 个百分点内。

**复现**：

```bash
.venv/Scripts/python.exe ml_train/scripts/bench.py --task sentiment \
  --models ml_train/models/sentiment_weibosenti_bin,ml_train/models/sentiment_rbt3 --rows 2000
```

## 待补基准

情绪六类、立场六类、句向量检索、语义去重、零样本：等各自候选模型下载/训练完成后按同一脚本补测；没有实测数字的模型不得进入 `default_for`。
