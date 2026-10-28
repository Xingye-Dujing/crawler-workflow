"""The analysis and process nodes: operations, their parameters, and the tables they emit.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/test_i18n.py``).
"""

ZH = {
    'accumulate.done': '累积数据集「{name}」：新增 {added} 行，当前共 {total} 行（版本 {version}）',
    'aggression.lexicon_done': (
        '网暴言论识别（词库）：{rows} 行中 {violent} 行含暴力言论，其中 {severe} 行为严重'
        '（漏报无法度量：词表之外的说法看不见）'
    ),
    'analysis.alert_fired': '二次爆发预警：{period} 触发 {signal}，数值 {value}',
    'analysis.alert_floor': '热度保持倍率不能超过 1（那等于要求热度上涨才算爆发），收到 {value}',
    'analysis.alert_none': (
        '未触发：幅度最大的是 {period}，连续 {streak} 期平均 |Δ| 未到 {swing}，强度斜率未到 {heating}'
    ),
    'analysis.alert_none_log': '预警检查了 {checked} 期：连续 {streak} 期、幅度阈值 {swing}，一条都没触发',
    'analysis.alert_reason': '连续 {streak} 期变化 {moves}；强度斜率 {intensity}；本期热度 {volume}（{held}）',
    'analysis.alert_rows': '预警至少要比连续期数多一行：需要 {least} 行，只有 {rows} 行',
    'analysis.alert_skipped': '「{col}」有 {n} 行解析不出日期，它们不参与预警判断',
    'analysis.alert_streak': '连续期数至少是 1，收到 {value}',
    'analysis.alert_threshold': '「{name}」阈值必须大于 0，收到 {value}',
    'analysis.bad_option': '「{op}」的「{param}」没有「{value}」这个选项（可用：{allowed}）',
    'analysis.bert_fallback': '{op} 的 bert 不可用（{reason}），本次改用 {used} 产出结果（非 bert）',
    'analysis.bin_failed': '列 {col} 分箱失败：{err}',
    'analysis.bot_col_missing': '水军可能性需要「{col}」列，表里没有',
    'analysis.bot_done': '水军可能性：{rows} 行里 {flagged} 行被标为可疑（来自 {authors} 个作者）',
    'analysis.bot_evidence_burst': '发帖突发：某10分钟窗内达 {peak} 条（各作者峰值中位 {median}）',
    'analysis.bot_evidence_dup': '与他人文本高度雷同（{ratio}）',
    'analysis.bot_limit': (
        '水军可能性只是召回线索、不是判决：它只能看见表内的跨账号重复文本与发帖突发，'
        '改了措辞和时间的协同账号一律漏检，且漏检率不可测'
    ),
    'analysis.calc_failed': '计算列 {col} = {expr} 失败：{err}',
    'analysis.cluster_cancelled': '已停止：还有 {n} 个簇没问模型，它们的摘要标为未处理',
    'analysis.cluster_done': '聚类摘要：{n} 个簇已写出（模型 {model}）',
    'analysis.cluster_empty': '簇 {group} 的摘要返回为空',
    'analysis.cluster_failed': '簇 {group} 的摘要失败：{err}',
    'analysis.cluster_no_texts': '簇 {group} 里没有可摘要的文本，无法问模型',
    'analysis.cluster_prompt': (
        '你是舆情分析研究员。下面是某网络暴力事件语料按语义聚类后、同一个簇里的若干条原始文本。'
        '请用不超过 40 个汉字概括这一簇在说什么；只输出概括本身，不要解释、不要引号。\n'
        '簇号：{group}\n簇内条数：{size}\n代表文本：\n{texts}'
    ),
    'analysis.coherence_best': (
        '主题数扫描（{low}…{high}）：一致性最高在 {coherence} 个主题，困惑度最低在 {perplexity} 个'
    ),
    'analysis.coherence_capped': '文本只有 {rows} 篇，扫描的终点从 {high} 个主题降到 {rows} 个',
    'analysis.coherence_pairs': (
        '每主题取 {topn} 个词，但这些词没有一对出现在同一篇文本里（跳过 {pairs} 对）：一致性无法测量，只有困惑度可读'
    ),
    'analysis.coherence_range': '主题数扫描的起点不能大于终点：{low} > {high}',
    'analysis.coherence_row': 'n_topics={topics}  coherence={coherence}  perplexity={perplexity}',
    'analysis.coherence_sampled': '主题数扫描只抽 {used} 篇文本（共 {total} 篇可用），换个样本数字会变',
    'analysis.col_missing': '未找到列“{col}”',
    'analysis.compare_agg': '{op}：未知聚合「{agg}」，数值列只支持 sum 或 mean（列名按聚合命名，名实必须相符）',
    'analysis.compare_done': '跨平台对比：{platforms} 个平台（数值列 {value}）',
    'analysis.cooccur_count': '共现次数阈值至少是 1，收到 {value}',
    'analysis.cooccur_done': '共词网络：{words} 个候选词、{docs} 篇文本，{pairs} 对里 {edges} 对达到阈值 {floor}',
    'analysis.cooccur_empty': ('没有一对词共现达到阈值 {floor}：{pairs} 对里最高只有 {top} 次，请降低阈值或放宽候选词'),
    'analysis.cooccur_topn': '共词网络的候选词上限是 {cap}（词数翻倍则边数翻四倍），收到 {value}',
    'analysis.cooccur_words': '只选出 {found} 个候选词，凑不出一对共现（要求前 {topn} 个）',
    'analysis.dedupe_distance': '近重复去重支持的距离是 0–{max} 位，收到 {value}，已拒绝（不做全量两两比对）',
    'analysis.dedupe_similar': (
        '近重复去重：在「{column}」上按 SimHash 距离 ≤{distance} 判定，删除 {n} 行（每组保留首次出现的那行）'
    ),
    'analysis.evolution_done': (
        '情感演化：按「period」聚合出 {n} 个时段（{periods}），情感指数 =(积极−消极)/总数 ∈ [-1, 1]'
    ),
    # The intensity curve is only honest if the periods it could not score say so: a blank
    # in an exported table is invisible, and 0.5 would print as "measured, and neutral".
    'analysis.evolution_unscored': '「{col}」在时段「{periods}」里一行分数都没有，这些时段的情感强度留空',
    'analysis.flow_done': '主题流向：{stages} 个阶段之间得到 {edges} 条边（阈值 {value}，实测最高 {best}）',
    'analysis.flow_no_edges': ('没有一条主题流向达到阈值 {value}：实测最相似的一对是 {best}，把阈值调到它以下再来'),
    'analysis.flow_similarity': '「流向相似度阈值」要在 0 到 1 之间，收到 {value}',
    'analysis.flow_stage_empty': '阶段「{stage}」里没有主题行（先检查「{col}」）',
    'analysis.flow_stages': '主题流向至少要 2 个相邻阶段，现在只有 {stages} 个',
    'analysis.flow_weights': '{topic}（阶段「{stage}」）的「{col}」里没有可用的词权重，无法算分布差异',
    'analysis.forecast_dates': '「{col}」不是能解析成日期的时段列（一个日期都没有）：阶段名没法外推',
    'analysis.forecast_done': '{method} 外推：{rows} 期观测，往后 {horizon} 步，间隔 {gap} 天（末期 {last}）',
    'analysis.forecast_duplicate': '「{col}」里有同一天出现两行：{days}（两行会被当成趋势的两步）',
    # ── 往前看：曲线外推与二次爆发预警 ──
    'analysis.forecast_horizon': '外推步数至少是 1，收到 {value}（0 步只是把最后一格再抄一遍）',
    'analysis.forecast_rows': '外推至少要 {least} 期观测，这一列只有 {rows} 期同时给出时间与数值',
    'analysis.forecast_season': '季节类方法的周期长度至少 2 期，收到 {value}',
    'analysis.forecast_season_rows': '季节方法观测不足：至少要 {season} 期，本列只有 {rows} 期',
    'analysis.forecast_smooth': '平滑系数「{name}」要在 0 与 1 之间（不含两端），收到 {value}',
    'analysis.forecast_uneven': '时段间隔不齐：{rows} 期里有 {steps} 步不是 {gap} 天，未来格按 {gap} 天间隔标注',
    'analysis.forecast_window': '移动平均的窗口至少 2 期才能平均，收到 {value}',
    'analysis.forecast_window_rows': '窗口 {window} 期至少要留一期来预测，这一列只有 {rows} 期',
    'analysis.join_missing_cols': '合并失败：这些列不存在：{cols}',
    'analysis.join_need_keys': '合并失败：请填写左右两边的关联列',
    'analysis.join_no_right': '合并失败：没有拿到右表数据（请把第二条连线接到作为右表的节点）',
    'analysis.keyword_pos_no_match': (
        '按词性 {tags} 过滤后，{rows} 行文本一个关键词都没留下——多半是词性写法不对：'
        '请用 jieba 的标签（如 n、v、vn、a），而不是中文词性名'
    ),
    'analysis.label_cached': '主题概括：新问模型 {asked} 次，重放缓存答案 {replayed} 次（同一张表重跑不再重复付费）',
    'analysis.label_cancelled': '已停止：还有 {n} 个主题没问模型，它们的概括标为未处理',
    'analysis.label_done': '主题概括：{n} 个主题已写出（模型 {model}）',
    'analysis.label_empty': '{topic} 的主题概括是空的（模型只回了标点）',
    'analysis.label_failed': '{topic} 的主题概括失败：{err}',
    'analysis.label_fallback': '主题「{topic}」未获模型概括，已按其权重词回退标注（{reason}）',
    'analysis.label_fallback_all': '{n} 个主题无模型可用，全部按权重词回退标注',
    # 主题概括：一行一次模型调用，所以失败要说清是哪个主题，停手也要说清还剩几个没问。
    'analysis.label_no_llm': '「{op}」没有拿到模型客户端：只有画布上的运行才带模型',
    'analysis.label_no_words': '{topic} 的「{col}」是空的，没有特征词就没有可概括的东西',
    'analysis.label_prompt': (
        '你是舆情分析研究员。下面是某网络暴力事件在一个阶段里一个主题的特征词与代表文本。'
        '请用不超过 15 个汉字概括这个主题在说什么；只输出概括本身，不要解释、不要引号。\n'
        '阶段：{stage}\n主题编号：{topic}\n特征词：{words}\n代表文本：{samples}'
    ),
    'analysis.label_too_many': '主题概括要逐主题问模型：{rows} 行超过了上限 {limit}，请先把主题表缩小',
    'analysis.multi_models_run': '多模型对比：本次用 {n} 个模型跑「{op}」：{models}',
    'analysis.need_multi_models': '「{op}」的 bert 模式要多模型对比至少需 2 个模型（当前 {n} 个）',
    # A count the step reads as an integer. The panel cannot send junk here (the normalizer drops
    # an unreadable box to the default), but a hand-written workflow file and /api/analysis/run
    # both reach the service, where int('abc') would otherwise surface as an opaque node failure.
    'analysis.need_number': '「{op}」的「{param}」要是一个整数，收到「{value}」',
    # A cleaning step that this table cannot carry out. `{op}` and `{param}` stay the
    # storage names on purpose: they are what the caller of /api/analysis/run wrote,
    # and what the Settings panel stores in the node's JSON, so a person fixing a
    # hand-written pipeline can match them against the file they edited.
    'analysis.need_param': '「{op}」缺少「{param}」，请先填写',
    'analysis.rename_blank': '「{op}」：这些列的新名字是空的，请填写：{cols}',
    'analysis.reply_graph_done': '回复传播图：{edges} 条边、{nodes} 个节点',
    'analysis.reply_graph_no_edges': (
        '回复传播图找不到可关联的回复：请确认「评论者」「楼层」「父楼层」三列存在，'
        '且确有回复行的「父楼层」能对上某条顶层评论的「楼层」'
    ),
    'analysis.review_cancelled': '已停止：还有 {n} 个簇没问模型，它们的综述标为未处理',
    'analysis.review_done': '簇综述：{n} 个簇已写出（模型 {model}）',
    'analysis.review_empty': '簇 {group} 的综述返回为空',
    'analysis.review_fact_label': 'LLR 标签：{label}',
    'analysis.review_fact_members': '代表节点（按频次）：{members}',
    'analysis.review_fact_size': '簇内节点数：{n}',
    'analysis.review_fact_span': '年份跨度：{span}',
    'analysis.review_failed': '簇 {group} 的综述失败：{err}',
    'analysis.review_failed_blank': '簇 {group} 的综述失败，按要求留空：{err}',
    'analysis.review_failed_fallback': '簇 {group} 的综述失败，已改用表格事实生成的兜底句：{err}',
    'analysis.review_fallback_text': '（未经模型，按表格事实生成）该簇含 {size} 个节点，代表节点：{members}',
    'analysis.review_no_groups': '簇综述找不到分组列 {col}：请先让上游文献计量节点开启聚类',
    'analysis.review_prompt': (
        '你是文献计量与科学计量研究员。下面是一个知识图谱聚类簇的**既有度量**（全部来自表格，不是推测）。'
        '请据此写出 3–5 句该簇所代表的研究前沿：它关注什么问题、由哪些概念支撑、'
        '在给定年份区间里可能的演化方向。只写分析本身，不要复述数据、不要列点、不要客套；用{language}回答。'
        '\n'
        '{facts}'
    ),
    'analysis.stage_blank': '「{col}」有 {n} 行没有阶段（时间戳没解析出来），它们不进任何主题模型',
    # 分阶段主题模型。每一句都点名是哪个阶段、哪个主题，因为「某个阶段没跑出来」在一堆
    # TopicⅠ-1 … TopicⅤ-4 里是查不出来的。
    'analysis.stage_order': (
        '「{col}」这一列已经看不出阶段先后（跨节点会退化成普通文本）。把「按时间划分阶段」与它放在同一条'
        '流水线，或填「阶段排序列」指向一个时间列'
    ),
    'analysis.stage_order_col': '「{op}」的「阶段排序列」在表里不存在：{col}',
    'analysis.stage_order_unparsed': '「{col}」里排不出这些阶段的先后（没有任何可解析的时间）：{stages}',
    'analysis.stage_order_unranked': (
        '「{col}」里没有这些阶段的序号（要的是数字：划分阶段 的阶段序号，或 分阶段 LDA 的 stage_order）：{stages}'
    ),
    'analysis.stages_basis_first': '自曲线首日 {day} 起',
    'analysis.stages_basis_valley': '自谷底 {valley} 的次日起',
    'analysis.stages_done': '阶段建议：{n} 个候选窗口、覆盖 {rows} 行（{span}）',
    'analysis.stages_edges': '建议边界 edges（左闭右开，末位是最后一天+1）：{edges}',
    'analysis.stages_folded': '曲线上的峰多于 {kept} 个，只保留最高的 {kept} 个（折掉了 {dropped} 个）',
    'analysis.stages_folded_windows': (
        '{n} 个窗口短于「最短窗口」{days} 天，已并入相邻较长的窗口（一天冲上来的不算一个阶段）'
    ),
    'analysis.stages_labels': '建议阶段名 labels（与 edges 一一对应，仅占位，可改名）：{labels}',
    'analysis.stages_no_peak': (
        '发文量曲线里找不到 {ratio} 倍于日常（中位数 {floor} 行/日）的转折峰，'
        '这一列撑不起阶段划分——曲线只有一段，就不要切成多段'
    ),
    'analysis.stages_ratio': '「峰倍率」至少要是 1（高于平常的一天才算峰），收到 {value}',
    # A boundary PROPOSAL: this step rewrites no row and does not decide when the event
    # turned — that needs the dates the researcher knows (the notice, the apology, the
    # filing), which are not in the post counts.
    'analysis.stages_sparse': '这一列只有 {days} 天有记录，切不出阶段（至少需要 {least} 天）',
    'analysis.step_col_missing': '「{op}」：表里没有名为「{col}」的列',
    'analysis.step_cols_missing': '「{op}」：表里没有这些列：{cols}',
    'analysis.time_bin_edges': '时间分段里有无法解析成日期的边界：{edges}',
    'analysis.time_bin_labels': '时间分段需要「边界数 = 阶段名数 + 1」，现在是 {edges} 个边界、{labels} 个名称',
    'analysis.time_bin_order': '{op} 的边界必须按时间从早到晚排列',
    'analysis.time_binned': '{col} 划分完成：{detail}',
    'analysis.time_unparsed': (
        '「{col}」有 {n} 行不是可解析的时间（站点只给了相对标签，如「09月26日 21:00」），已留空而不是猜一个年份'
    ),
    'analysis.timeline_blank': '「{col}」有 {n} 行不属于任何阶段，它们不进生命周期',
    'analysis.timeline_done': (
        '主题生命周期：{topics} 个主题（{stages} 个阶段），{multi} 个跨多阶段、{secondary} 个判为次生舆情'
        '（词重合阈值 {value}）'
    ),
    'analysis.timeline_overlap': '「同主题词重合度」要在 0 到 1 之间，收到 {value}',
    'analysis.timeline_partial': '「{col}」有 {n} 行不是数值，它们在峰值里按 0 计',
    'analysis.timeline_secondary': '次生舆情：{topic} 的阶段路径 {path}',
    'analysis.timeline_size': '「{col}」里一个数值都没有，峰值无从测量（留空不等于峰为 0）',
    # ── 阶段之后的读数：主题生命周期、跨阶段流向、主题数扫描、共词 ──
    # Each refusal names the number it measured, so the fix is a choice with a figure in front
    # of it rather than a guess at what the step wanted.
    'analysis.timeline_stages': '主题生命周期至少要 2 个阶段才谈得上「先后」，现在只有 {stages} 个',
    'analysis.timeline_words': '阶段「{stage}」的 {topic} 在「{col}」里没有特征词，无法跨阶段追踪它',
    'analysis.topic_count': 'LDA 主题数至少要 2，收到 {value}（1 个主题只是"整段文本"）',
    'analysis.topic_done': (
        'LDA 主题模型：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}（数值越低拟合越好，但过小意味着在记原文）'
    ),
    'analysis.topic_embed_done': '嵌入主题：{model}，{n} 个主题，{rows} 行文本',
    'analysis.topic_embed_failed': '句向量模型「{model}」加载或运行失败：{err}',
    'analysis.topic_embed_unavailable': '嵌入主题方法缺少可选依赖：{packages}（不回退到 LDA，请安装或改用 LDA）',
    'analysis.topic_empty_cluster': (
        '嵌入主题「{topic}」没有分到任何文本：这是模型的答复，不是画布的错——'
        '主题数 {n} 是请求值，模型实际只切出 {got} 个'
    ),
    'analysis.topic_features': 'LDA 无法从这一列抽到特征词（可能整列都是标点或停用词）：{err}',
    'analysis.topic_lambda': 'λ 要在 0 到 1 之间（0=只看相对溢出，1=只看主题内概率），收到 {value}',
    # 主题可视化（pyLDAvis 那两张图的数据面）。λ 是「按主题自身概率」还是「按相对全库的溢出」
    # 排序，同一模型会给出两份不同的词表，所以用了哪个值必须随表一起说出来。
    'analysis.topic_map_done': (
        '主题距离图：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}'
        '（气泡大小=主题占比，坐标=两主题词分布的 JS 散度经 MDS）'
    ),
    'analysis.topic_method_auto_embedding': '主题方法 auto：检测到编码器，使用 embedding（{model}）',
    'analysis.topic_method_auto_lda': '主题方法 auto：无编码器包，改用 LDA（结果按 LDA 计）',
    'analysis.topic_rows': 'LDA 需要至少和主题数一样多的文本：主题 {topics} 个、有效文本 {rows} 行',
    'analysis.topic_salience_done': (
        '主题显著词：{n} 个主题、{rows} 篇文本、共 {terms} 行，λ={value}（1=按主题内概率排序，0=按相对全库的溢出排序）'
    ),
    'analysis.topic_stage_counts': (
        '每阶段主题数要与阶段一一对应：{stages} 个阶段，收到 {counts}（只填一个数字表示各阶段同数）'
    ),
    'analysis.topic_stage_done': '阶段「{stage}」：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}',
    'analysis.topic_stage_empty': '阶段「{stage}」一行都没有，无法为它建模（先检查「{col}」的边界）',
    'analysis.topic_stage_features': '阶段「{stage}」抽不到特征词：{err}',
    'analysis.topic_stage_number': '每阶段主题数只能是整数，收到「{value}」',
    'analysis.topic_stage_rows': (
        '阶段「{stage}」只有 {rows} 篇可用文本，撑不起 {topics} 个主题（LDA 至少要有和主题数一样多的文本）'
    ),
    'analysis.topic_stage_topic_words': '{topic}（{stage}）: {words}',
    'analysis.topic_stage_unused': '阶段「{stage}」的 {topic} 没有分到任何文本（doc_n=0），特征词改用该主题的词分布',
    'analysis.topic_stage_words': (
        '阶段「{stage}」的 {topic} 一个特征词都选不出来（没有文本归到这个主题，请调小该阶段的主题数）'
    ),
    'analysis.type_convert_failed': '列 {col} 转换为 {dtype} 失败：{err}',
    'anomaly.done': '异常检测：{n}/{total} 行被标记（contamination={c:.2f}）',
    'anomaly.ignored_columns': '异常检测：以下列不是数值列，已跳过（{columns}）',
    'anomaly.no_numeric': '没有可用于异常检测的数值列',
    'anomaly.no_usable_columns': '异常检测：你指定的列都不是数值列（{columns}）',
    'anomaly.too_few': '行数过少（{n} < {min}），异常检测无法给出结论',
    'clean.regex_done': '正则清洗：保留 {kept} 行、判定删除 {dropped} 行（未做主题相关性判断，那需要 llm 模式）',
    'clean.unknown_mode': '清洗节点没有名为「{mode}」的模式（可用：regex、llm）',
    'cluster.dbscan': 'DBSCAN 发现 {n} 个簇 + {noise} 个噪声点',
    'cluster.done': '聚类完成：{rows} 行分为 {clusters} 簇（轮廓系数={score:.3f}）',
    'cluster.no_features': '文本无法分词（可能只有符号），已跳过聚类：{err}',
    'cluster.not_enough': '有效行数不足，无法聚类（至少需要 2 行）',
    'corr.done': '相关性分析（{method}）：找到 {n} 对（min_abs={min_abs:.2f}）',
    'corr.ignored_columns': '相关性分析：以下列不是数值列，已跳过（{columns}）',
    'corr.need_cols': '相关性分析至少需要 2 个数值列',
    'corr.no_usable_columns': '相关性分析：你指定的列都不是数值列（{columns}）',
    'emotion.bert_bad_label': 'BERT 模型回了一个不认识的情绪标签「{label}」，无法归入这六类',
    'emotion.bert_done': '[BERT] 情绪分类完成，{n} 行，失败 {failed} 行',
    'emotion.bert_failed': 'BERT 情绪判断失败：{err}',
    'emotion.bert_loaded': 'BERT 情绪模型已加载：{model}（{runtime}/{precision}，跑在 {device}，逐批）',
    'emotion.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'emotion.bert_no_model': 'BERT 模式还需要在「模型」里填一个情绪分类模型名（本地目录或仓库名），空着无法判断',
    'lex.needTerms': '请至少提供一个词。',
    'lex.unknownKind': '未知的词库类型：{kind}',
    'lex.userdictLoadFailed': '加载 jieba 用户词典失败。',
    'lex.userdictReadFailed': '读取用户词库失败，分词器保持不变。',
    'ml.bad_model_name': '模型名「{name}」不合法：必须是单个路径安全的组件，不含分隔符',
    'ml.emotion_done': '[ML] 情感分类完成，共处理 {n} 行，模式: ML',
    'ml.emotion_failed': 'ML 情感预测失败：{err}——回退为 Neutral',
    'ml.missing_col': 'DataFrame 缺少必需的列“{col}”。跳过分析。',
    'ml.model_untrained_refused': (
        '「{name}」模型尚未训练，也没有可加载的已保存模型 —— 拒绝作答，而不是给每行编一个中性结果'
    ),
    'ml.need_two_labels': '训练至少需要 2 个不同的标签，当前只有：{label}',
    'ml.no_rows': '没有需要处理的行（目标列为空）。',
    'ml.no_training_rows': '没有可用的训练数据：所有行的文本或标签都是空的',
    'ml.tendency_done': '[ML] 倾向性分析完成，共处理 {n} 行，模式: ML',
    'ml.tendency_failed': 'ML 倾向性预测失败：{err}——回退为 Objective Statement',
    'ner.dropped': '实体识别：{n} 条模型答案未在原文中出现，已丢弃（不记录推测出的实体）',
    'net.blocked': '。诊断：本机出网正常，但该平台的主机连不上，可能是站点故障或本地拦截',
    'net.offline': '。诊断：本机当前连不上任何外网（两个对照主机都不通），请先恢复网络再跑',
    'net.region': '。诊断：本机目前到不了该平台所在的那一侧网络（对照主机不通，另一端正常）——请换网络后重跑',
    'net.slow': '。诊断：两侧网络都能连通，因此没有依据判断这一页为什么没到；可以再跑一次，或按停止结束',
    'net.speed': '（实测下载约 {speed} kB/s）',
    'sentiment.bad_thresholds': '正向阈值 {pos} 不得低于负向阈值 {neg}，那样每一行都会同时满足两边',
    'sentiment.bert_bad_label': 'BERT 模型回了一个不认识的标签「{label}」，无法归入正面/负面/中性',
    'sentiment.bert_failed': 'BERT 判断失败：{err}',
    'sentiment.bert_loaded': 'BERT 情感模型已加载：{model}（{runtime}/{precision}，跑在 {device}，逐批）',
    'sentiment.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'sentiment.bert_need_runtime': 'torch+transformers 或 onnxruntime+tokenizers',
    'sentiment.bert_no_labels': '这个 BERT 模型目录没有 id2label 标签表，输出读不成类别：{path}',
    'sentiment.bert_no_model': 'BERT 模式还需要在「模型」里填一个情感模型名（本地目录或仓库名），空着无法判断',
    'sentiment.bert_no_model_dir': '没有找到 BERT 模型目录：{path}。{remedy}',
    'sentiment.bert_no_onnx': '这个 BERT 模型目录里没有可加载的 ONNX 图：{path}',
    'sentiment.bert_onnx_inputs': '这个 ONNX 图的输入不是本程序约定的四路，实测：{found}',
    'sentiment.bert_session_dropped': '为控制内存已释放更早加载的 BERT 模型：{model}（后面再用到会重新加载）',
    'sentiment.ml_failed': 'ML 情感极性预测失败：{err}——回退为 neutral',
    'sentiment.packRemedyFrozen': (
        '桌面版的 BERT 模型是一个单独的压缩包：把 CaiXiHui-bert-models-win64.zip 解压到程序目录下的 '
        'bert_models\\，再重启程序'
    ),
    'sentiment.packRemedySource': (
        '源码版需要先用 ml_train/scripts/export_onnx_bert.py 从训练好的权重导出 ONNX 目录，'
        '或在节点的「模型」里填一个已存在的目录名'
    ),
    # ── 情感极性（snownlp / bert / ml / llm）───────────────────────────
    # A row that fails to read stays blank, so the failure line has to say the count:
    # 「判断为中性」 and 「没判断出来」 are different statements about the text.
    'sentiment.scored': '情感极性（{mode}）：已判断 {n} 行',
    'sentiment.scored_failed': '情感极性：{n} 行读取失败，留空（不是中性）',
    'sentiment.snownlp_failed': 'SnowNLP 判断失败：{err}',
    'sentiment.unknown_mode': '使用了未知的情感极性模式「{mode}」',
    'sig.degenerate': '显著性检验：{method} 无法计算（组数或组内样本不足、方差为零），不给假 p 值',
    'sig.done': '显著性检验（{method}）：{n_groups} 组、共 {n} 行，统计量={statistic}，p={p}',
    'sig.group_column_missing': '显著性检验：分组列“{col}”不在表里',
    'sig.no_group_column': '显著性检验：没有指定分组列',
    'sig.no_usable_rows': '显著性检验：分组“{col}”丢空值/非数值后一行都不剩',
    'sig.no_value_column': '显著性检验：没有指定数值列',
    'sig.two_groups_only': '显著性检验：{method} 只比较两组，实际 {n} 组——请改用 ANOVA / Kruskal-Wallis',
    'sig.two_groups_required': '显著性检验：{method} 至少需要两组，实际 {n} 组',
    'sig.unknown_method': '显著性检验：未知方法“{method}”',
    'sig.value_column_missing': '显著性检验：数值列“{col}”不在表里',
    'sig.value_not_numeric': '显著性检验：数值列“{col}”整列都无法转成数字',
    'tendency.bert_bad_label': 'BERT 模型回了一个不认识的倾向标签「{label}」，无法归入这六类',
    'tendency.bert_done': '[BERT] 倾向分类完成，{n} 行，失败 {failed} 行',
    'tendency.bert_failed': 'BERT 倾向判断失败：{err}',
    'tendency.bert_loaded': 'BERT 倾向模型已加载：{model}（{runtime}/{precision}，跑在 {device}，逐批）',
    'tendency.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'tendency.bert_no_model': 'BERT 模式还需要在「模型」里填一个倾向分类模型名（本地目录或仓库名），空着无法判断',
}

