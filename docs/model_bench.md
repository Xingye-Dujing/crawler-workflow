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

## 本地 Ollama 多选一 / 短标签实测（2026-11-21）

`ml_train/scripts/bench_ollama_llm.py`,C-Eval 验证集 6 个中文科目 100 题（A/B/C/D）+ 微博情感 60 条,
同一 prompt、固定 seed 42、温度 0、`think=false`、每次只生成 1–2 个 token。
原始报告:`ml_train/logs/llm_bench/ollama_qwen_mcq_20261121.json`。

| 模型 | 体积 | C-Eval 准确率 | 情感准确率 | 调用/秒 | 备注 |
|---|---:|---:|---:|---:|---|
| `qwen3.5:0.8b` | 1.04GB | 0.39 | **0.8167** | 0.34 | 100% GPU |
| `qwen3.5:2b` | 2.74GB | 0.54 | 0.7833 | 0.34 | 100% GPU |
| `qwen3.5:4b` | 3.39GB | **0.66** | 0.7333 | 0.33 | 100% GPU,当前批量档 |
| `qwen3.5:9b` | 6.59GB | 0.73 | 未测 | 0.31 | **20% CPU / 80% GPU**,部分层已溢出 |

**结论:4b 仍是“速度/配置同档”里质量最好的已装模型。** 9B 多选一只高 7 点,但体积翻倍且已开始
CPU 卸载,速度更慢,不再同档;按体积/速度分档,批量档继续用 4b,难例/生成继续用 9b。
2b/0.8b 逐行短标签看着不差,但那是 60 条样本上的 2–5 条差距(噪声),且 C-Eval 明显更弱,
不适合做需要判断的任务。

**速度的关键发现**:四个模型的调用速度几乎相同(0.31–0.34 次/秒),与本项目此前测的 0.29 行/秒
一致 —— 逐行 LLM 的瓶颈是每次请求的固定开销,不是参数量。因此换同档模型不会变快;
加速只能靠“少调用 LLM”:封闭标签交给微调 BERT,LLM 只做清洗/主题命名/报告。

**未完成的跨家族对比**:`gemma4:e4b`(5.5GB)下载到 85%(约 4.7GB)时按用户要求停止;
`minicpm5:1b` 在 Ollama 库里不存在。因此没有证据表明存在“同体积同速度但质量更高”的非 Qwen 替代,
不能凭规格编造。需要时按 `ollama pull gemma4:e4b` 完成后用同一脚本补测。

情感那 60 条不建议当真:BERT 已经在同一任务上达到 0.98,LLM 跑它属于用错工具;这里只是验证指令遵循。

## 情感极性·多语料版（2026-11-21）

`ml_train/scripts/train_sentiment_mixed.py`：在原 weibo_senti_100k 之上并入四个新数据集，每个来源按 seed 42
各留 5% 做留出；旧默认和新模型在同一批行上评测。原始报告：`ml_train/logs/mixed_train/sentiment_mixed.json`。

| 数据集 | 新 `sentiment_mixed_rbt3` accuracy / macro-F1 | 旧 `sentiment_rbt3` |
|---|---|---|
| 混合留出（6,374） | **0.9597 / 0.9587** | 0.9321 / 0.9304 |
| JDReview test（533） | **0.8987 / 0.8375** | 0.7880 / 0.7270 |
| OnlineShopping test（1000） | **0.9230 / 0.9228** | 0.7990 / 0.7985 |
| waimai test（1000） | **0.8990 / 0.8825** | 0.7430 / 0.7326 |

**结论：四个集合全胜，且三个外部测试集旧模型从未训练过。默认切换为 `sentiment_mixed_rbt3`。**
吞吐对照（同机 `bench.py --task sentiment --rows 2000`，报告 `ml_train/logs/model_bench/sentiment_20261121_113726.json`）：
新模型 **334.6 行/秒**、峰值 476MB，旧模型 174.2 行/秒、327MB（两者在该抽样上 accuracy 同为 0.9845，
属含训练行的同机对照，不是干净泛化）。旧权重保留在 `ml_train/models/sentiment_rbt3` 与备份目录；
回退只需把清单的 `default_for` 移回。
注意这里的“混合留出”里 weibo 那部分旧模型可能见过（原模型用全量语料训练），所以真正的干净证据是三列外部测试集。

## 情绪六类·多语料实验（2026-11-21）

`ml_train/scripts/train_emotion_mixed.py`：EWECT usual_train + 对话情绪 2,809 行（只取与项目六类精确对应的
5 类；关切/厌恶/疑问按名丢弃），每来源 5% 留出。原始报告：`ml_train/logs/mixed_train/emotion_mixed.json`。

