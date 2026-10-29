# AI 分析 · 数据处理 · 可视化

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。

AI 分析（双提供方 / 情感 / 倾向 / NER / 关键词等）、通用数据处理算子与事件研究套件、以及可视化图表与 LaTeX 出图的完整说明。

## AI 分析
- **双 AI 提供方**：本地 Ollama 或 OpenRouter API（免费模型列表一键拉取、连接测试），模型选择、批量保存行数、截断长度均可在 AI 面板配置；
  OpenRouter Key 仅存浏览器 localStorage，不落服务器。
- **逐节点模型**：AI 面板选的是整轮运行的默认模型；每个用本地 Ollama 的分析节点（清洗 / 情感 / 倾向 / NER）还可在自己的面板单独挑一个模型，
  默认「跟随全局」即沿用运行级模型；OpenRouter 运行不提供此下拉。
- **为什么默认主推微调 BERT（而非通用大模型）**：见 [`docs/why_finetuned_bert.md`](why_finetuned_bert.md)——质量、速度、成本、确定性四维对比，含本机实测的 accuracy/F1。
- **BERT 有两个运行时，打包版走第二个**：`sentiment` / `emotion` / `tendency` 三个节点的 `bert` 模式都通过 `analyzers/sentiment.py` 里**同一个加载器**
  回答，返回同一种 `{'label','score'}` 值。选择顺序：装了 `torch`+`transformers` 就用它（开发机，有显卡就上显卡），否则用 `onnxruntime`+`tokenizers` 跑导出的
  ONNX 图（**Windows 桌面版就是这一条**，包里没有 torch），两者都没有才按名拒绝/降级。日志一定写明 `runtime=` 与 `precision=`。导出与实测脚本见
  `ml_train/scripts/export_onnx_bert.py` + `ml_train/scripts/eval_onnx_parity.py`（结论：fp32 图与 torch 逐条判定完全一致，默认发 fp16，int8 会让 6.7–14.2% 的行改判定，
  只作为显式选项保留；模型本体不进应用包，见 [`desktop/README.md`](../desktop/README.md)）。下面各条里「缺 `torch`/`transformers` 就降级」的说法要按这条读：**两种运行时都不可用**才降级。

- **情感分析（三模式）**：LLM 逐行深度分析、传统 ML（sklearn TF-IDF + 逻辑回归）批量推理，或**微调 BERT**；情绪标签集现按 **SMP2020-EWECT 六类**
  （`Anger`/`Fear`/`Joy`/`Neutral`/`Sadness`/`Surprise`，此前是少了 `Surprise` 的五类）。
  - ML 通路现统一走 jieba 词 + **那份停用词表去噪** + `class_weight=balanced` 逻辑回归（子线性 TF）；`build_tfidf_pipeline(char_features=True)` 可再并入字 n-gram。
    `/api/analysis/train` 的自训与 `ml_train/` 的重训共用这一管线。
  - `bert`（**默认**；未点名模型时自动取注册表里 emotion op 的默认模型）：填一个本机 HuggingFace 目录路径即可整列**分批推理**（有显卡自动走显卡，`batch_size`、
    `max_length`（默认 512）可调）；`pipeline('text-classification')` 直接读模型的 `id2label`，**换任何一套六类情绪模型都不用改分析器**。缺 `torch`/`transformers`
    或无注册模型可解析时，执行器**自动降级到 `ml` 并打印本次实际用的模式**（绝不静默把 ml 结论冒充成 bert）；分析器被直接当 bert 调用仍按名拒绝；读不出的行留空，不臆造 `Neutral`。
    产出模型见 `ml_train/scripts/train_emotion_bert.py`（在 `ml_train/datasets/ewect_smp2020/train/usual_train.txt` 上微调 `hfl/chinese-roberta-wwm-ext`，写到 `ml_train/models/emotion_ewect_six/`）；
    本机实测（留出切片）accuracy≈0.81 / macro-F1≈0.79，训练细节见 `ml_train/`。
- **情感极性（四模式）**：输出 `sentiment`（`positive`/`negative`/`neutral`）与 `score`（0–1 正极性概率）两列。它是**独立的一个操作**而不是「情感分析」的第三个开关：
  SnowNLP 与中文情感 BERT 回答的是"这段话偏正面吗"，给不出六类情绪、也给不出倾向性的六类传播标签，硬塞进去只能靠猜。
  - `snownlp`（bert 跑不动时的默认回退，无需模型、无需 GPU、不掏任何 API）：随包附带的朴素贝叶斯极性模型；另有「判定为正面的下限 / 判定为负面的上限」两个可调档位，落在两者之间记为中性。
    SnowNLP 在购物评论上训出来、对客观陈述明显偏负（"会议定于周三举行"实测 0.24），所以阈值是节点参数而不是写死的 0.5，`score` 列始终保留原始概率。
  - `ml`：与情感/倾向同一条「训练模型」通路，从表里已标注的行拟合 `data/models/sentiment.pkl`。
  - `llm`：逐行走大模型，与情感/倾向共用批量、缓存与断点检查点。
  - `bert`：**默认**（未点名模型时自动取注册表 sentiment op 的默认模型）。本机跑不动 bert（缺 `torch`/`transformers`，或无注册模型可解析）时，节点执行器**自动降级到
    `snownlp`，并在控制台打印本次实际用了哪种**——绝不静默把 SnowNLP 的结论冒充成 bert。分析器**本身**被直接当 bert 调用仍按名拒绝（纵深防御）；勾 ≥2 模型的多模型对比不降级、维持按名拒绝。
    **注**：这一条通路在本仓库**从未真跑过**（开发机没有对应模型），不要把它当作已验证功能。
- **倾向性分析（三模式）**：LLM 逐行、传统 ML 批量，或**微调 BERT**（六类传播立场标签，与情感/情绪共用同一条 `bert` 后端与分批推理）。
  - `bert`（**默认**；未点名模型时自动取注册表里 tendency op 的默认模型，缺栈/无模型时执行器降级到 `ml` 并打印）：倾向**没有公开语料**，所以模型来自 **LLM 蒸馏**——
    `ml_train/scripts/distill_tendency_labels.py` 用节点自己的 `llm` 通路在真实微博上逐条打标签（产出 `ml_train/datasets/tendency_distilled.csv`），再由
    `ml_train/scripts/train_tendency_bert_v1.py` / `train_tendency_bert_v2.py` 微调 `hfl/chinese-roberta-wwm-ext`。`pipeline('text-classification')` 直接读 `id2label`
    （六类标签含空格/斜杠，原样匹配），**换任何六类立场模型都不用改分析器**。缺栈/无模型时执行器降级到 `ml` 并打印实际模式（多模型对比不降级），模型回了不认识的标签时该行留空、**不臆造 `Objective Statement`**。
    本机实测（约 7,720 条蒸馏、5% 留出）accuracy≈0.73 / macro-F1≈0.68；`Controversy`/`Satire` 仍是最弱两格。训练配方与全部数字见 `ml_train/`。
