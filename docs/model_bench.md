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

## 情绪六类（2026-11-20）

训练脚本自身的留出指标（同一基础语料 SMP2020-EWECT usual_train）：

| 模型 | macro-F1 | 训练轮次 | 结论 |
|---|---:|---:|---|
| `emotion_ewect_six`（110M，原默认） | **0.792** | 3 | 保持默认 |
| `emotion_rbt6`（6 层蒸馏） | 0.7426 | 1 | 低约 5 分，不切换 |

轻量版 1 分钟即可训完，但质量未进 1 分区间，按规则不做默认；保留为显存紧张时的快速档。

## 立场六类（2026-11-20）

训练脚本 DEV（Qwen 蒸馏标签，衡量“模仿老师”而非人工真值）：

| 模型 | macro-F1 | 训练轮次 | 结论 |
|---|---:|---:|---|
| `tendency_stance_v2_cyberbully`（110M，推荐） | **0.668**（dev seed42，另一次 0.681） | 多轮 + 自训练 | 保持默认 |
| `tendency_rbt6`（6 层蒸馏） | 0.4945 | 1 | 低约 17 分，不切换 |

rbt6 的稀有类 Controversy 在 1 轮后 F1 为 0；小模型在这个任务上不能只靠缩短训练追平。保留为速度对照，不作默认。

## 待补基准

句向量检索（gte-small vs bge-small）、语义去重、零样本、重排：等各自候选下载/接入后按同一脚本补测；没有实测数字的模型不得进入 `default_for`。
