# ml_train —— 训练数据 / 脚本 / 模型 分类目录

本目录是**本地实验区**（gitignored，`backend/` 不引用其中路径；改分析器的特征或标签集需在此重训）。
按用途分四类放置，方便快速选到对的模型。

```
ml_train/
├── models/     已训练的 HuggingFace 模型目录（部署用；节点「已注册模型」下拉 / bert 路径指向这里）
├── datasets/   训练语料与标注数据（csv / 原始数据集）
├── scripts/    训练 / 蒸馏 / 爬取 / 评估 / 扫描 脚本
├── logs/       每次运行的日志与脚本产出的对比/调参 md（证据留档）
└── .hf-cache/  HuggingFace 预训练基座下载缓存（脚本 HF_HOME 指向它；删了会自动重下）
```

## models/ —— 模型清单

| 目录 | 节点·用途 | 标签集 | 训练来源脚本 | 关键指标 |
|------|-----------|--------|--------------|----------|
| `tendency_stance_v2_cyberbully` | tendency「网暴模型」（**推荐**） | 六类传播立场（含空格/斜杠，见各目录 config.json 的 id2label） | `scripts/train_tendency_bert_v2.py` | macro-F1 ≈0.69，Controversy ≈0.50（详见 `docs/tendency_model_comparison.md`） |
| `tendency_stance_v1` | tendency（蒸馏基线，对照） | 同上六类 | `scripts/train_tendency_bert_v1.py` | acc 0.731 / macro-F1 0.681 |
| `emotion_ewect_six` | emotion 六类情绪 | Anger/Fear/Joy/Neutral/Sadness/Surprise | `scripts/train_emotion_bert.py` | acc 0.811 / macro-F1 0.792（留出） |
| `sentiment_weibosenti_bin` | sentiment 极性二分类 | negative / positive（中性交给阈值） | `scripts/train_sentiment_bert.py` | 见该目录 README |

> 旧名对照：`bert_tendency_v2_model`→`tendency_stance_v2_cyberbully`；`bert_tendency_model`→`tendency_stance_v1`；
> `bert_emotion_model`→`emotion_ewect_six`；`bert_sentiment_model`→`sentiment_weibosenti_bin`。

## 如何在 app 里选用模型

后端已加模型注册表。把要用的模型登记进 **`data/model_registry.json`**（每条形如
`{"name": "网暴模型…", "path": "ml_train/models/tendency_stance_v2_cyberbully", "desc": "…"}`），
`GET /api/models` 会把它送出；情感/倾向/情绪节点的 **bert 模式**因此多出一个「已注册模型」下拉，
**按名字选**即可（选项 value 是该模型的路径），下面仍保留原始路径输入框。

- 路径一律写**相对仓库根**的形式（`ml_train/models/<目录>`），后端按仓库根解析 → 换机器/换检出目录不失效。
- 填错模型时分析器**按名拒绝**未知标签、绝不静默改用别的模型；bert 模式缺 `torch/transformers` 也按名拒绝。

## 上传云盘 / 分享给他人（相对路径的意义）

1. 打包某个模型目录，例如 `models/tendency_stance_v2_cyberbully/`（只含 `config.json`、`model.safetensors`、
   `tokenizer*.json`、`README.md` 等顶层文件——**训练检查点已清除，部署不需要它们**）。
2. 对方把解压出的目录放到其仓库的 `ml_train/models/<同名目录>`。
3. 对方在其 `data/model_registry.json` 里加一条相对路径（或直接用现成注册表），节点下拉即出现该模型。

## datasets/ —— 数据

| 文件 | 内容 |
|------|------|
| `weibo_clean_265k.csv` | 26.5 万条已清洗真实微博（曾名 `1-clean_weibo_text.csv`；含 label/text） |
| `weibo_senti_100k.csv` | ~10 万条正负情感标注（曾名 `2-weibo_senti_100k.csv`） |
| `ewect_smp2020/` | SMP2020-EWECT 六类情绪公开语料（`train/usual_train.txt` 等；曾名 `SMP2020-EWECT/`） |
| `tendency_distilled.csv` | 由 `scripts/distill_tendency_labels.py` 用节点自身 llm 通路蒸馏出的六类立场语料 |
| `controversy_crawl.csv` | 按事件热度窗口真实爬取的评论（带 keyword/source_url/日期出处，可回溯） |
| `controversy_labeled.csv` | 上面爬取结果经标注后的版本 |
| `tendency_holdout_template.csv` | 人工留出集模板（填 `human_label` 后另存为 `tendency_holdout_labeled.csv`） |

## scripts/ —— 脚本（用 `.venv`，仓库根下运行）

**训练（需可选 torch/transformers，见 requirements-optional.txt）**
- `train_tendency_bert_v2.py` ★ 产出「网暴模型」；`train_tendency_bert_v1.py` 蒸馏基线
- `train_emotion_bert.py` 情绪六类；`train_sentiment_bert.py` 极性二分类
- `train_sklearn_ml.py` 情感/情绪的 sklearn（词袋）模型（原 `train_and_eval.py`）

**数据制备**
- `distill_tendency_labels.py` 立场语料硬标签蒸馏；`distill_tendency_softlabel.py` 软标签蒸馏（**已放弃**，仅留档）
- `selftrain_tendency.py` 自训练/伪标签；`crawl_controversy.py` 走 app 执行路径的两阶段爬取
- `make_holdout.py` 生成人工留出集模板

**评估 / 实验驱动**
- `run_encoder_comparison.py` 编码器横向对比（写 `logs/tendency_comparison.md`）
- `run_tuning_sweep.py` 类权重/focal/学习率扫描（写 `logs/tendency_tuning.md`）
- `eval_ab_batch2.py` 固定评估 A/B（离题第二批语料的负增益实测；依赖已清除的 pre-crawl 快照，见脚本内注释）
- `eval_teacher_ceiling.py` 老师模型天花板（需 `datasets/tendency_holdout_labeled.csv`）

> 倾向六分类的完整实验与判读见版本库内的 `docs/tendency_model_comparison.md`。