- **微调模型注册表（显示名 + 按操作选默认）**：`bert` 模式的「模型名」不再只能手敲路径。运维在 `data/model_registry.json` 里登记
  `{name, path, operation, desc}`——**`operation` 这个字段决定它是哪个分析节点的候选、以及该节点未点名时的默认模型**（`emotion`/`tendency`/`sentiment`；
  路径用**相对仓库根**的 `ml_train/models/…`，换机/换检出目录不失效）。后端 `GET /api/models` 送出，情绪/倾向/情感节点的 `bert` 面板就列出**已注册模型复选框**，按**显示名**
  （如 **「网暴模型」**——基于网络暴力事件真实语料微调的倾向六分类，产出在 `ml_train/models/tendency_stance_v2_cyberbully/`）勾选，勾选写入 `bert_models`（逗号分隔的**路径**，运行按路径加载，
  名字只给人读），下面仍保留原始路径框填未注册模型；二者只 `bert_models` 优先。文件缺失或损坏时复选框整组消失、路径框仍在——**注册表是可选加速器，不是运行前提**。
- **多模型对比**：`bert` 模式勾选 **≥2 个模型**（`bert_models`）时，该分析节点对同一文本列**逐模型各跑一遍**，输出一张**长表**：原表每行 × 每模型一行，新增
  **`模型`**（显示名）与 **`原行`**（跨模型对齐同一条文本）两列，标签/置信列沿用各操作现名。**只勾 1 个模型时保持原样**（就地加两列、不拉长表），老画布不受影响。
  选择按去重排序存，点选顺序不改变节点指纹；`bert_models` 是选数据的输入，进指纹、不进 `_VOLATILE_PARAMS`。对比可视化：**模型×标签分布**用现成**热力图**（`x_field=模型`、`y_field=标签列`）；
  **模型间一致率**用图表 **`model_agreement`**，按 `模型`/`原行`/标签列算两两模型判定相同的百分比、画 model×model 方阵热力图（仅 echarts，无 LaTeX 版本）。缺列按名拒绝，不足 2 模型也拒绝而非画 1×1 空图。
- **语义数据清洗**：自动过滤广告、无关内容与低质量数据（LLM 判定）。
- **关键词提取**：TF-IDF / TextRank（依赖 jieba）。
- **文本聚类**：K-Means / DBSCAN 自动发现文本分组。`analyzers/clustering.py` 接受 `kmeans` 与 `kmeans++` 两个写法（都走 sklearn 的 KMeans，默认 **k-means++ 初始化**、
  `n_init='auto'`、`random_state=42`，所以同一张表两次跑出同一分组），或 `dbscan`（按 `eps`/`min_samples` 自动发现簇数、把噪声标出来）。
- **命名实体识别（双模式）**：正则规则（人名/机构/地名/日期，零依赖），或改用大模型抽取；可只保留四类中的某几类。
- **异常检测**：Isolation Forest 自动标记数值异常行（少于 5 行、或没有可用数值列时**明确报错**，不会给每行填 0 分冒充"已检查、无异常"）。
- **相关性分析**：Pearson / Spearman / Kendall 相关系数矩阵（点名的列全是文本时报错并点名该列；混选时只算可用列并在控制台说明跳过了哪些）。
- **显著性检验（跨组比较）**：拿**一个类别列当分组、一个数值列当取值**，检验各组之间这个数值有没有统计意义上的差异。四种方法两两配对（参数 / 非参数）：
  - `ttest` → **Welch's t**（`equal_var=False`），**恰好两组**；面板与统计标签都写 Welch，不冒充 Student's t。
  - `anova` → 单因素方差分析，**≥2 组**（统计量 F）。
  - `mannwhitney` → Mann-Whitney U，两组，t 的秩检验替身。
  - `kruskal` → Kruskal-Wallis H，≥2 组，ANOVA 的秩检验替身。
  - p 值一律取 **scipy 的真实分布 CDF**（t / F / 秩检验），不用 numpy 近似；scipy 因此升为**直接声明依赖**（`requirements.txt`）。输出**一行**整洁结果，列名固定为
    下游图/预览的输入合同：`method, group_column, value_column, statistic, p_value, n_groups, group_sizes, significant_005`（后者按**固定 α=0.05** 判）。
    `group_sizes` 说明各组实际用了多少行——**先丢掉**空分组标签与转不成数值的行，报的是「测了多少」。**能算才算**：缺列、组数不对（如给 ttest 却三组，句里点名「试 ANOVA/Kruskal-Wallis」）、
    方差为零等退化情形一律**按名报错、绝不回一张空表**。
- **模型训练**：从已有 LLM 标注数据一键训练传统 ML 模型（`ml_train/scripts/train_sklearn_ml.py`），后续推理无需 Ollama。

## 数据处理
- **通用数据分析节点**：确定性清洗算子全集（与面板 `panels/node-analysis.js` 的 `ANALYSIS_OPS` 一一对应）：**去空值**(`drop_null`)、**填充空值**(`fill_null`)、去重(`drop_duplicates`)、
  近重复去重(`dedupe_similar`)、条件筛选(`filter_rows`)、**选择列**(`select_columns`)、重命名列(`rename_columns`)、**去除空白**(`strip_whitespace`)、类型转换(`convert_type`)、排序(`sort_rows`)、
  采样(`sample_rows`)、分组聚合(`groupby_agg`)、表关联(`join_tables`)、列计算(`column_calc`)、数值分箱(`bin_column`)等，可独立于爬虫直接处理任意表格数据；这些算子的细节参数现在都能从面板设置：
  **去空值**可选「任一列为空即删」或「全部列为空才删」，**填充空值**可选用给定值填充或前向/后向填充（ffill/bfill），**数值分箱**可填等宽箱数（如 `4`）或直接给边界（如 `0, 60, 80, 100`）并配箱标签；
  算子被拒（写了不存在的算子、给文本列求和、比较条件填非数字）时**节点判失败并写明原因**，不再回一张空表让运行看起来成功。
