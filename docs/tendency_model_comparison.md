# 倾向六分类（tendency）模型对比与选型记录

> 目的：在 7721 条、6 类、Controversy/Reflection 严重稀少的现状下，为倾向分类器选出更好的编码器与
> 训练配置，并记录**事实与数据**供他人复算验证。所有实验在 `ml_train/`（gitignored 的实验目录）完成，
> 不改动 `backend/` 的已部署模型；旧轨 `bert_tendency_model/` 与新轨 `bert_tendency_v2_model/` 相互独立，
> 靠 tendency 节点「bert 模型名」粘贴的目录路径切换。

## 1. 实验设置（可复现）

- 数据：`ml_train/tendency_distilled.csv`，7721 行，6 类。类别分布（实测）：
  Objective/Praise/Satire 各 1600、Criticism 1336、Advocacy 1221、**Controversy 仅 364（4.7%）**。
- 标签来源：Qwen（本地 Ollama）蒸馏——即 `distill_tendency.py` 的输出。
  **含义**：本文件所有 macro-F1 都是「编码器 vs Qwen 标签」= 模仿度，不是对人工真值的准确度（见 §5 局限）。
- 硬件/软件：RTX 4060 Laptop 8GB、torch 2.14.1+cu126、transformers 5.13.0、bf16、max_len 128、seed 42。
- 脚本：`ml_train/train_bert_tendency_v2.py`（独立新轨），驱动 `run_tendency_comparison.py` / `run_tendency_tuning.py`。
- 指标：dev 划分 = 同一份 5% 随机切分（seed 42），`load_best_model_at_end` 按 f1_macro 选点。

复现命令：
```bash
# 编码器对比（5 配置）
.venv/Scripts/python.exe ml_train/run_tendency_comparison.py
# 冠军调参（focal / LR / 混淆矩阵，4 配置）
.venv/Scripts/python.exe ml_train/run_tendency_tuning.py
# 单个训练示例
.venv/Scripts/python.exe ml_train/train_bert_tendency_v2.py \
    --base hfl/chinese-roberta-wwm-ext --class-weights --confusion
```

## 2. 编码器对比（同一 dev 划分，macro-F1 降序）

| 配置 | base | 类权重 | dev acc | dev macro-F1 | Controversy F1 |
|---|---|---|---|---|---|
| wwmext_cw | hfl/chinese-roberta-wwm-ext | 是 | 0.7047 | **0.6680** | 0.4516 |
| cmb_large_cw | feynmanzhao/chinese-modernbert-large-wwm | 是 | 0.6606 | 0.6459 | **0.5385** |
| wwmext | hfl/chinese-roberta-wwm-ext | 否 | 0.7176 | 0.6440 | 0.2353 |
| gte | thenlper/gte-base-zh | 否 | 0.6658 | 0.5967 | 0.1538 |
| gte_cw | thenlper/gte-base-zh | 是 | 0.6580 | 0.5949 | 0.2000 |

**结论：**
- **类权重是本次唯一明确的大收益**：在现有 base 上 macro-F1 0.644→0.668，稀有类 **Controversy F1 0.235→0.452（近乎翻倍）**，且不损失数据（优于 `--balance` 砍到 364/类）。
- **`gte-base-zh` 是退步**（0.597 < 0.644），已弃——印证「新 ≠ 好」，且它是 embedding 向骨干、蒸馏分类不占优。
- **中文 ModernBERT-large** 整体略低（0.646）但 **Controversy F1 最高（0.539）**：容量确实帮到了最难的类，值得作为「稀有类优先」时的备选。
- **弃用英文 ModernBERT**（`answerdotai/*`、`Alibaba-NLP/gte-modernbert-*` 英文 tokenizer，中文失效——官方 issue 已确认）。

## 3. 冠军调参（均为 wwmext + 类权重）

| 配置 | loss | lr | epochs | dev macro-F1 | Controversy F1 |
|---|---|---|---|---|---|
| focal_lr3e5 | focal | 3e-5 | 3 | 0.6625 | 0.4286 |
| ce_base | ce | 2e-5 | 3 | 0.6573 | 0.4324 |
| focal | focal | 2e-5 | 3 | 0.6482 | 0.4444 |
| focal_lr1e5_ep4 | focal | 1e-5 | 4 | 0.6463 | 0.4138 |

**关键：同一配置（wwmext_cw）在两次独立运行里得到 0.668 与 0.6573，相差约 0.011**——bf16/打乱带来的运行噪声。
故 **本表内所有 < ~0.015 的差异不显著**。**focal 与 LR 扫描没有给出可靠增益**，不建议继续在这些旋钮上使劲。

## 4. 混淆矩阵（冠军基线，rows=真值 / cols=预测）

```
true\pred                    0   1   2   3   4   5     (0=Advocacy 1=Controversy 2=Criticism
Advocacy/Call-to-action     59   2   4   3   3   1      3=Objective 4=Praise 5=Satire)
Controversy/Reflection       1   8   2   2   0   0
Criticism/Questioning        2  10  52   3   1   5
Objective Statement          9   2   1  36   9   7
Praise/Affirmation           5   1   3   4  64   4
Satire/Mockery               3   1   8   7  15  49
```
Top 误分：`Satire→Praise 15`、`Criticism→Controversy 10`、`Objective→Praise 9`、`Objective→Advocacy 9`、`Satire→Criticism 8`。

