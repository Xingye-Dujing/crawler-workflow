# 能力技能目录（自动生成）

> 由 `tools/gen_capabilities.py` 从清单的第七段生成，请勿手改。
> 运行时由 `capabilities_kernel.knowledge` 直接渲染同一份清单，页面不会比接口旧。

| 技能 | 分组 | 一句话 | 何时使用 |
|---|---|---|---|
| [node.name](nodes/name.md) | meta | 工作流命名 is pure metadata: it names the run and must feed a real node. | At the head of a canvas whose runs should be grouped by a readable name. |
| [node.source](nodes/source.md) | data | 数据源 crawls one platform with one mode and emits that mode’s table (a search, a board, an author page, a note/article list, or one link list). The platform matrix decides the fields, the required values and whether the mode needs a saved login. | When the corpus is a platform search, a board, an author page or a link list. |
| [node.upload](nodes/upload.md) | data | 文件上传 turns one stored dataset into the same row table a crawl produces. Downstream nodes never know the difference; the dataset id is the binding. | When the corpus is a file rather than a crawl: the one place a file enters a workflow. |
| [node.resume](nodes/resume.md) | data | 断点续采 adopts rows an earlier run already stored. Blank ids mean “newest unfinished run of this workflow shape, fullest node”; a limit truncates the adopted table. | When the original source cannot run again but its rows are already paid for. |
| [node.comment](nodes/comment.md) | data | 评论采集 walks the comments of the article links on one form, batch by batch, and emits the same comment table a 数据源 in comments mode produces (评论内容/评论时间/点赞数/文章URL …). The cursor records only the leading links it PROVED complete, so 继续 replays from the first hole. | When the post table is known and the comments under each post are the corpus. |
| [node.process](nodes/process.md) | process | 处理 runs one operation over the upstream text column: cleaning, tokenize, word frequency, TF-IDF/TextRank, sentiment/emotion/tendency, NER, clustering, correlation and the qualitative coding operations. The operation selects both the result columns and the required inputs. | After a crawl/upload when the rows need cleaning or one text/algorithm operation. |
| [node.python](nodes/python.md) | process | Python 节点 runs one saved script from the account’s script library over the upstream rows. The script reads CIXI_INPUT and writes CIXI_OUTPUT (JSON Lines); the node stores its id, not code. | When a transformation is not one of the built-in operations and should be reused as a script. |
| [node.analysis](nodes/analysis.md) | analysis | 数据分析 runs an ordered pipeline of operators over one table: filter/select/rename/join/group, statistics, text analysis (keyword/topic/LDA) and chart-ready aggregates. Each operator declares the columns it reads and the columns it emits. | When rows need a multi-step table transformation; a single text operation belongs on 处理. |
| [node.tokenize](nodes/tokenize.md) | process | 分词 turns one text column into a word table: word/frequency pairs, bare words, or a single space-joined line. The upstream rows are the corpus; the node never reads a file itself. | When a later step needs word frequencies or one word per row: word cloud, bar chart, corpus statistics. Use the process node for cleaning-only passes. |
| [node.biblio](nodes/biblio.md) | biblio | 文献计量 builds a bibliometric network from a record table: co-occurrence, co-citation or coupling, with slice/look-back windows, top-N/G-index/threshold selection, LRF/MST/Pathfinder pruning, cluster labels (LLR/LSI/MI/TF-IDF), burst detection, structural variation, and five output shapes (nodes/edges/clusters/bursts/variation/dual_map). | After 文献融合 or a CNKI import, when the records should become a citation/co-word map. |
| [node.verify](nodes/verify.md) | process | 采集校验 reads two tables: the promised list and the crawled result. It matches keys, compares the expected count (评论数) with the actual rows, and emits 采集状态/期望条数/实际条数/缺失条数/完成度. | After a comment crawl, when the list says how many comments each post should have. |
| [node.fuse](nodes/fuse.md) | biblio | 文献融合 merges several source tables into one canonical record table: each role (entity, year, title, author, affiliation, text, reference, source) declares candidate column names, and the first candidate a source really has answers the role. | When CNKI/platform tables from different sources should become one record set. |
| [node.accumulate](nodes/accumulate.md) | data | 数据累积 appends the rows passing through it into a named lineage. ``identity=row`` appends every row; ``identity=columns`` appends only rows whose key columns are not already present. | When repeated runs should accumulate into one growing dataset instead of separate files. |
| [node.visualize](nodes/visualize.md) | visualize | 可视化 builds one chart from the upstream rows: an ECharts option or a matplotlib image, plus optional LaTeX figure/table. The chart type decides which fields it reads; the fields it requires are refused before a run. | When rows should become a chart; a PDF document belongs on PDF 编译. |
| [node.compile](nodes/compile.md) | visualize | PDF 编译 collects the LaTeX emitted by visualize parents and compiles one document. It reads parent artifacts, not rows, and refuses an empty source instead of producing a blank PDF. | When several charts/tables should become one PDF; a single chart can be saved directly. |
| [node.output](nodes/output.md) | output | 保存 merges every incoming table into one file, or saves a PDF from visualize/compile parents. Column sets must match; the executor refuses a merge rather than exporting only the first table. | At the end of a chain when the rows or the PDF need a file on disk. |
| [operator.drop_null](operators/drop_null.md) | clean | 删除所选列中含空值的行（任一为空或全部为空）。 | 在分析前去掉缺字段的行，或只保留每一列都填写完整的行。 |
| [operator.fill_null](operators/fill_null.md) | clean | 用固定值或上/下一行的值填补所选列的空单元格。 | 缺失值是“未填写”而不是“不存在”时，保留行并补上占位值。 |
| [operator.drop_duplicates](operators/drop_duplicates.md) | clean | 按所选列删除重复行；exact 逐字比较，normalized 先做全半角/空白归一。 | 同一行被采集了两次（翻页重叠、导出合并）时去重。 |
| [operator.dedupe_similar](operators/dedupe_similar.md) | clean | 按一列文本的 SimHash 距离删除近似重复行（改写、加表情、换标点）。 | 评论/转发里同一句话被改写多次时，保留一条代表。 |
| [operator.semantic_dedupe](operators/semantic_dedupe.md) | clean | 用本地句向量比较一列文本，删掉语义重复的行（同义改写也算）。 | 同一观点被换词重写多次，需要按意思去重时。 |
| [operator.similar_to](operators/similar_to.md) | clean | 用本地句向量找出与给定文字最相似的前 K 行，输出新的相似度表。 | 围绕一个说法找相关评论/帖子，而不是按关键词精确过滤。 |
| [operator.filter_rows](operators/filter_rows.md) | clean | 按一列与给定值的比较（等于/包含/大于/为空…）保留或删除行。 | 把分析限定在一个子集：某平台、某时间段、包含某个词。 |
| [operator.select_columns](operators/select_columns.md) | clean | 只保留列出的列（按此顺序），其余列丢弃。 | 导出或画图前把表收窄到需要的几列。 |
| [operator.rename_columns](operators/rename_columns.md) | clean | 把一列改名为另一个名字（旧列 -> 新列）。 | 上游列名与下游图表/算子约定的列名不一致时对齐一次。 |
| [operator.strip_whitespace](operators/strip_whitespace.md) | clean | 去掉所选列文本首尾的空白（含全角空格），行数不变。 | 采集文本带换行/缩进，导致去重、分词或图表标签不一致时。 |
| [operator.convert_type](operators/convert_type.md) | clean | 把一列转换为文本/整数/小数/布尔/日期时间类型。 | CSV 里数字被读成文本、时间戳需要变成 datetime 以按时间排序时。 |
| [operator.sort_rows](operators/sort_rows.md) | clean | 按一列升序或降序重排行（行集合不变）。 | 图表 X 轴或分阶段分析要求按时间/热度排序时。 |
| [operator.sample_rows](operators/sample_rows.md) | clean | 随机抽取 n 行或比例的样本（可固定随机种子）。 | 大表先抽样看效果，或做对照实验时取固定样本。 |
| [operator.groupby_agg](operators/groupby_agg.md) | statistics | 按一列分组，对另一列求和/均值/计数等，输出每组一行。 | 把明细表变成“每个平台/每天/每个主题一行”的统计表再画图。 |
| [operator.join_tables](operators/join_tables.md) | join | 把第二条输入的表格按连接键拼到第一条上（left/right/inner/outer/cross）。 | 把主题表、统计表或另一平台的结果按共同键合并成一张宽表。 |
| [operator.anti_join](operators/anti_join.md) | join | 按连接键排除已出现在第二张表里的行（内容去重），可只保留交集。 | 新一轮采集前先剔掉上一轮已抓过的链接/内容。 |
| [operator.column_calc](operators/column_calc.md) | clean | 用一列或多列的算式派生新列（如 点赞 / 评论）。 | 图表需要比率、差值或加权分，而表里只有原始计数时。 |
| [operator.bin_column](operators/bin_column.md) | clean | 把数值列分成若干区间或给定边界，并写成一列分箱标签。 | 把连续的热度/时长变成可做分组统计的类别。 |
| [operator.extract_time](operators/extract_time.md) | time | 从时间列派生日期、小时、星期、月或年，写成新列。 | 事件研究要按天聚合、看周内节律，或给分阶段准备时间基准列。 |
| [operator.bin_time](operators/bin_time.md) | time | 按给定时间边界把行切成阶段，并写入阶段名与可选的阶段序号。 | 要做分阶段 LDA、主题演化或情感演化，先把时间轴切成“发酵/爆发/衰退”。 |
| [operator.suggest_stages](operators/suggest_stages.md) | time | 按时间列的每日/每窗行数曲线，提议若干个阶段边界（起点、终点、峰值）。 | 不知道该把事件切成几段时，先让数据给出候选边界，再人工确认。 |
| [operator.topic_model](operators/topic_model.md) | topic | 对一列文本做主题建模（LDA 或句向量聚类），输出主题号、排名、特征词与权重。 | 要看语料由哪些议题构成，并得到每主题的特征词表。 |
| [operator.topic_by_stage](operators/topic_by_stage.md) | topic | 按阶段列分别做主题建模，输出阶段、主题、特征词、权重、文档数与困惑度。 | 要比较“发酵期”和“爆发期”的议题差异，就需要每阶段一套主题。 |
| [operator.topic_label](operators/topic_label.md) | topic | 让本地模型读每主题的特征词与样本文本，写出一句主题概括。 | 主题表只有“词1 词2”时，需要给人读得懂的主题名或摘要。 |
| [operator.cluster_label](operators/cluster_label.md) | topic | 按聚类列分组，让本地模型为每个簇写摘要，输出每簇一行。 | 已按主题/相似度聚好类，需要给每类一句可读的概括。 |
| [operator.cluster_review](operators/cluster_review.md) | biblio | 按文献聚类分组，汇总成员、频次与年份跨度，并让模型写簇综述。 | 知识图谱聚类已生成，需要逐簇的文献计量解读。 |
| [operator.reply_graph](operators/reply_graph.md) | social | 按评论者、楼层与父楼层还原“谁回复谁”的关系，输出带权重的边表。 | 要画互动网络、找关键传播者或社区结构时。 |
| [operator.compare_platform](operators/compare_platform.md) | statistics | 按平台列（或任意分组列）统计行数，并可对一列数值求均值/求和。 | 多平台合并后要比较各平台的量与强度。 |
| [operator.topic_map](operators/topic_map.md) | topic | 把主题投射到二维平面（pc1/pc2），并给出每主题的占比与特征词。 | 要画主题距离图（气泡位置=主题距离，大小=占比）。 |
| [operator.topic_salience](operators/topic_salience.md) | topic | 为每主题的词按“总体频率 + 主题内频率”的加权相关度排序，输出显著词表。 | 要画显著词图，或说明每个主题真正有区分度的词（而不是全语料高频词）。 |
| [operator.topic_timeline](operators/topic_timeline.md) | topic | 跨阶段追踪主题：首次出现、峰值、最后出现的阶段与规模，识别二次爆发。 | 要讲“议题如何随事件推进”的故事，需要每主题的生命周期轨迹。 |
| [operator.topic_flow](operators/topic_flow.md) | topic | 按特征词相似度把相邻阶段的主题配对，输出来源/目标、相似度与分歧度的流向边。 | 要画主题流向桑基图，说明“发酵期哪个议题变成了爆发期的什么议题”。 |
| [operator.topic_coherence](operators/topic_coherence.md) | topic | 在给定主题数区间上扫一遍 LDA，输出每个主题数的连贯度，帮助选择主题数。 | 不确定 n_topics 取几时，用连贯度曲线给依据。 |
| [operator.cooccur](operators/cooccur.md) | topic | 统计同一文本窗口内共同出现的词对，输出 source/target/value 边表。 | 要画词语共现网络，看概念如何绑定在一起。 |
| [operator.sentiment_evolution](operators/sentiment_evolution.md) | time | 按时间列聚合情感标签，输出每期正/中/负占比、总量与可选的情感指数。 | 要画情感演化曲线：时间 × 正负比例 × 强度。 |
| [operator.forecast](operators/forecast.md) | time | 用移动平均、Holt 或 Holt-Winters 对一条曲线外推若干期，并给出区间。 | 情感演化曲线需要往后看几期（预测区间是模型给的，不是事实）。 |
| [operator.alert](operators/alert.md) | time | 按连续涨跌、摆动幅度、升温与量能规则，在曲线上标出二次爆发预警点。 | 要在情感/热度曲线上自动指出“需要人工复核的时刻”。 |