- **分词节点**：jieba 对任意文本列分词，输出词频对，供导出或词云使用。
- **中文社交文本处理**（针对微博这类短文本、水军刷屏的语料）：
  - **清洗节点有两种模式**。`regex` 不用模型：剥掉转发链（`你的评论//@某人:原文` 只留你自己的那段）、`@提及`、`#话题#` 标记、链接与 `O网页链接`/`展开c` 占位符、`[表情]` 代码，
    整行只剩这些东西的判为「删除」。它**不判断主题相关性**——那是 `llm` 模式的职责。源文本列原样保留，清洗结果写在 `cleaned_text` 旁边。留空=默认走 `llm`。
  - **情感极性节点支持 BERT**：填一个本机模型名即可整列**分批推理**（有显卡自动走显卡，`batch_size` 可调，默认 32）；模型给出的正/负标签按概率签名后套用同一组正负阈值。
    加载用 `pipeline('sentiment-analysis', model=路径)`、`_signed_polarity` 只认 `positive`/`negative` 子串，故**换任何 HF 情感模型都不用改分析器**。要"非常高"的准确率：用
    `ml_train/scripts/train_sentiment_bert.py` 在 `ml_train/datasets/weibo_senti_100k.csv`（正/负；`--with-clean` 可再并入 `ml_train/datasets/weibo_clean_265k.csv` 的 喜悦→正、愤怒/厌恶/低落→负）
    上微调一个中文 base BERT（默认 `hfl/chinese-roberta-wwm-ext`），产出 `ml_train/models/sentiment_weibosenti_bin/`。本机实测（5% 留出）accuracy = macro-F1 ≈ 0.978，词袋 `ml` 档约 0.78；训练细节见 `ml_train/`。
  - **中性从哪来（用 bert 模式前必读）**：这条通路的模型是**正 / 负二分类**头，`_signed_polarity` 把正类概率签成一个 0–1 的极性分写进 `score`；模型**从不直接产出 `neutral`**
    （训练源 `ml_train/datasets/weibo_senti_100k.csv` 与 `weibo_clean_265k.csv` 都只有正/负标注，也不要臆造 neutral 行去训练）。第三列 `sentiment` 的 `neutral` 完全由 `label_for_score`
    用**正负阈值**卡出来：默认「判定为正面的下限」0.6、「判定为负面的上限」0.4，`score ≥ 0.6` 判正面、`≤ 0.4` 判负面、之间记中性（边界含等号）。`torch`/`transformers` 在 `requirements-optional`；
    bert 模式缺依赖或模型跑不动时，节点执行器**降级到 `snownlp` 并打印实际用的模式**；`pipeline` 推理不需要 `accelerate`，它只被 gitignore 的训练脚本 `ml_train/scripts/train_sentiment_bert.py` 用到。
  - **关键词节点**新增「基于自己语料的 TF-IDF」：jieba 内置 IDF 来自新闻语料，微博口语词会因此排错位；这一档直接用你自己的表拟合 IDF。另可填**词性过滤**（如 `n,vn,v,a`），去关键词表里的「转发/哈哈/回复」。
  - **网暴言论识别**（算法处理节点的新操作 `aggression`）：论文的研究对象是**暴力言论**而不是负面情绪，"有多冷"被当成"有多骂"是论文治理章节要区分的两件事。四类特征：谩骂、人身攻击、隐私披露（手机号/身份证/住址/人肉开盒）、
    造谣转述，输出三列 `aggression`(none/mild/severe)、`aggression_score`、`aggression_hits`。默认走**词库模式**：无需模型、不花钱、同一张表两次跑出同一张表；它明说自己是**召回器不是判定器**——换个说法的攻击看不见，
    而这一点在这里无法度量，所以词表就放在代码里让它的不足可见。隐私披露权重高于谩骂；「造谣/辟谣」这类辟谣用词**故意不算**暴力。要覆盖委婉语与谐音变体就切 `llm` 模式（复用逐行 Runner 的全套机制，本轮无模型只由注入的 stub 客户端验证）。
  - **事件研究套件**（复刻"舆情生命周期 + 主题演化 + 情感演化图谱"这类研究，如《基于情感演化图谱的网络暴力事件防范与治理研究》的表 1）：
    **提取时间维度**(`extract_time`) 从时间列派生 `日期`/小时/星期等（解析不了的相对时间标签留空，不猜年份）；**按时间划分阶段**(`bin_time`) 用「边界+阶段名」把行打上生命周期标签（边界左闭右开，按自然日比较）；
    它还能多写一列**阶段序号**（数字，首阶段=1）——这不是冗余：阶段列是有序 categorical，而每过一个节点表格都会被 `pd.DataFrame(records)` 重建回普通字符串，中文阶段名按码点排序会把「二次爆发期」排到「发酵期」前面，
    于是一张按阶段分组的表就把生命周期读反了却看着完整。**只有数字能跨过那道边界**；分组聚合还可加**附加聚合**（`列:函数`，逗号分隔的 `agg_metrics`）。**按发文量建议阶段边界**(`suggest_stages`) 读每日发帖曲线的峰谷，
    打印出可直接粘进上一步的 `edges`/`labels`（一个「峰」是连续若干天 ≥ 比率×日常中位数的一段，短于「最短窗口」的窗口并入行数更多的邻居并警告说明）。
    **主题模型**(`topic_model`)（以及下面的距离图 / 显著词 / 分阶段）**默认 `method`=`auto`**：装了 sentence-transformers 等可选包就用句向量 + KMeans（默认 `BAAI/bge-small-zh-v1.5`，本机实测主题相干性优于 LDA），
    没装就自动走 LDA——两者都会在控制台**写明实际用了哪种**，绝不把 auto 出的 LDA 结果冒充成 embedding。想强制一种就显式选 `method`=`embedding`（没编码器时**按名拒绝、绝不静默替换**）或 `lda`；可选依赖见 `requirements-optional.txt`。
    实测对比脚本见 `ml_train/scripts/topic_bakeoff.py`。**同一套 `method` 选项（`auto`/`embedding`/`lda`）现在覆盖全部主题步骤**——`主题模型`、`分阶段 LDA`、`主题距离图数据`、`各主题显著词数据` 都接受它，
    且**输出列名逐字不变**（`pc1/pc2/prevalence_pct` 与 `term/overall_freq/within_freq` 契约照旧），所以可在同一张画布就地做 LDA↔embedding 的 A/B。embedding 复用**同一份 CountVectorizer 词矩阵**，只把「文档→主题」
    的指派从 LDA 后验换成 KMeans 簇。注意**困惑度是 LDA 的量**，走 embedding 时该字段如实留空（nan），不伪造一个看似可与 LDA 比大小的数。**分阶段 LDA**(`topic_by_stage`) 先按阶段列切分语料、逐阶段建模，输出「每(阶段,主题)一行」的宽表
    （`阶段 / 主题编号 / 特征词 / 权重 / 该主题帖子数 / 困惑度 / 代表文本`）；每阶段主题数可统一填一个数，也可逐阶段列举（`5,6,4,4,4`）；阶段先后要么来自同一流水线里的阶段列、要么由你指定一个时间列，两者都没有就拒绝而不是按中文字典序猜。
    **主题概括（模型）**(`topic_label`) 对每个主题问一次模型，把「不超过 15 字」的概括写进 `主题概括` 列。默认任一主题失败就让节点失败（可切「留空继续」），没配模型则一开始就拒绝——答案存进 runs.db 的 llm_cache，缓存键就是那条提示词，
    所以同一张表重跑不再重复付费。**情感演化曲线**(`sentiment_evolution`) 按任意分组列算出积极/中性/消极的数量与占比、情感指数 `(积极−消极)/总数 ∈ [-1,1]`，再加热度 `volume_pct` 与可选的情感强度 `intensity = |score−0.5|×2` 的均值。
    **主题距离图（数据）**(`topic_map`) 与**各主题显著词（数据）**(`topic_salience`) 是 pyLDAvis 那张图的「数据面」，不装 pyLDAvis 也不装 gensim：前者一行一主题给 `topic / pc1 / pc2 / prevalence_pct / doc_n / feature_words`——
    坐标是主题两两词分布的 **Jensen-Shannon 散度**经**经典 MDS**（特征分解）降到二维，符号固定所以同一张表永远画出同一张图；后者一行一(主题,词)，同时给 `overall_freq`（全库频次）与 `within_freq`（该主题自身频次），排序按 Sievert & Shirley 的
    相关性 `λ·log p(w|t) + (1−λ)·log(p(w|t)/p(w))`（**λ=1** 按主题内概率、**λ=0** 按相对全库的溢出，本次用的值会随表一起打进控制台）。**主题生命周期（次生舆情）**(`topic_timeline`) 靠特征词的重合度（Jaccard，默认 0.5）跨阶段追下去，
    输出 `首现阶段 / 峰值阶段 / 末现阶段 / 覆盖阶段数 / 阶段路径 / 规模合计 / is_secondary`；`is_secondary` 用论文的两条判据（不是开场那个主题，**且**峰值出现在首现之后）。**主题流向**(`topic_flow`) 把相邻阶段的主题按词分布算 JS 散度换成相似度 `1/(1+d)`，
    超过阈值才出一条边（`source / target / similarity / from_stage / to_stage`，正好是桑基图的 x/y/值）；一条边都达不到阈值时它拒绝并告诉你实测最相似的一对是多少。**主题数扫描**(`topic_coherence`) 对 `min…max` 逐个拟合，给困惑度与一致性
    （按文档统计的 NPMI，只是发表口径 C_v 的一部分，不要拿它去对论文里的数字）；语料大时默认只抽 2000 篇。**共词网络**(`cooccur`) 候选词取本表 TF-IDF 表，数同现次数输出 `source / target / value`；候选词上限 120，超了会拒绝而不是悄悄截断。
    **回复传播边**(`reply_graph`) 用评论自带的 `楼层`/`父楼层` 把每条回复对回其顶层评论的作者，输出 `src_author / dst_author / weight`；一条回复都关联不上时按名拒绝。**跨平台对比**(`compare_platform`) 按 `platform` 列每个平台出一行
    （条数 `n` 加对一个可选数值列的聚合）；这个 `platform` 列由**输出(保存)节点合并多个上游爬虫时**统一盖下，表里没有该列时按名拒绝。**聚类摘要**(`cluster_label`) 读聚类给每行贴的标签列与该行的**原始文本**，每簇问一次模型写一段摘要。
    **簇综述·研究前沿**(`cluster_review`) 是它的**文献计量版**：喂给模型的不是文本而是该簇**已有的度量**（LLR 标签、节点数、代表节点、年份跨度），请它写 3–5 句"这个簇构成什么研究前沿"；`on_fail=fallback` 生成的句子会在**格子里**写明"未经模型"。
    **水军可能性**(`bot`) 按**作者**读整表：某作者与他人高度雷同（复用去重同款 SimHash，跨账号才算）的文本占比，加上相对全库中位的发帖突发，写 `bot_score/bot_level/bot_evidence`；它是**召回线索不是判决**，缺 `评论者`/`评论时间`/`正文` 任一列都按名拒绝。
    **情感走向外推**(`forecast`) 把曲线形状往后推若干期（不是预测事件），四种方法都手算、不引 statsmodels（`moving_average`/`holt`）；时段列必须能解析成**日期**（"发酵期"这类阶段名没法外推，直接拒绝）。**二次爆发预警**(`alert`) 把论文的"提前干预"
    落成一条可读的规则（`转向`=连续 N 期同向超阈、`升温`=强度每步上升超阈，两者都要热度还在）；一条都没触发时也出一行 `未触发` 并带上实测到的最大幅度。这几个算子的产出可直接接折线图、**双轴折线**、**占比堆叠图**与导出。
    **事件标注**给柱状/折线/双轴折线：填 `2024-05-19=公安通报; 2024-04-23=遗体打捞`，在横轴那个类别上画竖直虚线；标签必须与轴上取值一字不差，对不上就拒绝并把可选标签列出来；选 Matplotlib 时会明确拒绝。**阶段先后怎么跨过节点边界**：
    `按时间划分阶段` 写的是有序 categorical，而每过一个节点表格都会被 `pd.DataFrame(records)` 重建回普通字符串——所以 `分阶段 LDA` 还会写一列 `stage_order`（数字序号），`主题生命周期` 与 `主题流向` 都读它来定先后；两个都没有就拒绝，绝不按名字猜。
  - **去重分三层**：`去重`(`drop_duplicates`) 有两种判重依据——`exact`（逐字相同）与 `normalized`（忽略链接/@/话题/表情的归一化后相同，能识别水军改写）；**近重复去重（SimHash）**(`dedupe_similar`) 按语义指纹的距离分组，抓「改一个词的转发」。
    归一化只用于比较，落库的仍是原文。距离默认 **8** 位（微博评论里「改一个词」大约差 5–18 位，两条互不相关的评论差 26–28 位）；往上调（上限 15）提召回、降精确率，建议按自己那张表逐次调整。