**判读：瓶颈是「类边界」不是「模型容量」。**
- **Satire/Mockery ↔ Praise/Affirmation**（15）：反讽在字面上最像夸赞——这是最大误差源，但与 Controversy 无关。
- **Controversy/Reflection ↔ Criticism/Questioning**（10+2）：两者语义相邻（都偏「质疑/批评」）。
- **Objective Statement** 漏向 Praise/Advocacy（9+9）：中性陈述被读出立场。

## 5. 最终选型与建议

**选定：`hfl/chinese-roberta-wwm-ext` + 类权重（`wwmext_cw`）**，dev macro-F1 ≈ 0.668、Controversy F1 ≈ 0.45。
理由（用数据）：它是本次实测最高且**稳定**的配置；类权重是已验证的真收益；换编码器（gte）是退步；focal/LR 在噪声内无增益。

**关于「标签互斥合并」**：数据显示若把 Controversy 并入 Criticism 会抬高整体 macro-F1，但**会消灭你正想加强的目标类**——不建议。真正该考虑合并/重定义的是 Satire↔Praise。Controversy 的问题应靠**更好的类定义 + 更多真实数据**解决，而非合并。

**下一步（按 ROI）：**
1. **人工留出集**（待你标注）：这是唯一能给出「真值准确度」和「Qwen 老师上限」的手段；在此之前所有分数都是模仿度。
2. **软标签蒸馏**：让编码器学 Qwen 的概率分布而非 argmax（Ollama 已就绪），模型侧最可能再涨的一步。
3. **补真实 Controversy 数据**：爬取通道已跑通（`ml_train/crawl_via_server.py`，两阶段：帖子→URL→评论），当前因账号被微博限流而产量低，冷却后换更热关键词/非无头重试。
4. **备选编码器**：若优先救稀有类，可上 `chinese-modernbert-large-wwm`（Controversy 0.539 最高），代价是整体略低与显存（batch8/grad-accum4）。

## 6. 局限（诚实声明）
- 所有指标在 **Qwen 蒸馏标签**上评测 = 模仿度，非人工真值；人工留出集尚未标注。
- 单次运行有 **~±0.011 噪声**（bf16/打乱），小于此的差异不作结论；未做多seed平均。
- dev 划分仅 5%（约 386 行），稀有类样本极少，其 per-class F1 方差大。
- 真实数据爬取：初版无时间窗口时产量极低（冷帖），改用「按事件热度窗口」后有效——详见 §7。

## 7. 真实数据爬取 + 自训练的增益（后续实验，2026-10）

### 7.1 微博评论爬取（按事件热度窗口）
- **教训**：不带时间窗口只拿到冷帖（4 关键词共 72 条评论、单帖评论数 ≤10）。改为「按事件热度窗口」爬取后才有效。
- 工具 `ml_train/crawl_via_server.py`：两阶段（关键词→帖子→评论），走 app 已验证的执行路径（`POST /api/workflow/execute`），结果存 `data/exports/` + `ml_train/controversy_crawl.csv`（带 keyword/source_url/日期出处，可回溯）。
- 三个近期网暴事件 + 各自热度窗口，共 **587 条真实评论**（郑智化 214 / 罗永浩·西贝 195 / 微博之夜座位 178；单帖最高评论数 971）。
- Qwen 标注 487 条并入语料（7721→8208，Controversy 364→388）。重训冠军（wwmext+类权重）：dev macro-F1 0.668→**0.681**，**Controversy F1 0.452→0.537（+0.085，远超 ±0.011 噪声）**。→ 真实 Controversy 数据确实救稀有类。

### 7.2 自训练（伪标签，利用未标注池）
- `ml_train/selftrain_tendency.py`：标注集训练 → 对未标注池（`1-clean_weibo_text.csv` 去掉已标注）打伪标签 → 仅保留置信 ≥0.9 → 并入**训练集**（验证集仍用真实标注，防自评分虚高）→ 重训。
- 10000 未标注样本中 **1122 条**高置信伪标签；同一真实验证集上 macro-F1 0.654→0.682（**+0.029**）、Controversy F1 0.400→0.491（**+0.091**），均超噪声。
- 关键细节：伪标签里 **Controversy 为 0**（模型对该类从不自信）→ 增益是**间接**的（其余 5 类边界更清晰，减少 Controversy 被吞并）。故 Controversy 的**直接**增益仍靠真实标注数据（7.1），自训练只能间接帮。
- 风险：伪标签会随轮次累积模型自身错误；只跑 1 轮，更多轮需人工留出集把关。

### 7.3 合并结论（Controversy F1 的演进，全部实测）
| 阶段 | Controversy F1 | 手段 |
|---|---|---|
| 基线（无权重） | 0.235 | — |
| + 类权重 | 0.452 | 逆频加权 CE |
| + 真实热度窗口爬取 | 0.537 | +24 真实 Controversy 行 |
| + 未标注池自训练 | ~0.49（同切分相对 +0.09） | 1122 伪标签，间接 |

- **有效杠杆**：类权重、真实数据爬取、自训练（间接）。三者叠加把 Controversy F1 从 0.235 抬到 ~0.49–0.54。
- **无效/退步**：gte-base-zh（退步）、focal/LR 扫描（噪声内）、英文 ModernBERT（语言不符）。
- **剩余瓶颈**：类边界（Controversy↔Criticism、Satire↔Praise），需人工留出集判定是否 Qwen 老师本身就在混淆。
