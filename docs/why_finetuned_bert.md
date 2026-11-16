# 为什么这三类分析用微调 BERT，而不是通用大模型

情感 / 倾向 / 情绪三个节点的 `bert` 档（微调中文 BERT，`hfl/chinese-roberta-wwm-ext` 系）是**默认且主推**；`llm`（逐行
Ollama/OpenRouter）、`ml`（sklearn TF-IDF + 逻辑回归）是另两档，情感另有 `snownlp` 兜底。功能见 `docs/analysis.md`，
倾向选型见 `docs/tendency_model_comparison.md`；本文只回答“为什么不用大模型”。

## 结论

- 对**封闭标签集的逐行分类**（情感二/多类、情绪六类、立场六类），微调 BERT 在质量、速度、成本、确定性上同时占优：
  ~400MB 模型一次前向出一整批标签，固定标签集上不输通用大模型——因为标注本就来自大模型蒸馏。
- 需要**深度判断**（主题相关性、语义清洗、跨行结论、指代/讽刺推理）时，`llm` 仍是正确选择；二者分工。
- 任务形状正好是微调 BERT 的甜点区：标签集封闭固定（是分类不是生成）、单事件数千到数十万条、同一行每次必须同一标签
  （续跑/指纹/缓存的前提）、单机单用户且不强依赖联网 API。

## 与通用大模型对比

| | 微调 BERT | 通用大模型（qwen3.5:9b 类） |
|---|---|---|
| 质量 | 拟合大模型在固定标签集上的判断分布，便宜地追平老师 | 开放对话更强，但这里是六选一 |
| 每行计算 | 一次前向（≤512 token），出各类概率 | 逐 token 解码，成本随输出长度涨 |
| 输出 / 开销 | `id2label` 结构化概率；~400MB，进程内调用 | 正则抽标签，会漂移；9B daemon，逐行 HTTP |
| 断点/缓存 | 快到整列重算不心疼 | 需要昂贵答案缓存 + 逐行检查点 |

三点关键：**质量**来自蒸馏（qwen3.5:4b 在 26 万条真实微博上打六类标签，产出 `tendency_distilled.csv` 再微调）；
**可控**是结构化概率而非自由文本；**新 ≠ 好**——更大的编码器不保证窄标签集更好却更慢（`gte-base-zh` 实测退步，
英文 ModernBERT 的中文 tokenizer 失效）。

## 实测质量（每行标明语料/划分；同一模型在不同划分上是两个数）

| 任务·模型 | 语料 / 划分 | 指标 |
|---|---|---|
| 情绪 `emotion_ewect_six` | EWECT `usual_train` 27,766 条，3 epoch，5% 留出 | accuracy 0.811 / macro-F1 0.792 |
| 情感 `sentiment_weibosenti_bin` | `weibo_senti_100k`，3 epoch，5% 留出 | accuracy = macro-F1 = 0.9785 |
| 立场 `tendency_stance_v1`（蒸馏基线） | `tendency_distilled.csv` ~7,720 条，5% 留出 | accuracy 0.731 / macro-F1 0.681 |
| 立场 `tendency_stance_v2_cyberbully`（推荐） | 编码器对比 dev（seed 42，5%） | macro-F1 0.668 / Controversy F1 0.452 |
| 同上，并入 batch1 真实数据 | 8,208 条重训，同一 dev | macro-F1 0.681 / Controversy F1 0.537 |

稀有类 `Controversy` 与反讽 `Satire` 仍最弱，蒸馏受老师判断限制；但在**这个固定标签集 + 这个速度/成本约束**下够用。

## 实测吞吐（生产代码路径）

条件：RTX 4060 Laptop 8.6GB、torch 2.14.1+cu126 / transformers 5.13.0、fp32、batch 32 / max_len 512，数据为
`ml_train/datasets/tendency_distilled.csv` 的 `text` 列 8,208 行真实微博；模型加载单列不计入吞吐。三个模型整列分别
34.79 / 34.22 / 34.71 s，即约 **230–240 条/秒**（均值 ≈237），2 万条约 1.5 分钟、10 万条约 7 分钟；冷加载 1.77–7.34 s。

对照同一 `LLMClient`、同一 GPU、串行逐行（Ollama 节点本就 `workers=1`）：qwen3.5:9b ≈0.29 rows/s、4b ≈0.31 rows/s，
同一 8,208 行约 7–8 小时，**约 800 倍**差距。这是串行、单条、输出极短的 N=25 样本；绝对值随配置浮动，但一到两个数量级
由计算形状决定。数字绑定该环境（更快的卡/fp16 更高，CPU 低一个量级），不是普适承诺。

## 什么时候仍用 `llm`

- **主题相关性 / 语义清洗**、**跨行结论/摘要/报告段落**：前者判断“离题吗”，后者需要生成——都是 LLM 的职责。
- **小量探索性深度分析**：要模型“想一想”时用 `llm`；量大到需要续跑/成本可控时切 `bert`。`ml` 是纯 CPU 极轻量兜底。

## 诚实边界

- 上限受蒸馏老师约束，稀有类/反讽仍弱。**默认就是 `bert`**（`services/analysis/process.py` 的 `PROCESS_ENUMS`）；
  `bert` 跑不动时（缺 `torch`/`transformers` 或无注册模型），**节点执行器挑一个免依赖回退档并打印实际用了哪种**：
  `emotion`/`tendency` → `ml`，`sentiment` → `snownlp`，绝不静默把 A 模型的结论写进 B 模型声称的列。分析器被直接当
  `bert` 调用时缺依赖仍**按名拒绝**；勾 ≥2 模型的多模型对比**不降级**、维持按名拒绝。