- **文件持久化**：上传/粘贴的文件注册为数据集（内容哈希寻址、zlib 压缩存库），保存的工作流随时可重新加载自己的输入文件；无引用且长期未用的文件自动清理。「数据集管理」面板支持逐个改名/删除（被已存工作流引用的**当场拒**），
  面板头的**清空**则连被引用的也一并删——这一点差别写在确认框里。
- **通用导出节点**：一个节点支持导出 CSV / JSON / Excel / TXT / HTML / Markdown / Parquet 七种格式（Parquet 需要列式引擎 pyarrow，属 `requirements-optional.txt` 里的可选依赖、CI 不装；缺引擎时该格式**按名拒绝**并提示 `pip install pyarrow`）。
- **一键运行报告**：工具栏「生成报告」把本次运行（或运行记录里任选一条历史运行）的每张表格与服务端渲染的图表拼成**一个自包含 HTML**——样式与图片全部内联，离线能看、能打印。可选「附 AI 结论」，只根据统计数字让模型写一段话；还能选「生成并导出 PDF」
  ——用用户自己的无头 Chrome 把 HTML 打印成 PDF（不引入新依赖，找不到 Chrome 或打印失败只少一个 PDF）。因为内容来自互联网抓取的文本，报告页只经 `/api/report/view` 提供，并带禁止脚本的 CSP 策略。

