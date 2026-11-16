# 倾向六分类（tendency）模型对比与选型

目标：在 6 类、`Controversy`/`Reflection` 严重稀少的语料上选出更好的编码器与训练配置。实验在 gitignored 的 `ml_train/`
（`models/`、`datasets/`、`scripts/`、`logs/`，见 `ml_train/README.md`）完成，不改 `backend/` 的已部署模型。旧轨
`models/tendency_stance_v1/` 与新轨 `models/tendency_stance_v2_cyberbully/` 相互独立，靠倾向节点的“已注册模型”下拉
（或 `ml_train/models/…` 相对路径）切换。

## 设置
- 数据：`ml_train/datasets/tendency_distilled.csv`。初始蒸馏 7,721 行（Objective/Praise/Satire 各 1600、Criticism 1336、
  Advocacy 1221、Controversy 364）；并入 batch1 真实数据后为 **8,208 行 / Controversy 388**。batch2 已回退、搁置在
  `controversy_labeled.csv`，不入训练。
- 标签来源：Qwen（本地 Ollama）蒸馏，`ml_train/scripts/distill_tendency_labels.py` 的输出；所以所有 macro-F1 都是
  “编码器 vs Qwen 标签”的**模仿度**，不是人工真值准确度。
- 硬件/软件：RTX 4060 Laptop 8GB、torch 2.14.1+cu126、transformers 5.13.0、bf16、max_len 128、seed 42。脚本
  `ml_train/scripts/train_tendency_bert_v2.py` 驱动 `run_encoder_comparison.py` / `run_tuning_sweep.py`；dev 是同一份 5%
  随机切分（seed 42），`load_best_model_at_end` 按 f1_macro 选点。

```bash
.venv/Scripts/python.exe ml_train/scripts/run_encoder_comparison.py
.venv/Scripts/python.exe ml_train/scripts/run_tuning_sweep.py
.venv/Scripts/python.exe ml_train/scripts/train_tendency_bert_v2.py --base hfl/chinese-roberta-wwm-ext --class-weights --confusion
```

## 编码器对比（同一 dev，macro-F1 降序）
| 配置 | base | 类权重 | dev acc | dev macro-F1 | Controversy F1 |
|---|---|---|---|---|---|
| wwmext_cw | hfl/chinese-roberta-wwm-ext | 是 | 0.7047 | **0.6680** | 0.4516 |
| cmb_large_cw | feynmanzhao/chinese-modernbert-large-wwm | 是 | 0.6606 | 0.6459 | **0.5385** |
| wwmext | hfl/chinese-roberta-wwm-ext | 否 | 0.7176 | 0.6440 | 0.2353 |
| gte | thenlper/gte-base-zh | 否 | 0.6658 | 0.5967 | 0.1538 |
| gte_cw | thenlper/gte-base-zh | 是 | 0.6580 | 0.5949 | 0.2000 |

- **类权重是唯一明确的大收益**：macro-F1 0.644→0.668，Controversy F1 0.235→0.452，且不丢数据（优于把每类砍到 364）。
- **`gte-base-zh` 是退步**（embedding 向骨干不适合蒸馏分类），已弃。
- 中文 ModernBERT-large 整体略低但 Controversy F1 最高，可作“稀有类优先”的备选。
- **英文 ModernBERT 弃用**：英文 tokenizer 中文失效。

## 调参与诊断
冠军配置（wwmext + 类权重）上扫描 focal / LR 四组：focal_lr3e5 0.6625、ce_base 0.6573、focal 0.6482、focal_lr1e5_ep4
0.6463。同一配置两次独立运行得 0.668 与 0.6573，噪声约 ±0.011，所以 **< 0.015 的差异不显著**；focal 与 LR 没有可靠增益。

混淆矩阵的 Top 误分：`Satire→Praise 15`、`Criticism→Controversy 10`、`Objective→Praise 9`、`Objective→Advocacy 9`、
`Satire→Criticism 8`。**瓶颈是类边界，不是模型容量**：反讽字面最像夸赞；Controversy 与 Criticism 语义相邻；中性陈述被读出立场。

## 选型与边界
**选定 `hfl/chinese-roberta-wwm-ext` + 类权重**：dev macro-F1 ≈0.668、Controversy F1 ≈0.45，是实测最高且稳定的配置。
**不要把 Controversy 并入 Criticism**：会抬高整体分数却消灭目标类；真正该重定义的是 Satire↔Praise。Controversy 的问题要靠
更好的类定义 + 更多真实数据解决。

- 所有分数是**模仿度**，人工留出集尚未标注（唯一能给出真值准确度与老师上限的手段）；单次运行约 ±0.011 噪声，未做多 seed
  平均，dev 仅 5%（约 386 行），稀有类 per-class F1 方差大。
- 有效杠杆：类权重、真实热度窗口爬取、未标注池自训练（间接）。三者把 Controversy F1 从 0.235 抬到 ~0.49–0.54。
- 真实数据要用**事件热度窗口**爬（`ml_train/scripts/crawl_controversy.py`：关键词→帖子→评论，结果进 `data/exports/` 与
  `ml_train/datasets/controversy_crawl.csv`，带 keyword/source_url/日期可回溯）；不带时间窗口只拿到冷帖。
- 自训练只保留置信 ≥0.9 的伪标签、验证集仍用真实标注；伪标签里 Controversy 为 0，所以增益是间接的，直接增益仍靠真实标注；
  只跑 1 轮，更多轮需人工留出集把关。
- batch2（13 个明星/八卦事件）在**固定评估 A/B** 下净效应为 macro-F1 −0.018、Controversy −0.042（超噪声），已回退到
  batch1-only。**相关性 > 数量**；跨语料版本的分数不可直接比，必须同一 val 才能归因。`ml_train/README.md` 把推荐模型
  四舍五入成 ≈0.69 / ≈0.50，本文精确值是 0.681 / 0.537——同一组数，两种精度。若优先救稀有类，备选
  `chinese-modernbert-large-wwm`（Controversy 0.539），代价是整体略低与显存（batch8/grad-accum4）。