| 数据集 | 新 `emotion_mixed_v1` accuracy / macro-F1 | 旧默认 `emotion_ewect_six` |
|---|---|---|
| 混合留出（1,528） | 0.8141 / 0.7972 | 0.8135 / **0.7983** |
| EWECT 官方评测（2,000） | 0.7885 / 0.7528 | **0.7915 / 0.7579** |

**结论：不切换。** 混合留出基本打平（差 1 行、macro-F1 还略低），官方留出集新模型低 0.3–0.5 点，
属于噪声范围内但没有胜出证据；新模型权重会在清理时删除，旧默认保持不变。

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

## 检索/重排候选基准（2026-11-21，已完成）

2026-11-21 新增候选：`bge-base-zh`、`bge-large-zh`、`bge-reranker-v2-m3`、`cluener-ner`、`cold-offensive`
已入清单与资产表，并已实测（结论见下）。未入选的权重与基准数据集已在清理时删除，**清单和资产表条目保留**，
需要复测时按下面命令重新下载即可，不必重复判断“要不要试”：

```bash
.venv/Scripts/python.exe ml_train/scripts/fetch_assets.py --kind models \
  --only bge-base-zh,bge-large-zh,bge-reranker-v2-m3,cluener-ner,cold-offensive
.venv/Scripts/python.exe ml_train/scripts/fetch_assets.py --kind datasets --only t2-reranking
.venv/Scripts/python.exe ml_train/scripts/bench_retrieval.py --task embedding --dataset t2-reranking \
  --rows 200 --sample 400 \
  --models BAAI/bge-small-zh-v1.5,BAAI/bge-base-zh-v1.5,BAAI/bge-large-zh-v1.5,thenlper/gte-small-zh
.venv/Scripts/python.exe ml_train/scripts/bench_retrieval.py --task reranker --dataset t2-reranking \
  --rows 200 --sample 400 --batch-size 8 \
  --models BAAI/bge-reranker-base,BAAI/bge-reranker-v2-m3
```

固定 seed 42、同一留出切片，原始报告保留在 `ml_train/logs/model_bench/retrieval_*.json`;
没有实测数字的模型不进入 `default_for`。LCQMC 因为四个模型 recall 全部饱和到 1.0，不用于选型。

### 2026-11-21 句向量实测（T2Reranking，200 query / 6,327 候选，RTX 4060 Laptop）

| 模型 | recall@10 | rows/s | 峰值显存 |
|---|---:|---:|---:|
| `bge-small-zh-v1.5`（现默认） | 0.975 | **145.9** | 886MB |
| `bge-base-zh-v1.5` | 0.985 | 42.5 | 1,660MB |
| `bge-large-zh-v1.5` | **0.990** | 17.2 | 2,806MB |
| `gte-small-zh` | 0.965 | 220.9 | 1,711MB |

report: `ml_train/logs/model_bench/retrieval_embedding_20261121_105421.json`

**决定：默认仍用 `bge-small-zh-v1.5`。** 前三名的 recall 差距只有 3 行/200 query（0.975 vs 0.990），
在 200 行样本上不构成显著差异；而 small 的吞吐是 base 的 3.4 倍、large 的 8.5 倍，显存也最低。
按“最优 1 个百分点内取最快”的规则，base/large 虽在 1 分区间内，但收益未证明、代价实测明确，
所以不切换；`gte-small` 更慢更差，也不切。LCQMC 的对照因为四个模型 recall 全部为 1.0（饱和），
不用于选型。

### 2026-11-21 重排实测（T2Reranking，200 query / 400 对，同 seed）

| 模型 | pairwise accuracy | pairs/s | 批次 | 峰值显存 |
|---|---:|---:|---:|---:|
| `bge-reranker-base`（现默认） | 0.68 | **76.4** | 32 | 1,606MB |
| `bge-reranker-v2-m3` | 0.69 | 0.5 | 8 | 5,424MB |

report: `ml_train/logs/model_bench/retrieval_reranker_20261121_105923.json` 与
`ml_train/logs/model_bench/retrieval_reranker_20261121_111333.json`

**决定：默认仍用 `bge-reranker-base`。** 1 个百分点的准确率差（400 对里的 4 对）在样本噪声内，
而 v2-m3 即便用小批次也只有 base 的 1/150 吞吐、峰值显存是 3.4 倍；它第一次与 base 同进程加载时
还触发了 8GB 卡的 CUDA OOM。注意两者批次不同（8GB 卡跑不动 v2-m3 的 batch 32），所以吞吐差距是
保守下界；质量差则同批数据、同 seed，可比。

句向量检索（gte-small vs bge-small）、语义去重、零样本、重排：等各自候选下载/接入后按同一脚本补测；没有实测数字的模型不得进入 `default_for`。