## 文献计量

CiteSpace 风格的知识图谱能力以 **Bibliometrics 节点**接入工作流。它是普通表格节点：上游可以是 Upload（CSV/Excel/JSON/CNKI/CSSCI），也可以是爬虫节点；列映射把任意表接成网络，CNKI/CSSCI 只是默认列名。实现为净室重写（Kleinberg 突现、PFNET、
谱聚类、LLR 等公开算法），不包含 CiteSpace 代码或其 JCR 基线数据。

- **导入**：格式注册表识别的是**实测过的导出件**——CNKI 三种按钮（RefWorks `.txt`、NoteExpress `.net`、EndNote `.enw`）、CSSCI 文本、WoS（纯文本 / Excel / RIS / BibTeX）、Scopus CSV（中英文表头、`Article number`/`Art. No.` 都认）、
  Dimensions CSV（要选 **Export full record → CSV**，第一行是版权横幅，读前先跳）、Lens **学术文献集合**的 CSV、PubMed（Medline 文本与 CSV 摘要）、RIS、BibTeX、EndNote。**PubMed 没有 XML 读法**。Lens 的**专利集合**按名拒绝，它的 `References` 列写的是 Lens 记录 ID 而非引文文本，
  所以共被引与文献耦合只能用 WoS/Scopus/CSSCI 这类带引文文本的导出；它也没有作者单位/地址列，机构与国家网络对 Lens 按名拒绝。规范化列为 `记录ID/题名/作者/作者单位/来源期刊/年份/卷/期/页码/关键词/摘要/参考文献/DOI/格式`，并按实际数据追加 `国家/学科/引用次数/使用次数/基金/文献类型/语言/引文`。
  **WoS 的 Excel 只缺 Cited References 这一列**（整列为空，用户确认网站就没提供这个导出项）：用 Excel 能建关键词/学科/基金网络，但引文网络与引文突现要用「纯文本 + 全记录与引用的参考文献」。
- **实体**：关键词 / 作者 / 机构 / 国家 / 学科 / 主题词 / 基金共现；文献、作者、期刊共被引；文献耦合；来源期刊耦合。CiteSpace 的 `Source`、`Grant`、`Article` 分别作为 `source`、`grant`、`article` 节点类型接入。共现类只需要实体列与年份列；引文/耦合类需要参考文献列。CNKI RefWorks 通常没有参考文献，引文模式会按名拒绝。
- **网络**：按年份切片（`slice_years`），每片按 TopN / Top% / g-index / 阈值三元组选择后合并；支持 look-back years、最低 TC/usage 过滤、citation expansion（0–2 阶，上限 500 条/文献并播报）、cosine / Dice / Jaccard / association、
  **整次/分数计数**（`counting`：`fractional` 把每篇文档的 1 份信用均摊给它承载的连边对；耦合类网络选了会按名拒绝）、每节点最大连边 + LRF、cc/ccv 边过滤、最大连通分量；剪枝 none / MST / Pathfinder，作用域可选 `slices`（逐片剪完再合并，默认）或 `merged`。
  Pathfinder 三参数：**`pathfinder_r`**（Mantel 的 r 范数 `1`/`2`/`inf`）、**`pathfinder_lmax`**（间接路径最长几跳，`0`=不限）、**`pathfinder_dmax`**（保留比例，`1`=全留）。判据是：一条连边只有自身距离不比两端之间最好的间接路径更长时才保留。规模超过预算时**按名拒绝**并写出测到的节点数、层数与运算量，绝不静默降级。