EN = {
    'accumulate.done': 'Cumulative dataset “{name}”: +{added} rows, {total} total (version {version})',
    'aggression.lexicon_done': (
        'cyberbullying scan (word list): {violent} of {rows} rows carry violent speech, {severe} severe '
        '(misses cannot be measured here — wording outside the list is invisible)'
    ),
    'analysis.alert_fired': 'flare-up warning: {period} fired {signal} at {value}',
    'analysis.alert_floor': 'the volume-hold ratio cannot exceed 1 (that asks for growth), got {value}',
    'analysis.alert_none': (
        'nothing fired: the largest swing was {period}, and {streak} consecutive moves stayed under {swing} '
        'while the intensity slope stayed under {heating}'
    ),
    'analysis.alert_none_log': 'warning checked {checked} periods (streak {streak}, swing {swing}) and fired on none',
    'analysis.alert_reason': (
        'moves over the last {streak} periods {moves}; intensity slope {intensity}; volume {volume} ({held})'
    ),
    'analysis.alert_rows': 'the warning needs one row more than the streak: asked for {least}, this table has {rows}',
    'analysis.alert_skipped': '{n} rows of "{col}" parse to no date, so they join no warning check',
    'analysis.alert_streak': 'the streak has to be at least 1 period, got {value}',
    'analysis.alert_threshold': 'the "{name}" threshold has to be above 0, got {value}',
    'analysis.bad_option': '{op} has no "{param}" option "{value}" (available: {allowed})',
    'analysis.bert_fallback': '{op} bert unavailable ({reason}); this run used {used} for the column, not bert',
    'analysis.bin_failed': 'Binning failed for {col}: {err}',
    'analysis.bot_col_missing': 'bot likelihood needs the "{col}" column, which is not in this table',
    'analysis.bot_done': 'bot likelihood: {flagged} of {rows} rows flagged suspect (across {authors} authors)',
    'analysis.bot_evidence_burst': 'posting burst: {peak} posts in one 10-minute window (author peaks median {median})',
    'analysis.bot_evidence_dup': 'text highly similar to another account ({ratio})',
    'analysis.bot_limit': (
        'bot likelihood is a recall hint, not a verdict: it only sees cross-account near-duplicate text '
        'and posting bursts inside the table; a coordinated account that varies wording and timing is '
        'missed, and that miss rate is unmeasurable'
    ),
    'analysis.calc_failed': 'Column calc failed for {col} = {expr}: {err}',
    'analysis.cluster_cancelled': 'stopped: {n} clusters were never asked, and their summaries are marked 未处理',
    'analysis.cluster_done': 'cluster summaries: {n} clusters written (model {model})',
    'analysis.cluster_empty': 'the summary for cluster {group} came back empty',
    'analysis.cluster_failed': 'the summary for cluster {group} failed: {err}',
    'analysis.cluster_no_texts': 'cluster {group} has no text to summarise, so the model cannot be asked',
    'analysis.cluster_prompt': (
        'You are a public-opinion analyst. Below are several raw posts that fall in the SAME semantic cluster '
        'of a cyberbullying corpus. Summarise what this cluster is about in one short sentence; output the '
        'summary alone, no explanation, no quotes.\n'
        'Cluster: {group}\nSize: {size}\nSample texts:\n{texts}'
    ),
    'analysis.coherence_best': (
        'topic-count sweep ({low}…{high}): best coherence at {coherence} topics, lowest perplexity at {perplexity}'
    ),
    'analysis.coherence_capped': (
        'only {rows} texts are available, so the sweep stops at {rows} topics instead of {high}'
    ),
    'analysis.coherence_pairs': (
        'no pair of the {topn} top words of any topic appears in one text ({pairs} pairs skipped): '
        'coherence is unmeasurable here, only perplexity is readable'
    ),
    'analysis.coherence_range': 'the topic-count sweep cannot start above where it ends: {low} > {high}',
    'analysis.coherence_row': 'n_topics={topics}  coherence={coherence}  perplexity={perplexity}',
    'analysis.coherence_sampled': (
        'the sweep fits {used} sampled texts out of {total} available; a different sample moves the numbers'
    ),
    'analysis.col_missing': 'Column "{col}" not found',
    'analysis.compare_agg': (
        '{op}: unknown aggregate "{agg}" — the value column supports only sum or mean '
        '(its name declares the aggregate, so the label must match how it was computed)'
    ),
    'analysis.compare_done': 'cross-platform compare: {platforms} platforms (value column {value})',
    'analysis.cooccur_count': 'the co-occurrence count threshold has to be at least 1, got {value}',
    'analysis.cooccur_done': (
        'co-occurrence network: {words} candidate words over {docs} texts, {edges} of {pairs} pairs at or above {floor}'
    ),
    'analysis.cooccur_empty': (
        'no word pair reached the count threshold {floor}: the busiest of {pairs} pairs appeared {top} times, '
        'so lower the threshold or widen the candidates'
    ),
    'analysis.cooccur_topn': (
        'a co-occurrence network caps its candidate words at {cap} (doubling the words '
        'quadruples the edges), got {value}'
    ),
    'analysis.cooccur_words': (
        'only {found} candidate words were available, which cannot form a pair (asked for the top {topn})'
    ),
    'analysis.dedupe_distance': (
        'near-duplicate dedupe supports a distance of 0–{max} bits, got {value}: '
        'a larger one is refused rather than answered with an all-pairs scan'
    ),
    'analysis.dedupe_similar': (
        'Near-duplicate dedupe: SimHash distance ≤{distance} on "{column}", dropped {n} rows (first of each group kept)'
    ),
    'analysis.evolution_done': (
        'Sentiment evolution: {n} periods from "period" ({periods}); index = (positive − negative) / total ∈ [-1, 1]'
    ),
    'analysis.evolution_unscored': (
        'no rows of "{col}" carry a score in {periods}, so the sentiment intensity is left empty there'
    ),
    'analysis.flow_done': 'topic flow: {edges} edges between {stages} phases (threshold {value}, best measured {best})',
    'analysis.flow_no_edges': (
        'no topic pair reached the similarity threshold {value}: the closest measured pair was {best}, '
        'so lower the threshold below it'
    ),
    'analysis.flow_similarity': 'the flow similarity threshold has to be between 0 and 1, got {value}',
    'analysis.flow_stage_empty': 'phase "{stage}" holds no topic rows (check "{col}" first)',
    'analysis.flow_stages': 'topic flow needs at least 2 adjacent phases, this table has {stages}',
    'analysis.flow_weights': (
        '{topic} (phase "{stage}") has no usable word weights in "{col}", so no divergence can be computed'
    ),
    'analysis.forecast_dates': '"{col}" is not a period column of dates: a phase NAME cannot be extrapolated',
    'analysis.forecast_done': (
        '{method} forecast: {rows} observed periods, {horizon} steps ahead, {gap}-day spacing (last {last})'
    ),
    'analysis.forecast_duplicate': '"{col}" has two rows for the same day: {days} (they read as two steps of a trend)',
    # ── Looking forward: extrapolating the curve, and the flare-up warning ──
    'analysis.forecast_horizon': 'the horizon has to be at least 1 step, got {value} (0 just copies the last cell)',
    'analysis.forecast_rows': (
        'extrapolating needs at least {least} observed periods, this column gives {rows} with both a date and a number'
    ),
    'analysis.forecast_season': 'a seasonal method needs a cycle length of at least 2 periods, got {value}',
    'analysis.forecast_season_rows': 'seasonal methods need at least {season} observed periods; this column has {rows}',
    'analysis.forecast_smooth': 'the smoothing factor "{name}" has to be strictly between 0 and 1, got {value}',
    'analysis.forecast_uneven': (
        'the periods are not evenly spaced: {steps} of {rows} gaps are not {gap} days, '
        'so future rows are labelled {gap} days apart'
    ),
    'analysis.forecast_window': 'a moving average needs 2 periods to average, got {value}',
    'analysis.forecast_window_rows': (
        'a window of {window} still needs one period left to forecast, this column has {rows}'
    ),
    'analysis.join_missing_cols': 'Join failed — no such column: {cols}',
    'analysis.join_need_keys': 'Join failed: set both the left and the right key column',
    'analysis.join_no_right': "Join failed: no right-hand table — connect it as this node's second input",
    'analysis.keyword_pos_no_match': (
        'After the POS filter {tags}, none of the {rows} text rows kept a single keyword — '
        'the tag spelling is likely wrong: use jieba tags (n, v, vn, a), not Chinese POS names'
    ),
    'analysis.label_cached': (
        'topic summaries: {asked} new questions to the model, {replayed} answers replayed from the '
        'cache (re-running the same table no longer pays twice)'
    ),
    'analysis.label_cancelled': 'stopped: {n} topics were never asked, and their summaries are marked 未处理',
    'analysis.label_done': 'topic summaries: {n} written (model {model})',
    'analysis.label_empty': 'the summary for {topic} came back empty (the model answered with punctuation only)',
    'analysis.label_failed': 'the summary for {topic} failed: {err}',
    'analysis.label_fallback': 'no model summary for {topic}; labelled from its weighted words ({reason})',
    'analysis.label_fallback_all': 'no model available; {n} topics all labelled from their weighted words',
    'analysis.label_no_llm': '{op} was handed no model client: only a canvas run carries one',
    'analysis.label_no_words': '{topic} has an empty "{col}", and there is nothing to summarise without feature words',
    'analysis.label_prompt': (
        'You are a public-opinion researcher. Below are the feature words and sample posts of one topic '
        'inside one phase of a cyberbullying event. Summarise what this topic is about in at most six words; '
        'output the phrase alone, no explanation, no quotes.\n'
        'Phase: {stage}\nTopic: {topic}\nFeature words: {words}\nSample posts: {samples}'
    ),
    'analysis.label_too_many': (
        'the labelling step asks the model once per topic: {rows} rows is over the limit of {limit}, '
        'so filter the topic table first'
    ),
    'analysis.multi_models_run': 'multi-model compare: {op} ran over {n} models: {models}',
    'analysis.need_multi_models': '{op} bert mode needs ≥2 models to compare (now {n})',
    'analysis.need_number': '{op}: "{param}" has to be a whole number, got "{value}"',
    'analysis.need_param': '{op} needs {param}, which is empty',
    'analysis.rename_blank': '{op}: these columns have no new name — set one for: {cols}',
    'analysis.reply_graph_done': 'reply graph: {edges} edges over {nodes} nodes',
    'analysis.reply_graph_no_edges': (
        'the reply graph found no resolvable reply: check that 评论者 / 楼层 / 父楼层 exist and '
        "that some reply's parent floor matches a top-level comment's floor"
    ),
    'analysis.review_cancelled': 'stopped: {n} clusters were never asked, their reviews are marked unprocessed',
    'analysis.review_done': 'cluster review: {n} clusters written (model {model})',
    'analysis.review_empty': 'the review for cluster {group} came back empty',
    'analysis.review_fact_label': 'LLR label: {label}',
    'analysis.review_fact_members': 'strongest members (by frequency): {members}',
    'analysis.review_fact_size': 'nodes in cluster: {n}',
    'analysis.review_fact_span': 'year span: {span}',
    'analysis.review_failed': 'the review of cluster {group} failed: {err}',
    'analysis.review_failed_blank': 'the review of cluster {group} failed and was left blank as asked: {err}',
    'analysis.review_failed_fallback': (
        'the review of cluster {group} failed; a sentence built from the table facts was used instead: {err}'
    ),
    'analysis.review_fallback_text': (
        '(generated from the table, not by a model) this cluster holds {size} nodes; strongest members: {members}'
    ),
    'analysis.review_no_groups': (
        'cluster review cannot find its grouping column {col}: enable clustering upstream first'
    ),
    'analysis.review_prompt': (
        'You are a scientometrics researcher. Below are the EXISTING metrics of one cluster of a '
        'knowledge map (every figure comes from the table, not from speculation). From them write '
        '3-5 sentences on the research front this cluster forms: what problem it addresses, which '
        'concepts hold it up, and the direction it is likely moving in over the given year span. '
        'Give the analysis only - do not restate the data, do not bullet, do not preamble. '
        'Answer in {language}.'
        '\n'
        '{facts}'
    ),
    'analysis.stage_blank': (
        '{n} rows have no "{col}" value (their timestamp did not parse), so they join no topic model'
    ),
    # Staged topic modelling. Every one of these names WHICH stage and WHICH topic, because
    # "one phase produced nothing" is undiagnosable once the table holds TopicⅠ-1 … TopicⅤ-4.
    'analysis.stage_order': (
        '"{col}" no longer says which phase came first (a column that crosses a node boundary '
        'is rebuilt from records and loses its order). Keep 按时间划分阶段 in the same pipeline, '
        'or name a 阶段排序列 that holds a time'
    ),
    'analysis.stage_order_col': '{op}: the stage-order column "{col}" is not in this table',
    'analysis.stage_order_unparsed': 'no phase order can be read for {stages}: "{col}" holds no parsable time there',
    'analysis.stage_order_unranked': 'no phase order can be read for {stages}: "{col}" holds no number there',
    'analysis.stages_basis_first': "opens on the curve's first day {day}",
    'analysis.stages_basis_valley': 'opens the day after the valley on {valley}',
    'analysis.stages_done': 'phase proposal: {n} candidate windows covering {rows} rows ({span})',
    'analysis.stages_edges': 'suggested edges, left-closed/right-open, the last one is the final day + 1: {edges}',
    'analysis.stages_folded': (
        'the curve holds more than {kept} peaks; the tallest {kept} were kept ({dropped} folded away)'
    ),
    'analysis.stages_folded_windows': (
        '{n} window(s) were shorter than the {days}-day minimum and joined their larger neighbour '
        '(a single tall day is not a phase)'
    ),
    'analysis.stages_labels': 'suggested labels, one per window (placeholders — rename them): {labels}',
    'analysis.stages_no_peak': (
        'the post-count curve has no turning peak {ratio}× above the usual day (median {floor} rows/day): '
        'one stretch of a curve must not be cut into several phases'
    ),
    'analysis.stages_ratio': 'the peak ratio has to be at least 1 (a peak is a day above the usual), got {value}',
    # A boundary PROPOSAL: this step rewrites no row and does not decide when an event
    # turned, because that needs the dates the researcher knows (the notice, the apology,
    # the filing) and not the post counts.
    'analysis.stages_sparse': (
        'only {days} days carry records in this column, which cannot be cut into phases ({least} needed)'
    ),
    'analysis.step_col_missing': '{op}: no column named "{col}" in this table',
    'analysis.step_cols_missing': '{op}: these columns are not in this table: {cols}',
    'analysis.time_bin_edges': 'time binning got a boundary that is not a date: {edges}',
    'analysis.time_bin_labels': (
        'time binning needs one more boundary than there are phase names: {edges} boundaries and {labels} names'
    ),
    'analysis.time_bin_order': '{op} boundaries must run from earliest to latest',
    'analysis.time_binned': '{col} split done: {detail}',
    'analysis.time_unparsed': (
        '"{col}" has {n} rows that are not a parseable time (the site only gave a relative label such as '
        '"09月26日 21:00"); they are left empty rather than guessed into a year'
    ),
    'analysis.timeline_blank': '{n} rows of "{col}" belong to no phase, so they join no lifecycle',
    'analysis.timeline_done': (
        'topic lifecycles: {topics} subjects over {stages} phases, {multi} spanning more than one phase '
        'and {secondary} flagged as a secondary flare-up (word-overlap threshold {value})'
    ),
    'analysis.timeline_overlap': 'the same-topic word overlap has to be between 0 and 1, got {value}',
    'analysis.timeline_partial': '{n} rows of "{col}" are not numbers and count as 0 when finding the peak',
    'analysis.timeline_secondary': 'secondary flare-up: {topic} runs {path}',
    'analysis.timeline_size': '"{col}" holds no number at all, so a peak cannot be measured (blank is not a peak of 0)',
    # ── Reads taken after the phases: lifecycles, flow, a topic-count sweep, co-occurrence ──
    'analysis.timeline_stages': (
        'a lifecycle needs at least 2 phases to say "before" and "after", this table has {stages}'
    ),
    'analysis.timeline_words': '{topic} of phase "{stage}" has no feature words in "{col}", so it cannot be followed',
    'analysis.topic_count': 'LDA needs at least 2 topics, got {value} (one topic is just "the whole text")',
    'analysis.topic_done': (
        'LDA topic model: {n} topics over {rows} texts, perplexity {perplexity} '
        '(lower fits better, but far too low means it is memorising the corpus)'
    ),
    'analysis.topic_embed_done': 'embedding topics: {model}, {n} topics over {rows} texts',
    'analysis.topic_embed_failed': 'embedding model "{model}" failed to load or run: {err}',
    'analysis.topic_embed_unavailable': (
        'the embedding topic method is missing optional packages: {packages} '
        '(it does not fall back to LDA; install them or choose LDA)'
    ),
    'analysis.topic_empty_cluster': (
        'embedding topic "{topic}" received no documents: that is the model\'s answer, not a canvas '
        'error — {n} was the requested count and the clustering produced {got}'
    ),
    'analysis.topic_features': 'LDA could find no features in this column (punctuation or stopwords only?): {err}',
    'analysis.topic_lambda': (
        'λ must sit between 0 and 1 (0 = over-representation only, 1 = within-topic probability only), got {value}'
    ),
    'analysis.topic_map_done': (
        'intertopic map: {n} topics over {rows} texts, perplexity {perplexity} '
        '(bubble size = topic share; coordinates = MDS of the Jensen-Shannon distance between word distributions)'
    ),
    'analysis.topic_method_auto_embedding': 'topic method auto: encoder detected, using embedding ({model})',
    'analysis.topic_method_auto_lda': (
        'topic method auto: sentence-transformers (or another optional package) is absent, '
        'falling back to LDA — these results are LDA, not embedding'
    ),
    'analysis.topic_rows': 'LDA needs at least as many texts as topics: {topics} topics, {rows} usable rows',
    'analysis.topic_salience_done': (
        'salient terms: {terms} rows for {n} topics over {rows} texts, λ={value} '
        '(1 ranks by probability within the topic, 0 by over-representation against the corpus)'
    ),
    'analysis.topic_stage_counts': (
        '{stages} stages need one topic count each, got {counts} (a single number means the same for every stage)'
    ),
    'analysis.topic_stage_done': 'phase "{stage}": {n} topics over {rows} texts, perplexity {perplexity}',
    'analysis.topic_stage_empty': (
        'phase "{stage}" holds no rows at all, so nothing can be modelled (check the boundaries in "{col}")'
    ),
    'analysis.topic_stage_features': 'phase "{stage}" yielded no feature words: {err}',
    'analysis.topic_stage_number': 'topics per stage must be a whole number, got "{value}"',
    'analysis.topic_stage_rows': (
        'phase "{stage}" has only {rows} usable texts, which cannot carry {topics} topics '
        '(LDA needs at least as many texts as topics)'
    ),
    'analysis.topic_stage_topic_words': '{topic} (phase "{stage}"): {words}',
    'analysis.topic_stage_unused': (
        'no text was assigned to {topic} in phase "{stage}" (doc_n=0), '
        'so its feature words come from the topic distribution'
    ),
    'analysis.topic_stage_words': (
        'nothing could be selected as a feature word for {topic} in phase "{stage}" — no text was assigned to it, '
        "so lower that stage's topic count"
    ),
    'analysis.type_convert_failed': 'Type conversion failed for column {col} -> {dtype}: {err}',
    'anomaly.done': 'Anomaly detection: {n}/{total} rows flagged (contamination={c:.2f})',
    'anomaly.ignored_columns': 'Anomaly detection: skipped the non-numeric columns ({columns})',
    'anomaly.no_numeric': 'No numeric columns available for anomaly detection',
    'anomaly.no_usable_columns': 'Anomaly detection: none of the columns you named holds numbers ({columns})',
    'anomaly.too_few': 'Too few rows ({n} < {min}) — anomaly detection cannot reach a conclusion',
    'clean.regex_done': (
        'Regex clean: kept {kept} rows, marked {dropped} for deletion '
        '(topic relevance is not judged here — that needs the llm mode)'
    ),
    'clean.unknown_mode': 'the clean node has no mode named "{mode}" (available: regex, llm)',
    'cluster.dbscan': 'DBSCAN found {n} clusters + {noise} noise points',
    'cluster.done': 'Clustering completed: {rows} rows into {clusters} clusters (silhouette={score:.3f})',
    'cluster.no_features': 'Text could not be segmented (symbols only?) — clustering skipped: {err}',
    'cluster.not_enough': 'Not enough valid rows for clustering (need >= 2)',
    'corr.done': 'Correlation analysis ({method}): {n} pairs found (min_abs={min_abs:.2f})',
    'corr.ignored_columns': 'Correlation: skipped the non-numeric columns ({columns})',
    'corr.need_cols': 'Need at least 2 numeric columns for correlation analysis',
    'corr.no_usable_columns': 'Correlation: none of the columns you named holds numbers ({columns})',
    'emotion.bert_bad_label': 'the BERT model answered an unrecognised emotion label "{label}"',
    'emotion.bert_done': '[BERT] emotion classification done, {n} rows, {failed} failed',
    'emotion.bert_failed': 'BERT emotion failed: {err}',
    'emotion.bert_loaded': 'BERT emotion model loaded: {model} ({runtime}/{precision}, on {device}, in batches)',
    'emotion.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'emotion.bert_no_model': 'BERT mode needs an emotion model named; empty means nothing can be judged',
    'lex.needTerms': 'Provide at least one term.',
    'lex.unknownKind': 'Unknown lexicon kind: {kind}',
    'lex.userdictLoadFailed': 'Failed to load the jieba user dictionary.',
    'lex.userdictReadFailed': 'Could not read the user lexicon; leaving the tokenizer untouched.',
    'ml.bad_model_name': 'Model name "{name}" is invalid: must be one path-safe component, no separators',
    'ml.emotion_done': '[ML] Emotion classification done, {n} rows, mode: ML',
    'ml.emotion_failed': 'ML emotion prediction failed: {err} — falling back to Neutral',
    'ml.missing_col': 'DataFrame is missing the required column "{col}". Skipping analysis.',
    'ml.model_untrained_refused': (
        '"{name}" has no trained model and nothing saved to load — refusing to answer '
        'rather than inventing a neutral verdict for every row'
    ),
    'ml.need_two_labels': 'Training needs at least 2 distinct labels; this data only has: {label}',
    'ml.no_rows': 'Nothing to process (the target column is empty).',
    'ml.no_training_rows': 'No training data: every row has an empty text or label',
    'ml.tendency_done': '[ML] Tendency analysis done, {n} rows, mode: ML',
    'ml.tendency_failed': 'ML tendency prediction failed: {err} — falling back to Objective Statement',
    'ner.dropped': 'NER: dropped {n} model answer(s) that do not appear in the source text (nothing is guessed)',
    'net.blocked': (
        '. Diagnosis: this machine routes normally but the platform host itself does not answer, '
        'which is a site outage or a local interception rather than a slow page'
    ),
    'net.offline': (
        '. Diagnosis: this machine has no outbound connection at all right now (both control hosts fail), '
        'so restore the network before running again'
    ),
    'net.region': (
        '. Diagnosis: this machine cannot reach the side of the internet that platform lives on (the control host '
        'for it fails while the other answers) — switch network and run it again'
    ),
    'net.slow': (
        '. Diagnosis: both sides connect, so there is no evidence for why this page did not arrive; '
        'run it again, or press Stop to end the run'
    ),
    'net.speed': ' (measured about {speed} kB/s)',
    'sentiment.bad_thresholds': 'the positive threshold {pos} cannot sit below the negative threshold {neg}',
    'sentiment.bert_bad_label': 'the BERT model answered an unrecognised label "{label}"',
    'sentiment.bert_failed': 'BERT failed: {err}',
    'sentiment.bert_loaded': 'BERT sentiment model loaded: {model} ({runtime}/{precision}, on {device}, in batches)',
    'sentiment.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'sentiment.bert_need_runtime': 'torch+transformers or onnxruntime+tokenizers',
    'sentiment.bert_no_labels': 'that BERT model folder has no id2label table, so an output is not a class: {path}',
    'sentiment.bert_no_model': 'BERT mode needs a sentiment model named; empty means nothing can be judged',
    'sentiment.bert_no_model_dir': 'no BERT model folder was found: {path}. {remedy}',
    'sentiment.bert_no_onnx': 'no loadable ONNX graph in that BERT model folder: {path}',
    'sentiment.bert_onnx_inputs': 'this ONNX graph does not expose the four inputs this path expects; found: {found}',
    'sentiment.bert_session_dropped': 'released an earlier BERT model to bound memory: {model} (it reloads if needed)',
    'sentiment.ml_failed': 'ML sentiment polarity prediction failed: {err} — falling back to neutral',
    'sentiment.packRemedyFrozen': (
        'the desktop build gets its BERT models from a separate archive: unpack '
        'CaiXiHui-bert-models-win64.zip into a bert_models\\ folder beside the exe and restart'
    ),
    'sentiment.packRemedySource': (
        'a source checkout exports them first: ml_train/scripts/export_onnx_bert.py writes the ONNX '
        "folder from the trained weights, or name an existing folder in the node's model field"
    ),
    'sentiment.scored': 'Sentiment polarity ({mode}): judged {n} rows',
    'sentiment.scored_failed': 'Sentiment polarity: {n} rows could not be read and are left blank (not neutral)',
    'sentiment.snownlp_failed': 'SnowNLP failed: {err}',
    'sentiment.unknown_mode': 'unknown sentiment polarity mode "{mode}"',
    'sig.degenerate': 'Significance test: {method} cannot be computed (few samples or zero variance) — no fake p',
    'sig.done': 'Significance test ({method}): {n_groups} groups, {n} rows, statistic={statistic}, p={p}',
    'sig.group_column_missing': 'Significance test: group column "{col}" is not in the table',
    'sig.no_group_column': 'Significance test: no group column given',
    'sig.no_usable_rows': 'Significance test: no usable rows left after dropping blanks/non-numeric (group "{col}")',
    'sig.no_value_column': 'Significance test: no value column given',
    'sig.two_groups_only': 'Significance test: {method} needs exactly 2 groups, found {n} — try ANOVA/Kruskal-Wallis',
    'sig.two_groups_required': 'Significance test: {method} needs at least two groups, found {n}',
    'sig.unknown_method': 'Significance test: unknown method "{method}"',
    'sig.value_column_missing': 'Significance test: value column "{col}" is not in the table',
    'sig.value_not_numeric': 'Significance test: value column "{col}" cannot be read as numbers',
    'tendency.bert_bad_label': 'the BERT model answered an unrecognised tendency label "{label}"',
    'tendency.bert_done': '[BERT] tendency classification done, {n} rows, {failed} failed',
    'tendency.bert_failed': 'BERT tendency failed: {err}',
    'tendency.bert_loaded': 'BERT tendency model loaded: {model} ({runtime}/{precision}, on {device}, in batches)',
    'tendency.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'tendency.bert_no_model': 'BERT mode needs a tendency model named; empty means nothing can be judged',
}