- **指标**：度、中介中心性（节点多时按 500 源点采样并播报）、特征向量中心性（按连通分量计算）、PageRank、Sigma = `(中介中心性+1)^突现强度`；输入含 `引用次数` 时追加 `总被引/H指数`，含 `使用次数` 时追加 `使用次数合计`。
- **聚类**：归一化 Laplacian 谱聚类，聚类数留空时按特征值间隙自动选择；模块度 Q、轮廓值写入运行摘要；标签支持 LLR / LSI / MI / TF-IDF，来源由 `label_source`（`all`/`title`/`abstract`/`keywords`/`author`）选择，显式来源缺列**运行前按名拒绝**。
- **突现**：两状态 Kleinberg Viterbi，按逐年文档数计算；每个节点保留最强突现区间，突现词表另写 CSV。耦合类节点是施引单元本身，禁止突现。
- **结构变异**（`variation`）：度量**相邻两个切片之间**一个节点连接模式的移动量——取该节点两期连边强度分布之间的 **Jensen–Shannon 散度（比特）**；选 JSD 而不是裸 KL 是因为"某邻居出现/消失"会让 KL 变成无穷大。`variation_min`（默认 0.05 bit）是上报阈值。
  **只有两期都有连边的节点才计分**——"原来有模式、后来什么都没有"是消失，不是结构改变。切片不连续时**不跨缺口比较**。`output_shape=variation` 输出该表（`节点 / 起始年 / 结束年 / 结构变化 / 前邻居 / 后邻居 / 新增邻居 / 消失邻居`）。少于两个切片、或耦合类网络都会**按名拒绝**。
- **情感 / 话题叠加**：`sentiment_column` / `topic_column` 填**上游已经写出的标签列**。每个节点追加两列：`情感倾向` + `情感分布`（或 `主导话题` + `话题分布`）。分布是「提及该节点的文档里各标签的篇数」的规范 JSON；主导标签取篇数最多者，**并列按标签文字定序**。
  分母只含**有标签的文档**：空白是「没有判断」，不是「中性」。填了表中不存在的列、或整列没有任何标签，都在**运行前按名拒绝**。两列各配一张图：`sentiment_overlay`（每节点一条 100% 堆叠横条）与 `topic_overlay`（节点 × 话题热力图，格子是占比）。两张图都只画前 20 个节点 / 12 个话题并在标题下写明省略数。
- **人工校正**：`aliases` 每行 `规范名=别名1|别名2`，`exclude_values` 每行一个排除标签；两者在建图前合并/移除节点，并计入节点指纹。`cluster_labels` 每行 `#簇号 = 标签`，在 LLR/LSI/MI/TF-IDF 之后覆盖簇名（同样计入指纹）；填了人工簇标签却没开聚类 → 运行前按名拒绝。
- **输出**：默认 `output_shape=nodes`，一行一节点，固定列 `节点/类型/频次/首年/末年/年份序列/度/中介中心性/特征向量中心性/PageRank/Sigma/x/y/连接`；开启聚类追加 `聚类/聚类标签/轮廓值`，开启突现追加 `突现强度/突现起始/突现结束`。`连接` 与 `年份序列` 是规范 JSON 文本。
  `output_shape` 还可输出 `edges`/`clusters`/`bursts`；`dual_map` 输出 `map/source/target/weight/label/x/y` 的叠加表（`map` 取 `journal`/`category`/`overlay`），需要 `basemap_dataset_id` 指向一份自备的「期刊—学科」两列表，缺基线按名拒绝。
- **图**：`knowledge_graph`、`circular`、`cluster_timeline`、`landscape`、`burst`、`timezone`、`biblio_heatmap`、`graph3d`、`variation`、`dual_map`、`geo_map`、`sentiment_overlay`、`topic_overlay`、`concentric`（同心环：每个节点按**首次出现年份**落各自的环，内环最早、外环最新，环内按频次顺时针；
  没有年份的节点单独成最外一环并在图例里标「未知年份」），均仅 ECharts。缺列/无连边/未开聚类、突现或结构变异、没有叠加列时按名拒绝。十四类图均有 TikZ/pgfplots LaTeX 图源与 booktabs 三线表；`emit_latex` / `emit_latex_table` 在节点上默认开启。前端 `labelLayout` 按实际渲染矩形避让中文标签；y 轴分类标签**永不旋转**。
- **按年份回放**：图谱与环形图的每个节点都带自己的 `yearSeries`，预览与全屏窗口下方多一条回放条。节点按**到这一年为止累计的频次**长大，连边在**两端都已出现**的那一年才出现；最后一帧与完整图**逐字节相同**，已存的 PNG/SVG/LaTeX 仍是完整网络。只有 ECharts 画的图型有这条。
- **跨 run 监测**：`biblio` 节点填了 `watch_project` 之后，每次运行都会把自己这张网络**存成该项目的一个快照**，并与上一次捕获对比（`watch_baseline` 可指定更早的那一次）：新增/消失的节点与连边、逐列变化的节点属性、新簇/消失的簇、新突现/结束的突现、以及哪几项参数被改过，全部逐条打印并另存 `<画布>-<节点>-watch.csv`。
  两条按名拒绝：输出形态不是实体表、本次图谱空。`watch_*` 三项**不进节点指纹**也不写进快照的参数。配合顶栏定时任务即是监测流水线。
- **国家/地区地理图（`geo_map`）与它的世界底图**：底图是 **Natural Earth 1:110m Admin 0 — Countries（public domain）**，由 `tools/build_world_geojson.py` 生成并**随仓库分发**（`backend/static/geo/world.json`，239 个区域、约 200 KB）：只留 `name/zh/iso/alt`、
  坐标取两位小数、110m 缺的 65 个小国从 1:50m 补进来。名称解析走 `services/biblio/geo.py`（底图 `name/zh/iso/alt` → 导入器国别别名表 → 一张刻意保持短的桥表），`tests/unit/biblio/test_biblio_geo.py` 拿导入器能吐出的全部国名逐个比对底图。同一地区的多种写法按地区求和。**一处明确的制图主张**：Natural Earth 把台湾记为独立区域，
  构建脚本把台湾、香港、澳门的几何并入中国（坐标拼接而非重画），与本应用中国底图画法一致；图上会点名「并入其他区域 N 处」。
- **界面用的第三方文件全部入库，页面不向本站之外要东西**：`tools/vendor_frontend_assets.py` 取回并钉住 ECharts 5.4.3 / echarts-gl 2.0.9 / echarts-wordcloud 2.1.0、界面字体 Literata 的 14 个 woff2（SIL OFL）、以及 DataV 的中国省级底图 `backend/static/geo/china.json`。
  每个文件都有 SHA-256 断言。**缺失时的形状是"指名道姓"而不是空白**：图表库不在，各视图写一句"图表库没有加载（/vendor/echarts.min.js）"；底图读不到就把这句话**画进图里**。真浏览器用例读 `performance.getEntriesByType('resource')` 证明没有一个请求离开本站（`tests/integration/test_ui_layout.py`）。
- **产物**：默认写 `<节点>_graph.graphml`、`_graph.gml`、`_graph.net`（Pajek）、`_graph.json`、`_nodes.csv`、`_edges.csv`，开启聚类/突现时另写 `_clusters.csv`/`_bursts.csv`，登记到本次运行；`export_files` 可关闭。`dual_map` 形态只写表。
- **边界**：CNKI 无被引次数与 CR，因此无共被引/耦合/引用突现；双图叠加的期刊—学科基线由用户导入（`samples/biblio/biblio_basemap_demo.csv` 是合成样例），不内置任何商业 JCR 数据，缺文件按名拒绝。

演示：`data/workflows/文献计量演示：CNKI 与 CSSCI 知识图谱.json`（共 14 张图；双图叠加那条链默认**关闭**，因为基线要用户自备；**情感/话题叠加链也默认关闭**——本机实测 SnowNLP 把样例摘要涉及的关键词—文献共现全判为正面，一张全绿的横条图不是发现）。工作流按数据集 id 引用本机已注册的两份样例；换一台机器时先上传 `samples/biblio/biblio_cnki_demo.txt` 与 `samples/biblio/biblio_cssci_demo.txt`，再在两个 Upload 节点里重新选择。

## 跨源融合
- **`fuse` 节点**：把任意多张上游表折叠成一份规范记录表（`题名/作者/作者单位/来源期刊/年份/关键词/摘要/参考文献/记录ID/来源`）。每个角色是**候选列列表**，按顺序尝试：文献的 `关键词` 与帖子的 `话题` 折叠后进同一个词表，下游 `biblio` 节点用默认列映射即可。
  年份从 `2022-03-04 11:02` 这类时间戳里取四位年份，取不到就是空（`keep_undated` 决定这类行留不留）。
- **来源是数据，不是猜的**：表内自带 `平台`/`来源` 列就逐行取；否则用 `source_labels` 里为该父节点写的一行（`node-1 = 文献`）；再否则按父节点 id 登记。**不会**替一个没说过自己来历的表写「文献」。父节点没有可用实体列、或该列一个实体都没提出 → 按名拒绝并列出试过的候选。
- **图的来源列**：输入表带 `来源` 时，`biblio` 节点的输出多出 `来源`（该实体出现在哪些语料，`;` 连接）与 `跨源`（是否多于一个）两列；普通文献运行不会长出这两列。
- **为什么不用现成的 fan-in 合并**：引擎的多入线合并保留各表原有列名并把行拼起来，`关键词` 与 `话题` 于是永远在两个列里，而且没有任何一行还知道自己来自哪张表。`fuse` 因此读 `upstream`（每个父节点及其行）而不是 `current_input`，并为此**不**打印「第一条线是主输入」那条通用提示。
- **导出**：`export_files` 打开时把折叠后的记录表写成 CSV 并登记进运行产物台账（`fuse_records`）。

## 可视化
- **图表是论文样式，不是仪表盘样式**：一套印刷安全的配色（首个色是深板岩蓝）、衬线字体（Times New Roman + 宋体）、**折线不平滑、不填充渐变面积**、坐标轴细而可见、网格线浅虚线。分类轴**保留表格自己的行序**（早前 `aggregate` 末尾一个 `sort_index()` 把 表2 的阶段按字典序重排，于是图看着完整而生命周期被读反了）。
  密集分类轴（>12 个取值）会**旋转到 45° 并强制显示每一格**（`interval: 0`）：ECharts 默认为了避让会丢标签。力导向的关系图**先算定再画**（`force.animate: false` + 圆形初值 + `layoutAnimation: false`）。
- **关系图可「以某个节点为中心」渲染（`center_node`，可选）**：填入图中已有的某个词，就只画它的**邻域图（ego-network）**：该词 + 与它直接共现的词 + 这些词之间的边。这是一个真参数（进节点指纹、改变出图）；留空则画全部候选词（与从前逐字节一致）。填了图里没有的词会**按名拒绝**。
- **所有渲染文字跟随界面语言**：图例、series 名、坐标轴名、tooltip，以及从数据里读出的分类值（`positive/negative/neutral`→正面/负面/中性、`Topic-1`→主题-1、`PC1/PC2`→第一/第二主坐标 等）都在**显示层**统一翻译（`visualizer.py` 的 `_localize_label`）。库里与算子输出的**列名、标签值一律不改**（那是节点之间的输入契约）。
- **所有数词的步骤共用一份停用词表**（`backend/analyzers/stopwords.py`）：LDA 特征词、显著词、共词网络、关键词节点、词云以前各用各的过滤，所以 表1 的头部特征词里会出现 自己/一直/成为/一个；表本身保守收录，域内实词（网暴/警方/律师）一律保留，用例把这两个方向都钉住了。
- **通用可视化节点**：全部 30 种图表类型（`services/charts/registry.py` 的 `SPECS`）——柱状图 / 折线图 / **双轴折线** / **主题距离图** / **显著词图** / 饼图 / 散点图 / 直方图 / 箱线图 / 热力图 / **模型一致率**（`model_agreement`，多模型对比表专用：读 `模型`/标签/`原行` 三列，画两两模型判定相同的百分比方阵热力图）/
  桑基图 / **关系图**（力导向：共词网络与主题流向都吃这张表，起点固定为环形布局）/ 词云 / 中国地图，以及全部 14 类文献图（知识图谱/环形图谱/聚类时间线/景观图/突现词图/时区图/聚类年份热力图/三维图谱/结构变异图/双图叠加图/情感叠加图/话题叠加图/国家地区地理图/**同心环 `concentric`**），
  支持 ECharts（前端渲染）与 Matplotlib（服务端渲染）两种引擎（双轴折线、主题距离图、显著词图、模型一致率、关系图与全部文献图只有 ECharts 支持，选 Matplotlib 会明确拒绝而不是画成别的东西）。柱状/折线/双轴折线还能填**事件标注**。
- **占比堆叠图（stack_pct）**：横轴是分类（如阶段/时期），「堆叠字段」填逗号分隔的若干列，每列是柱内一段（如 `积极占比,中性占比,消极占比`），每个分类都被归一到 100%（计数会自动换算成占比）。横轴按数据表自身顺序保留阶段次序。列名随界面语言本地化显示，两种引擎都支持。
- **图表统一为文科论文印刷风格**：所有图表（两种引擎）都去掉网格线、只保留左/下两条坐标轴并以墨色绘制、文字用衬线；折线不再平滑也不填色阶（两点之间没有测量过的数据，画出来等于编造），柱条直角、力导向图一次算定不再在屏上漂移。
- **可视化节点另出 LaTeX（`emit_latex`，默认开）**：每个可视化节点除出图外，还生成一份**可被本机 xelatex 编译的 LaTeX 图源码**，写为 `data/exports/<节点标题>.txt`（standalone 文档，`xelatex` 直接编译成矢量 PDF，也可把其中 figure 体复制进论文）。用 pgfplots + TikZ（ctex 中文、booktabs），**对齐手工精修论文的观感**：全文**仿宋 FangSong**、
  muted 配色、淡点网格、坐标轴与柱顶数值**千分位**（`1000 sep`、禁科学计数）；主题距离图 / 共词关系图 / 桑基流向图的标签一律走**白底圆角框 + 引线**；分类过多时 X 轴自动倾斜并等距抽稀；**覆盖项目全部图型**。另有默认开的 `emit_latex_table` 复选框，可再输出一份 booktabs 三线表 `.txt`。LaTeX 生成失败只记一条具名日志，不影响该节点照常出图。
- **编译节点 + 图表直出 PDF**：**编译（`compile`）节点**上游只能接**可视化节点**，把它产出的 LaTeX（图和/或三线表）用**本机 `xelatex`** 合成一份 standalone 文档、编译成一个 PDF（图与表在同一份文件里）。再接一个**输出节点**即把 PDF 落成用户命名的文件；可视化节点直连输出节点也能出 PDF。
  **输出节点的格式按上游锁定**：上游是可视化/编译节点时**只有 PDF 可选**，其它上游则不出现 PDF；前端 `validateWorkflow` 与后端 `engine.validate` 同时把关。
  **`xelatex` 路径按操作系统探测**（`services/charts/pdf.py` 的 `XELATEX_PATHS`：Windows 找 **MiKTeX**、Linux 找 **TeX Live** `/usr/bin/xelatex`、macOS 找 **MacTeX** `/Library/TeX/texbin/xelatex`），也可在**设置 → 编译程序路径**里指定（留空则自动探测 PATH 与本 OS 的常见安装位置）；
  找不到编译器只让该节点具名失败，不崩整轮。编译失败时读的是 **`main.log` 而不是 stderr**（`-interaction=batchmode` 把真正的错误行写进日志），日志里能点名就点名——缺 `ctex.sty` 说成"缺宏包 ctex，用本机的 TeX 发行版补"、`The font "FangSong" cannot be found` 说成"找不到字体 FangSong，英文版系统要补中文（简体）字体"。
- **论文成稿（一键把这次运行排成一份 .tex/PDF）**：报告面板的运行下拉里多一个「论文成稿（LaTeX）」按钮，打 `POST /api/report/latex`，**请求只带 `run_id` 与标题**——图与三线表一律从这次运行**已登记的 LaTeX 源文件**读回来，所以论文里的图与预览里的图不可能各画一份，浏览器也没有把 LaTeX 交给编译器的路（那等于让它读任意文件）。
  合成 `article` + `ctex`（导言区复用图表自己的 preamble）：方法段逐节点给出分析单元与参数（只从已保存画布读、并与运行记下的指纹核对），随后是图 1 / 表 1 / 图 2 / 表 2……，末尾点名工作流、运行编号、时间窗与图表数。**先写 `.tex` 再编译**，编译器拒绝时留下的正是那份可继续排查的源文件，且绝不留半份 PDF。跑过却没登记 LaTeX 源的可视化节点文末点名「另有 N 个可视化节点没有登记 LaTeX 源…」。
  若干版面处理都是确定的：每项都是 `[H]` 浮动体（float 宏包）；贴进来的正文按页宽缩放（`\cixifit`，只在超出 `\textwidth` 时缩）；网络图按版面反过来定自己的尺寸（`GRAPH_BOX_CM`，只缩不放）；会互相遮盖的标签被丢掉并当场说明丢了几条（`_fit_labels`）；超过一页的三线表被切成整页的块（`TABLE_ROWS_PER_BLOCK=26`，续块用 `\caption*{…（续）}`，一行不丢）。
- **采集深度可调**：微信正文长度上限由 `Config.WECHAT_BODY_MAX_CHARS` 决定（默认 0，完整保留）；小红书数据源节点新增**每篇评论预览数**，填 `0` 真的跳过评论面板（以前即便只要 0 条，每篇仍会等满 10 秒）。
- **Chart Studio 图表工作台**：画布内嵌 ZENVIZ 工作台，可对任意节点/数据集的完整表格做自由图表创作，支持多数据源合并，成品 PNG 可保存回导出目录。
- **数据预览面板**：任意数据集都能以可翻页的表格形式查看真实数据行；**「平台」列显示本地化名称**（`douyin`→`抖音`，库里仍按原始 key 存，未知 key 回落原值不显示空白）。**导出的文件同样写本地化平台名**——导出走 `DataExporter`，存储身份仍是原始 key。
- **评论采集前的一次性提示**：画布含评论节点时，运行前提示「部分平台/视频的评论区不发布 IP 属地，『评论地区』列可能为空」（纯搜索画布不打扰）。
- **仪表盘看板**：把画布上所有 Visualize 节点的图表拼在一个网格里一起查看；**重启后端 / 刷新页面后自动回填**（图是数据行的投影，不额外写进运行库），没有最近结果时格子显示一条友好提示「尚无运行数据，请先运行一次工作流」（灰字备注、非红色报错，走 HTTP 200）。
- **图表另存为图片**：图表预览面板与看板每个格子都有「存为图片」，落到 `data/exports/` 里，文件名就是那张图的节点标题。两种引擎都管：ECharts 现取 `pixelRatio=2` 的白底 PNG，Matplotlib 直接存节点已拿到的那张图。**还没有画出来的图不发请求**，而是说明「先点预览或把节点跑完」。
- **图表全屏**：看板每个格子和预览面板都有「全屏」，弹出一个可拖动、可改大小的浮层窗口看单张图。它优先复用在屏上已经画好的那张，三者都没有才重新请求一次渲染——**且请求一定带上 `label_field`**，否则主题距离图会被重画成 `Topic-1` 编码。关窗即 `dispose`。
- **实时统计**：ECharts 图表展示情感/倾向性分布与执行汇总。
