"""Server-side message catalogue (zh / en) for everything the console shows.

Console output reaches the browser through three pipes — ``add_log()``,
``logging`` (via LogBufferHandler) and ``print()`` (via LogTee) — and it used
to be hardcoded, half in Chinese and half in English depending on which file
emitted it. Every user-visible line now goes through :func:`t`, which renders
it in the language of whoever triggered the run:

- HTTP requests carry ``X-Lang`` (the frontend patches ``fetch`` once, so
  every call gets it for free).
- A workflow runs in its own thread(s), and thread-locals are not inherited,
  so the language captured when the run starts is re-applied in each worker
  thread explicitly.

Unknown keys render as the key itself: a missing translation shows up loudly
in the console instead of silently falling back to a foreign language.
"""

import logging
import re
import threading

logger = logging.getLogger(__name__)

# printf-style placeholders ('%s', '%(name)d') that str.format cannot fill.
_BAD_PLACEHOLDER = re.compile(r'%(?:\(\w+\))?[#0-9+.-]*[sdfgrx]')

DEFAULT_LANG = 'zh'
LANGS = ('zh', 'en')

_local = threading.local()


# ─── Catalogue ──────────────────────────────────────────────────
# Keys are grouped by the emitter: wf.* (workflow engine / app.py),
# llm.* (analyzers/llm_client.py), crawl.<platform>.* (crawlers), and
# misc.* / analysis.* for the rest. The two tables must stay in sync —
# ``missing_keys()`` checks that in the tests.

_ZH = {
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] 正在执行节点：{nid}（{ntype}）',
    'wf.node_failed': '[{wf}] 节点 {nid} 执行失败：{err}',
    'wf.unnamed': '未命名工作流{i}',
    'wf.node_completed': '[{wf}] 节点 {nid} 完成（{done}/{total}）',
    'wf.multi_input': (
        '节点 {nid} 有 {n} 条上游连线：主输入取第一条（来自 {up}）；分析节点的连接用第二条当右表，'
        '输出节点则把全部上游合并成一张表'
    ),
    'wf.merge_not_tabular': (
        '节点 {nid} 的上游「{up}」不产出表格（是图表配置或错误应答），无法合并——请断开这条连线，'
        '或改接一个产出表格的节点'
    ),
    'wf.compile_no_source': '编译节点没有可编译的 LaTeX 来源（上游可视化节点既未产出图也未产出表）',
    'wf.merge_columns': (
        '节点 {nid} 合并上游表时列名不一致，对比「{up}」：多出 [{extra}]、缺少 [{missing}]。'
        '不做外连接合并——那会凭空补出空值，让文件看起来完整'
    ),
    'wf.merge_done': '节点 {nid} 合并 {tables} 张上游表 → {n} 行（{detail}）',
    'wf.merge_detail_sep': '、',
    'wf.merge_table_detail': '{name} {n} 行',
    'wf.validation_error': '校验错误：{err}',
    'wf.found': '发现 {n} 条工作流',
    'wf.starting': '开始执行工作流「{name}」',
    'wf.component_indexed': '{name}（第 {i}/{n} 条）',
    # No 'wf.completed' / 'wf.all_completed': `run.finished` says how the run
    # ended and carries the node counts, so a second sentence could only disagree.
    # One line per failure, and it says where the detail is: the log handler
    # forwards every logger call to the console, so the pair of messages this
    # replaced printed the same sentence twice.
    'wf.exec_exception': '执行失败，完整堆栈见服务端日志',
    'wf.wf_exception': '工作流「{wf}」执行失败，完整堆栈见服务端日志',
    # These refusals are printed by the executor as the node's own failure
    # (「节点 X 执行失败：…」), so they state the reason only — a second
    # 「分词失败：」/「可视化失败：」 inside them repeats the wrapper, and the node
    # used to be logged twice: once here without a name, once attributed.
    'wf.analysis_step': '[分析] {op}：{before} → {after} 行',
    # The labelling step needs a model: without one the step refuses instead of leaving the
    # column blank and settling the node DONE on work that did not happen.
    'wf.analysis_llm_no_model': '「主题概括」需要模型，但这条运行没有配置模型（设置 → 模型 / 节点模型）',
    'wf.analysis_steps_shape': '「steps」必须是步骤列表（每个一步一个对象），收到的是一个对象',
    'wf.analysis_step_removed': '（-{removed}）',
    'wf.analysis_step_nochange': '（无变化）',
    'wf.tokenize_no_column': '未配置要分词的文本列',
    'wf.tokenize_no_input': '没有上游数据，请连接数据源或文件上传节点',
    'wf.tokenize_no_col': '列“{col}”不在 {cols} 中',
    'wf.tokenize_done': '[分词] {mode} 已切分 {col} → {n} 行',
    'wf.visualize_no_input': '没有上游数据，请连接数据源或文件上传节点',
    'wf.visualize_done': '[可视化] 已渲染 {chart} 图表（{engine}），共 {n} 行',
    'wf.browser_opened': '已打开浏览器用于 {platform} 登录（{url}），等待 {n} 秒完成登录…',
    'wf.cookies_generated': '已生成 {platform} 的 Cookie（{n} 项）',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API Key 未填写',
    'llm.no_model': 'OpenRouter 模型名未填写',
    'llm.ollama_pkg_missing': 'ollama 包不可用：{err}',
    'llm.ollama_empty': 'Ollama 返回了空内容',
    'llm.ollama_fail_attempt': 'Ollama 调用失败（尝试 {i}/{n}）：{err}',
    'llm.ollama_exception': 'Ollama 调用异常（尝试 {i}/{n}）：{err}',
    'llm.ollama_failed': 'Ollama（{model}）调用失败：{err}',
    'llm.no_ollama_model': 'Ollama 模型名未填写（AI → 模型，可点“刷新”读取本地已拉取的模型）',
    'llm.ollama_unreachable': '连不上 Ollama 服务 {host}——请确认 ollama 已启动、服务地址正确：{err}',
    'llm.ollama_client_failed': 'Ollama 客户端初始化失败（{host}）：{err}',
    'llm.ollama_model_missing': 'Ollama 本地没有模型“{model}”——请在面板中改选一个已拉取的模型（{err}）',
    'llm.ollama_http': 'Ollama 拒绝请求（{code}）：{err}',
    'llm.net_error': '网络错误：{err}',
    'llm.or_net_exception': 'OpenRouter 网络异常（尝试 {i}/{n}）：{err}',
    'llm.or_bad_format': 'OpenRouter 响应格式异常：{err}',
    'llm.or_empty': 'OpenRouter 返回了空内容',
    'llm.or_401': 'OpenRouter：API Key 无效（401），请检查密钥',
    'llm.or_402': 'OpenRouter：余额不足（402）——免费模型不需要余额，请改选 :free 模型',
    'llm.or_404': 'OpenRouter：模型不存在（404）——"{model}"，请重新选择模型',
    'llm.or_429': 'OpenRouter：触发限流（429）——免费模型为共享额度，建议减小并发',
    'llm.or_429_wait': 'OpenRouter 429 限流（尝试 {i}/{n}），等待 {wait} 秒',
    'llm.or_5xx': 'OpenRouter 服务端错误（{code}）',
    'llm.or_5xx_attempt': 'OpenRouter {code}（尝试 {i}/{n}）',
    'llm.or_http_fail': 'OpenRouter 请求失败（{code}）：{body}',
    'llm.or_failed': 'OpenRouter 调用失败',
    'llm.checkpoint_loaded': '断点续跑：载入 {n} 行已完成结果（{file}）',
    'llm.cancelled': '已手动停止——已完成的行均已保存，可修复后从断点续跑',
    'llm.parse_failed': '[{label}] 第 {i}/{total} 行输出解析失败（连续失败 {f}）',
    'llm.row_exception': '[{label}] 行处理异常：{err}',
    'llm.row_done': '[{label}] 第 {done}/{total} 行完成',
    'llm.progress': '[{label}] 进度 {done}/{total}（已保存）',
    'llm.circuit_break': '连续 {f} 行调用失败——疑似网络断开 / Key 失效 / 模型不可用，本节点已中止。'
    '已完成 {done}/{total} 行并全部保存，恢复后重新执行会自动从断点续跑。',
    'llm.node_done': '[{label}] 节点完成 {done}/{total} 行',
    'llm.missing_column': 'DataFrame 缺少必需的列“{col}”——{label} 节点失败，请检查文本列配置',
    'llm.no_rows': '[{label}] 没有需要处理的行（“{col}”列为空）。',
    'llm.start': '[{label}] 共 {total} 行待处理，调用方式：{transport}（每条数据一次询问，文本越长越耗 token）',
    # Neither line carries the failure text: the executor states it once, attributed
    # to the node. These two say only what that line cannot — what survived.
    'llm.aborted': '[{label}] 已完成 {done} 行，结果已保存',
    'llm.stopped': '[{label}] 已停止，已完成行的结果已保存',
    'llm.unfinished': '[{label}] {n} 行未处理（标记为 {mark}）。重新执行同一节点将从断点续跑，只补这些行。',
    # ── upload node ───────────────────────────────────────────
    'upload.no_file': '文件上传节点未选择文件，请在节点设置里上传 CSV / JSON / TXT',
    'upload.stale': '已上传的数据集失效（服务可能重启过），请重新上传文件',
    'upload.loaded': '已载入上传文件 {name}：{n} 行',
    # ── bibliometrics / knowledge graph ───────────────────────
    'biblio.entity.keyword': '关键词',
    'biblio.entity.author': '作者',
    'biblio.entity.institution': '机构',
    'biblio.entity.country': '国家/地区',
    'biblio.entity.term': '主题词',
    'biblio.entity.category': '学科',
    'biblio.entity.journal': '来源期刊（耦合）',
    'biblio.entity.source': '来源期刊（Source）',
    'biblio.entity.funder': '基金/资助机构',
    'biblio.entity.grant': '基金（Grant）',
    'biblio.entity.document_cocitation': '文献共被引',
    'biblio.entity.author_cocitation': '作者共被引',
    'biblio.entity.journal_cocitation': '期刊共被引',
    'biblio.entity.article': '被引文献（Article）',
    'biblio.entity.document': '文献（耦合）',
    'biblio.entity.bibliographic_coupling': '文献耦合',
    'biblio.bad_option': '{nid}：{param} 的值「{value}」无效（可选：{allowed}）',
    'biblio.time_range': '{nid}：时间范围无效：{start} > {end}',
    'biblio.coupling_no_burst': '{nid}：文献耦合的节点是施引文献本身，突现检测在此没有意义；请关闭突现',
    'biblio.column_missing': '文献计量需要「{col}」列（{entity}），当前表没有该列',
    'biblio.refs_missing': (
        '{type} 需要参考文献：每条记录至少 2 条【参考文献】；CNKI RefWorks 通常不含参考文献，请改用 CSSCI 导出'
    ),
    'biblio.refs_low_rate': '参考文献解析率 {rate} 低于 {floor}：无法可靠构建引文图谱',
    'biblio.refs_field_low': '{field} 解析率 {rate} 低于 {floor}：无法可靠构建引文图谱',
    'biblio.citation_expansion_done': '引文扩展 depth={depth}：通过数据集内已有文献新增 {added} 条可解析引文',
    'biblio.no_records': '没有可用文献记录：请确认年份列可解析',
    'biblio.no_records_in_range': '{start}–{end} 范围内没有文献记录',
    'biblio.year_missing': '{n} 条记录缺少年份，已跳过（时间切片需要年份）',
    'biblio.records_skipped': '{n} 条记录没有可分析的实体，已跳过',
    'biblio.wide_ref_skipped': '{n} 条参考文献被超过 {cap} 篇文献同时引用，已跳过其两两配对（过大团会淹没图）',
    'biblio.mst_done': 'MST 剪枝（{scope}）：{before} → {after} 条边',
    'biblio.pruning_scope.slices': '逐切片',
    'biblio.pruning_scope.merged': '合并网络',
    'biblio.pfnet_depth_all': '不限',
    'biblio.pfnet_done': (
        'Pathfinder 剪枝（{scope}，r={r}，最长间接路径 {lmax} 跳，保留比例 {dmax}）：'
        '{before} → {after} 条边（共 {units} 张网络）'
    ),
    'biblio.pfnet_refused': (
        'Pathfinder 要把每条连边与两端之间最好的间接路径逐对比较：{nodes} 个节点 × {levels} 层约需 {work} 次运算，'
        '超过上限 {limit}。请降低 TopN 或 pathfinder_lmax，或改用 MST 剪枝'
        '（r=∞ 且不限跳数时二者本是同一张图，那种情况本实现会自动走生成森林快路，不会拒）'
    ),
    'biblio.betweenness_sampled': '节点数 {n} 超过 2000，中介中心性使用 {k} 个源点采样',
    'biblio.eigen_failed': '特征向量中心性未收敛，已改用归一化加权度（0–1）作为回退并播报',
    'biblio.burst_done': '突现检测：{nodes}/{total} 个节点有突现',
    'biblio.burst_truncated': (
        '节点表只标记最强 {kept}/{total} 段突现（图上展示上限来自 burst_top；完整突现表仍在 CSV 产物中）'
    ),
    'biblio.cluster_too_many': '节点数 {n} 超过谱聚类上限 {cap}：请收紧 TopN/时间范围，或关闭聚类',
    'biblio.label_fallback': '聚类标签方法 {asked} 没有可用文本，实际使用 {used}（已在运行摘要中如实标明）',
    'biblio.no_edges': '{start}–{end} 年没有共现边：请降低阈值、扩大时间范围或换一种实体类型',
    'biblio.no_edges_after_prune': '{pruning} 剪枝后没有边：请减少最大连边数或改用 none',
    'biblio.no_edges_after_threshold': '阈值 (c, cc, ccv) 过滤后没有边：请降低 cc/ccv 或扩大时间范围',
    'biblio.no_edges_after_component': '保留最大连通分量后没有边：请关闭该选项或降低筛选阈值',
    'biblio.largest_component': '已保留最大连通分量：节点 {before} → {after}，其余分量已剪除',
    'biblio.shape_needs_cluster': '{nid}：输出形态 clusters 需要开启聚类，请先开启或改回 nodes/edges',
    'biblio.shape_needs_burst': '{nid}：输出形态 bursts 需要开启突现检测，请先开启或改回 nodes/edges',
    'biblio.shape_needs_variation': '{nid}：输出形态 variation 需要开启结构变异检测，请先开启或改回其它形态',
    'biblio.counting_no_coupling': (
        '{nid}：耦合网络（{entity}）里两篇施引文献就是连边的两端，没有第三方文档的信用可拆分，'
        '分数计数（fractional）不适用；请改回 full 或换用共被引/共现类型'
    ),
    'biblio.counting_fractional': '分数计数：每篇文档把 1 份信用均分给它承载的实体，{docs} 篇文档参与折算',
    'biblio.variation_needs_slices': (
        '结构变异要比较相邻两个切片，本次只有 {n} 个切片可比（请缩小 slice_years 或放宽年份范围）'
    ),
    'biblio.variation_no_coupling': (
        '结构变异只适用于按年切片的关系网络：耦合网络（{entity}）的连边属于两篇施引文献、不属于某一年，'
        '没有切片间的变化可测'
    ),
    'biblio.variation_done': '结构变异：{rows} 行（最高 {node} {pair} = {score} bit，阈值 {floor}）',
    'biblio.variation_empty': '结构变异：没有节点在相邻切片间的连接模式变化达到阈值 {floor} bit',
    'biblio.overlay_no_labels': (
        '「{col}」列没有任何标签（{n} 条记录全为空）：无法叠加，请先检查上游情感/情绪/话题步骤是否真的写出了这一列'
    ),
    'biblio.overlay_partial': '「{col}」：{n}/{total} 条记录没有标签，未计入叠加（分母只含已标注文档）',
    'biblio.overlay_no_nodes': '「{col}」有标签，但没有任何留下来的节点带标签，叠加列为空',
    'biblio.dual_map_needs_basemap': '{nid}：输出形态 dual_map 需要选择期刊—学科 basemap 数据集',
    'biblio.dual_map_columns': '双图叠加 basemap 需要期刊列（{journal}）和学科列（{category}）',
    'biblio.dual_map_done': '双图叠加已生成：期刊 {journals} 个 / 学科 {categories} 个',
    'biblio.isolates_dropped': '{n} 个孤立节点在成图后没有连边，已从节点表移除',
    'biblio.aliases_applied': '别名合并：{n} 个节点标签已按用户映射归一',
    'biblio.exclusions_applied': '排除列表：{n} 个节点标签已按用户设置移除',
    'biblio.cluster_labels_applied': '人工簇标签已应用：{n} 条',
    'biblio.cluster_label_unmatched': '簇 {cluster}：本次运行没有这个簇，该行标签未生效',
    'biblio.cluster_labels_need_cluster': '{nid}：填写了人工簇标签但未开启聚类，请开启聚类或清空该框',
    'biblio.watch_needs_project': '{nid}：填了监测基准或捕获名却没填监测项目，请先写项目名或清空这两个框',
    'biblio.watch_needs_entity_table': '{nid}：监测需要一行一实体的输出形态，{shape} 的行不是实体表',
    'biblio.watch_empty': '{nid}：本次图谱没有任何节点或连边，无法建档监测（空表会让下次对比把全部实体报成消失）',
    'biblio.watch_baseline_missing': '{nid}：监测项目里找不到基准「{label}」（现有：{known}）',
    'biblio.watch_project_note': '由文献计量节点的跨 run 监测自动建档',
    'biblio.watch_project_created': '[监测] 项目「{name}」不存在，已新建（本次为该项目的第一个快照）',
    'biblio.watch_first_done': '[监测] 项目「{project}」已建档「{label}」：{nodes} 个节点 / {edges} 条连边；'
    '无更早的快照可比',
    'biblio.watch_done': '[监测] 项目「{project}」：「{baseline}」→「{label}」，{detail}'
    '（每类最多列 {limit} 条，总数见括号）',
    'biblio.watch_unchanged': '[监测] 图谱与基准完全一致（{nodes} 个节点 / {edges} 条连边）：上游没有新数据时会这样',
    'biblio.watch_params_differ': '[监测] 有 {n} 项参数与基准不同（{names}）——先排除是节点被改过，再读成领域变了',
    'biblio.watch_shape_differs': '[监测] 基准是 {a} 形态、本次是 {b} 形态，两者的行数差不是领域的变化',
    'biblio.watch.nothing': '无变化',
    'biblio.watch.node_added': '节点新增',
    'biblio.watch.node_removed': '节点消失',
    'biblio.watch.node_changed': '节点属性变化',
    'biblio.watch.edge_added': '连边新增',
    'biblio.watch.edge_removed': '连边消失',
    'biblio.watch.edge_weight': '连边强度变化',
    'biblio.watch.cluster_added': '新簇',
    'biblio.watch.cluster_removed': '簇消失',
    'biblio.watch.cluster_relabeled': '簇改名',
    'biblio.watch.cluster_size': '簇规模变化',
    'biblio.watch.burst_added': '新突现',
    'biblio.watch.burst_removed': '突现结束',
    'biblio.watch.burst_strength': '突现强度变化',
    'biblio.watch.param': '参数变化',
    'biblio.watch.first': '首次建档（节点数/连边数）',
    'fuse.no_input': '{nid}：跨源融合需要至少一个输入表',
    'fuse.empty_parent': '{nid}：上游 {pid} 没有行，无法参与融合',
    'fuse.no_entity_column': '{nid}：上游 {pid} 没有可作实体的列（试过：{wanted}）',
    'fuse.no_rows': '{nid}：上游 {pid} 的「{column}」列没有提出任何实体',
    'fuse.needs_entity': '{nid}：跨源融合需要至少一个实体候选列（如 关键词,话题）',
    'fuse.source_named': '[跨源融合] 来源「{source}」：{pid} 贡献 {rows} 条',
    'fuse.build_done': '[跨源融合] {parents} 张表 → {rows} 条记录，来源：{sources}',
    'biblio.too_many_nodes': '节点数 {n} 超过上限 {cap}：请收紧 TopN 或缩短时间范围',
    'biblio.too_many_edges': '边数 {n} 超过上限 {cap}：请收紧 TopN/最大连边数',
    'biblio.links_too_large': '节点「{node}」的连接 JSON 超过 {cap} 字节：请降低最大连边数',
    'biblio.import_duplicates': '{n} 条重复文献已合并',
    'biblio.import_no_year': '{n} 条文献缺少年份',
    'biblio.import_skipped': '{n} 条空记录已跳过',
    'biblio.import_ok': '已识别 {format} 文献导出：{n} 条记录',
    'biblio.build_done': '文献计量完成：{entity}，{nodes} 个节点 / {edges} 条边（{start}–{end}）',
    'biblio.export_failed': '文献计量导出失败：{err}',
    # ── 「缺什么、在这台机器上怎么补」的按系统分支 ──────────────────────────
    # 一条补救说明在三套系统上说的是三件事：Windows 补字体功能、Linux 装发行包、macOS 用系统自带。
    # 键名由 utils.machine_deps.remedy_key 拼出，所以全清单（前缀 × 平台）由
    # tests/unit/test_missing_dependency_messages.py 从取值那头逐个查在不在。
    'deps.systemFont.win32': '请安装仿宋/黑体等中文字体（英文版 Windows 要在「可选功能」里补中文简体字体）后重启程序',
    'deps.systemFont.linux': '请安装中文字体（Debian/Ubuntu：apt-get install fonts-noto-cjk）后重启程序',
    'deps.systemFont.darwin': 'macOS 自带苹方/宋体；若仍缺请装 Noto Sans CJK 后重启程序',
    'deps.texFont.win32': (
        '纸质图用 ctex + 仿宋（FangSong），需要系统装有该字体（英文版 Windows 要补「中文（简体）」字体功能）'
    ),
    'deps.texFont.linux': '非 Windows 上纸质图改用 ctex 自带的 fandol 中文字体集，需要 texlive-lang-chinese',
    'deps.texFont.darwin': '非 Windows 上纸质图改用 ctex 的 macnew 字体集（系统自带宋体/黑体）',
    'deps.texPackage.win32': (
        '用 MiKTeX 控制台（或 miktex packages install）补上，或在 MiKTeX 设置里允许「联网自动安装缺失包」后重试'
    ),
    'deps.texPackage.linux': (
        '用发行版包装对应宏包（Debian/Ubuntu：apt-get install texlive-lang-chinese texlive-latex-extra），'
        '或 tlmgr install 该包'
    ),
    'deps.texPackage.darwin': 'MacTeX 下用 sudo tlmgr install 该包，或在 TeX Live Utility 里安装',
    'deps.xelatex.win32': '找不到 xelatex，无法编译 PDF：请安装 MiKTeX，或在「设置」里指定编译程序路径',
    'deps.xelatex.linux': (
        '找不到 xelatex，无法编译 PDF：请安装 TeX Live 的 xelatex'
        '（Debian/Ubuntu：apt-get install texlive-xetex），或在「设置」里指定路径'
    ),
    'deps.xelatex.darwin': '找不到 xelatex，无法编译 PDF：请安装 MacTeX（含 xelatex），或在「设置」里指定路径',
    'chart.noCjkFont': (
        '本机字体里没有能显示汉字的字体（已找过：{checked}）：'
        'Matplotlib 出的 PNG 里中文会是方框——{remedy}'
        '（ECharts 的图用浏览器字体，LaTeX 的图用 ctex，均不受此影响）'
    ),
    'chart.biblio_missing': '文献计量图缺少列：{cols}（请让上游文献计量节点输出完整表）',
    'chart.biblio_no_nodes': '文献计量图没有可画的节点',
    'chart.biblio_geo_none': '地理图画不出来：{names} 等名称都不在世界底图里（请检查「节点」列是否为国家/地区名）',
    'chart.biblio_geo_unknown': '底图无此区域 {n} 个：{names}',
    'chart.biblio_geo_merged': '并入其他区域 {n} 处：{detail}',
    'chart.biblio_geo': '国家/地区',
    'chart.biblio_geo_note': '纸质图按发文量排序画出前若干国家/地区（世界地图的几何不进 LaTeX），全部数值见三线表',
    'chart.biblio_no_links': '知识图谱没有连接：请检查“连接”列或降低筛选阈值',
    'chart.biblio_no_years': '文献计量图没有可用的年份：请检查首年/末年或年份序列',
    'chart.biblio_no_clusters': '文献计量图没有聚类结果：请在上游节点开启聚类',
    'chart.biblio_no_bursts': '没有突现词可画：请在上游节点开启突现检测并调整 gamma/最短时长',
    'chart.biblio_bad_json': '「{col}」不是合法 JSON：请让上游文献计量节点重新生成结果',
    'chart.biblio_single_category': '节点',
    'chart.biblio_unknown': '不支持的文献计量图类型：{type}',
    'chart.biblio_year': '年份',
    'chart.biblio_cluster': '聚类',
    'chart.biblio_span': '时间跨度',
    'chart.biblio_duration': '持续年数',
    'chart.biblio_burst': '突现区间',
    'chart.biblio_variation': '结构变异',
    'chart.biblio_pair': '相邻切片',
    'chart.biblio_no_variation': '没有结构变异可画：请在上游节点开启 variation 并调整变异量阈值 variation_min',
    'chart.biblio_no_sentiment': (
        '这张表没有「情感分布」列：请在上游接入情感/情绪/倾向步骤，并在文献计量节点填写「情感/情绪列」'
    ),
    'chart.biblio_no_topics': (
        '这张表没有「话题分布」列：请在上游接入文本聚类/话题步骤，并在文献计量节点填写「话题列」'
    ),
    'chart.biblio_overlay_unlabelled': '另有 {n} 个节点没有任何标签，图上从略',
    'chart.biblio_overlay_truncated': '只画前 {shown}/{total} 个节点，完整分布见表格与 CSV',
    'chart.biblio_topics_truncated': '只画前 {shown}/{total} 个话题',
    'chart.biblio_share': '占比（%）',
    'chart.biblio_topic_share': '话题占比',
    'chart.biblio_ring_rule': '同心环 {rings} 个：内→外为首次出现年份',
    'chart.biblio_ring_unknown': '未知年份',
    'chart.biblio_ring_nodes': '节点数',
    'chart.biblio_ring_reps': '代表节点',
    'chart.biblio_ring_total': '频次合计',
    # The paper's three-line table prints the variation columns by name, so the server needs the
    # words too — same keys the browser catalogue uses for the panel's table headers.
    'biblio.col.节点': '节点',
    'biblio.col.起始年': '起始年',
    'biblio.col.结束年': '结束年',
    'biblio.col.结构变化': '结构变化',
    'biblio.col.前邻居': '前邻居',
    'biblio.col.后邻居': '后邻居',
    'biblio.col.新增邻居': '新增邻居',
    'biblio.col.消失邻居': '消失邻居',
    'biblio.col.情感倾向': '情感倾向',
    'biblio.col.情感分布': '情感分布',
    'biblio.col.主导话题': '主导话题',
    'biblio.col.话题分布': '话题分布',
    'chart.biblio_activity': '年度活动',
    'chart.biblio_nodes': '节点',
    'chart.biblio_links': '连线',
    'chart.biblio_journal_map': '期刊网络',
    'chart.biblio_category_map': '学科网络',
    'chart.biblio_overlay': '期刊—学科叠加',
    'biblio.workspace_no_node': '运行 {rid} 中没有节点 {nid}：请重新选择运行',
    'biblio.workspace_not_biblio': '{nid}：该节点不是文献计量节点，工作区只读文献计量产出表',
    'biblio.workspace_empty_table': '{nid}：该节点没有已存行（可能被停止、失败或已被清理策略删除）',
    'biblio.project_needs_name': '项目需要一个名字（重命名同样如此）',
    'biblio.project_not_found': '找不到项目 {pid}：它可能已被删除',
    'biblio.snapshot_not_found': '找不到快照 {sid}：它可能已被删除',
    'biblio.compare_needs_two': '对比需要两个不同的快照（基准与当前）',
    'biblio.snapshot_done': '[文献计量] 已存快照「{label}」：{nodes} 个节点 / {edges} 条连边（参数已核对：{verified}）',
    'chart.biblio_map_layer': '图层',
    'chart.biblio_map_source': '起点',
    'chart.biblio_map_target': '终点',
    'chart.biblio_map_weight': '权重',
    'api.biblioEmpty': '无法从 {format} 文件中解析出任何文献记录',
    'api.biblioDecode': '无法解码文件 {name}（已尝试 UTF-8 与 GB18030）',
    'api.biblioNotRecognized': '无法把 {name} 识别为任何已支持的文献导出格式',
    'api.biblioLensPatent': '这是 Lens 的专利库导出（列里有 Jurisdiction、Inventors、Application Number），'
    '不是学术文献。文献计量网络按学术文献建模，把发明人与申请人当作者画出来只会得到一张错图；'
    '请在 Lens 里改选文献（非专利）集合后重新导出',
    # ── 文献来源导出指引（services/biblio_sources.py） ──────────────
    # 每条只写「我们解析过的真实文件」能支持的话：缺什么就写缺什么，不猜站点还有别的按钮。
    'source.CNKI.purpose': '中文文献共现网络的入口：关键词、作者、机构、期刊都能建图。'
    '知网导出不含参考文献与被引次数，因此引文类分析会在运行前点名拒绝，而不是画空图。',
    'source.CNKI.steps': '1. 在知网按主题/关键词检索，需要时用年限与来源收窄\n'
    '2. 勾选结果条目，点「导出/参考文献」\n'
    '3. 在导出页选「RefWorks」，得到 CNKI-<时间>-RefWorks.txt\n'
    '4. 把这份 .txt 直接上传；同一页的 NoteExpress、EndNote 两个按钮本应用也认',
    'source.CNKI.missing': '无参考文献列表 ⇒ 共被引、文献耦合、引文突现做不了\n'
    '无被引次数 ⇒ 「总被引/H 指数」列不会出现，按被引筛选保持关闭',
    'source.CSSCI.purpose': '中文社科文献的引文入口：CSSCI 导出带参考文献列表，所以共被引与文献耦合可用；'
    '它不带摘要与 DOI。',
    'source.CSSCI.steps': '1. 进入南京大学中国社会科学研究评价中心的检索页\n'
    '2. 按年/来源/关键词检索后导出文本，导出内容要含【参考文献】与【年代卷期】'
    '（每篇以【来源篇名】开头）\n'
    '3. 标签里带对齐空格（【关 键 词】、【期    刊】、【基    金】），'
    '年份卷期合并在【年代卷期】的 2021,(2):146-155 里，机构写成【机构名称】=[作者]单位.院系——'
    '本应用就按这套真实写法解析\n'
    '4. 上传该 .txt',
    'source.CSSCI.missing': '无【摘要】⇒ 聚类标签来源要选「关键词」；选「摘要」会按名拒绝\n'
    '无 DOI ⇒ 跨库合并只能按题名与作者匹配',
    'source.WoS.purpose': '英文文献的完整入口：参考文献、被引次数、使用次数、学科与国家都在这份导出里，'
    '共被引/耦合与国家级合作网络都能建。',
    'source.WoS.steps': '1. 在 Web of Science 核心合集检索\n'
    '2. 勾选记录 →「导出」，记录内容选到最完整的一档：「全记录与引用的参考文献」'
    '（Full Record and Cited References）\n'
    '3. 文件格式首选「纯文本文件」，得到带 CR/TC/UT 标签的 .txt\n'
    '4. 上传 .txt；Excel（.xls/.xlsx）、RIS、BibTeX 也认——注意 Excel 里**没有 Cited References 列**'
    '（站点不提供），引文分析要用纯文本',
    'source.WoS.missing': 'Excel 的 Cited References 列不可用：站点在 Excel 导出里不提供这一列'
    '（实测 30 条整列为空，只写 Cited Reference Count 这个数字）⇒ 用 Excel 时引文网络与引文突现做不了；'
    '关键词（14/30）、学科、基金、使用次数在 Excel 里都可用。'
    '要引文分析请用「纯文本 + 全记录与引用的参考文献」（23/30 条带 CR）',
    'source.Scopus.purpose': 'Scopus 的 CSV 下载：带参考文献、被引次数与作者单位，机构网络与国家网络都能建；'
    '中文界面导出的中文表头同样能读。',
    'source.Scopus.steps': '1. 在 Scopus 检索\n'
    '2. 勾选结果 →「下载」→ 格式选 CSV\n'
    '3. 字段里务必勾上 References（参考文献）、Affiliations（作者单位）与 Cited by（施引文献）'
    '——单位列决定机构网络与国家网络能不能建\n'
    '4. 上传 .csv——中文界面会得到 文献标题/来源出版物名称/施引文献/'
    '参考文献 等列名，本应用都认',
    'source.Scopus.missing': 'Scopus 站点导出不提供 Subject area 与 usage 列（不是漏勾）⇒ '
    '学科共现与按使用次数筛选不可用；'
    '英文界面的列名会随版本变化（Citation count / Cited by、Article number / Art. No.），'
    '两种写法都认',
    'source.Dimensions.purpose': 'Dimensions 的 Publication 导出（Export full record → CSV）：被引次数、学科分类、'
    '基金与 MeSH 主题词都在，一份常有数百条。',
    'source.Dimensions.steps': '1. 在 Dimensions 检索\n'
    '2. 勾选结果 → Export → 选「Export full record」，File format 保持「CSV - Comma separated」\n'
    '3. 不要选「Export for bibliometric mapping」——那是给 VOSviewer/CiteSpace 的网络文件，'
    '本应用读的是记录表；也不要用「Export for reference manager → BibTeX」，'
    '那种文件能按 BibTeX 读，但被引次数、学科与基金都不在里面\n'
    '4. 一次最多 500 条（All items - max 500 items per download），超出就分批导出或勾'
    '「Send email when export is ready」——文件在 Export center 保留 30 天\n'
    '5. 上传 .csv——它的第一行是版权横幅而不是表头，导入会先跳过横幅再读列名',
    'source.Dimensions.missing': '实测这份导出没有 References 列 ⇒ 共被引、文献耦合、引文突现做不了\n'
    '另两种导出（bibliometric mapping、reference manager）我们没有真实件，'
    '所以不声明能读——要引文网络请补 WoS/Scopus/CSSCI',
    'source.Lens.purpose': 'Lens 的学术文献（Scholarly Works）CSV 导出：作者、来源刊、年份、学科、MeSH、'
    '关键词、摘要、DOI、被引次数与基金都在，一份可达上千条。',
    'source.Lens.steps': '1. 在 Lens 检索，并把集合切到 Scholarly Works——不要停在 Patents，'
    '专利导出会被点名拒绝\n'
    '2. 勾选记录 → Export → CSV，字段里保留 Title / Author/s / Publication Year / Source Title / '
    'Volume / Issue Number / Start Page / Keywords / MeSH Terms / Fields of Study / '
    'Citing Works Count / Funding / DOI / Abstract\n'
    '3. 上传 .csv（表头里必须有 Lens ID 与 Citing Works Count 或 Fields of Study，'
    '否则识别不出这是学术集合）',
    'source.Lens.missing': '实测这份导出的 References 列写的是 Lens 记录 ID（形如 002-341-399-981-03X），'
    '不是引文文本 ⇒ 共被引与文献耦合做不了，需要引文网络请用 WoS/Scopus/CSSCI\n'
    '没有任何作者单位或地址列 ⇒ 机构网络与国家网络做不了；'
    'Source Country 是期刊所在国，本应用不会把它当成作者所在国\n'
    '没有使用次数（usage）列 ⇒ 按使用次数筛选保持关闭',
    'source.PubMed.purpose': 'PubMed 免机构授权，适合生物医学文献的关键词/作者/机构/国家共现网络。',
    'source.PubMed.steps': '1. 在 PubMed 检索\n'
    '2. 勾选记录 →「Save」→ Format 选「Text（Medline）」，Create File 后得到 .txt 或 .nbib\n'
    '3. 上传它；Format 选「CSV」得到的摘要文件也读，但它不含摘要与关键词，只适合当引用清单',
    'source.PubMed.missing': '没有参考文献与被引次数 ⇒ 引文类分析不可用',
    'source.RIS.purpose': '通用引文交换格式，多数数据库与文献管理软件都能导出 .ris。',
    'source.RIS.steps': '1. 在 Web of Science 里勾选记录 →「导出」→ 文件格式选「RIS File」\n'
    '2. 或在 Zotero 里右键条目 →「导出条目」→ 格式选 RIS\n3. 上传 .ris',
    'source.RIS.missing': '实测 WoS 的 RIS 导出不含被引次数，单位里也不含国家 ⇒ 按被引筛选与国家网络不可用',
    'source.BibTeX.purpose': 'LaTeX 工作流的通用格式，Zotero 与 WoS 都能导出 .bib。',
    'source.BibTeX.steps': '1. 在 Web of Science 的导出格式里选「BibTeX」，'
    '或在 Zotero 里右键条目 →「导出条目」→ 格式选 BibTeX\n2. 上传 .bib',
    'source.BibTeX.missing': '字段随导出工具而异：缺作者的条目会被计入「跳过」并在控制台点名，不会被当成空记录',
    'source.EndNote.purpose': '知网的「EndNote 下载」按钮或 EndNote/Zotero 都能产出 .enw。',
    'source.EndNote.steps': '1. 知网导出页选「EndNote 下载」，或在文献管理软件里导出 .enw\n2. 上传 .enw',
    'source.EndNote.missing': '实测知网的 .enw 不含参考文献与被引次数',
    'source.NoteExpress.purpose': '知网「NoteExpress 下载」按钮产出的 .net 文件，字段与 RefWorks 版一致。',
    'source.NoteExpress.steps': '1. 知网导出页选「NoteExpress 下载」\n2. 上传得到的 .net 文件',
    'source.NoteExpress.missing': '与 RefWorks 版同样没有参考文献与被引次数',
    'engine.biblio_no_input': '{nid} 需要且只接受一个上游数据表（文献导入节点）',
    'engine.biblio_multi_input': '{nid} 有 {n} 个上游连接：文献计量只接受一个输入，请只保留一条连线',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': '清洗',
    'label.emotion': '情感分析',
    'label.sentiment': '情感极性',
    'label.tendency': '倾向性分析',
    'label.ner': '实体识别',
    'ner.dropped': '实体识别：{n} 条模型答案未在原文中出现，已丢弃（不记录推测出的实体）',
    # ── node type labels (console fallbacks; mirror frontend app.js) ──
    'node.name': '工作流命名',
    'node.source': '数据源',
    'node.upload': '上传文件',
    'node.process': '处理',
    'node.analysis': '分析',
    'node.visualize': '可视化',
    'node.tokenize': '分词',
    'node.output': '输出',
    'node.resume': '断点续跑',
    'node.comment': '评论采集',
    'node.compile': '编译',
    'node.biblio': '文献计量',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': '开始搜索知乎关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.zhihu.authorStart': '[知乎] 采集作者「{author}」的回答与文章，目标 {n} 条',
    'crawl.zhihu.authorEmpty': '[知乎] 没有填写作者（主页链接或 /people/ 后面的 id）：{author}',
    'crawl.zhihu.authorTabEmpty': '[知乎] 作者「{author}」的「{tab}」标签页没有内容（这类作品他确实没发过），跳过',
    'crawl.zhihu.authorTabDone': '[知乎] 「{tab}」标签页采集结束，累计 {n} 条（原因：{reason}）',
    'crawl.zhihu.fallbackSearch': '知乎深链搜索返回空壳，改用搜索框重新提交关键词',
    'crawl.zhihu.emptyOrBlocked': (
        '知乎搜索页未返回任何结果（触发风控/登录墙或页面失效）：'
        '请在执行设置中关闭无头模式，或稍后重试；已采集的数据不受影响'
    ),
    'crawl.cookiesSeeded': 'Cookie 预置：{host} 接受 {n}/{total} 条',
    'crawl.redrive': '页面没落到站点（停在 {where}），重发一次导航',
    # Observation only — never a claim about what the crawl then did. This line is
    # written by ``check_login_wall``, which cannot know the caller's policy: weibo
    # and zhihu stop, while WeChat's batch skips that one article and carries on to
    # the next. Saying 「已停止本次抓取」 there told the user their batch had ended.
    # The stop, when it happens, is announced by the node refusing with
    # ``run.cookieExpired``, which also says what to do about it.
    'crawl.loginWall': '登录墙：{platform} 的 {where} 被重定向到登录页',
    'crawl.riskBlocked': '风控拦截：{platform} 的 {where} 返回了安全验证而非内容（会话未必失效，稍后重试）',
    # Neither of the two above: the browser wrote this page itself, so the site never saw
    # the request and the session is not the thing in question.
    'crawl.unreachable': '浏览器自己拒绝了这次访问：{platform} 的 {where}{detail}',
    'crawl.unreachableToken': '（{token}）',
    'crawl.promptDismissed': '{label} 的首屏弹窗已自动点掉：「{button}」',
    'crawl.promptUnmatched': '{label} 的首屏弹窗无法对应按钮（页面提供：{buttons}），本次可能需等待其自动消失',
    'crawl.zhihu.url': '搜索URL: {url}',
    'crawl.zhihu.loaded': '搜索页面已加载，开始滚动加载更多内容...',
    'crawl.zhihu.processed': '已处理第 {i} 条结果，当前有效数据: {n} 条',
    'crawl.zhihu.skipped': '第 {i} 条结果无有效内容，已跳过',
    'crawl.zhihu.process_error': '处理第 {i} 条结果时出错: {err}',
    'crawl.zhihu.finished': '搜索完成，共获取 {n} 条有效结果（目标 {total} 条）',
    'crawl.zhihu.scrolling': '滚动第 {i} 次，等待内容加载...',
    'crawl.zhihu.no_more': '检测到"没有更多了"，停止滚动（滚动 {i} 次）',
    'crawl.zhihu.scroll_round': '滚动第 {i} 次完成，当前卡片数: {n} 条（目标: {total} 条）',
    'crawl.zhihu.target_reached': '已达到目标数量 {n} 条，停止滚动',
    'crawl.zhihu.stuck': '连续 {n} 轮滚动既无新卡片、页面也不再变高，且未出现「没有更多了」，停止滚动',
    'crawl.zhihu.no_growth': '卡片数未增长 ({n}/3)，再次滚动确认...',
    'crawl.zhihu.phase_done': '滚动加载阶段完成，最终获取 {n} 个卡片',
    # One fact, one line: what the 正文 column actually holds. The search page only ever
    # carries an excerpt, so a crawl that did not expand has to say so once at the end.
    'crawl.zhihu.excerpt_only': '未展开正文：本次所有正文都是搜索页摘要（可在数据源节点勾选「展开全文」）',
    # 热榜: measured as one answer of 30 questions with every paging parameter ignored,
    # so the mode never promises more than the board holds.
    'crawl.zhihu.hotStart': '开始采集知乎热榜，目标 {n} 条',
    'crawl.zhihu.hotDone': '热榜采集结束：{n} 条（目标 {total} 条）',
    'crawl.zhihu.hotCapped': '热榜一共只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.zhihu.hotRefused': '知乎热榜接口没有给出榜单（返回 {answer}）',
    'crawl.zhihu.hotWall': '知乎热榜需要登录：当前 Cookie 被挡在登录页，无法读取榜单',
    'crawl.zhihu.bodies_short': '另有 {n} 条回答未能展开，其正文仍为搜索页摘要',
    'crawl.zhihu.expand_stopped': '连续 {n} 次展开均无回应，本次剩余行改用搜索页摘要',
    # ── crawlers: weibo ───────────────────────────────────────
    'crawl.weibo.keyword': '关键词: {kw}',
    'crawl.weibo.range': '时间范围: {start} 至 {end}',
    'crawl.weibo.links': '共生成 {n} 个搜索链接（每小时1个）',
    'crawl.weibo.keyword_plain': '关键词: {kw}（无时间范围，单链接搜索）',
    'crawl.weibo.processing': '正在处理第 {i}/{total} 个搜索链接',
    'crawl.weibo.url': 'URL: {url}',
    'crawl.weibo.link_done': '第 {i} 个链接爬取完成，获取 {n} 条数据',
    'crawl.weibo.accumulated': '当前累计数据: {n} 条',
    'crawl.weibo.target_reached': '已达到目标数量 {n} 条，停止翻页',
    'crawl.weibo.authorStart': '开始采集作者 {uid} 的作品，目标 {n} 条',
    'crawl.weibo.authorDone': '作者作品采集结束：{n} 条（{reason}）',
    # 热搜: one answer is the whole board, so the three lines below are the only
    # things this mode can honestly say.
    'crawl.weibo.hotStart': '开始采集微博热搜，目标 {n} 条',
    'crawl.weibo.hotDone': '热搜采集结束：{n} 条（目标 {total} 条）',
    'crawl.weibo.hotCapped': '热搜榜本次只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.weibo.hotRefused': '微博热搜接口没有给出榜单（返回 {answer}）',
    # Said when the request was never issuable: the browser was left on a frame that is not weibo.com, so
    # the same-origin fetch had no host to ask. Blaming the endpoint there would convict it of an answer
    # it never gave.
    'crawl.weibo.hotNoHost': '微博热搜未采集：浏览器还停在「{where}」，没回到 weibo.com（访客引导未完成，'
    '页面内请求发不出去；这是到场帧的问题，不是接口拒绝）',
    'crawl.weibo.authorEmpty': '「{author}」不是微博作者地址：填 weibo.com/u/<UID> 主页链接或数字 UID',
    'crawl.weibo.authorWall': '微博把 UID {uid} 的主页弹回了登录页：这个会话进不去作者页',
    'crawl.weibo.authorMirror': (
        'UID {uid} 的答复第一行不属于该作者——接口给的是首页时间线而不是作者作品，拒绝张冠李戴'
    ),
    'crawl.weibo.authorRefused': (
        'mymblog 接口拒绝应答（状态 {status}，UID {uid}）：这是按会话的限流，Cookie 可能并未失效，请稍后再试'
    ),
    'crawl.weibo.authorNoPosts': 'UID {uid} 没有返回任何作品：这个账号可能确实没发过微博',
    'crawl.weibo.visiting': '访问搜索链接: {url}',
    'crawl.weibo.no_result': '该时间段无搜索结果，跳过',
    'crawl.weibo.waiting': '等待页面加载...',
    'crawl.weibo.page_loaded': '页面加载完成',
    'crawl.weibo.total_pages': '检测到总页数: {n}',
    'crawl.weibo.page_crawling': '  正在爬取第 {i}/{total} 页...',
    'crawl.weibo.page_empty': '  第 {i} 页无有效卡片，跳过',
    'crawl.weibo.page_done': '  第 {i} 页爬取完成，共 {n} 条，累计 {total} 条',
    'crawl.weibo.link_error': '处理搜索链接时出错: {err}',
    'crawl.weibo.page_timeout': (
        '    等了 {secs} 秒：这一页既没有给出卡片，也没有给出「无结果」牌（导航{settled}）'
        '—— 这一句只说代码看得见的东西，不能据此断定窗口里没有内容'
    ),
    'crawl.weibo.navSettled': '已完成',
    'crawl.weibo.navUnsettled': '未完成，那是慢网络而不是站点的拒绝',
    'crawl.weibo.page_gave_up': (
        '    这台浏览器已经有 {waits} 个搜索页一次内容都没交付：不再把整段预算花在新的窗口上'
        '（这是「取不到页面」，不是「这个窗口没有内容」）'
    ),
    'crawl.weibo.walk_done': '微博搜索收尾：{n} 条（目标 {target}，窗口走到第 {walked}/{total} 个，原因：{reason}）',
    'crawl.weibo.max_page': '最大页码: {n}',
    'crawl.weibo.pages_fail': '获取总页数失败: {err}',
    'crawl.weibo.page_cards': '    本页共发现 {n} 个卡片',
    'crawl.weibo.card_error': '    卡片 {i}: 处理出错，已跳过',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': '未提供 URL，返回空结果。',
    # ── 断点续跑与去重（爬虫侧） ──────────────────────────────
    'crawl.resume_have': '断点续跑：已采集 {n} 条，接着往下采而不是重来',
    'crawl.sink_failed': '增量落盘失败（这条仍然在本次结果里，但可能没进库）：{err}',
    'crawl.wechat.duplicate': '跳过重复的推文链接：{url}',
    'crawl.xhs.note_dup': '跳过重复的笔记：{url}',
    'crawl.zhihu.duplicate': '跳过重复的第 {i} 条回答',
    'ds.too_many_rows': '文件共 {n} 行，超过数据集上限 {limit} 行，无法保存',
    'crawl.wechat.batch_start': '开始批量抓取 {n} 篇微信公众号文章',
    'crawl.wechat.processing': '正在抓取第 {i} / {total} 篇',
    'crawl.wechat.url': 'URL: {url}',
    # No 阅读/点赞/打赏: WeChat publishes none of the three to a browser that is not
    # the client (measured), so a line naming them would be a column with a plausible
    # face and no source — and this template once printed its own placeholders,
    # because the call site passed four keywords and the text asked for seven.
    'crawl.wechat.success': '第 {i}/{total} 篇已抓取：《{title}》（{author}）',
    'crawl.wechat.failed': '第 {i}/{total} 篇抓取失败：正文没有取到',
    'crawl.wechat.wait': '等待 1 秒后继续下一篇',
    'crawl.wechat.batch_done': '批量抓取完成：{n} / {total} 篇成功',
    'crawl.wechat.navigating': '正在打开文章链接',
    'crawl.wechat.wait_title': '等待文章标题 (#activity-name) 加载',
    'crawl.wechat.loaded': '文章页面加载成功',
    'crawl.wechat.timeout': '页面加载超时: {url}',
    'crawl.wechat.scroll': '滚动到底部以触发懒加载',
    'crawl.wechat.scroll_done': '滚动完成',
    'crawl.wechat.extracting': '正在提取文章字段',
    'crawl.wechat.title': '标题: {title}',
    'crawl.wechat.author': '作者（公众号）: {author}',
    'crawl.wechat.pub_time': '发布时间: {time}',
    'crawl.wechat.content_len': '正文长度: {n} 字',
    'crawl.wechat.preview': '正文预览: {preview}',
    'crawl.wechat.no_content': '重试后仍未找到正文元素。',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[小红书搜索] 开始搜索关键词: "{kw}"，目标数量: {n}',
    'crawl.xhs.url': '[小红书搜索] 已访问搜索URL: {url}',
    'crawl.xhs.page_ready': '[小红书搜索] 初始搜索结果页加载完成',
    'crawl.xhs.page_timeout': '[小红书搜索] 初始内容加载超时，可能没有搜索结果，将继续尝试滚动',
    'crawl.xhs.links': '[小红书搜索] 共收集到 {n} 条笔记链接',
    'crawl.xhs.note_ok': '[小红书搜索] 成功提取: {title}...',
    'crawl.xhs.note_error': '[小红书搜索] 处理笔记时出错: {err}',
    'crawl.xhs.finished': '[小红书搜索] 搜索完成，共获取 {n} 条有效笔记数据',
    'crawl.xhs.target_reached': '[收集链接] 已达到目标数量 {n}，停止加载',
    'crawl.xhs.collect_done': '[收集链接] 收集完成，共 {n} 条链接',
    'crawl.xhs.detail_visit': '[爬取详情] 正在访问详情页: {url}',
    'crawl.xhs.detail_ready': '[爬取详情] 详情页加载完成',
    'crawl.xhs.detail_timeout': '[爬取详情] 详情页加载超时',
    'crawl.xhs.deadNote': '[详情] 笔记被安全验证挡住（非会话失效），跳过：{url}',
    'crawl.xhs.content_len': '[爬取详情] 正文长度: {n} 字',
    'crawl.xhs.author': '[爬取详情] 作者: {author}',
    'crawl.xhs.pub_time': '[爬取详情] 发布时间: {time}',
    'crawl.xhs.metrics': '[爬取详情] 互动数据 - 点赞: {likes}, 收藏: {favs}, 评论数: {comments}',
    'crawl.xhs.comment_count': '[爬取详情] 评论列表: {n} 条',
    'crawl.xhs.comment_skip': '[提取评论] 预览数=0，跳过评论面板（不等待）',
    'crawl.xhs.comment_start': '[提取评论] 开始提取评论，最多 {n} 条',
    'crawl.xhs.comment_found': '[提取评论] 共找到 {n} 个评论元素',
    'crawl.xhs.comment_error': '[提取评论] 提取第 {i} 条评论时出错: {err}',
    'crawl.xhs.comment_done': '[提取评论] 共提取 {n} 条评论',
    # ── analysis / services ───────────────────────────────────
    'export.done': '已导出 {n} 行至 {path}（{fmt}）',
    'export.parquet_engine_missing': '导出 Parquet 需要列式引擎 pyarrow，请先安装：pip install pyarrow',
    # 「文件名带时间范围」 asks the save node to print a window it cannot see: the crawl
    # states it, this node receives a table. Both answers name the reason instead of
    # inventing a range, because a file labelled with the wrong month is worse than one
    # that was never written.
    'export.window_none': '文件名要求带时间范围，但这条链路上没有任何采集节点声明开始/结束时间',
    'export.window_many': '文件名要求带时间范围，但这条链路上有 {n} 个不同的时间窗，一个文件说不清它装的是哪一段',
    'export.window_ignored': '节点 {nid}：结果文件照常生成，仅「文件名追加时间范围」被忽略——{reason}',
    'analysis.type_convert_failed': '列 {col} 转换为 {dtype} 失败：{err}',
    'analysis.calc_failed': '计算列 {col} = {expr} 失败：{err}',
    'analysis.bin_failed': '列 {col} 分箱失败：{err}',
    'analysis.col_missing': '未找到列“{col}”',
    'analysis.keyword_pos_no_match': (
        '按词性 {tags} 过滤后，{rows} 行文本一个关键词都没留下——多半是词性写法不对：'
        '请用 jieba 的标签（如 n、v、vn、a），而不是中文词性名'
    ),
    'analysis.dedupe_similar': (
        '近重复去重：在「{column}」上按 SimHash 距离 ≤{distance} 判定，删除 {n} 行（每组保留首次出现的那行）'
    ),
    'analysis.dedupe_distance': '近重复去重支持的距离是 0–{max} 位，收到 {value}，已拒绝（不做全量两两比对）',
    'analysis.time_unparsed': (
        '「{col}」有 {n} 行不是可解析的时间（站点只给了相对标签，如「09月26日 21:00」），已留空而不是猜一个年份'
    ),
    'analysis.time_binned': '{col} 划分完成：{detail}',
    'analysis.time_bin_labels': '时间分段需要「边界数 = 阶段名数 + 1」，现在是 {edges} 个边界、{labels} 个名称',
    # A boundary PROPOSAL: this step rewrites no row and does not decide when the event
    # turned — that needs the dates the researcher knows (the notice, the apology, the
    # filing), which are not in the post counts.
    'analysis.stages_sparse': '这一列只有 {days} 天有记录，切不出阶段（至少需要 {least} 天）',
    'analysis.stages_ratio': '「峰倍率」至少要是 1（高于平常的一天才算峰），收到 {value}',
    'analysis.stages_no_peak': (
        '发文量曲线里找不到 {ratio} 倍于日常（中位数 {floor} 行/日）的转折峰，'
        '这一列撑不起阶段划分——曲线只有一段，就不要切成多段'
    ),
    'analysis.stages_folded': '曲线上的峰多于 {kept} 个，只保留最高的 {kept} 个（折掉了 {dropped} 个）',
    'analysis.stages_folded_windows': (
        '{n} 个窗口短于「最短窗口」{days} 天，已并入相邻较长的窗口（一天冲上来的不算一个阶段）'
    ),
    'analysis.stages_done': '阶段建议：{n} 个候选窗口、覆盖 {rows} 行（{span}）',
    'analysis.stages_edges': '建议边界 edges（左闭右开，末位是最后一天+1）：{edges}',
    'analysis.stages_labels': '建议阶段名 labels（与 edges 一一对应，仅占位，可改名）：{labels}',
    'analysis.stages_basis_first': '自曲线首日 {day} 起',
    'analysis.stages_basis_valley': '自谷底 {valley} 的次日起',
    'analysis.time_bin_edges': '时间分段里有无法解析成日期的边界：{edges}',
    'analysis.time_bin_order': '{op} 的边界必须按时间从早到晚排列',
    'analysis.topic_count': 'LDA 主题数至少要 2，收到 {value}（1 个主题只是"整段文本"）',
    'analysis.topic_embed_unavailable': '嵌入主题方法缺少可选依赖：{packages}（不回退到 LDA，请安装或改用 LDA）',
    'analysis.topic_embed_failed': '句向量模型「{model}」加载或运行失败：{err}',
    'analysis.topic_embed_done': '嵌入主题：{model}，{n} 个主题，{rows} 行文本',
    'analysis.topic_empty_cluster': (
        '嵌入主题「{topic}」没有分到任何文本：这是模型的答复，不是画布的错——'
        '主题数 {n} 是请求值，模型实际只切出 {got} 个'
    ),
    'analysis.topic_method_auto_embedding': '主题方法 auto：检测到编码器，使用 embedding（{model}）',
    'analysis.topic_method_auto_lda': '主题方法 auto：无编码器包，改用 LDA（结果按 LDA 计）',
    'analysis.bert_fallback': '{op} 的 bert 不可用（{reason}），本次改用 {used} 产出结果（非 bert）',
    'analysis.topic_rows': 'LDA 需要至少和主题数一样多的文本：主题 {topics} 个、有效文本 {rows} 行',
    'analysis.topic_features': 'LDA 无法从这一列抽到特征词（可能整列都是标点或停用词）：{err}',
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
    'analysis.topic_stage_number': '每阶段主题数只能是整数，收到「{value}」',
    'analysis.topic_stage_counts': (
        '每阶段主题数要与阶段一一对应：{stages} 个阶段，收到 {counts}（只填一个数字表示各阶段同数）'
    ),
    'analysis.stage_blank': '「{col}」有 {n} 行没有阶段（时间戳没解析出来），它们不进任何主题模型',
    'analysis.topic_stage_empty': '阶段「{stage}」一行都没有，无法为它建模（先检查「{col}」的边界）',
    'analysis.topic_stage_rows': (
        '阶段「{stage}」只有 {rows} 篇可用文本，撑不起 {topics} 个主题（LDA 至少要有和主题数一样多的文本）'
    ),
    'analysis.topic_stage_features': '阶段「{stage}」抽不到特征词：{err}',
    'analysis.topic_stage_words': (
        '阶段「{stage}」的 {topic} 一个特征词都选不出来（没有文本归到这个主题，请调小该阶段的主题数）'
    ),
    'analysis.topic_stage_unused': '阶段「{stage}」的 {topic} 没有分到任何文本（doc_n=0），特征词改用该主题的词分布',
    'analysis.topic_stage_done': '阶段「{stage}」：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}',
    'analysis.topic_stage_topic_words': '{topic}（{stage}）: {words}',
    # 主题可视化（pyLDAvis 那两张图的数据面）。λ 是「按主题自身概率」还是「按相对全库的溢出」
    # 排序，同一模型会给出两份不同的词表，所以用了哪个值必须随表一起说出来。
    'analysis.topic_map_done': (
        '主题距离图：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}'
        '（气泡大小=主题占比，坐标=两主题词分布的 JS 散度经 MDS）'
    ),
    'analysis.topic_salience_done': (
        '主题显著词：{n} 个主题、{rows} 篇文本、共 {terms} 行，λ={value}（1=按主题内概率排序，0=按相对全库的溢出排序）'
    ),
    'analysis.topic_lambda': 'λ 要在 0 到 1 之间（0=只看相对溢出，1=只看主题内概率），收到 {value}',
    # 主题概括：一行一次模型调用，所以失败要说清是哪个主题，停手也要说清还剩几个没问。
    'analysis.label_no_llm': '「{op}」没有拿到模型客户端：只有画布上的运行才带模型',
    'analysis.label_too_many': '主题概括要逐主题问模型：{rows} 行超过了上限 {limit}，请先把主题表缩小',
    'analysis.label_no_words': '{topic} 的「{col}」是空的，没有特征词就没有可概括的东西',
    'analysis.label_failed': '{topic} 的主题概括失败：{err}',
    'analysis.label_empty': '{topic} 的主题概括是空的（模型只回了标点）',
    'analysis.label_fallback': '主题「{topic}」未获模型概括，已按其权重词回退标注（{reason}）',
    'analysis.label_fallback_all': '{n} 个主题无模型可用，全部按权重词回退标注',
    'analysis.label_cancelled': '已停止：还有 {n} 个主题没问模型，它们的概括标为未处理',
    'analysis.label_done': '主题概括：{n} 个主题已写出（模型 {model}）',
    'analysis.label_cached': '主题概括：新问模型 {asked} 次，重放缓存答案 {replayed} 次（同一张表重跑不再重复付费）',
    'analysis.label_prompt': (
        '你是舆情分析研究员。下面是某网络暴力事件在一个阶段里一个主题的特征词与代表文本。'
        '请用不超过 15 个汉字概括这个主题在说什么；只输出概括本身，不要解释、不要引号。\n'
        '阶段：{stage}\n主题编号：{topic}\n特征词：{words}\n代表文本：{samples}'
    ),
    'analysis.cluster_prompt': (
        '你是舆情分析研究员。下面是某网络暴力事件语料按语义聚类后、同一个簇里的若干条原始文本。'
        '请用不超过 40 个汉字概括这一簇在说什么；只输出概括本身，不要解释、不要引号。\n'
        '簇号：{group}\n簇内条数：{size}\n代表文本：\n{texts}'
    ),
    'analysis.cluster_done': '聚类摘要：{n} 个簇已写出（模型 {model}）',
    'analysis.cluster_failed': '簇 {group} 的摘要失败：{err}',
    'analysis.cluster_cancelled': '已停止：还有 {n} 个簇没问模型，它们的摘要标为未处理',
    'analysis.cluster_no_texts': '簇 {group} 里没有可摘要的文本，无法问模型',
    'analysis.review_prompt': (
        '你是文献计量与科学计量研究员。下面是一个知识图谱聚类簇的**既有度量**（全部来自表格，不是推测）。'
        '请据此写出 3–5 句该簇所代表的研究前沿：它关注什么问题、由哪些概念支撑、'
        '在给定年份区间里可能的演化方向。只写分析本身，不要复述数据、不要列点、不要客套；用{language}回答。'
        '\n'
        '{facts}'
    ),
    'analysis.review_fact_size': '簇内节点数：{n}',
    'analysis.review_fact_label': 'LLR 标签：{label}',
    'analysis.review_fact_members': '代表节点（按频次）：{members}',
    'analysis.review_fact_span': '年份跨度：{span}',
    'analysis.review_done': '簇综述：{n} 个簇已写出（模型 {model}）',
    'analysis.review_failed': '簇 {group} 的综述失败：{err}',
    'analysis.review_failed_fallback': '簇 {group} 的综述失败，已改用表格事实生成的兜底句：{err}',
    'analysis.review_failed_blank': '簇 {group} 的综述失败，按要求留空：{err}',
    'analysis.review_empty': '簇 {group} 的综述返回为空',
    'analysis.review_cancelled': '已停止：还有 {n} 个簇没问模型，它们的综述标为未处理',
    'analysis.review_no_groups': '簇综述找不到分组列 {col}：请先让上游文献计量节点开启聚类',
    'analysis.review_fallback_text': '（未经模型，按表格事实生成）该簇含 {size} 个节点，代表节点：{members}',
    'analysis.cluster_empty': '簇 {group} 的摘要返回为空',
    'analysis.reply_graph_no_edges': (
        '回复传播图找不到可关联的回复：请确认「评论者」「楼层」「父楼层」三列存在，'
        '且确有回复行的「父楼层」能对上某条顶层评论的「楼层」'
    ),
    'analysis.reply_graph_done': '回复传播图：{edges} 条边、{nodes} 个节点',
    'analysis.compare_done': '跨平台对比：{platforms} 个平台（数值列 {value}）',
    'analysis.compare_agg': '{op}：未知聚合「{agg}」，数值列只支持 sum 或 mean（列名按聚合命名，名实必须相符）',
    'analysis.bot_col_missing': '水军可能性需要「{col}」列，表里没有',
    'analysis.bot_done': '水军可能性：{rows} 行里 {flagged} 行被标为可疑（来自 {authors} 个作者）',
    'analysis.bot_limit': (
        '水军可能性只是召回线索、不是判决：它只能看见表内的跨账号重复文本与发帖突发，'
        '改了措辞和时间的协同账号一律漏检，且漏检率不可测'
    ),
    'analysis.bot_evidence_dup': '与他人文本高度雷同（{ratio}）',
    'analysis.bot_evidence_burst': '发帖突发：某10分钟窗内达 {peak} 条（各作者峰值中位 {median}）',
    'analysis.topic_done': (
        'LDA 主题模型：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}（数值越低拟合越好，但过小意味着在记原文）'
    ),
    'analysis.evolution_done': (
        '情感演化：按「period」聚合出 {n} 个时段（{periods}），情感指数 =(积极−消极)/总数 ∈ [-1, 1]'
    ),
    # The intensity curve is only honest if the periods it could not score say so: a blank
    # in an exported table is invisible, and 0.5 would print as "measured, and neutral".
    'analysis.evolution_unscored': '「{col}」在时段「{periods}」里一行分数都没有，这些时段的情感强度留空',
    # ── 阶段之后的读数：主题生命周期、跨阶段流向、主题数扫描、共词 ──
    # Each refusal names the number it measured, so the fix is a choice with a figure in front
    # of it rather than a guess at what the step wanted.
    'analysis.timeline_stages': '主题生命周期至少要 2 个阶段才谈得上「先后」，现在只有 {stages} 个',
    'analysis.timeline_overlap': '「同主题词重合度」要在 0 到 1 之间，收到 {value}',
    'analysis.timeline_blank': '「{col}」有 {n} 行不属于任何阶段，它们不进生命周期',
    'analysis.timeline_size': '「{col}」里一个数值都没有，峰值无从测量（留空不等于峰为 0）',
    'analysis.timeline_partial': '「{col}」有 {n} 行不是数值，它们在峰值里按 0 计',
    'analysis.timeline_words': '阶段「{stage}」的 {topic} 在「{col}」里没有特征词，无法跨阶段追踪它',
    'analysis.timeline_done': (
        '主题生命周期：{topics} 个主题（{stages} 个阶段），{multi} 个跨多阶段、{secondary} 个判为次生舆情'
        '（词重合阈值 {value}）'
    ),
    'analysis.timeline_secondary': '次生舆情：{topic} 的阶段路径 {path}',
    'analysis.flow_stages': '主题流向至少要 2 个相邻阶段，现在只有 {stages} 个',
    'analysis.flow_similarity': '「流向相似度阈值」要在 0 到 1 之间，收到 {value}',
    'analysis.flow_weights': '{topic}（阶段「{stage}」）的「{col}」里没有可用的词权重，无法算分布差异',
    'analysis.flow_stage_empty': '阶段「{stage}」里没有主题行（先检查「{col}」）',
    'analysis.flow_no_edges': ('没有一条主题流向达到阈值 {value}：实测最相似的一对是 {best}，把阈值调到它以下再来'),
    'analysis.flow_done': '主题流向：{stages} 个阶段之间得到 {edges} 条边（阈值 {value}，实测最高 {best}）',
    'analysis.coherence_range': '主题数扫描的起点不能大于终点：{low} > {high}',
    'analysis.coherence_sampled': '主题数扫描只抽 {used} 篇文本（共 {total} 篇可用），换个样本数字会变',
    'analysis.coherence_capped': '文本只有 {rows} 篇，扫描的终点从 {high} 个主题降到 {rows} 个',
    'analysis.coherence_row': 'n_topics={topics}  coherence={coherence}  perplexity={perplexity}',
    'analysis.coherence_pairs': (
        '每主题取 {topn} 个词，但这些词没有一对出现在同一篇文本里（跳过 {pairs} 对）：一致性无法测量，只有困惑度可读'
    ),
    'analysis.coherence_best': (
        '主题数扫描（{low}…{high}）：一致性最高在 {coherence} 个主题，困惑度最低在 {perplexity} 个'
    ),
    'analysis.cooccur_topn': '共词网络的候选词上限是 {cap}（词数翻倍则边数翻四倍），收到 {value}',
    'analysis.cooccur_count': '共现次数阈值至少是 1，收到 {value}',
    'analysis.cooccur_words': '只选出 {found} 个候选词，凑不出一对共现（要求前 {topn} 个）',
    'analysis.cooccur_empty': ('没有一对词共现达到阈值 {floor}：{pairs} 对里最高只有 {top} 次，请降低阈值或放宽候选词'),
    'analysis.cooccur_done': '共词网络：{words} 个候选词、{docs} 篇文本，{pairs} 对里 {edges} 对达到阈值 {floor}',
    # ── 往前看：曲线外推与二次爆发预警 ──
    'analysis.forecast_horizon': '外推步数至少是 1，收到 {value}（0 步只是把最后一格再抄一遍）',
    'analysis.forecast_window': '移动平均的窗口至少 2 期才能平均，收到 {value}',
    'analysis.forecast_season': '季节类方法的周期长度至少 2 期，收到 {value}',
    'analysis.forecast_season_rows': '季节方法观测不足：至少要 {season} 期，本列只有 {rows} 期',
    'analysis.forecast_smooth': '平滑系数「{name}」要在 0 与 1 之间（不含两端），收到 {value}',
    'analysis.forecast_dates': '「{col}」不是能解析成日期的时段列（一个日期都没有）：阶段名没法外推',
    'analysis.forecast_rows': '外推至少要 {least} 期观测，这一列只有 {rows} 期同时给出时间与数值',
    'analysis.forecast_window_rows': '窗口 {window} 期至少要留一期来预测，这一列只有 {rows} 期',
    'analysis.forecast_duplicate': '「{col}」里有同一天出现两行：{days}（两行会被当成趋势的两步）',
    'analysis.forecast_uneven': '时段间隔不齐：{rows} 期里有 {steps} 步不是 {gap} 天，未来格按 {gap} 天间隔标注',
    'analysis.forecast_done': '{method} 外推：{rows} 期观测，往后 {horizon} 步，间隔 {gap} 天（末期 {last}）',
    'analysis.alert_streak': '连续期数至少是 1，收到 {value}',
    'analysis.alert_threshold': '「{name}」阈值必须大于 0，收到 {value}',
    'analysis.alert_floor': '热度保持倍率不能超过 1（那等于要求热度上涨才算爆发），收到 {value}',
    'analysis.alert_rows': '预警至少要比连续期数多一行：需要 {least} 行，只有 {rows} 行',
    'analysis.alert_skipped': '「{col}」有 {n} 行解析不出日期，它们不参与预警判断',
    'analysis.alert_reason': '连续 {streak} 期变化 {moves}；强度斜率 {intensity}；本期热度 {volume}（{held}）',
    'analysis.alert_none': (
        '未触发：幅度最大的是 {period}，连续 {streak} 期平均 |Δ| 未到 {swing}，强度斜率未到 {heating}'
    ),
    'analysis.alert_none_log': '预警检查了 {checked} 期：连续 {streak} 期、幅度阈值 {swing}，一条都没触发',
    'analysis.alert_fired': '二次爆发预警：{period} 触发 {signal}，数值 {value}',
    'clean.unknown_mode': '清洗节点没有名为「{mode}」的模式（可用：regex、llm）',
    'aggression.lexicon_done': (
        '网暴言论识别（词库）：{rows} 行中 {violent} 行含暴力言论，其中 {severe} 行为严重'
        '（漏报无法度量：词表之外的说法看不见）'
    ),
    'clean.regex_done': '正则清洗：保留 {kept} 行、判定删除 {dropped} 行（未做主题相关性判断，那需要 llm 模式）',
    # A cleaning step that this table cannot carry out. `{op}` and `{param}` stay the
    # storage names on purpose: they are what the caller of /api/analysis/run wrote,
    # and what the Settings panel stores in the node's JSON, so a person fixing a
    # hand-written pipeline can match them against the file they edited.
    'analysis.need_param': '「{op}」缺少「{param}」，请先填写',
    # A count the step reads as an integer. The panel cannot send junk here (the normalizer drops
    # an unreadable box to the default), but a hand-written workflow file and /api/analysis/run
    # both reach the service, where int('abc') would otherwise surface as an opaque node failure.
    'analysis.need_number': '「{op}」的「{param}」要是一个整数，收到「{value}」',
    'analysis.step_col_missing': '「{op}」：表里没有名为「{col}」的列',
    'analysis.step_cols_missing': '「{op}」：表里没有这些列：{cols}',
    'analysis.bad_option': '「{op}」的「{param}」没有「{value}」这个选项（可用：{allowed}）',
    'analysis.need_multi_models': '「{op}」的 bert 模式要多模型对比至少需 2 个模型（当前 {n} 个）',
    'analysis.multi_models_run': '多模型对比：本次用 {n} 个模型跑「{op}」：{models}',
    'analysis.rename_blank': '「{op}」：这些列的新名字是空的，请填写：{cols}',
    'cluster.not_enough': '有效行数不足，无法聚类（至少需要 2 行）',
    'cluster.dbscan': 'DBSCAN 发现 {n} 个簇 + {noise} 个噪声点',
    'cluster.done': '聚类完成：{rows} 行分为 {clusters} 簇（轮廓系数={score:.3f}）',
    'anomaly.no_numeric': '没有可用于异常检测的数值列',
    'anomaly.no_usable_columns': '异常检测：你指定的列都不是数值列（{columns}）',
    'anomaly.ignored_columns': '异常检测：以下列不是数值列，已跳过（{columns}）',
    'anomaly.too_few': '行数过少（{n} < {min}），异常检测无法给出结论',
    'anomaly.done': '异常检测：{n}/{total} 行被标记（contamination={c:.2f}）',
    'corr.need_cols': '相关性分析至少需要 2 个数值列',
    'corr.no_usable_columns': '相关性分析：你指定的列都不是数值列（{columns}）',
    'corr.ignored_columns': '相关性分析：以下列不是数值列，已跳过（{columns}）',
    'corr.done': '相关性分析（{method}）：找到 {n} 对（min_abs={min_abs:.2f}）',
    'sig.no_group_column': '显著性检验：没有指定分组列',
    'sig.no_value_column': '显著性检验：没有指定数值列',
    'sig.group_column_missing': '显著性检验：分组列“{col}”不在表里',
    'sig.value_column_missing': '显著性检验：数值列“{col}”不在表里',
    'sig.value_not_numeric': '显著性检验：数值列“{col}”整列都无法转成数字',
    'sig.no_usable_rows': '显著性检验：分组“{col}”丢空值/非数值后一行都不剩',
    'sig.two_groups_only': '显著性检验：{method} 只比较两组，实际 {n} 组——请改用 ANOVA / Kruskal-Wallis',
    'sig.two_groups_required': '显著性检验：{method} 至少需要两组，实际 {n} 组',
    'sig.degenerate': '显著性检验：{method} 无法计算（组数或组内样本不足、方差为零），不给假 p 值',
    'sig.unknown_method': '显著性检验：未知方法“{method}”',
    'sig.done': '显著性检验（{method}）：{n_groups} 组、共 {n} 行，统计量={statistic}，p={p}',
    'ml.model_untrained_refused': (
        '「{name}」模型尚未训练，也没有可加载的已保存模型 —— 拒绝作答，而不是给每行编一个中性结果'
    ),
    'ml.missing_col': 'DataFrame 缺少必需的列“{col}”。跳过分析。',
    'ml.no_rows': '没有需要处理的行（目标列为空）。',
    'ml.emotion_failed': 'ML 情感预测失败：{err}——回退为 Neutral',
    # ── 情感极性（snownlp / bert / ml / llm）───────────────────────────
    # A row that fails to read stays blank, so the failure line has to say the count:
    # 「判断为中性」 and 「没判断出来」 are different statements about the text.
    'sentiment.scored': '情感极性（{mode}）：已判断 {n} 行',
    'sentiment.scored_failed': '情感极性：{n} 行读取失败，留空（不是中性）',
    'sentiment.snownlp_failed': 'SnowNLP 判断失败：{err}',
    'sentiment.bert_failed': 'BERT 判断失败：{err}',
    'sentiment.ml_failed': 'ML 情感极性预测失败：{err}——回退为 neutral',
    'sentiment.unknown_mode': '使用了未知的情感极性模式「{mode}」',
    'sentiment.bad_thresholds': '正向阈值 {pos} 不得低于负向阈值 {neg}，那样每一行都会同时满足两边',
    'sentiment.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'sentiment.bert_no_model': 'BERT 模式还需要在「模型」里填一个情感模型名（本地目录或仓库名），空着无法判断',
    'sentiment.bert_bad_label': 'BERT 模型回了一个不认识的标签「{label}」，无法归入正面/负面/中性',
    'sentiment.bert_loaded': 'BERT 情感模型已加载：{model}（{runtime}/{precision}，跑在 {device}，逐批）',
    'sentiment.bert_need_runtime': 'torch+transformers 或 onnxruntime+tokenizers',
    'sentiment.bert_no_onnx': '这个 BERT 模型目录里没有可加载的 ONNX 图：{path}',
    'sentiment.bert_no_model_dir': '没有找到 BERT 模型目录：{path}。{remedy}',
    'sentiment.packRemedyFrozen': (
        '桌面版的 BERT 模型是一个单独的压缩包：把 CaiXiHui-bert-models-win64.zip 解压到程序目录下的 '
        'bert_models\\，再重启程序'
    ),
    'sentiment.packRemedySource': (
        '源码版需要先用 ml_train/scripts/export_onnx_bert.py 从训练好的权重导出 ONNX 目录，'
        '或在节点的「模型」里填一个已存在的目录名'
    ),
    'sentiment.bert_no_labels': '这个 BERT 模型目录没有 id2label 标签表，输出读不成类别：{path}',
    'sentiment.bert_onnx_inputs': '这个 ONNX 图的输入不是本程序约定的四路，实测：{found}',
    'sentiment.bert_session_dropped': '为控制内存已释放更早加载的 BERT 模型：{model}（后面再用到会重新加载）',
    'emotion.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'emotion.bert_no_model': 'BERT 模式还需要在「模型」里填一个情绪分类模型名（本地目录或仓库名），空着无法判断',
    'emotion.bert_loaded': 'BERT 情绪模型已加载：{model}（{runtime}/{precision}，跑在 {device}，逐批）',
    'emotion.bert_failed': 'BERT 情绪判断失败：{err}',
    'emotion.bert_bad_label': 'BERT 模型回了一个不认识的情绪标签「{label}」，无法归入这六类',
    'emotion.bert_done': '[BERT] 情绪分类完成，{n} 行，失败 {failed} 行',
    'tendency.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'tendency.bert_no_model': 'BERT 模式还需要在「模型」里填一个倾向分类模型名（本地目录或仓库名），空着无法判断',
    'tendency.bert_loaded': 'BERT 倾向模型已加载：{model}（{runtime}/{precision}，跑在 {device}，逐批）',
    'tendency.bert_failed': 'BERT 倾向判断失败：{err}',
    'tendency.bert_bad_label': 'BERT 模型回了一个不认识的倾向标签「{label}」，无法归入这六类',
    'tendency.bert_done': '[BERT] 倾向分类完成，{n} 行，失败 {failed} 行',
    'ml.tendency_failed': 'ML 倾向性预测失败：{err}——回退为 Objective Statement',
    'ml.emotion_done': '[ML] 情感分类完成，共处理 {n} 行，模式: ML',
    'ml.tendency_done': '[ML] 倾向性分析完成，共处理 {n} 行，模式: ML',
    'cookie.saved': '已保存 {platform} 的 Cookie',
    # 一个平台可以多份登录：那句保存的话必须说出是**哪一份**，否则控制台里「已保存 微博 的 Cookie」
    # 指的是哪一个账号无从判断（用户要的正是逐个 Cookie 管理）。{account} 由 CookieManager 先取好
    # 词（空白=默认账号、default2=默认账号2、自己起的名字原样），这里只负责成句。
    'cookie.savedAccount': '已保存 {platform} 的 Cookie（账号：{account}）',
    'cookies.accountDefault': '默认账号',
    'cookies.accountDefaultNumbered': '默认账号{n}',
    'cookie.started': '已启动登录浏览器，请在弹出的窗口完成登录，然后点「已完成登录」',
    'cookie.jobCancelled': '{platform} 登录已取消',
    'cookie.windowClosed': '登录窗口被关闭，未捕获 Cookie；请重新发起登录',
    'cookie.noCookies': '等待结束仍未获得 Cookie——若登录未完成，请重试',
    'cookie.droppedForeign': (
        '已忽略 {n} 条不属于 {platform} 的 Cookie：登录常会经过第三方站点，它们不进本平台的 Cookie 文件'
    ),
    'cookie.allForeign': '{platform} 的 Cookie 一条都没保存：粘贴的内容全属于其它站点，请粘贴该平台自身的 Cookie',
    # ── Cookie 用途与获取步骤（面板直接把这些讲给用户） ──────────
    'cookie.zhihu.purpose': '解锁知乎搜索结果与回答、评论正文；未登录时知乎常常只回一个登录引导页。',
    'cookie.zhihu.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录知乎（扫码或手机号）\n'
        '2. 随便翻一页，确认右上角已是你的头像\n'
        '3. 回到本面板点「已完成登录」'
    ),
    'cookie.weibo.purpose': '解锁微博搜索（s.weibo.com）与评论 JSON 接口；未登录会被跳回 passport 二维码页。'
    '微博只认一份一直在用的会话：同账号并行翻页、或另开一个浏览器重放同一份 Cookie，都会被弹回登录页。'
    '所以抓取请始终用同一个 Profile，也不要同时跑两条微博。',
    'cookie.weibo.steps': (
        '1. 点「浏览器生成」，在窗口里登录微博\n2. 手动搜一次关键词，能看到微博列表即可\n3. 回到本面板点「已完成登录」'
    ),
    'cookie.bilibili.purpose': '解锁 B 站搜索、视频详情与评论区；未登录时搜索会被折叠，评论只给前几条。',
    'cookie.bilibili.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录哔哩哔哩（扫码或手机号）\n'
        '2. 打开任意视频并滚到评论区，能看到评论列表即可\n'
        '3. 回到本面板点「已完成登录」'
    ),
    'cookie.douyin.purpose': '解锁抖音网页版搜索、视频文案与评论区；未登录常常只给首屏且看不到评论。',
    'cookie.douyin.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录抖音网页版（扫码或手机号）\n'
        '2. 打开任意视频，右侧能看到评论区即可\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：抖音网页版对自动化浏览器较敏感，若窗口里出现滑块验证，请在窗口内手动完成后再保存。'
    ),
    'crawl.dy.target_reached': '[抖音] 已达到目标数量 {n} 条，停止',
    'crawl.dy.round': '[抖音] 第 {i} 屏：{n} 张卡片（新 {fresh} 个，已收录 {done} 条）',
    'crawl.dy.noMore': (
        '[抖音] 列表自己写了「暂时没有更多了」：翻了 {screens} 屏，最后一屏 {cards} 张卡片，'
        '这一轮的供给就到这儿（不是滚动没生效）'
    ),
    'crawl.dy.processed': '[抖音] 已收录视频 {i}，当前有效数据: {n} 条',
    'crawl.dy.authorStart': '[抖音作者] 开始采集该作者的作品，目标 {n} 条（计数在同页遮罩里逐条点开取，不整页跳转）',
    'crawl.dy.authorEmpty': '[抖音作者] 没有给出作者（粘贴 douyin.com/user/… 链接或那串 sec_uid）：{author}',
    'crawl.dy.authorNoWorks': '[抖音作者] 该作者的主页自报作品数为 0，本就没有可采集的内容',
    'crawl.dy.authorDone': '[抖音作者] 作品列表采集结束，共 {n} 条（主页自报 {works} 条）',
    'crawl.dy.authorDoneNoCount': '[抖音作者] 作品列表采集结束，共 {n} 条（主页未给出作品数，无法判断是否已到末尾）',
    'crawl.dy.authorNoCards': (
        '[抖音作者] 该作者主页始终没有渲染出作品列表，本次未采集。页面自报：{page}；地址：{url}。'
        '主页自报作品数 {works} 条，所以这是被拦截或页面出错，不是「这个人没发过作品」'
    ),
    'crawl.dy.authorNotMounted': (
        '[抖音作者] 该作者主页既没有渲染出作品列表、也没有给出作品数，本次未采集。'
        '页面自报：{page}；地址：{url}。这两种缺省同时出现只可能是被拦截或页面出错'
    ),
    'crawl.dy.wall': (
        '[抖音] 浏览器被挡在「验证码中间页」：抖音网页版对无头浏览器与频繁请求都会弹验证。'
        '请确认已在 Cookie 面板用「可见窗口」登录并保存，稍后再重试本关键词'
    ),
    'crawl.dy.detailEmpty': '[抖音] 视频 {i} 的详情页没有渲染出数据，已跳过该行',
    'crawl.dy.detailWalled': (
        '[抖音] 视频 {i} 这一条被站点挡在「验证码中间页」（图文页在这台设备上就是这样，视频页不受影响）'
        '，已跳过该行：它不是「站点没内容」，也不是登录态失效'
    ),
    'crawl.dy.detailSwapped': (
        '[抖音] 要打开的是 {i}，浏览器却给了另一条视频 {shown}（站点自己换了内容）'
        ' —— 这一行不入库：宁可少一行，也不把别人的文案和计数挂在这个链接下'
    ),
    'crawl.dy.detailNoIdentity': (
        '[抖音] 视频 {i} 的详情页只渲染出计数条，作者与发布时间都没有，已跳过该行：'
        '一条说不出是谁、什么时候发的记录不是数据，只是把额度花在一个空行上'
    ),
    'crawl.dy.detailSlow': (
        '[抖音] 视频 {i} 的详情页在加载超时内没加载完，已跳过该行：这是网络或站点响应慢，稍后重试可能就拿到了'
    ),
    'crawl.dy.modalDeferred': (
        '[抖音] 有 {n} 条作品卡片的遮罩打不开、本轮跳过：这不是「没有更多了」，是读不到，稍后可重试'
    ),
    # The one refusal on this page that needs no waiting and no probing: the document is
    # the browser's own, and it says which address it refused.
    'crawl.dy.noPageRefused': '[抖音] 浏览器自己拒绝了这一页，因此不可能有卡片：{url}{detail}',
    'crawl.dy.hotStart': '[抖音热榜] 开始采集热榜，目标 {n} 条（榜单一次给全，不逐条打开）',
    'crawl.dy.hotTarget': '[抖音热榜] 已采集到目标 {n} 条，不再读取榜单',
    'crawl.dy.hotDone': '[抖音热榜] 榜单采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.dy.hotCapped': '[抖音热榜] 榜单本次只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.dy.hotWall': '[抖音热榜] 打开榜单页时被挡在「验证码中间页」，本次未采集：请先在 Cookie 面板登录并保存抖音',
    'crawl.dy.hotRefused': '[抖音热榜] 榜单接口没有给出榜单（返回 {answer}）',
    'crawl.bili.start': '[哔哩哔哩搜索] 开始搜索关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.bili.url': '[哔哩哔哩搜索] 搜索URL: {url}',
    'crawl.bili.page': '[哔哩哔哩搜索] 第 {page} 页：{n} 个视频（新 {fresh} 个，已收录 {done} 条）',
    'crawl.bili.empty_page': '[哔哩哔哩搜索] 第 {page} 页没有视频卡片，停止翻页',
    'crawl.bili.no_more': '[哔哩哔哩搜索] 连续两页都是已抓过的视频，列表已到末尾（第 {page} 页）',
    'crawl.bili.processed': '[哔哩哔哩搜索] 已收录 {i}，当前有效数据: {n} 条',
    'crawl.bili.duplicate': '[哔哩哔哩搜索] {i} 已存在于本次运行，跳过',
    'crawl.bili.target_reached': '[哔哩哔哩搜索] 已达到目标数量 {n} 条，停止翻页',
    'crawl.bili.authorStart': '[哔哩哔哩] 采集 UP主 {mid} 的投稿视频，目标 {n} 条',
    'crawl.bili.hotStart': '[哔哩哔哩] 采集{board}，目标 {n} 条（榜单接口自带全部数字，不逐条请求）',
    'crawl.bili.hotPage': '[哔哩哔哩] 榜单第 {page} 页：{n} 条（新 {fresh} 条，已收录 {done} 条）',
    'crawl.bili.hotDone': '[哔哩哔哩] 榜单采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.bili.boardPopular': '热门榜',
    'crawl.bili.boardRanking': '周排行榜',
    'crawl.bili.authorEmpty': '[哔哩哔哩] 没有填写 UP主（space.bilibili.com 链接或数字 mid）：{author}',
    'crawl.bili.authorNoVideos': '[哔哩哔哩] UP主 {mid} 的投稿列表没有渲染出视频（可能真的没投过稿）',
    'crawl.bili.authorDone': '[哔哩哔哩] 投稿列表采集结束，共 {n} 条（原因：{reason}）',
    'crawl.bili.watermarkHit': '[哔哩哔哩] 遇到上次完成的边界 {i}，停止继续翻页',
    'crawl.bili.goneVideo': '[哔哩哔哩搜索] {i} 稿件不存在或已失效（{code}），跳过这一条',
    'crawl.bili.fetchEmpty': '[哔哩哔哩搜索] {i} 的稿件接口没有返回可读数据（非 JSON 或被 WAF 拦截），跳过这一条',
    'crawl.bili.rankingCapped': '[哔哩哔哩] {board}本次只有 {n} 条（目标 {total} 条）：榜单大小由站点决定',
    'crawl.bili.finished': '[哔哩哔哩搜索] 搜索完成，共获取 {n} 条有效结果（目标 {total} 条）',
    'crawl.bili.blocked': (
        '[哔哩哔哩] 接口拒绝返回数据（code={code}）：Cookie 可能已失效或触发了风控，'
        '请在 Cookie 面板重新登录并保存后继续运行'
    ),
    'crawl.hg.boardHotDrama': '热播榜',
    'crawl.hg.boardRealDrama': '真人剧热播榜',
    'crawl.hg.boardAiDrama': 'AI剧热播榜',
    'crawl.hg.boardComicDrama': '漫剧热播榜',
    'crawl.hg.boardUnknown': '[红果短剧] 没有这个榜单：{board}（可选：{options}）',
    'crawl.hg.start': '[红果短剧] 开始采集{board}，目标 {n} 条（翻页只走站点自己给出的下一页地址）',
    'crawl.hg.target_reached': '[红果短剧] 已采集到目标 {n} 条，不再翻页',
    'crawl.hg.page': '[红果短剧] 第 {page} 页：{n} 条（新 {fresh} 条，已收录 {done} 条）',
    'crawl.hg.lastPage': '[红果短剧] 第 {page} 页是站点给出的最后一页，不再翻页（已收录 {n} 条）',
    'crawl.hg.replay': '[红果短剧] 第 {page} 页的「下一页」指回了当前地址（{url}），翻页停住：按未采满处理',
    'crawl.hg.noFresh': '[红果短剧] 连续两页都没有新条目（第 {page} 页），翻页停住：按未采满处理',
    'crawl.hg.finished': '[红果短剧] 采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.hg.noBoard': (
        '[红果短剧] 等待 {seconds} 秒后这一页仍没有榜单数据（页面上的数据键：{keys}）：{url}'
        '——可能是站点改版或网络没有把这一页送到'
    ),
    'crawl.hg.noPageRefused': '[红果短剧] 浏览器自己拒绝了这一页，因此不可能有榜单数据：{url}{detail}',
    'crawl.hg.searchUnsupported': '[红果短剧] 该站点只提供四个热播榜单，没有关键词搜索（收到关键词：{keyword}）',
    'crawl.hg.noDetail': '[红果短剧] 该平台没有「按链接采集」的模式，也还没有测量过详情页读取（{url}）',
    # ─── 评论收割（桌面播放器 + 本地代理；机制见 docs/crawler_notes.md 红果短剧）───
    'crawl.hg.cmt.start': '[红果短剧] 开始收割评论：{title}（{episodes} 集，子回复{replies}）',
    'crawl.hg.cmt.on': '开',
    'crawl.hg.cmt.off': '关',
    'crawl.hg.cmt.episode': '[红果短剧] 第 {n}/{total} 集：{have} 条评论（站点报 {site_total} 条）',
    'crawl.hg.cmt.replyPage': '[红果短剧] 楼层 {floor} 的子回复：{n} 条',
    'crawl.hg.cmt.danmakuSkipped': '[红果短剧] 丢弃 {n} 条弹幕引导行（它们不是评论）',
    'crawl.hg.cmt.finished': '[红果短剧] 评论收割结束，共 {n} 行（{episodes} 集）',
    'crawl.hg.cmt.noPlayer': (
        '[红果短剧] 找不到红果短剧桌面播放器（{path}）——请在 设置 › 红果播放器路径 填写它的 exe 位置'
    ),
    'crawl.hg.cmt.noMitmdump': (
        '[红果短剧] 找不到 mitmdump（{detail}）——安装：pip install mitmproxy（见 requirements-optional.txt）'
    ),
    'crawl.hg.cmt.needsExtras': (
        '[红果短剧] 评论收割是 Windows 桌面功能，'
        '本机缺少 {missing}（按 requirements-optional.txt 安装；云端模式不可用）'
    ),
    'crawl.hg.cmt.needsExtrasFrozen': (
        '[红果短剧] 桌面版未打包 {names}：评论收割要 mitmdump 与驱动桌面窗口的 UI Automation，只能在源码版运行该节点'
    ),
    'crawl.hg.cmt.caNotTrusted': (
        '[红果短剧] mitmproxy 根证书未受信任且自动安装未成功。手动命令（PowerShell）：{command}'
    ),
    'crawl.hg.cmt.caInstalled': '[红果短剧] 已把 mitmproxy 根证书装入当前用户受信任的根（播放器解密需要）',
    'crawl.hg.cmt.playerBusy': (
        '[红果短剧] 红果播放器已经开着且不走本工具的代理——请先关闭它，本节点会自己带代理启动播放器'
    ),
    'crawl.hg.cmt.noTraffic': (
        '[红果短剧] 等待 {seconds} 秒没有收到这一集的评论页（{title}）——播放器可能未登录、被弹窗挡住或版本过旧'
    ),
    'crawl.hg.cmt.dramaNotFound': '[红果短剧] 在播放器里搜不到这部剧：{title}',
    # Emitted per board during the search, so a drama that is absent from the client reads as
    # "working through the boards", not as a frozen window (the not-found case grinds every
    # board×scroll before dramaSkipped fires — without this line the user saw no progress).
    'crawl.hg.cmt.scanningBoard': '[红果短剧] 在《{label}》里查找《{title}》…',
    # A drama the client would not open steps aside and is named; only a run that never
    # reached what the site counted is a failure, and the node says so at the end.
    'crawl.hg.cmt.dramaSkipped': (
        '[红果短剧] 界面树始终没有唤醒，本次跳过这部剧：{title}（点一下播放器窗口后「继续」可补采）'
    ),
    # Named because the player's own feed walks away from the drama we entered: measured
    # 2026-10-20, after the first ↓ every following page belonged to the show the account had
    # been watching, and those rows would have been filed under the requested 剧名.
    'crawl.hg.cmt.feedDrifted': (
        '[红果短剧] 《{title}》走到第 {ep} 集时播放流已切到另一部剧（book {book}），'
        '该剧余下的集数不再尝试——已收的行属于所请求的剧'
    ),
    # Said from the SCREEN, not the traffic: the player prints the drama it is showing as
    # ``@剧名`` in its header. Asking that before harvesting keeps another show's comments out
    # of this table when a card click lands elsewhere or a ↓ walks off into the account's own
    # queue. The episode counter is NOT readable while the drawer is open (measured), so no
    # message here claims a position the walk cannot see.
    'crawl.hg.cmt.screenMismatch': (
        '[红果短剧] 屏幕上正在播的是《{have}》，不是所请求的《{want}》——本剧到此不再往下采'
        '（已收下的行仍属于所请求的剧；这不是搜不到，是播放器没把这部剧放在台上）'
    ),
    'crawl.hg.cmt.repliesExpanded': '[红果短剧] 已展开 {n} 处子回复',
    'crawl.hg.cmt.episodeShort': (
        '[红果短剧] 《{title}》第 {ep} 集只拿到 {have} 条，站点报 {site_total} 条——该集不完整'
    ),
    'crawl.hg.cmt.groupShort': (
        '[红果短剧] 分集 {group}（第 {ep} 集）只拿到 {have} 条，站点报 {site_total} 条——该集不完整'
    ),
    # Said because an expanded child thread prints its own total, and the walk clicks 展开 once
    # per thread: without this line a thread the site counts at 200 children and delivers 20
    # would still let the node claim the site said it was done.
    'crawl.hg.cmt.replyShort': (
        '[红果短剧] 第 {floor} 楼的子回复只收到 {have} 条，站点报 {site_total} 条——该楼子回复不完整'
    ),
    'crawl.hg.cmt.treeCold': (
        '[红果短剧] 播放器窗口已打开，但界面树迟迟没有建立（WebView2 可访问性未唤醒）。'
        '用鼠标点一下播放器窗口再重跑本节点'
    ),
    'crawl.hg.cmt.titleMissing': '[红果短剧] 详情页没有打印剧名，播放器里不知道该搜什么：{url}',
    'crawl.hg.cmt.groupMismatch': '[红果短剧] 收到的评论页属于 {got} 而不是所请求的 {want}，已丢弃',
    'crawl.platformNotCrawlable': '该平台目前只支持保存登录 Cookie，还不支持采集（{platform}）——'
    '请先改用已支持的平台，或等待该平台的抓取实现完成',
    'cookie.xiaohongshu.purpose': '解锁小红书搜索、笔记正文与评论；未登录会撞登录墙且只给首屏。',
    'cookie.xiaohongshu.steps': (
        '1. 点「浏览器生成」，在窗口里登录小红书\n2. 打开任意一篇笔记，能看到评论区即可\n3. 回到本面板点「已完成登录」'
    ),
    'cookie.twitter.purpose': (
        '解锁 X（推特）的搜索、用户时间线、推文正文与回复；未登录时这些页面基本只回一个登录引导页。'
    ),
    'cookie.twitter.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录 x.com（账号密码或手机号+验证码）\n'
        '2. 随便打开一条推文，确认回复区能加载出来（auth_token 与 ct0 两条 Cookie 缺一不可）\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：X 对新设备登录常会追加一次验证码，请在同一个窗口里做完再保存。'
    ),
    'cookie.instagram.purpose': '解锁 Instagram 的博主帖子、标签页与评论；未登录时页面只给登录墙，接口也会拒绝。',
    'cookie.instagram.steps': (
        '1. 点「浏览器生成」，在窗口里登录 instagram.com\n'
        '2. 打开任意一个帖子页，能看到评论区即可\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：若登录被转到 Facebook，请等它回到 Instagram 之后再点保存。'
    ),
    'cookie.youtube.purpose': (
        '解锁 YouTube 的订阅、播放列表、历史记录与评论；未登录也能看公开视频，但这些页面常被限流或折叠。'
    ),
    'cookie.youtube.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录 YouTube（Google 账号）\n'
        '2. 回到 youtube.com 首页，确认右上角已是你的头像\n'
        '3. 回到本面板点「已完成登录」——保存前浏览器会自动回到 YouTube 页面，'
        'Google 账号自身的 Cookie 不会被写进本平台文件'
    ),
    'cookie.entryRejected': (
        '该链接不属于 {platform} 的域名，已改用平台登录页（不允许把别的站点的 Cookie 存进本平台的 Cookie 文件）'
    ),
    'cookie.verifying': '正在用已保存的 Cookie 试探该平台…',
    'cookie.verifyFailed': '验证失败：{err}',
    'cookie.verify.ok': '{platform} 的 Cookie 可用',
    'cookie.verify.loginWall': '{platform} 仍被挡在登录页：请重新登录并保存',
    'cookie.verify.noCookie': '{platform} 还没有 Cookie：请先登录保存',
    'cookie.verify.checkedUrl': '验证地址：{url}',
    # 运行前自动验证（preflight）：三条结论对应三种下一步，合并任何一条都会把
    # 用户支到错误的动作上——重新登录，或者什么也不做地等待。
    'cookie.pre.valid': '{platform} 的 Cookie 可用',
    'cookie.pre.expired': '{platform} 的 Cookie 已失效：页面被弹回登录页',
    'cookie.pre.unknown': '{platform} 的 Cookie 无法核对（不代表有效，本次不拦截）',
    'cookie.pre.noLogin': '{platform} 的抓取不需要登录',
    'cookie.pre.notCrawlable': '{platform} 目前只能取 Cookie，还不能采集',
    'cookie.pre.account': '（账号 {account}）',
    'cookie.pre.notListed': '这个平台谁都不认识，没有验证：{platform}',
    'cookie.pre.busy': '{platform} 的浏览器正被占用',
    'cookie.pre.timeout': '验证超时（{n} 秒）',
    'cookie.pre.riskControl': '页面回的是验证码/风控',
    'cookie.verify.unclear': '{platform} 的验证没有结论：页面回的是验证码/风控，与 Cookie 是否有效无关',
    'cookie.verify.cloudHeadless': (
        '本机是无窗口的服务器：上面这次验证只能用无头浏览器完成，而部分站点对无头访问回的是验证码或空白，'
        '这不证明 Cookie 失效（要按登录态复核，请在有窗口的机器上验证）'
    ),
    # The page never came from the site at all, so nothing about the cookie was tested —
    # and 「可用」 here would be cached and reused by every later run.
    'cookie.verify.unreachable': '{platform} 无法验证：浏览器自己没能打开这个地址（本机网络或 DNS），未检验到 Cookie',
    'cookie.delete.none': '{platform} 没有已保存的 Cookie 可删除',
    'cookie.delete.profileHolds': '注意：{platform} 的浏览器 profile 仍是登录状态，删这个文件不会把它登出',
    # 保存即更新：粘贴成功的这一刻就把这份 Cookie 送进它自己的 profile，不再要用户按第二个按钮
    # （原来那个 /api/cookies/refresh-profile 与它的四句拒绝一起删掉了）。只有一种情况当场做不到——
    # 那个浏览器正被占用——而这句话必须说：「保存成功」与「这次没进到 profile」在粘贴框里长得一样。
    'cookie.plant.deferred': (
        '{platform} 的浏览器正被占用（可能有抓取在跑），这次没能更新进 profile；Cookie 已保存，下一次抓取会自动带上它'
    ),
    'cookie.refresh.failed': '更新 profile 登录态失败：打不开该平台的浏览器（{err}）',
    'cookie.refresh.done': '已把保存的 {platform} Cookie 更新进它的浏览器 profile（{n} 条）',
    # Measured: a cookie without an expiry is never written to the profile store, so it
    # dies with the window that was opened to plant it. The count is said because the
    # alternative is a promise the next restart will break.
    'cookie.refresh.sessionOnly': '其中 {n} 条没有有效期（会话 Cookie），关掉这个窗口后不会留在 profile 里',
    'cookie.delete.failed': '删除 Cookie 文件失败：{err}',
    'api.platformsRequired': 'platforms 字段必须是平台名列表',
    'api.cookieBusy': '已有 {platform} 的登录窗口打开中——请先完成或取消它',
    'api.bodyNotObject': '请求体必须是 JSON 对象',
    'api.paramInvalid': '参数 {name} 无效',
    'api.payloadTooLarge': '请求体超过上限 {limit} MB，请分割后重试',
    'api.workflowNameRequired': '缺少有效的工作流名称',
    'api.workflowMissing': '没有这个已保存的工作流：{name}',
    'api.workflowNameTaken': '已有同名工作流「{name}」，重命名会覆盖它，请换一个名字',
    'api.workflowNameSame': '新旧名字是同一个文件，没有可重命名的东西',
    'api.workflowRenamed': '工作流已重命名：{old} → {new}',
    'wfHistory.invalid': '这份画布状态存不下来：需要带 nodes 列表的对象',
    'wfHistory.labelTooLong': '快照名称超过 {n} 个字符',
    'wfHistory.workflowNameTooLong': '工作流名称超过 {n} 个字符',
    'wfHistory.unserializable': '画布里含有无法序列化的内容，不能存为快照',
    'wfHistory.full': '画布历史已满（{max} 份），请先删除旧快照再保存',
    'wfHistory.missing': '没有这个画布快照：{id}',
    'wfHistory.corrupt': '画布快照 {id} 的内容已损坏，无法恢复',
    'wfHistory.workflowRequired': '请先保存工作流，再设置布局基准',
    'wfHistory.badStrategy': '未知的自动排布策略：{strategy}',
    'wfHistory.baselineRequired': '按历史基准排布需要先指定一个快照',
    'project.noWorkflow': '请先保存一个工作流，再导出项目包',
    'project.workflowUnreadable': '工作流文件无法读取：{name}',
    'project.datasetMissing': '工作流引用的数据集不存在：{id}',
    'project.templateMissing': '引用的可复用模板不存在，已跳过：{id}',
    'project.badZip': '项目包不是有效的 zip 文件',
    'project.tooManyEntries': '项目包条目过多（上限 {max}）',
    'project.tooLarge': '项目包解压后超过 {mb} MB',
    'project.fileTooLarge': '项目包内的文件过大：{file}（上限 {mb} MB）',
    'project.badEntry': '项目包内的文件路径不合法：{file}',
    'project.entryMissing': '项目包缺少文件：{file}',
    'project.badJson': '项目包内的 JSON 无法读取：{file}',
    'project.checksum': '项目包文件校验失败：{file}',
    'project.badFormat': '不是采析绘项目包',
    'project.badVersion': '项目包版本不支持：{version}',
    'project.badManifest': '项目包清单缺少列表：{section}',
    'project.tooMany': '项目包里的 {section} 过多（上限 {max}）',
    'project.noWorkflowInBundle': '项目包里没有工作流',
    'project.datasetInvalid': '项目包里的数据集无法读取：{id}',
    'project.datasetTooLarge': '数据集 {id} 超过 {max} 行',
    'project.workflowInvalid': '项目包里的工作流无法读取：{name}',
    'project.datasetRefMissing': '工作流引用的数据集不在项目包里：{id}',
    'project.templateInvalid': '可复用模板无法导入：{name}',
    'project.templateRefMissing': '工作流「{name}」引用的模板不在项目包里：{id}（实例自带的快照仍然可用）',
    'project.lineageMissing': '引用的累积数据集不存在，已跳过：{name}',
    'project.lineageInvalid': '项目包里的累积数据集信息无法读取',
    'project.noFile': '请选择一个项目包文件',
    'compare.runMissing': '没有这次运行：{rid}',
    'compare.sameRun': '不能拿一次运行和它自己对比',
    'compare.nodeMissing': '运行 {rid} 里没有节点 {node}',
    'compare.tooManyRows': '节点 {node} 的数据超过 {max} 行，无法对比',
    'reusable.invalid': '可复用节点模板的内容无法理解',
    'reusable.nameRequired': '可复用节点需要一个名字',
    'reusable.nameTooLong': '模板名称超过 {n} 个字符',
    'reusable.descriptionTooLong': '模板说明超过 {n} 个字符',
    'reusable.noNodes': '可复用节点里至少要有一个节点',
    'reusable.tooManyNodes': '一个可复用节点最多包含 {n} 个节点',
    'reusable.badNode': '模板里有无法理解的节点',
    'reusable.badNodeId': '节点 id 缺失或重复：{id}',
    'reusable.badNodeType': '节点 {id} 的类型不能放进可复用节点：{type}',
    'reusable.badNodeParams': '节点 {id} 的参数不是对象',
    'reusable.badConnections': '模板里的连线无法理解',
    'reusable.badConnection': '连线两端不是模板内的节点：{a} → {b}',
    'reusable.cycle': '模板里存在环，无法按顺序执行',
    'reusable.badInputs': '模板的输入槽列表无法理解',
    'reusable.badInput': '输入槽指向一个不存在的节点：{id}',
    'reusable.badOutputs': '模板的输出槽列表无法理解',
    'reusable.badOutput': '输出槽指向一个不存在的节点：{id}',
    'reusable.oneOutput': '可复用节点必须恰好有一个输出节点（现在有 {n} 个）',
    'reusable.outputHasNext': '输出节点 {id} 还有后续节点，请选择真正的末端节点',
    'reusable.nameTaken': '已有同名可复用模板「{name}」',
    'reusable.full': '可复用模板已达上限（{max} 个），请先删除旧模板',
    'reusable.corrupt': '可复用模板 {id} 的内容已损坏',
    'reusable.missing': '没有这个可复用模板：{id}',
    'reusable.badId': '可复用模板 id 形状不对：{id}',
    'reusable.noTemplateForRun': '可复用节点「{name}」没有可运行的模板',
    'reusable.badTemplate': '可复用节点「{name}」的模板无法展开（节点类型或连线不被接受）',
    'reusable.tooManyInputs': '可复用节点「{name}」的外部连线比输入槽多',
    'reusable.missingInputs': '可复用节点「{name}」需要 {n} 个输入，当前只接了 {wired} 个',
    'api.fieldTypeInvalid': '字段 {name} 类型不正确',
    'api.stepsMustBeObjects': 'steps 必须是对象列表，每项含 "op" 与可选 "params"',
    'api.noCookieJob': '当前没有进行中的登录窗口',
    'cookie.deleted': '已删除 {platform} 的 Cookie',
    'cookie.deletedAccount': '已删除 {platform}（账号：{account}）的 Cookie',
    'cookie.renamed': '已把 {platform} 的登录改名：{old} → {new}（Cookie 文件与浏览器目录一起搬）',
    'cookie.renamedFileOnly': '已把 {platform} 的登录改名：{old} → {new}（该账号还没开过浏览器，只动了文件）',
    'cookie.profileDeleted': '已删除 {platform} · {account} 的浏览器 Profile（该设备已登出；Cookie 文件不动）',
    'cookie.profileDelete.none': '{platform} · {account} 没有可删除的浏览器 Profile',
    'store.workflow_saved': '工作流已保存：{path}',
    'store.dataset_saved': '文件已持久化：{name}（{rows} 行，id {did}）',
    'store.datasets_bound': '工作流 {wf} 已绑定 {n} 个上传文件',
    'ds.corrupt': '数据集 {did} 读不出来（记录已损坏），请重新上传',
    'ds.lineage_name_required': '累积数据集需要一个名字',
    'ds.lineage_identity': '未知的去重方式：{value}（只能是整行或指定列）',
    'ds.lineage_keys_required': '按列去重时必须填写去重列',
    'ds.lineage_key_missing': '去重列不在表中：{cols}',
    'ds.lineage_columns': '累积数据集「{name}」的列与已有版本不一致：多出 {extra}；缺少 {missing}',
    'ds.lineage_too_large': '累积数据集「{name}」将达 {n} 行，超过上限 {max}',
    'ds.lineage_current_missing': '累积数据集「{name}」的当前版本 {id} 不存在',
    'ds.lineage_missing_dataset': '导入累积数据集时找不到数据集 {id}',
    'accumulate.done': '累积数据集「{name}」：新增 {added} 行，当前共 {total} 行（版本 {version}）',
    'engine.accumulate_no_name': '节点 {nid}：累积数据集节点还没有填名字',
    'engine.accumulate_bad_identity': '节点 {nid}：未知的去重方式 {value}',
    'engine.accumulate_no_keys': '节点 {nid}：按列去重时必须填写去重列',
    'engine.accumulate_one_parent': '节点 {nid}：累积数据集节点必须恰好有一个上游',
    'engine.accumulate_bad_parent': '节点 {nid}：累积数据集的上游 {up} 不是表格节点',
    'engine.watermarkUnsupported': '节点 {nid}：跨运行水位只支持哔哩哔哩作者投稿',
    'engine.watermarkRecrawl': '节点 {nid}：跨运行水位与「重新采集」不能同时开启',
    'node.accumulate': '累积数据集',
    'ds.purged': '已清理 {days} 天未使用且无工作流引用的文件：{n} 个',
    'ds.purge_result': '清理孤立文件 {n} 个，保留 {kept} 个仍在使用的文件',
    'ds.cleared': '已清空全部已保存文件：{n} 个',
    'ds.clearBusy': '正在运行的那次可能正在读取这些数据集，请先停止或等它跑完再清空',
    'ds.rebound': '按文件名重新接上数据集 {name}（{did}）——工作流可以直接跑了',
    'ds.missing': '工作流引用的上传文件已不在库中：{name}',
    'api.datasetMissing': '没有这个已保存的数据集：{did}',
    'api.datasetNameInvalid': '这个名称不能用作数据集名（去掉路径字符后为空）：{name}',
    'lex.unknownKind': '未知的词库类型：{kind}',
    'lex.needTerms': '请至少提供一个词。',
    'lex.userdictReadFailed': '读取用户词库失败，分词器保持不变。',
    'lex.userdictLoadFailed': '加载 jieba 用户词典失败。',
    'api.lineageMissing': '没有这个累积数据集：{name}',
    'api.datasetInLineage': (
        '这份文件是累积数据集「{name}」的当前版本；删除会让累积历史断开（强制删除会同时重置该累积集）'
    ),
    'api.datasetInUse': '这些已保存的工作流仍在引用该文件，删除后它们会变成空数据源：{workflows}',
    'api.datasetTooBig': '文件太大没法存：{err}',
    'api.diffTwoSources': '对比需要两个数据源（"a" 与 "b"），每个是 dataset_id 或 node_id+workflow_name 或内联 data',
    'api.diffKeyMissing': '对比键「{name}」不是两份表都有的列，无法据此匹配行',
    'api.diffKeyNotUnique': '对比键「{name}」在某份表里有重复值，无法唯一对应每一行',
    'data.mergeNeedTwo': '合并至少需要两个数据集',
    'data.mergeMissing': '要合并的数据集不存在：{id}',
    'data.mergeNameRequired': '合并结果需要一个名字',
    'data.mergeNameTooLong': '合并结果的名字超过 {n} 个字符',
    'data.mergeColumns': '数据集「{name}」的列与第一份不一致：多出 {extra}；缺少 {missing}',
    'data.mergeTooLarge': '合并后共 {n} 行，超过上限 {max}',
    'history.recorded': '「{wf}」已记录 {n} 条历史指标',
    'history.run_deleted': '执行历史：删除运行 {rid} 的 {n} 条记录',
    'executor.task_failed': '任务失败：{err}',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': '记录执行历史失败（不影响流程）',
    'misc.save_workflow_failed': '保存工作流失败',
    'misc.i18nAudit': '文本目录有问题（不影响运行，但请修复）：{issue}',
    'misc.exportDeleteFailed': '无法删除导出文件 {name}：{err}',
    'misc.cookie_save_failed': '保存 Cookie 失败: {err}',
    'misc.cookie_gen_failed': '生成 Cookie 失败: {err}',
    'misc.studio_source_failed': '图表工坊合并载入：来源读取失败',
    'misc.source_probe_failed': '数据源探测失败',
    'misc.studio_saved': '图表工坊已保存 {path}（{bytes} 字节）',
    'misc.chartPdfSaved': '图表 PDF 已生成：{name}（{bytes} 字节）',
    'misc.browser_open_failed': '无法打开浏览器：{err}',
    'misc.browserNotFound': '这台机器没有可接住地址的默认浏览器，请手动打开：{url}',
    'misc.cloudNoBrowser': '云端模式不会尝试打开浏览器（服务器上没有浏览器可开）；请在自己机器上访问：{url}',
    'misc.server_starting': '爬虫工作流服务启动，端口 {port}',
    'misc.consoleUtf8': ('本机的控制台编码 {streams} 写不出汉字，已改为 UTF-8（每个流只改一次，日志不会再因此丢行）'),
    'misc.visualize_failed': '图表渲染失败：{err}',
    'misc.export_failed': '导出文件写入失败',
    # ── 爬虫内部的调试信息 ────────────────────────────────────
    # 这些走 logging.debug，默认级别下不打印；仍走 i18n，别让控制台里
    # 混进写死的中文/英文。
    'crawl.cookies_failed': '{platform}：载入 Cookies 失败（{err}），本次爬取可能因未登录而结果为空',
    'crawl.xhs.untitled': '无标题',
    'crawl.debug.title_missing': '未找到标题元素',
    'crawl.debug.content_missing': '未找到正文元素',
    'crawl.debug.author_missing': '未找到作者/公众号元素',
    'crawl.debug.time_missing': '未找到发布时间元素',
    'crawl.debug.comments_missing': '评论区域未加载或不存在',
    'crawl.debug.comment_item': '第 {i} 条评论：{author} - {text}...',
    'crawl.debug.card_skip': '卡片 {i}：跳过（无发布者）',
    'crawl.debug.card_author': '卡片 {i}：发布者="{v}"',
    'crawl.debug.card_time': '卡片 {i}：发布时间="{v}"',
    'crawl.debug.card_len': '卡片 {i}：正文长度={v}',
    'crawl.debug.card_metrics': '卡片 {i}：转发={f} 评论={c} 点赞={l}',
    'crawl.debug.card_images': '卡片 {i}：图片={n} 张',
    'crawl.debug.pager_missing': '未检测到分页按钮，只有一页',
    'crawl.debug.content_retry': '正文未提取到，稍后重试一次',
    # ── 参数校验 / 接口错误（会直接显示在提示条里） ────────────
    'crawl.weibo.bad_date': '日期格式不对：{value}（应为 YYYY-MM-DD）',
    'crawl.weibo.need_both_dates': '开始时间与结束时间必须同时填写（只填一个会被忽略，搜索范围会完全不同）',
    'crawl.weibo.bad_range': '结束时间（{end}）必须晚于开始时间（{start}）',
    'chart.count': '数量',
    'chart.noRunData': '尚无运行数据，请先运行一次工作流。',
    # Chart display labels — the column tokens the tool emits and the category values it can
    # group by. These localize ONLY at render time (the stored column names are unchanged), so
    # a Chinese run prints 发帖量 while an English run prints Total; unknown values pass through.
    'chart.col.total': '发帖量',
    'chart.col.sentiment_index': '情感指数',
    'chart.col.sentiment': '情感',
    'chart.col.prevalence_pct': '主题占比(%)',
    'chart.col.doc_n': '主题文档数',
    'chart.col.feature_words': '特征词',
    'chart.col.topic': '主题',
    'chart.col.score': '得分',
    'chart.col.weights': '权重',
    'chart.col.period': '时期',
    'chart.col.intensity': '强度',
    'chart.col.term': '词语',
    'chart.col.overall_freq': '总体词频',
    'chart.col.within_freq': '主题内词频',
    'chart.col.sample_texts': '样本帖',
    'chart.col.share': '占比 (%)',
    'chart.col.positive_pct': '积极占比',
    'chart.col.neutral_pct': '中性占比',
    'chart.col.negative_pct': '消极占比',
    'latex.done': '已生成 LaTeX 图：{file}',
    'latex.table_done': '已生成 LaTeX 三线表：{file}',
    'latex.failed': 'LaTeX 生成失败：{reason}',
    'chart.value.positive': '正面',
    'chart.value.negative': '负面',
    'chart.value.neutral': '中性',
    'chart.col.emotion': '情绪',
    'chart.col.tendency': '倾向',
    'chart.col.confidence': '置信度',
    'chart.col.tendency_confidence': '倾向置信度',
    'chart.col.aggression_score': '暴力评分',
    'chart.value.anger': '愤怒',
    'chart.value.fear': '恐惧',
    'chart.value.joy': '快乐',
    'chart.value.sadness': '悲伤',
    'chart.value.surprise': '惊讶',
    'chart.value.tendency_objective': '客观陈述',
    'chart.value.tendency_praise': '赞扬/肯定',
    'chart.value.tendency_criticism': '批评/质疑',
    'chart.value.tendency_controversy': '争议/反思',
    'chart.value.tendency_advocacy': '倡议/呼吁',
    'chart.value.tendency_satire': '讽刺/嘲讽',
    'chart.series.topics': '主题',
    'chart.axis.pc1': '第一主坐标',
    'chart.axis.pc2': '第二主坐标',
    'chart.range.high': '高',
    'chart.range.low': '低',
    'ml.no_training_rows': '没有可用的训练数据：所有行的文本或标签都是空的',
    'ml.need_two_labels': '训练至少需要 2 个不同的标签，当前只有：{label}',
    'ml.bad_model_name': '模型名「{name}」不合法：必须是单个路径安全的组件，不含分隔符',
    'cluster.no_features': '文本无法分词（可能只有符号），已跳过聚类：{err}',
    'engine.source_no_platform': '节点 {nid}：数据源节点没有选择平台',
    'engine.source_unknown_platform': '节点 {nid}：{platform} 还没有可用的采集实现，请改用已支持的平台',
    'engine.source_unknown_mode': '节点 {nid}：{platform} 没有这种采集内容，请在该节点的「采集内容」里改选一种',
    'engine.source_missing': '节点 {nid}：必填项「{field}」还没有填写',
    'engine.source_bad_option': '节点 {nid}：「{field}」没有「{value}」这个选项，请在该节点的下拉里改选一个',
    'engine.source_no_cookie_account': (
        '节点 {nid}：{platform} 的账号「{account}」没有可用的 Cookie——请先到 Cookie 面板为该账号保存一份，'
        '或在该节点改用已有 Cookie 的账号（不会借用别的账号登录，也不会静默少采）'
    ),
    'engine.source_link_mismatch': '节点 {nid}：{n} 个链接与所选平台（{platform}）不符',
    'engine.source_needs_machine': '节点 {nid}：这台机器跑不了这种采集（{reason}），请换采集内容或在能跑的机器上运行',
    'engine.source_bad_backend': '节点 {nid}：采集方式「{backend}」不存在，请改用 Selenium 或 CatBus',
    'engine.source_catbus': '节点 {nid}：CatBus 引擎无法采集这一项：{detail}',
    'catbus.noRunnableCell': 'CatBus 对这个平台没有任何可运行的读功能',
    'cap.requiresWindowsDesktop': '需要 Windows 桌面版：该模式要在本机驱动播放器或窗口',
    # Feeding a link mode from an upstream table column: the wire is allowed only where
    # the matrix declares a feed (Field.fed_by), and every mismatch is refused BY NAME —
    # a wired-but-unfed crawl would silently re-crawl the pasted list the user thinks
    # they replaced, and a fed crawl with no wire would read a table that is not there.
    'engine.source_feed_no_mode': (
        '节点 {nid}：这种采集内容不接受上游表格，逐行喂送只支持「链接列表」类表单，请断开这条连线或改选采集内容'
    ),
    'engine.source_feed_no_column': '节点 {nid}：已连接上游表格，但没有填写「{field}」要逐行读取的列名',
    'engine.source_feed_no_input': ('节点 {nid}：填写了上游列名，但该节点没有连接任何数据表（标注用的「名称」线不算）'),
    'source.feed_column_missing': '节点 {nid}：上游表格没有名为「{col}」的列',
    'source.feed_skipped': '上游喂送：跳过 {n} 个空单元格（没有可读的链接）',
    'field.keyword': '关键词',
    'field.urls': '文章链接',
    'field.author': '作者',
    'field.board': '榜单',
    'field.account': '登录账号',
    'field.backend': '采集方式',
    'field.catbusAccount': 'CatBus 账号',
    'field.catbusRoom': '直播间',
    'field.catbusFolder': '收藏夹',
    'field.catbusSeries': '合集',
    'field.catbusConversation': '会话 ID',
    'field.catbusProduct': '商品',
    'field.catbusCommentId': '评论 ID',
    'field.format': '格式',
    'engine.upload_no_file': '节点 {nid}：上传节点还没有选择文件',
    'engine.comment_no_urls': '节点 {nid}：评论节点还没有填写文章链接',
    # The supported list is generated from the comment router's own domain table,
    # because that table is what actually decides the answer — naming the platforms
    # in the sentence left two messages that kept claiming the old four long after
    # the fifth landed.
    'comment.no_urls': '评论节点没有可抓取的链接（支持：{platforms}）',
    'comment.unsupported': '评论节点忽略了 {n} 个不支持的链接（仅支持：{platforms}）',
    # Named because a count of dropped 「links」 sends the user hunting for a typo in a URL,
    # when what the node actually lacks is the platform that declared it takes plain names.
    'comment.unsupportedNames': '其中 {n} 行不是链接而是名称：按名称喂入需节点先选定平台'
    '（红果短剧 的「评论」模式按剧名走播放器自己的榜单）',
    'comment.noAdapter': '{platform} 还没有评论抓取实现，该链接无法处理：{url}',
    'comment.commentsClosed': '该内容未开放评论区（或未产生评论）：{url}',
    'comment.ytNoPage': 'YouTube 页面没有加载成视频页（可能需要登录或被拦截）：{url}',
    'comment.xNoList': '[X 评论] 这条推文页面没有渲染出任何内容（链接失效、被删或被拦截）：{url}',
    # YouTube is crawled as JSON from inside its own page, so its console lines
    # talk about rounds and answers, not about scrolling a list.
    'crawl.yt.noContext': '[YouTube] 页面未提供 innertube 配置（被拦截或结构已变）：{url}',
    'crawl.yt.callFailed': '[YouTube] {endpoint} 接口调用失败',
    'crawl.yt.badAnswer': '[YouTube] {endpoint} 返回 {status}，非 JSON',
    'crawl.yt.wall': '[YouTube] 触发了人机验证页：{url}',
    'crawl.yt.searchStart': '[YouTube] 关键词「{kw}」，目标 {n} 条',
    'crawl.yt.authorStart': '[YouTube] 作者「{author}」的作品，目标 {n} 条',
    'crawl.yt.authorEmpty': '[YouTube] 没有填写作者（@handle、频道链接或 UC… ID）：{author}',
    'crawl.yt.authorNotFound': '[YouTube] 该地址不是频道主页，读不到频道 ID：{author}',
    'crawl.yt.authorNoVideos': '[YouTube] 该作者的视频页没有作品：{author}',
    'crawl.yt.page': '[YouTube] 第 {page} 轮：{n} 条（{fresh} 条新增，已采 {done}）',
    'crawl.yt.noPage': '[YouTube] 第 {page} 轮没有返回条目，停止翻页',
    'crawl.yt.processed': '[YouTube] 已存第 {i} 条：{title}',
    'crawl.yt.targetReached': '[YouTube] 已达目标 {n} 条，停止采集',
    'crawl.yt.drained': '[YouTube] 接口不再给出下一页游标，列表已到末尾',
    'crawl.yt.replay': '[YouTube] 第 {page} 轮没有新增，判定列表已耗尽',
    'crawl.yt.noResults': '[YouTube] 关键词「{kw}」没有匹配的公开视频（或本次会话被限制）',
    'crawl.yt.finished': '[YouTube] 本次共采集 {n} 条（目标 {total} 条）',
    # X（推特）只渲染一个虚拟列表：卡片数不增长而推文一直换血，所以它的日志说
    # 「留住了多少」，不说「页面上有几张卡」。
    'crawl.x.start': '[X] 关键词「{kw}」，目标 {n} 条（最新优先）',
    'crawl.x.target_reached': '[X] 已达目标 {n} 条，停止滚动',
    'crawl.x.authorStart': '[X] 作者「{author}」的推文，目标 {n} 条',
    'crawl.x.authorEmpty': '[X] 没有填写作者（@handle 或主页链接）：{author}',
    'crawl.x.wall': '[X] 被拒绝访问（登录墙或 403）：{url}',
    'crawl.x.loadSlow': '[X] 页面未在预期时间内加载完，已按当前 DOM 继续：{url}',
    'crawl.x.no_cards': '[X] 时间线里一条推文都没有渲染出来（被拦截、关键词过窄或账号无推文）：{url}',
    'crawl.x.finished': '[X] 共保留 {n} 条（结束原因：{reason}）',
    'comment.biliBadAnswer': '哔哩哔哩评论接口未返回数据（code={code}）：{url}',
    'comment.biliShort': '[B站评论] 游标收到 {rows} 条，站点标注 {declared} 条（匿名深翻页被限流）：{url}',
    'comment.dyNoId': '链接里没有视频 ID，无法抓评论：{url}',
    'comment.dyNoPanel': '评论区没有渲染出来（可能被折叠或需要登录）：{url}',
    'comment.dyGone': '[抖音评论] 站点把这条链接换成了另一条视频（{shown}），这条按失效处理：{url}',
    'comment.dyNone': '该视频计有 {n} 条评论，页面未展开评论列表：{url}',
    'comment.dyShort': (
        '[抖音评论] {url}：站点写着 {declared} 条，本表 {rows} 条 + 子回复 {nested} 条（还差 {gap} 条未采到）'
        ' —— 本次收尾原因是「{reason}」，所以差额不是「这条视频就这么多」'
    ),
    'comment.weiboShowFailed': '[微博评论] 评论接口取不回来（Cookie 可能失效或被限流）：{url}',
    'comment.weiboReplay': (
        '[微博评论] 第 {page} 页没有交出新的一条（游标仍在动）：按「站点在重复同一批」收工，本次 {rows} 条'
    ),
    'comment.weiboShort': (
        '[微博评论] 站点写着 {declared} 条，本表只有 {rows} 条（差 {gap} 条）'
        '—— 差额是楼中楼：这个接口在当前会话里不整批返回子评论，只有父行自带的那条预览已入表'
    ),
    'comment.weiboFetchDied': (
        '[微博评论] 第 {page} 页评论接口取数失败，就此收尾：本次 {rows} 条'
        '（站点标注 {declared} 条，差额 {gap} 条未采到；游标停在失败的那一页，可继续）'
    ),
    'comment.zhihuNoPanels': '[知乎评论] 这个回答页面上没有评论面板（可能已关闭或未加载）：{url}',
    'comment.zhihuNoAuthor': '[知乎评论] 本轮 {total} 条里有 {n} 条在自己的子树内没有作者链接（匿名或被折叠）',
    'comment.zhihuPanelCapped': '[知乎评论] 滚满 {n} 轮（含展开子回复）仍未走完，按轮次上限收工（本次 {rows} 条）',
    'comment.zhihuRound': '[知乎评论] 第 {r} 轮新增 {n} 条（累计 {total}）',
    'comment.zhihuPanelShort': '[知乎评论] 页面写着 {declared} 条，本次取到 {rows} 条（差额未采到）',
    'comment.xhsPanelCapped': '[小红书评论] 滚满 {rounds} 轮仍未走完，按轮次上限收工（本次 {rows} 条）：{url}',
    'comment.prefix': '[评论]',
    'comment.platformMismatch': '已忽略 {n} 个与所选平台（{platform}）不符的链接',
    'comment.allMismatched': '所有链接都与所选平台（{platform}）不符，请检查文章链接',
    'comment.article': '评论：{url} 新增 {n} 条（{status}）',
    'comment.done': (
        '评论采集完成：{urls} 个链接（正常 {ok}、拦截 {blocked}、失效 {dead}），共 {rows} 条评论，输出 {files} 个文件'
    ),
    'comment.status.ok': '正常',
    'comment.status.blocked': '被登录墙/风控拦截',
    'comment.status.dead': '链接不可读',
    'engine.process_no_op': '节点 {nid}：处理节点没有选择操作',
    'engine.output_no_op': '节点 {nid}：输出节点没有选择操作',
    'engine.output_no_upstream': '节点 {nid}：输出节点没有任何上游连线，没有可保存的表格',
    'engine.output_no_table': (
        '节点 {nid}：输出节点的上游都不产出表格（命名节点只是元数据，可视化节点产出的是图表配置）'
    ),
    'engine.output_needs_pdf': '节点 {nid}：上游是可视化/编译节点时，输出格式必须为 PDF',
    'engine.output_pdf_mixed': '节点 {nid}：PDF 输出不能与表格类上游混接（请只用可视化或编译节点作上游）',
    'engine.output_pdf_only_pdfable': '节点 {nid}：PDF 输出的上游必须是可视化节点或编译节点',
    'engine.output_pdf_two_sources': '节点 {nid}：PDF 输出不能同时接可视化节点与编译节点（二选一）',
    'engine.compile_no_upstream': '节点 {nid}：编译节点没有上游连线（需要连接可视化节点）',
    'engine.compile_bad_parent': '节点 {nid}：编译节点只能接收可视化节点的 LaTeX，上游「{up}」不是可视化节点',
    'engine.compile_source_both_off': (
        '节点 {nid}：上游可视化「{up}」的 LaTeX 图与三线表复选框都没勾选，编译节点无内容可编'
    ),
    'engine.analysis_no_op': '节点 {nid}：分析节点没有配置操作或步骤',
    'engine.cycle': '工作流存在环，以下节点无法排序：{nodes}',
    # A wire whose end is not on the canvas is not a cycle. Reporting it as one
    # (with an empty node list, which is what the old code produced) sent users
    # hunting a loop that did not exist.
    'engine.dangling_connection': '连线指向画布上不存在的节点：{src} → {dst}',
    # An empty canvas is refused, never "completed": 0/0 nodes with a 已完成 toast
    # reads as a run that worked.
    'engine.empty_canvas': '画布上没有任何节点，没有可运行的工作流',
    'engine.unknown_node_type': '节点 {nid}：未知的节点类型「{type}」，工作流引擎无法执行它',
    'engine.tokenize_no_column': '节点 {nid}：分词节点缺少文本列',
    'engine.visualize_no_chart': '节点 {nid}：可视化节点没有选择图表类型',
    'engine.visualize_no_x': '节点 {nid}：可视化节点缺少 X 字段',
    'engine.name_no_label': '节点 {nid}：命名节点的工作流名称不能为空',
    'engine.name_not_head': '节点 {nid}：命名节点必须打头，不能有上游节点接入',
    'engine.name_no_downstream': '节点 {nid}：命名节点后面必须连接下游节点',
    'wf.unknown_process_op': '使用了未知操作「{op}」',
    'wf.join_no_right_table': '合并表需要两条上游连线：第一条是左表，第二条是右表',
    'analysis.join_no_right': '合并失败：没有拿到右表数据（请把第二条连线接到作为右表的节点）',
    'analysis.join_need_keys': '合并失败：请填写左右两边的关联列',
    'analysis.join_missing_cols': '合并失败：这些列不存在：{cols}',
    'api.alreadyRunning': '已有工作流正在运行，请先停止或等它跑完',
    'api.needConfirm': '这个操作会动到全部记录，请把 confirm 显式设为 true 再来',
    'api.foreignOriginRefused': '本站只服务本机浏览器：这个请求来自「{origin}」，未鉴权又握着真实账号，故拒绝',
    'api.killNoIdent': '没有给出线程 ID',
    'api.killNotFound': '找不到该线程',
    'api.killProtected': '不能结束受保护的线程：{name}',
    'api.killLiveWorker': '这是正在运行的采集线程，请点「停止」而不是强杀它',
    'api.killNotAlive': '该线程已不存活',
    'api.killInvalidId': '无效的线程 ID',
    'api.killFailedGeneric': '结束线程失败',
    'api.killDone': '线程「{name}」已结束',
    # Two bulk deletions, each naming what it destroyed. The claims figure is not decoration:
    # 清空运行记录 also hands back the "已采集" ledger, so the next crawl really will re-fetch
    # what an earlier one collected — a user who reads 「清空了 3 条」 and then watches the same
    # workflow crawl twice as much needs this line to know why.
    'run.cleared': '已清空运行记录：{runs} 条，并交回 {claims} 条"已采集"认领（这些条目下次会重新爬）',
    'exports.cleared': '已清空导出目录：删除 {n} 个文件',
    'exports.notAPart': '「{name}」不是分片文件（形如 名称.part000.csv），无法按名字清除它这一批',
    'exports.clearBusy': '正在运行的那次会把分片文件写进导出目录，请先停止或等它跑完再清空',
    'lock.refuse': '这一项已被锁定，请先解锁再删除/清空它',
    'lock.badKey': '锁定请求缺少有效的面板或条目名',
    'api.needApiKey': 'OpenRouter API Key 未填写（设置 → AI）',
    'api.needModel': 'OpenRouter 模型未选择（设置 → AI）',
    'api.needOllamaModel': '未选择 Ollama 模型（设置 → AI → 模型，可点“刷新”读取本地模型）',
    'api.cloudNoLocalModel': (
        '这台服务器没有本地模型可连（「{provider}」需要宿主自己跑一个 Ollama 守护进程）：'
        '云端部署只支持 OpenRouter，请在「设置 → AI」里改选 OpenRouter 并填入模型与 API Key'
    ),
    'api.cloudNoLoginWindow': (
        '这台服务器没有可以登录的窗口：请在「Cookie」面板里粘贴 Cookies JSON 保存，'
        '系统会在保存时替该账号建好 Profile 并种进去'
    ),
    'api.platformRequired': '平台不能为空',
    'api.cookiesRequired': 'Cookies 数据不能为空',
    'api.unsupportedPlatform': '不支持的平台：{platform}',
    'api.badAccount': '账号名不合法：{account}（字母、数字、下划线或连字符，1-24 个；统一按小写保存）',
    'api.cookieRenameEmptyTarget': '新名字不能留空',
    'api.cookieRenameBadName': '新名字不合法：字母、数字、下划线或连字符，1-24 个（统一按小写保存）',
    'api.cookieRenameDefault': '默认账号不能改名：它的浏览器目录就是该平台目录本身，其它账号都装在里面',
    'api.cookieRenameSameName': '新旧名字一样，没有改任何东西',
    'api.cookieRenameNoSource': '这个账号没有已保存的登录，改不了名',
    'api.cookieRenameTaken': '这个名字已经有另一份登录了，换一个个别的名字',
    'api.cookieRenameBusy': '这个账号的浏览器正在被占用，请等当前采集结束后再改名',
    'api.cookieRenameFailed': '改名失败：{err}',
    'api.profileDeleteBadName': '账号名不合法，无法定位要删除的 Profile：{account}',
    'api.profileDeleteDefault': '默认账号没有可删除的浏览器 Profile：它的数据就是平台目录本身，其它账号都在里面',
    'api.profileDeleteBusy': '{platform} · {account} 的浏览器正在被占用，请等当前采集结束后再删除它的 Profile',
    'api.llmModelsFailed': '获取 OpenRouter 模型列表失败：{err}',
    'api.ollamaModelsFailed': '读取本地 Ollama 模型列表失败：{host}（请确认 ollama 已启动、服务地址正确）：{err}',
    'api.parseFailed': '文件解析失败：{err}',
    'api.unsupportedUpload': '不支持的文件类型：{name}（可用 .csv .tsv .json .txt .xlsx .xls）',
    'api.excelMultiSheet': '工作簿「{name}」有多个非空工作表（{sheets}），一次只能导入一张表，请先拆成单个表再上传',
    'api.columnMissing': '数据里没有这一列：{column}',
    'api.needLabeledRows': '至少需要 10 行带标签的数据，当前只有 {n} 行',
    'api.noSourceTable': '所选节点都没有可用的数据表',
    'api.badRequest': '请求格式不对：{what}',
    'api.svgNotSvg': 'SVG 保存被拒：内容不是以 <svg 开头或缺少 xmlns 声明',
    'api.svgTruncated': 'SVG 保存被拒：文件没有以 </svg> 结束（可能被截断）',
    'api.svgRefused': 'SVG 保存被拒：图中含有 {found}，这类标记可能带脚本或外部引用',
    'api.svgTooLarge': 'SVG 保存被拒：内容 {cap} 字节已是上限，这不像是画出来的图',
    'api.pdfNeedsName': 'PDF 生成被拒：请给出该图已登记的 LaTeX 文件名',
    'api.pdfUnregistered': 'PDF 生成被拒：{name} 不在运行台账里，本程序没写过这个文件，不交给 xelatex 编译',
    'api.pdfWrongKind': 'PDF 生成被拒：{kind} 不是 LaTeX 源文件，只有本程序登记的 .txt 图源可以编译',
    'api.pdfMissingFile': 'PDF 生成被拒：台账记着 {name}，但导出目录里已找不到它（可能被清除）',
    # ── 运行时设置校验 ────────────────────────────────────────
    'set.driverMissing': '驱动文件不存在：{path}',
    'set.driverEmpty': '驱动路径为空：将由 Selenium 自动取与当前 Chrome 匹配的驱动（首次需要联网）',
    'set.browserMissing': '浏览器程序不存在：{path}',
    'set.latexMissing': 'LaTeX 编译程序（xelatex）不存在：{path}',
    'set.harvestMissing': '红果收割组件（{tool}）不是已存在的文件：{path}',
    # The two CatBus paths are accepted as either a file or a CatBus checkout directory, so the
    # warning says which of the two complaints it is, and names the setting the box belongs to.
    'set.catbusMissing': 'CatBus 组件（{tool}）在该位置不存在：{path}',
    'set.catbusNeedFile': '{tool} 要填可执行程序本身，不是它所在的目录：{path}',
    'set.badWindow': '窗口大小格式应为 宽x高（如 1920x1080），已恢复默认 {default}',
    'set.badNumber': '{setting} 不是数字，已恢复默认 {value}',
    'set.outOfRange': '{setting} 超出范围 {lo}-{hi}，已恢复默认 {value}',
    'set.badOllamaHost': 'Ollama 地址需以 http:// 或 https:// 开头，已恢复默认',
    'set.badFlag': '{setting} 需要 true/false 值，已恢复默认',
    'set.badProfileDir': '浏览器 Profile 目录必须填绝对路径（收到：{value}），已恢复为内置目录',
    'set.saveFailed': '设置未能写入磁盘（本次会话内仍生效）：{err}',
    # ── 断点续跑（durable run state） ────────────────────────
    'run.row_limit': '节点 {nid} 已达到保存上限 {limit} 行，超出部分不再落库',
    'run.interrupted_by_restart': '服务重启时被打断',
    'run.interrupted_by_dead_worker': '执行线程已不在，记录自动判定为中断',
    'run.promoted': '发现 {n} 条上次没跑完的记录，已标记为「可续跑」',
    'run.claims_released': '重跑节点：已归还 {n} 条「已采集」认领（运行 {rid}），这些条目会重新采',
    'run.reconciled': '发现 {n} 条线程已结束却没写下结论的记录，已判定为「已中断」',
    'run.recordWriteFailed': '记录 {rid} 的结论没能写进数据库（{err}）：运行记录会在下次刷新时自动补上判定',
    'run.start_failed': '运行线程启动失败（{err}）：本次运行已放弃，队列继续处理下一个',
    'run.nodeStopped': '节点 {nid} 已按「停止」结束：本次保留 {n} 行',
    'run.finished.stopped': '，{n} 个被停止',
    'crawl.chromeMissing': (
        '本机没有可用的 Chrome，采集打不开浏览器。安装 Chrome，'
        '或在「设置 → 浏览器路径」里指向它（本系统的可执行名：{browser}）'
    ),
    'crawl.browserBinaryMissing': '设置里的浏览器路径不存在：{path}。改正它，或清空让程序自己找 Chrome',
    'crawl.disguiseUnreadable': (
        '无头浏览器的伪装没有生效：读不到自己的 User-Agent（{err}）。'
        '这次将以「裸无头」继续，部分站点会给出一张没有内容的空页'
    ),
    'crawl.disguisePartial': (
        '无头浏览器的伪装只应用了一部分（{err}）。这次可能仍以无头指纹被站点识别，行数偏少时先按这条排查'
    ),
    'crawl.driverMissing': (
        '设置里的 chromedriver 路径不存在：{path}。'
        '它多半是与当前 Chrome 版本不匹配而失效了：换成匹配的驱动，'
        '或清空该设置让 Selenium 自己取（首次需要联网）'
    ),
    'crawl.browserStartFailed': (
        '浏览器没有启动：{err}。常见原因是 chromedriver 与 Chrome 版本不匹配、'
        '首次自动取驱动需要联网、或该 Chrome 配置目录正被另一个 Chrome 占用'
    ),
    'crawl.stopped': '收到「停止」，本次抓取到此为止',
    # Said by a session whose browser process was already reaped, so it must not claim a person did
    # anything: the same object answers a cookie window that was closed after its grace ran out.
    'crawl.driverDead': '这个浏览器进程已经关掉了，不再向它发送命令',
    'run.started': '本次运行已记账：{rid}（随时可中断，数据逐条落库）',
    'run.resume_from': '续跑模式：接着 {at} 那次往下跑，此前已保存 {rows} 行',
    'run.restored': '节点 {nid} 沿用上次结果（{n} 行），不再重跑',
    'run.resume_crawl': '节点 {nid} 从上次中断处继续抓取（已有 {have} 行）',
    'run.heavy_result': '内存提示：节点「{nid}」产出 {n} 行，运行结束前每个节点的这份结果都留在内存里',
    'comment.need_both': '节点 {nid}：按评论时间筛选必须同时给出开始和结束时间（半个区间无法界定范围）',
    'comment.bad_date': '节点 {nid}：评论时间筛选的日期无法解析（请用 YYYY-MM-DD）',
    'comment.bad_range': '节点 {nid}：评论时间筛选的结束时间早于开始时间',
    'comment.time_filtered': '节点 {nid}：按评论时间 {start} ~ {end} 筛选，保留 {kept} 条、丢弃 {dropped} 条',
    'run.recrawl': '重新采集：已释放 {n} 条历史去重记录，本节点将重新抓取',
    'run.dedupe_skipped': '增量采集：{n} 条结果此前已采集，本次被跳过（如需重抓请在采集节点开启「重新采集」）',
    'run.watermarkUnsupported': '跨运行水位只支持哔哩哔哩作者投稿（当前平台/模式：{platform} / {mode}）',
    'run.watermarkNoScope': '跨运行水位需要运行上下文里的节点指纹；直接调用执行器时不能启用',
    'run.watermarkLoaded': '跨运行水位：从上次完成的边界 {boundary} 开始，遇到它即停止',
    'run.watermarkFirst': '跨运行水位：这是第一次运行，完成后保存边界',
    'run.watermarkSaved': '跨运行水位已更新：{boundary}（本次新采 {n} 条）',
    'run.watermarkNoNew': '已到上次的边界 {boundary}，本次没有更新的条目',
    'run.dedupe_all_skipped': (
        '本节点的结果此前已全部采集，本次没有新数据传给下游；'
        '要重抓请在采集节点开启「重新采集」，要用旧数据请从运行记录导出或用断点续跑（Resume）节点续接'
    ),
    'run.progress_file': '分批导出：{file}（{rows} 行，共 {parts} 个分批文件）',
    'run.live_export': '实时导出：{file}（每处理完一批刷新一次，运行结束后保留）',
    'run.live_export_failed': '实时导出写入失败：{err}',
    'run.cookieExpired': (
        '登录态疑似失效：{platform} 的抓取被挡回登录页（COOKIE 可能过期）。'
        '已采集的数据全部保留——请到 设置→Cookie 更新后，用断点续跑从上次中断处继续'
    ),
    'run.cookieExpiredOk': '提示：{platform} 在目标达成后才遇到登录墙，本次数据完整，无需续跑',
    # A 风控 refusal is the OPPOSITE advice from a dead cookie: the session may be fine and
    # re-running straight into it only deepens the block, so the console names 风控, says it
    # is not a login problem, and tells the user to wait (继续 later), never to re-save.
    'run.riskControlled': (
        '{platform} 被安全验证（风控）拦下，本次未能采满——这不是登录态失效，请勿立刻重跑（立即再撞只会加重风控）。'
        '已采集的数据全部保留；可先开启 设置→慢速采集，稍后用「继续」从断点补采'
    ),
    # U1: a crawl that came back under its target WITHOUT naming a licensed end (the site
    # said it ran out, a wall, risk, or the user's 停止) is a real under-collect, not a
    # success — so it is refused BY NAME and kept resumable, never settled clean DONE.
    # The walk funnel rides on the line because "refused N of M" is what separates "the
    # site had no more" from "our scraper dropped what it got" (§6's silent-under-collect).
    'run.underTargetShort': (
        '{platform} 采到 {have}/{want} 条就停了，却没说站点自己到底了——这不是「采完了」。'
        '已保留 {have} 行，可点「继续」从断点补剩下的{walk}'
    ),
    # The funnel clause only when the crawler reported counts; a convicted short without
    # them omits it, rather than printing a fake measurement of zeros.
    'run.underTargetWalk': '（走查：扫 {scanned}、留 {kept}、拒 {refused}）',
    # Named because a feed of ten dramas that opened six is not a completed comment crawl;
    # the rows the six yielded stay in the table (the user chose 保留), and these four are
    # what 继续 still owes.
    'run.commentsSkipped': (
        '{platform} 有 {n} 部剧没有采完（没能进入播放器，或播放流中途切到了别的剧）：{names}——'
        '其余剧的行已保留；点「继续」会回到第一部未采完的剧起重走'
        '（已入库的评论按 评论ID 去重，不会重复入库）'
    ),
    # Said out loud because the alternative is silence that reads as "closed", while the
    # user may be looking at the window that is still open.
    'run.browserStuck': (
        '警告：{platform} 的浏览器关不掉（读不到它的进程号），它可能仍然开着，并会占用该平台目录最多 {seconds} 秒'
    ),
    # A page that never arrived, said once with the one thing the crawler cannot know:
    # whether this machine can reach anything at all. ``{advice}`` is left empty when the
    # page already named its own cause, so the sentence must read in both shapes.
    'run.pagePending': '{page}{streak}{advice}',
    'run.pageStreak': '；这已是本机连续第 {n} 次没有拿到页面',
    'net.region': '。诊断：本机目前到不了该平台所在的那一侧网络（对照主机不通，另一端正常）——请换网络后重跑',
    'net.offline': '。诊断：本机当前连不上任何外网（两个对照主机都不通），请先恢复网络再跑',
    'net.blocked': '。诊断：本机出网正常，但该平台的主机连不上，可能是站点故障或本地拦截',
    'net.slow': '。诊断：两侧网络都能连通，因此没有依据判断这一页为什么没到；可以再跑一次，或按停止结束',
    'net.speed': '（实测下载约 {speed} kB/s）',
    # Only for a comment node whose links came from several platforms and whose own
    # platform field is empty — the message must name what walled, and a hand-written
    # list of platforms the user never crawled reads worse than no list at all.
    'run.cookieAnyPlatform': '所采集的平台',
    'run.platformQueued': (
        '{platform} 正在被另一条工作流采集，本轮改为排队：{n} 秒后开始，'
        '避免同一账号在同一秒内发出两次搜索而被弹到登录页'
    ),
    'run.serialForced': (
        '{platform} 的多条采集强制排队串行执行：同一账号并行翻页必被弹回登录页，'
        '这个平台的串行由站点决定，与错峰设置无关'
    ),
    'run.platformStaggered': (
        '{platform} 与上一条同平台采集错开 {n} 秒后发车：这次没有排队，两条仍可能同时跑，'
        '只是避开同一账号一秒内发出两次搜索'
    ),
    'run.platformGateTimeout': '{platform} 等待采集时段超时（{n} 秒）：可能有浏览器窗口没有关闭',
    'run.queueAbandoned': '{platform} 的排队等待已取消（本次运行已停止）',
    'run.wallRetry': ('{platform} 在第一条数据之前就被弹到登录页，这更像同一账号被两次并发搜索撞了：{n} 秒后重试一次'),
    'crawl.profile_wait': '已排队 {seconds} 秒：这个 profile 同时只能开一个浏览器，{dir}',
    'run.profileOff': '本次执行不使用浏览器 Profile：每次都是全新设备（为让同平台的工作流真并行），Cookie 快照照常导入',
    'run.skippedWorkflows': '本次跳过（已禁用，不参与运行）：{names}',
    'crawl.profile_stuck': (
        '等待 profile 释放超时（{seconds} 秒）：{dir} —— 可能有浏览器没被关闭，请在进程面板结束残留的 Chrome 后重试'
    ),
    'crawl.profile_gave_up': '本次运行已停止：不再等待该 profile（{dir}），这次采集就此让路',
    'run.notCrawlable': (
        '「{label}」所在的平台（{platform}）目前只能保存登录 Cookie，还没有采集实现，'
        '因此不能作为数据源运行——请改用已支持的平台，或等该平台的抓取落地'
    ),
    'run.partial_down': '节点 {nid} 中断：已把 {n} 行已完成的结果交给下游',
    'run.failed_down': '节点 {nid} 失败且没有可用数据，下游按空表继续',
    'run.skipped_empty': '节点 {nid} 跳过：上游没有数据',
    'run.finished': '运行结束（{done}/{total} 个节点完成）',
    # Fragments appended to the line above, only when they are true: a run whose
    # numbers are all clean reads as one clean sentence rather than a table of
    # zeroes, while a run that starved or lost a node cannot be mistaken for one.
    'run.finished.skipped': '，{n} 个跳过',
    'run.finished.failed': '，{n} 个失败',
    'run.rejected': '未运行：工作流有 {n} 处问题，见上方提示',
    'resume.no_run': '续跑节点：没有选择运行记录，也没找到可续跑的记录',
    'resume.empty': '续跑节点：运行 {rid} 中「{nid}」没有可读取的数据行',
    'resume.unpicked': '未指定节点',
    'resume.loaded': '续跑节点：载入运行 {rid} 中节点 {nid} 的 {n} 行',
    'api.runNotFound': '找不到运行记录：{rid}',
    'api.runSettingOption': '画布设置里的「{setting}」没有「{value}」这个取值（可用：{allowed}）',
    'api.runLogTruncated': '（日志过长，仅下载前 {n} 行）',
    'api.exportNotFound': '导出文件不存在（或不允许下载）：{name}',
    # ── 一键报告（自包含 HTML） ───────────────────────────────
    'report.generated': '生成时间',
    'report.default_title': '{name} · 运行报告',
    'report.summary': '本次运行共 {nodes} 个节点，产出 {rows} 行数据，其中 {tables} 个节点有表格。',
    'report.charts': '图表',
    'report.run_facts': '运行信息',
    'report.tables': '数据表',
    'report.conclusion': '结论',
    'report.no_charts': '这些数据还不足以出图。',
    'report.chart_failed': '图表生成失败：{err}',
    'report.chartsFailed': '报告中的图表生成失败，正文与表格照常输出',
    'report.no_rows': '这个节点没有产出任何行。',
    'report.more_rows': '以上为前 {shown} 行，共 {total} 行；完整数据请用导出节点另存 CSV。',
    'report.method_section': '方法',
    'report.figure_section': '图表',
    'report.table_suffix': '（三线表）',
    'report.table_continued': '（续）',
    'report.method_biblio': '{title}：以{entity}为分析单元。参数（本系统内部枚举名，与运行记录及导出表一致）：{body}。',
    'report.method_fuse': '{title}：把多张上游表折叠为一份规范记录表（角色按候选列顺序尝试）。',
    'report.method_analysis': '{title}：分析步骤 {ops}。',
    'report.method_source': '{title}：采集 {platform} 的 {collect}，目标 {target} 条。',
    'report.method_upload': '{title}：数据集 {name}。',
    'report.method_unverified': '以下节点的参数无法与运行记录的指纹核对（画布已改动或文件已不在）：{names}。',
    'report.method_no_canvas': '本次运行没有可读取的已保存画布，因此下表只给出运行编号与时间窗，不给参数；'
    '需要方法段落请先保存画布再运行。',
    'report.method_provenance': '本稿由工作流「{workflow}」的一次运行自动合成，运行编号 {run_id}。',
    'report.method_window': '运行区间：{started} 至 {finished}。',
    'report.method_counts': '共 {figures} 张图、{tables} 张三线表；每张图与其表格来自同一次运行登记的同一份行表。',
    'report.missing_charts': '另有 {count} 个可视化节点没有登记 LaTeX 源，本稿不含它们的图与表：{names}。',
    'report.latex_no_run': '找不到这次运行（{rid}），无法合成成稿。',
    'report.latex_no_sources': '这次运行没有登记任何 LaTeX 图源或三线表，无法合成成稿：'
    '请在可视化节点勾选「生成 LaTeX」后重跑。',
    'report.row_count': '{n} 行 · {cols} 列',
    'report.fact.workflow': '工作流',
    'report.fact.run': '运行编号',
    'report.fact.status': '状态',
    'report.fact.started': '开始',
    'report.fact.finished': '结束',
    'api.reportNoData': '没有可写入报告的数据：请先运行一次工作流，或选择一条运行记录',
    # ── 运行队列 ──────────────────────────────────────────────
    'api.queued': '已排队：当前运行结束后自动开始（第 {at} 位）',
    'api.queueFull': '排队已满（最多 {n} 个），请等当前运行结束或先取消几个',
    'run.queued': '已排队（第 {at} 位）：{name}',
    'run.queuedUnnamed': '未命名工作流',
    'run.queue_started': '队列接续：{name} 开始运行（{rid}）',
    'run.queue_waited': '队列接续失败（已有运行在跑），{name} 重新排队',
    'run.queue_broken': '队列里的 {name} 无法启动，已跳过并继续下一个：{err}',
    'run.queue_restored': '重启后恢复了 {n} 个待运行任务',
    'run.queueMirrorFailed': '写入待运行队列镜像失败（内存队列仍是权威，不受影响）',
    'run.queueLoadFailed': '重启读取待运行队列镜像失败（本轮从空队列开始）',
    'run.queueStartFailed': '排队的运行无法启动',
    'run.browserReapFailed': (
        '停止超时后仍未终止这个浏览器进程（PID {pid}）：{err}——它的窗口配置目录会一直被占着，'
        '该平台下一次采集要等到锁超时'
    ),
    'history.cleared': '执行历史已清空',
    'api.workflowShapeInvalid': '工作流内容无法理解：需要带 nodes 列表的对象',
    'api.workflowNodeNoId': (
        '画布上有一个节点没有 id，无法运行（id 是节点的存储键）——请重新拖入该节点，或修复工作流文件'
    ),
    'api.resumeMissing': '无法继续：运行记录 {rid} 已被清理，继续会变成一次全新的从零采集，请改用「重新运行」',
    'api.rerunNoRun': '找不到这个工作流已保存的运行结果，无法从该节点重跑（请先运行一次）',
    'api.rerunNoNode': '当前画布里没有节点「{node}」，无从重跑',
    'api.rerunNoRows': '节点「{node}」在上次运行里没有可用的完成结果，无从重跑',
    'api.rerunRunLive': '该运行仍在进行中（或正在停止），不能重跑它的节点——请等它跑完或先停止它',
    'api.rerunBusy': '另一个运行仍在进行中：重跑会先删掉这部分已存结果，请等它跑完再重试',
    'api.rerunFingerprintMismatch': '画布与所选运行记录不是同一份工作流，无法复用其结果，请从运行详情重跑该节点',
    'api.historyNoRunId': '没有指定运行 ID，未删除任何执行历史',
    'run.store_unavailable': '本次运行无法开始：运行记录库打不开（磁盘满、文件损坏或被占用），未产生任何记录',
    'run.reportSaved': '报告已生成：{name}（{size} 字节）',
    'run.reportFailed': '报告生成失败：{err}',
    'run.reportConclusionFailed': '结论生成失败，报告已省略结论：{err}',
    'run.reportLatexSaved': '论文成稿已编译：{name}（{figures} 张图 / {tables} 张三线表）',
    'run.reportLatexFailed': '论文成稿失败：{err}',
    'run.compileSaved': 'PDF 已编译：{name}（{size} 字节）',
    'run.compileFailed': 'LaTeX 编译失败：{err}',
    'api.compilePdfFailed': 'LaTeX 编译为 PDF 失败：{err}',
    'api.compilePdfNoPackage': 'LaTeX 缺宏包 {package}.sty：{remedy}',
    'api.compilePdfNoFont': 'LaTeX 找不到字体 {font}：{remedy}',
    # ── 自动清理（housekeeping） ──────────────────────────────
    'housekeeping.done': (
        '自动清理：删除 {runs} 条过期运行记录、{files} 个孤立文件（另回收 {cache} 条模型缓存、{seen} 条去重记录）'
    ),
    'housekeeping.runStoreFailed': '运行记录自动清理失败（不影响本次运行）',
    'housekeeping.datasetStoreFailed': '孤立文件自动清理失败（不影响本次运行）',
    # Why a crawl walk stopped, said to the user (engine/feed.py and engine/pager.py return the
    # machine token; stop_reason_label() maps it to one of these).
    'crawl.stopReason.target': '达到目标条数',
    'crawl.stopReason.end': '已到列表末尾',
    'crawl.stopReason.no_new': '翻了几页都没有新条目',
    'crawl.stopReason.stuck': '连续滚动没有新内容出现',
    'crawl.stopReason.no_cards': '页面没有渲染出列表',
    'crawl.stopReason.empty_page': '某一页是空的',
    'crawl.stopReason.fetch_failed': '列表接口取数失败',
    'crawl.stopReason.stopped': '用户停止了运行',
    'crawl.stopReason.wall': '登录墙拦住了后面的窗口',
    'crawl.stopReason.risk': '站点风控拦住了后面的窗口（不是 Cookie 失效）',
    'crawl.stopReason.unreachable': '浏览器根本没取到页面（网络或域名不可达，站点从未见到这个会话）',
    # ── 定时任务（scheduler.py / services/schedule_store.py / services/cron.py）──────
    # A scheduled run has no browser request behind it, so its refusals are read in the task's own
    # history and in the form — never in a console nobody is watching at 03:00.
    'sched.notWired': '调度器没有接线（这是服务端启动顺序的问题，不是这条任务的问题）',
    'sched.badTask': '这条任务不是一个对象，无法保存',
    'sched.nameRequired': '请给这条定时任务起个名字',
    'sched.nameTooLong': '名字最多 {n} 个字符',
    'sched.workflowRequired': '请选择要定时运行的画布',
    'sched.canvasMissing': '找不到画布「{name}」（文件被改名或删除了）',
    'sched.canvasNeedsModel': '画布「{name}」里有需要模型的步骤，定时任务不碰模型（模型凭证只在浏览器里）',
    'sched.canvasReadFailed': '读取画布「{name}」时出错，已跳过这条任务',
    'sched.taskMissing': '找不到这条定时任务：{id}',
    'sched.storeUnreadable': '定时任务文件读不出来，已改名为 .corrupt 保留：{path}',
    'sched.badTrigger': '不认识的触发方式：{kind}',
    'sched.badClock': '时间要写成 HH:MM（例如 08:30），收到的是「{at}」',
    'sched.badWeekday': '星期要选周一至周日，收到的是「{value}」',
    'sched.badInterval': '间隔要在 1 到 {hi} 分钟之间，收到的是「{value}」',
    'sched.badTimezone': '不认识的时区：{name}（要写 IANA 名称，例如 Asia/Shanghai；留空表示服务器本地时区）',
    'sched.neverFires': '这个时间规则永远不会触发：{expr}',
    'sched.cronMinute': '分钟',
    'sched.cronHour': '小时',
    'sched.cronDay': '日期',
    'sched.cronMonth': '月份',
    'sched.cronWeekday': '星期',
    'sched.cronBadCount': 'cron 表达式要 5 段（分 时 日 月 周），收到 {n} 段：{expr}',
    'sched.cronBadField': '{field} 段看不懂：{value}',
    'sched.cronBadRange': '{field} 段的区间写反了：{value}',
    'sched.cronBadStep': '{field} 段的步长要是 1 以上的整数：{value}',
    'sched.cronBadStepBase': '{field} 段的「/」只能跟在 * 或 a-b 后面：{value}',
    'sched.cronOutOfRange': '{field} 段超出范围（{lo}-{hi}）：{value}',
    'sched.weekday1': '周一',
    'sched.weekday2': '周二',
    'sched.weekday3': '周三',
    'sched.weekday4': '周四',
    'sched.weekday5': '周五',
    'sched.weekday6': '周六',
    'sched.weekday7': '周日',
    'sched.zoneLocal': '服务器本地',
    'sched.everyDay': '每天 {at}',
    'sched.everyWeek': '每{weekday} {at}',
    'sched.everyMinutes': '每 {n} 分钟',
    'sched.cronAt': 'cron：{expr}',
    'sched.fired': '定时任务「{name}」到点，已开始运行',
    'sched.firedManual': '定时任务「{name}」被手动触发，已开始运行',
    'sched.startFailed': '定时任务「{name}」启动失败，已记入它的历史',
    'sched.missedLine': '定时任务「{name}」错过了一次触发（服务没在运行），已跳过并重排',
    'sched.tickFailed': '定时任务调度出错（这次的检查跳过了，下次照常）',
    # 第二采集后端 CatBus（services/catbus_bridge.py）：每一句都点名缺的是哪一样。
    # 一个读不到的答案不能变成空表，因为节点会在空表上判定完成。
    'catbus.noNode': '这台机器上没有 Node 运行时，CatBus 后端因此不可用（可用 CIXI_NODE_BIN 指定）',
    'catbus.noCli': (
        '这台机器有 Node，但找不到 CatBus 的采析绘适配器（可用 CIXI_CATBUS_CLI 指定文件，'
        '或用 CATBUS_HOME 指定它的源码目录）'
    ),
    'catbus.oldNode': 'CatBus 不接受这个 Node：{node} 报告 {version}（需要 22.22.2／24.15.0／26.0.0 以上）',
    'catbus.probeFailed': 'CatBus 适配器没能给出能力清单：{detail}',
    'catbus.probeUnreadable': 'CatBus 适配器返回的不是能读的答案：{detail}',
    'catbus.notInManifest': 'CatBus 的清单里没有 {platform} / {mode} 这一格，不能用它采',
    'catbus.timeout': 'CatBus 超过 {seconds} 秒没有返回，进程已被终止',
    'catbus.stopped': '{platform} / {mode} 已通过 CatBus 停止，已经落库的行保留',
    'catbus.columnDrift': 'CatBus 返回的列与能力清单不一致：缺少 {missing}，多出 {extra}',
    'catbus.noDetail': 'CatBus 后端不单独取详情（详情由适配器逐条补齐）：{url}',
    'catbus.targetReached': '目标 {n} 条已经在表里，CatBus 不再请求',
    'catbus.start': 'CatBus 开始采集：{mode}，目标 {n} 条',
    'catbus.startOnce': 'CatBus 开始执行：{mode}',
    'catbus.watermarkNote': 'CatBus 没有偏移量：水位线只界定哪些行入库，更旧的条目仍会被请求一次',
    'catbus.watermarkHit': 'CatBus 采到水位线 {i}，更旧的条目不再入库',
    'catbus.finished': 'CatBus 采集结束：本次新增 {n} 条（目标 {want}）',
    'catbus.finishedOnce': 'CatBus 执行结束：{mode}，本次新增 {n} 条',
    'catbus.warning': 'CatBus 报告：{text}',
    'catbus.refused': '{platform} / {mode} 通过 CatBus 采集失败：{detail}',
    'catbus.noIdentity': '{platform} / {mode} 的 CatBus 适配没有声明身份列，跨运行水位无法界定边界，因此拒绝',
    'catbus.paramUnsupported': (
        'CatBus 的 {platform} / {mode} 不接受这些采集条件：{params}。适配器会忽略它们，'
        '而一张看起来执行过条件的表比拒绝更糟——请改用 Selenium，或在设置里去掉这些条件'
    ),
    'catbus.pre.login': '{platform} 在 CatBus 里没有登录态',
}

_EN = {
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] Executing node: {nid} ({ntype})',
    'wf.node_failed': '[{wf}] Node {nid} failed: {err}',
    'wf.unnamed': 'Unnamed workflow {i}',
    'wf.node_completed': '[{wf}] Node {nid} completed ({done}/{total})',
    'wf.multi_input': (
        'Node {nid} has {n} incoming connections — the first (from {up}) is the primary input; '
        'an analysis node uses the second as its right-hand table, and an output node merges them all into one'
    ),
    'wf.merge_not_tabular': (
        'Node {nid}: upstream "{up}" produces no table (a chart spec or a refusal), so it cannot be merged — '
        'disconnect that wire or point it at a node that carries rows'
    ),
    'wf.compile_no_source': (
        'The compile node has no LaTeX to compile (its upstream visualize produced neither a figure nor a table)'
    ),
    'wf.merge_columns': (
        'Node {nid}: the upstream tables have different columns, compared with "{up}": extra [{extra}], '
        'missing [{missing}]. Not merged as an outer join — that fabricates empty cells and the file looks complete'
    ),
    'wf.merge_done': 'Node {nid} merged {tables} upstream tables → {n} rows ({detail})',
    'wf.merge_detail_sep': ', ',
    'wf.merge_table_detail': '{name} {n} rows',
    'wf.validation_error': 'Validation error: {err}',
    'wf.found': 'Found {n} workflow(s)',
    'wf.starting': 'Starting workflow "{name}"',
    'wf.component_indexed': '{name} (component {i} of {n})',
    # No 'wf.completed' / 'wf.all_completed' here either: see the zh block.
    # One line per failure, and it says where the detail is: the log handler
    # forwards every logger call to the console, so the pair of messages this
    # replaced printed the same sentence twice.
    'wf.exec_exception': 'Execution failed — the traceback is in the server log',
    'wf.wf_exception': 'Workflow "{wf}" failed — the traceback is in the server log',
    # Stated as the reason only: the executor prints these as the node's own
    # failure (「Node X failed: …」), so a "Tokenize failed:" prefix inside them
    # repeats the wrapper, and the pair used to print the same sentence twice —
    # once here with no node named, once attributed.
    'wf.analysis_step': '[Analysis] {op}: {before} -> {after} rows',
    'wf.analysis_steps_shape': '"steps" must be a LIST of steps (one object each), and this is a single object',
    'wf.analysis_llm_no_model': (
        'the 主题概括 step needs a model, and this run has none (Settings → model, or the node model box)'
    ),
    'wf.analysis_step_removed': ' (-{removed})',
    'wf.analysis_step_nochange': ' (no change)',
    'wf.tokenize_no_column': 'no text column is configured for tokenizing',
    'wf.tokenize_no_input': 'no upstream data — connect a data source or an upload node',
    'wf.tokenize_no_col': 'column "{col}" not found in {cols}',
    'wf.tokenize_done': '[Tokenize] {mode} segmented {col} -> {n} rows',
    'wf.visualize_no_input': 'no upstream data — connect a data source or an upload node',
    'wf.visualize_done': '[Visualize] Rendered {chart} chart ({engine}) from {n} rows',
    'wf.browser_opened': 'Browser opened for {platform} login ({url}); waiting {n}s for the user to log in',
    'wf.cookies_generated': 'Cookies generated for {platform} ({n} cookies)',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API key is missing',
    'llm.no_model': 'OpenRouter model name is missing',
    'llm.ollama_pkg_missing': 'ollama package unavailable: {err}',
    'llm.ollama_empty': 'Ollama returned empty content',
    'llm.ollama_fail_attempt': 'Ollama call failed (attempt {i}/{n}): {err}',
    'llm.ollama_exception': 'Ollama call error (attempt {i}/{n}): {err}',
    'llm.ollama_failed': 'Ollama ({model}) call failed: {err}',
    'llm.no_ollama_model': 'No Ollama model set (AI → Model — hit Refresh to list what the daemon has)',
    'llm.ollama_unreachable': 'Cannot reach the Ollama server at {host} — is ollama running? {err}',
    'llm.ollama_client_failed': 'Could not create the Ollama client for {host}: {err}',
    'llm.ollama_model_missing': 'Ollama has no local model "{model}" — pick a pulled one in the panel ({err})',
    'llm.ollama_http': 'Ollama rejected the request ({code}): {err}',
    'llm.net_error': 'Network error: {err}',
    'llm.or_net_exception': 'OpenRouter network error (attempt {i}/{n}): {err}',
    'llm.or_bad_format': 'OpenRouter response malformed: {err}',
    'llm.or_empty': 'OpenRouter returned empty content',
    'llm.or_401': 'OpenRouter: invalid API key (401) — check the key',
    'llm.or_402': 'OpenRouter: out of credit (402) — free models need none, pick a :free model',
    'llm.or_404': 'OpenRouter: model not found (404) — "{model}", pick another one',
    'llm.or_429': 'OpenRouter: rate limited (429) — free models share a quota, lower the concurrency',
    'llm.or_429_wait': 'OpenRouter 429 rate limit (attempt {i}/{n}), waiting {wait}s',
    'llm.or_5xx': 'OpenRouter server error ({code})',
    'llm.or_5xx_attempt': 'OpenRouter {code} (attempt {i}/{n})',
    'llm.or_http_fail': 'OpenRouter request failed ({code}): {body}',
    'llm.or_failed': 'OpenRouter call failed',
    'llm.checkpoint_loaded': 'Checkpoint: loaded {n} finished rows ({file})',
    'llm.cancelled': 'Stopped manually — completed rows are saved; re-run resumes from the checkpoint',
    'llm.parse_failed': '[{label}] Row {i}/{total}: output could not be parsed ({f} in a row)',
    'llm.row_exception': '[{label}] Row processing error: {err}',
    'llm.row_done': '[{label}] row {done}/{total} done',
    'llm.progress': '[{label}] Progress {done}/{total} (saved)',
    'llm.circuit_break': '{f} rows failed in a row — network down / invalid key / model unavailable. '
    'This node is aborted. {done}/{total} rows are finished and saved; re-running resumes from '
    'the checkpoint and only refills the rest.',
    'llm.node_done': '[{label}] Node finished {done}/{total} rows',
    'llm.missing_column': (
        'DataFrame is missing the required column "{col}" — the {label} node failed; check its text-column setting'
    ),
    'llm.no_rows': '[{label}] Nothing to process (column "{col}" is empty).',
    'llm.start': '[{label}] {total} rows queued via {transport} (one request per row — longer text costs more tokens)',
    'llm.aborted': '[{label}] {done} finished rows are saved',
    'llm.stopped': '[{label}] stopped; finished rows are saved',
    'llm.unfinished': '[{label}] {n} rows not processed (marked {mark}). Re-running this node resumes from '
    'the checkpoint and fills only those.',
    # ── upload node ───────────────────────────────────────────
    'upload.no_file': 'Upload node has no file yet — upload a CSV / JSON / TXT in its settings',
    'upload.stale': 'That uploaded dataset is gone (the server may have restarted) — upload the file again',
    'upload.loaded': 'Loaded uploaded file {name}: {n} rows',
    # ── bibliometrics / knowledge graph ───────────────────────
    'biblio.entity.keyword': 'Keyword',
    'biblio.entity.author': 'Author',
    'biblio.entity.institution': 'Institution',
    'biblio.entity.country': 'Country/Region',
    'biblio.entity.term': 'Term',
    'biblio.entity.category': 'Category',
    'biblio.entity.journal': 'Source journal (coupling)',
    'biblio.entity.source': 'Source (journal coupling)',
    'biblio.entity.funder': 'Funder/Grant',
    'biblio.entity.grant': 'Grant (funder)',
    'biblio.entity.document_cocitation': 'Document co-citation',
    'biblio.entity.author_cocitation': 'Author co-citation',
    'biblio.entity.journal_cocitation': 'Journal co-citation',
    'biblio.entity.article': 'Cited article',
    'biblio.entity.document': 'Document (coupling)',
    'biblio.entity.bibliographic_coupling': 'Bibliographic coupling',
    'biblio.bad_option': '{nid}: {param} = "{value}" is not valid (allowed: {allowed})',
    'biblio.time_range': '{nid}: invalid time range: {start} > {end}',
    'biblio.coupling_no_burst': (
        '{nid}: bibliographic-coupling nodes are the citing papers themselves; burst detection has no meaning '
        'there — turn burst off'
    ),
    'biblio.column_missing': 'Bibliometrics needs the "{col}" column ({entity}); this table has no such column',
    'biblio.refs_missing': (
        '{type} needs cited references: at least 2 【参考文献】 entries per record. CNKI RefWorks usually has none — '
        'use a CSSCI export instead'
    ),
    'biblio.refs_low_rate': 'Reference parse rate {rate} is below {floor}; a citation graph cannot be built reliably',
    'biblio.refs_field_low': '{field} parse rate {rate} is below {floor}; a citation graph cannot be built reliably',
    'biblio.citation_expansion_done': (
        'Citation expansion depth={depth}: added {added} parseable references from records in this table'
    ),
    'biblio.no_records': 'No usable bibliographic records: check that the year column is parseable',
    'biblio.no_records_in_range': 'No records in {start}–{end}',
    'biblio.year_missing': '{n} records have no year and were skipped (time slicing needs a year)',
    'biblio.records_skipped': '{n} records had no analysable entity and were skipped',
    'biblio.wide_ref_skipped': (
        '{n} references were cited by more than {cap} papers; their pairwise links were skipped '
        '(a giant clique would bury the graph)'
    ),
    'biblio.mst_done': 'MST pruning ({scope}): {before} → {after} edges',
    'biblio.pruning_scope.slices': 'per slice',
    'biblio.pruning_scope.merged': 'merged network',
    'biblio.pfnet_depth_all': 'unlimited',
    'biblio.pfnet_done': (
        'Pathfinder pruning ({scope}, r={r}, longest indirect path {lmax} links, keep fraction {dmax}): '
        '{before} → {after} edges ({units} networks)'
    ),
    'biblio.pfnet_refused': (
        'Pathfinder compares every link against the best indirect path between its endpoints: {nodes} nodes × '
        '{levels} levels is about {work} operations, above the {limit} budget. Lower top_n or pathfinder_lmax, '
        'or prune with MST instead (at r=∞ with unlimited depth the two are the same graph, and this build '
        'takes that fast path automatically)'
    ),
    'biblio.betweenness_sampled': 'More than {n} nodes; betweenness uses {k} sampled sources',
    'biblio.eigen_failed': (
        'Eigenvector centrality did not converge; normalized weighted degree (0–1) was used and printed'
    ),
    'biblio.burst_done': 'Burst detection: {nodes}/{total} nodes have a burst',
    'biblio.burst_truncated': (
        'The node table marks only the strongest {kept}/{total} bursts (burst_top controls the chart; '
        'the full burst table is still in the CSV artifact)'
    ),
    'biblio.cluster_too_many': (
        'Node count {n} exceeds the spectral-clustering cap ({cap}): narrow TopN/the time range, or turn clustering off'
    ),
    'biblio.label_fallback': (
        'Cluster-label method {asked} had no usable text; {used} was used and is named in the run summary'
    ),
    'biblio.no_edges': (
        'No co-occurrence edges in {start}–{end}: lower the threshold, widen the time range, or choose another entity'
    ),
    'biblio.no_edges_after_prune': '{pruning} pruning left no edges: lower max links per node or use none',
    'biblio.no_edges_after_threshold': (
        'The (c, cc, ccv) thresholds left no edges: lower cc/ccv or widen the time range'
    ),
    'biblio.no_edges_after_component': (
        'Keeping the largest connected component left no edges: disable it or lower the threshold'
    ),
    'biblio.largest_component': (
        'Kept the largest connected component: nodes {before} → {after}; smaller components were removed'
    ),
    'biblio.shape_needs_cluster': '{nid}: output_shape clusters needs clustering enabled; enable it or use nodes/edges',
    'biblio.shape_needs_burst': (
        '{nid}: output_shape bursts needs burst detection enabled; enable it or use nodes/edges'
    ),
    'biblio.shape_needs_variation': (
        '{nid}: output_shape variation needs structural-variation detection enabled; enable it or use another shape'
    ),
    'biblio.counting_no_coupling': (
        '{nid}: in a coupling network ({entity}) the two citing documents ARE the endpoints of the link, so there '
        'is no third document whose credit could be split — fractional counting does not apply; use full counting '
        'or a co-citation / co-occurrence node type'
    ),
    'biblio.counting_fractional': (
        'Fractional counting: each document spreads one unit of credit over the entities it carries '
        '({docs} documents contributed)'
    ),
    'biblio.variation_needs_slices': (
        'Structural variation compares consecutive slices, and this run has only {n} slice to compare '
        '(narrow slice_years or widen the year range)'
    ),
    'biblio.variation_no_coupling': (
        'Structural variation needs a network sliced by year: in a coupling network ({entity}) a link belongs to '
        'two citing papers rather than to one year, so there is no slice-to-slice change to measure'
    ),
    'biblio.variation_done': 'Structural variation: {rows} rows (highest {node} {pair} = {score} bits, floor {floor})',
    'biblio.variation_empty': (
        'Structural variation: no node moved its connection pattern by {floor} bits between consecutive slices'
    ),
    'biblio.overlay_no_labels': (
        'Column "{col}" holds no labels at all ({n} records are blank), so nothing can be overlaid — '
        'check that the upstream sentiment/emotion/topic step really wrote this column'
    ),
    'biblio.overlay_partial': (
        'Column "{col}": {n} of {total} records carry no label and are left out of the overlay '
        '(the denominator is labelled documents only)'
    ),
    'biblio.overlay_no_nodes': 'Column "{col}" has labels, but no surviving node carries one; '
    'the overlay columns are empty',
    'biblio.dual_map_needs_basemap': '{nid}: output_shape dual_map needs a journal-category basemap dataset',
    'biblio.dual_map_columns': (
        'The dual-map basemap needs a journal column ({journal}) and a category column ({category})'
    ),
    'biblio.dual_map_done': 'Dual map built: {journals} journals / {categories} categories',
    'biblio.isolates_dropped': '{n} isolated nodes had no edge after graph construction and were removed',
    'biblio.aliases_applied': 'Alias merge: {n} node labels were normalized by the user mapping',
    'biblio.exclusions_applied': 'Exclusion list: {n} node labels were removed by the user setting',
    'biblio.cluster_labels_applied': 'Manual cluster labels applied: {n}',
    'biblio.cluster_label_unmatched': 'Cluster {cluster}: this run has no such cluster, that line did nothing',
    'biblio.cluster_labels_need_cluster': '{nid}: manual cluster labels without clustering; enable it or clear the box',
    'biblio.watch_needs_project': '{nid}: a watch baseline or capture name without a project; '
    'name the project or clear both',
    'biblio.watch_needs_entity_table': '{nid}: monitoring needs a one-row-per-entity output shape; '
    '{shape} rows are not entities',
    'biblio.watch_empty': '{nid}: this network has no nodes and no links, so there is nothing to watch '
    '(an empty capture would report every entity as gone next time)',
    'biblio.watch_baseline_missing': '{nid}: no capture named "{label}" in the watch project (known: {known})',
    'biblio.watch_project_note': 'created automatically by cross-run bibliometric monitoring',
    'biblio.watch_project_created': '[watch] project "{name}" did not exist, so it was created '
    '(this run is its first capture)',
    'biblio.watch_first_done': '[watch] filed "{label}" in "{project}": {nodes} nodes / {edges} links; '
    'nothing older to compare with',
    'biblio.watch_done': '[watch] "{project}": "{baseline}" → "{label}", {detail} '
    '(at most {limit} names per category; totals in brackets)',
    'biblio.watch_unchanged': '[watch] identical to the baseline ({nodes} nodes / {edges} links): '
    'that is what a run with no new upstream data looks like',
    'biblio.watch_params_differ': '[watch] {n} parameter(s) differ from the baseline ({names}) — '
    'rule out an edited node before reading this as the field moving',
    'biblio.watch_shape_differs': '[watch] the baseline is a {a} table and this run is a {b} one, '
    'so a row-count gap is not a change in the field',
    'biblio.watch.nothing': 'no change',
    'biblio.watch.node_added': 'node added',
    'biblio.watch.node_removed': 'node gone',
    'biblio.watch.node_changed': 'node attribute changed',
    'biblio.watch.edge_added': 'link added',
    'biblio.watch.edge_removed': 'link gone',
    'biblio.watch.edge_weight': 'link weight changed',
    'biblio.watch.cluster_added': 'cluster added',
    'biblio.watch.cluster_removed': 'cluster gone',
    'biblio.watch.cluster_relabeled': 'cluster relabeled',
    'biblio.watch.cluster_size': 'cluster size changed',
    'biblio.watch.burst_added': 'new burst',
    'biblio.watch.burst_removed': 'burst ended',
    'biblio.watch.burst_strength': 'burst strength changed',
    'biblio.watch.param': 'parameter',
    'biblio.watch.first': 'first capture (nodes/links)',
    'fuse.no_input': '{nid}: cross-source fusion needs at least one input table',
    'fuse.empty_parent': '{nid}: upstream {pid} has no rows, so it cannot be fused',
    'fuse.no_entity_column': '{nid}: upstream {pid} has no column usable as entities (tried: {wanted})',
    'fuse.no_rows': '{nid}: upstream {pid} yielded no entity at all from its "{column}" column',
    'fuse.needs_entity': '{nid}: fusion needs at least one entity candidate column (e.g. 关键词,话题)',
    'fuse.source_named': '[fusion] source "{source}": {pid} contributed {rows} records',
    'fuse.build_done': '[fusion] {parents} tables → {rows} records, sources: {sources}',
    'biblio.too_many_nodes': '{n} nodes exceed the cap ({cap}): narrow TopN or the time range',
    'biblio.too_many_edges': '{n} edges exceed the cap ({cap}): narrow TopN or max links per node',
    'biblio.links_too_large': 'Node "{node}" has a link JSON larger than {cap} bytes: lower max links per node',
    'biblio.import_duplicates': '{n} duplicate records were merged',
    'biblio.import_no_year': '{n} records have no year',
    'biblio.import_skipped': '{n} empty records were skipped',
    'biblio.import_ok': 'Recognised a {format} export: {n} records',
    'biblio.build_done': 'Bibliometrics done: {entity}, {nodes} nodes / {edges} edges ({start}–{end})',
    'biblio.export_failed': 'Bibliometric export failed: {err}',
    'deps.systemFont.win32': (
        'install a Chinese font such as SimHei/FangSong (an English Windows needs the Simplified Chinese '
        'font feature under Settings > Optional features) and restart the app'
    ),
    'deps.systemFont.linux': (
        'install a Chinese font (Debian/Ubuntu: apt-get install fonts-noto-cjk) and restart the app'
    ),
    'deps.systemFont.darwin': (
        'macOS ships PingFang/Songti; if one is missing, install Noto Sans CJK and restart the app'
    ),
    'deps.texFont.win32': (
        'the paper figures use ctex with FangSong (仿宋), so the system needs that font (an English Windows '
        'needs the Simplified Chinese font feature installed)'
    ),
    'deps.texFont.linux': (
        "off Windows the paper figures use ctex's own fandol CJK font set, which needs texlive-lang-chinese"
    ),
    'deps.texFont.darwin': "off Windows the paper figures use ctex's macnew font set (the system Songti/Heiti)",
    'deps.texPackage.win32': (
        'install it with the MiKTeX console (or "miktex packages install"), or allow MiKTeX to fetch missing '
        'packages on the network and retry'
    ),
    'deps.texPackage.linux': (
        'install the matching distro package (Debian/Ubuntu: apt-get install texlive-lang-chinese '
        'texlive-latex-extra), or run tlmgr install <package>'
    ),
    'deps.texPackage.darwin': 'with MacTeX run sudo tlmgr install <package>, or install it in TeX Live Utility',
    'deps.xelatex.win32': (
        'xelatex was not found, so the PDF cannot be compiled: install MiKTeX, or set the compiler path in Settings'
    ),
    'deps.xelatex.linux': (
        'xelatex was not found, so the PDF cannot be compiled: install it with TeX Live (Debian/Ubuntu: '
        'apt-get install texlive-xetex), or set the compiler path in Settings'
    ),
    'deps.xelatex.darwin': (
        'xelatex was not found, so the PDF cannot be compiled: install MacTeX (it ships xelatex), or set the '
        'compiler path in Settings'
    ),
    'chart.noCjkFont': (
        'No installed font carries Chinese glyphs (looked for: {checked}): Chinese labels in Matplotlib PNG '
        'output will draw as boxes — {remedy} (ECharts figures use browser fonts and LaTeX figures use ctex, '
        'neither is affected)'
    ),
    'chart.biblio_missing': (
        'Bibliometric chart is missing column(s): {cols} (let the upstream biblio node emit the full table)'
    ),
    'chart.biblio_no_nodes': 'The bibliometric chart has no nodes to draw',
    'chart.biblio_geo_none': 'The geo map cannot be drawn: none of {names} is a region of the world '
    'basemap (is 节点 a country/region column?)',
    'chart.biblio_geo_unknown': '{n} name(s) have no region in the basemap: {names}',
    'chart.biblio_geo_merged': '{n} name(s) drawn inside another region: {detail}',
    'chart.biblio_geo': 'Country / region',
    'chart.biblio_geo_note': 'The printed figure ranks the leading countries/regions by output '
    '(world geometry is not drawn in LaTeX); every value is in the table',
    'chart.biblio_no_links': 'The knowledge graph has no links: check the 连接 column or lower the selection threshold',
    'chart.biblio_no_years': 'The bibliometric chart has no usable years: check 首年/末年 or 年份序列',
    'chart.biblio_no_clusters': 'The bibliometric chart has no clusters: enable clustering in the upstream biblio node',
    'chart.biblio_no_bursts': 'No burst terms to draw: enable burst detection upstream and adjust gamma/min duration',
    'chart.biblio_bad_json': '"{col}" is not valid JSON: re-run the upstream biblio node',
    'chart.biblio_single_category': 'Nodes',
    'chart.biblio_unknown': 'Unsupported bibliometric chart type: {type}',
    'chart.biblio_year': 'Year',
    'chart.biblio_cluster': 'Cluster',
    'chart.biblio_span': 'Time span',
    'chart.biblio_duration': 'Duration (years)',
    'chart.biblio_burst': 'Burst interval',
    'chart.biblio_variation': 'Structural variation',
    'chart.biblio_pair': 'Slice pair',
    'chart.biblio_no_variation': (
        'No structural variation to draw: enable variation upstream and adjust its variation_min threshold'
    ),
    'chart.biblio_no_sentiment': (
        'This table has no 情感分布 column: run a sentiment/emotion/tendency step upstream and name '
        "its column in the biblio node's sentiment field"
    ),
    'chart.biblio_no_topics': (
        'This table has no 话题分布 column: run a clustering/topic step upstream and name its column '
        "in the biblio node's topic field"
    ),
    'chart.biblio_overlay_unlabelled': '{n} nodes carry no label and are left off this figure',
    'chart.biblio_overlay_truncated': 'Showing the first {shown} of {total} nodes; '
    'the table and CSV carry the full distribution',
    'chart.biblio_topics_truncated': 'Showing the first {shown} of {total} topics',
    'chart.biblio_share': 'Share (%)',
    'chart.biblio_topic_share': 'Topic share',
    'chart.biblio_ring_rule': 'Concentric rings ({rings}): first year inside out',
    'chart.biblio_ring_unknown': 'year unknown',
    'chart.biblio_ring_nodes': 'Nodes',
    'chart.biblio_ring_reps': 'Representative nodes',
    'chart.biblio_ring_total': 'Total frequency',
    'biblio.col.节点': 'Node',
    'biblio.col.起始年': 'From year',
    'biblio.col.结束年': 'To year',
    'biblio.col.结构变化': 'Structural change (bits)',
    'biblio.col.前邻居': 'Neighbours before',
    'biblio.col.后邻居': 'Neighbours after',
    'biblio.col.新增邻居': 'Gained neighbours',
    'biblio.col.消失邻居': 'Lost neighbours',
    'biblio.col.情感倾向': 'Dominant sentiment',
    'biblio.col.情感分布': 'Sentiment distribution',
    'biblio.col.主导话题': 'Dominant topic',
    'biblio.col.话题分布': 'Topic distribution',
    'chart.biblio_activity': 'Yearly activity',
    'chart.biblio_nodes': 'Nodes',
    'chart.biblio_links': 'Links',
    'chart.biblio_journal_map': 'Journal map',
    'chart.biblio_category_map': 'Category map',
    'chart.biblio_overlay': 'Journal-category overlay',
    'biblio.workspace_no_node': 'Run {rid} has no node {nid}: pick another run',
    'biblio.workspace_not_biblio': '{nid}: not a bibliometrics node; the workspace reads bibliometric tables only',
    'biblio.workspace_empty_table': '{nid}: this node stored no rows (stopped, failed, or cleared by retention)',
    'biblio.project_needs_name': 'A project needs a name (so does a rename)',
    'biblio.project_not_found': 'No project {pid}: it may have been deleted',
    'biblio.snapshot_not_found': 'No snapshot {sid}: it may have been deleted',
    'biblio.compare_needs_two': 'Comparing needs two different snapshots (baseline and current)',
    'biblio.snapshot_done': '[bibliometrics] saved "{label}": {nodes} nodes / {edges} links (params {verified})',
    'chart.biblio_map_layer': 'Layer',
    'chart.biblio_map_source': 'Source',
    'chart.biblio_map_target': 'Target',
    'chart.biblio_map_weight': 'Weight',
    'api.biblioEmpty': 'No bibliographic records could be parsed from the {format} file',
    'api.biblioDecode': 'Could not decode {name} (tried UTF-8 and GB18030)',
    'api.biblioNotRecognized': 'Could not recognize {name} as any supported bibliographic export',
    'api.biblioLensPatent': 'This is a Lens PATENT export (its columns include Jurisdiction, Inventors and Application '
    'Number), not scholarly records. The bibliometric network models publications, so drawing '
    'inventors and applicants as authors would only produce a wrong figure',
    # ── Bibliographic source export guide (services/biblio_sources.py) ──
    # Every line is bounded by a file we actually parsed: what a source lacks is stated as
    # missing, and no button is named that we have not seen in a real export.
    'source.CNKI.purpose': 'The entry point for co-occurrence networks in Chinese literature: keywords, authors, '
    'institutions and journals all build. CNKI exports carry no reference list and no '
    'times-cited, so citation analyses refuse by name before running instead '
    'of drawing nothing.',
    'source.CNKI.steps': '1. Search CNKI by topic or keyword; narrow by year and source if needed\n'
    '2. Tick the records, then press Export / Bibliography\n'
    '3. Choose the RefWorks format on the export page and save CNKI-<timestamp>-RefWorks.txt\n'
    '4. Upload that .txt; the NoteExpress and EndNote buttons on the same page are read too',
    'source.CNKI.missing': 'No reference list ⇒ co-citation, bibliographic coupling and citation '
    'bursts are unavailable\n'
    'No times-cited ⇒ the 总被引/H指数 columns never appear and citation-count filters stay off',
    'source.CSSCI.purpose': 'The citation entry point for Chinese social science: the CSSCI export carries a '
    'reference list, so co-citation and coupling work; it carries no abstract and no DOI.',
    'source.CSSCI.steps': '1. Open the search page of the CSSCI centre at Nanjing University\n'
    '2. Search by year, source or keyword and export the text, making sure the records include '
    '【参考文献】and【年代卷期】(one record per 【来源篇名】)\n'
    '3. The real file pads its tags (【关 键 词】, 【期    刊】, 【基    金】), merges year, '
    'issue and pages into 【年代卷期】2021,(2):146-155, and writes affiliations as '
    '【机构名称】=[author]institute.department — the importer parses exactly that shape\n'
    '4. Upload the .txt',
    'source.CSSCI.missing': 'No 【摘要】⇒ pick 关键词 as the cluster-label source; choosing 摘要 refuses by name\n'
    'No DOI ⇒ cross-source matching can only use title and authors',
    'source.WoS.purpose': 'The complete English-language entry point: this export carries references, times-cited, '
    'usage counts, research areas and countries, so co-citation, coupling and country '
    'collaboration networks all work.',
    'source.WoS.steps': '1. Search the Web of Science Core Collection\n'
    '2. Select records → Export, and choose the fullest record option: '
    '"Full Record and Cited References"\n'
    '3. Prefer "Plain Text" as the file format — that is the .txt carrying the CR/TC/UT tags\n'
    '4. Upload the .txt; Excel (.xls/.xlsx), RIS and BibTeX are read too — note that Excel carries '
    'no Cited References column (the site does not offer one), so citation work needs the plain text',
    'source.WoS.missing': 'The Cited References field is unavailable in Excel: the site does not offer that column in '
    'the Excel download (measured: all thirty rows empty, only the Cited Reference Count number) ⇒ '
    'with Excel alone there is no citation network and no citation burst; keywords (14/30), '
    'categories, funding and usage ARE usable from Excel. For citation analysis use "Plain Text with '
    'Full Record and Cited References" (23/30 rows carry CR)',
    'source.Scopus.purpose': "Scopus' CSV download: references, times-cited and author affiliations are in it, so "
    'institution and country networks build, and the Chinese interface’s Chinese column headers '
    'are recognised too.',
    'source.Scopus.steps': '1. Search Scopus\n'
    '2. Select results → Download → format CSV\n'
    '3. Tick References, Affiliations and Cited by in the field list — the affiliation column '
    'decides whether institution and country networks can be built at all\n'
    '4. Upload the .csv (a Chinese-interface file arrives with 文献标题/来源出版物名称/'
    '施引文献/参考文献 columns, which the reader also accepts)',
    'source.Scopus.missing': 'The Scopus site offers neither a Subject area nor a usage column in this export '
    '(it is not a field you forgot to tick) ⇒ subject co-occurrence and the usage filter are unavailable; the '
    'English column names move between versions (Citation count / Cited by, Article number / '
    'Art. No.) and both spellings are accepted',
    'source.Dimensions.purpose': "Dimensions' full-record CSV export: times-cited, subject fields, funding and MeSH "
    'terms are present, and one export often holds hundreds of records.',
    'source.Dimensions.steps': '1. Search Dimensions\n'
    '2. Select results → Export → choose "Export full record", and leave File format on '
    '"CSV - Comma separated"\n'
    '3. Do not choose "Export for bibliometric mapping" — that writes a VOSviewer/CiteSpace '
    'network file, not the record table this app reads; and do not use "Export for reference '
    'manager → BibTeX", which is readable as BibTeX but drops times-cited, subject fields and '
    'funding\n'
    '4. One download holds at most 500 items ("All items - max 500 items per download"), so '
    'export in batches, or tick "Send email when export is ready" — the file stays in the '
    'Export center for 30 days\n'
    '5. Upload the .csv — its first row is a copyright banner, not the header, and the '
    'importer skips it before reading column names',
    'source.Dimensions.missing': 'Measured: this export carries no References column ⇒ co-citation, coupling and '
    'citation bursts are unavailable\n'
    'We have no real file for the other two exports (bibliometric mapping, reference manager), '
    'so we do not claim to read them — for a citation network add WoS/Scopus/CSSCI',
    'source.Lens.purpose': "Lens' Scholarly Works CSV export: authors, source journal, year, subject fields, MeSH "
    'terms, keywords, abstracts, DOIs, times-cited and funding are all in it, and one export can '
    'hold over a thousand records.',
    'source.Lens.steps': '1. Search Lens and switch the collection to Scholarly Works — do not stay on Patents, '
    'whose export is refused by name\n'
    '2. Select records → Export → CSV, keeping Title / Author/s / Publication Year / Source Title '
    '/ Volume / Issue Number / Start Page / Keywords / MeSH Terms / Fields of Study / Citing Works '
    'Count / Funding / DOI / Abstract in the field list\n'
    '3. Upload the .csv (the header must contain Lens ID plus Citing Works Count or Fields of '
    'Study, otherwise the file cannot be told apart from the patent collection)',
    'source.Lens.missing': 'Measured: the References column of this export is a list of Lens record ids '
    '(shaped like 002-341-399-981-03X), not citation text ⇒ co-citation and bibliographic coupling '
    'are unavailable; use WoS/Scopus/CSSCI for a citation network\n'
    'It has no affiliation or address column ⇒ institution and country networks cannot be built; '
    'Source Country names the journal’s country, and this app will not present it as the authors’\n'
    'No usage counts ⇒ the usage filter stays off',
    'source.PubMed.purpose': 'PubMed needs no institutional access and suits keyword, author, institution and '
    'country co-occurrence in biomedicine.',
    'source.PubMed.steps': '1. Search PubMed\n'
    '2. Select records → Save → Format "Text (Medline)", then Create File to get the .txt or .nbib\n'
    '3. Upload it; the CSV summary is read too, but it has no abstract and no '
    'keywords, so it works as a citation list rather than an analysis source',
    'source.PubMed.missing': 'No references and no times-cited ⇒ citation analyses are unavailable',
    'source.RIS.purpose': 'A general citation-exchange format: most databases and reference managers export .ris.',
    'source.RIS.steps': '1. In Web of Science: select records → Export → file format "RIS File"\n'
    '2. Or in Zotero: right-click items → Export Items → format RIS\n'
    '3. Upload the .ris',
    'source.RIS.missing': 'Measured: WoS’ RIS export carries no times-cited and no country in the affiliation ⇒ '
    'count filtering and the country network are unavailable',
    'source.BibTeX.purpose': 'The format LaTeX workflows already use; Zotero and Web of Science both export .bib.',
    'source.BibTeX.steps': '1. Choose "BibTeX" in Web of Science’s export format list, or in Zotero: '
    'right-click items → Export Items → format BibTeX\n2. Upload the .bib',
    'source.BibTeX.missing': 'Fields vary by tool: a record without an author is counted in the skipped total and '
    'named in the console, never stored as an empty row',
    'source.EndNote.purpose': "The .enw that CNKI's EndNote button produces, or that EndNote/Zotero export.",
    'source.EndNote.steps': '1. Choose the EndNote download on CNKI’s export page, or export .enw from a manager\n'
    '2. Upload the .enw',
    'source.EndNote.missing': 'Measured: CNKI’s .enw carries no references and no times-cited',
    'source.NoteExpress.purpose': "The .net file behind CNKI's NoteExpress button; its fields match the RefWorks one.",
    'source.NoteExpress.steps': '1. Choose the NoteExpress download on CNKI’s export page\n'
    '2. Upload the resulting .net file',
    'source.NoteExpress.missing': 'Like the RefWorks export: no reference list, no times-cited',
    'engine.biblio_no_input': '{nid} needs exactly one upstream data table (an Upload node)',
    'engine.biblio_multi_input': (
        '{nid} has {n} upstream connections: bibliometrics accepts one input; keep a single wire'
    ),
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': 'Clean',
    'label.emotion': 'Emotion',
    'label.sentiment': 'Sentiment polarity',
    'label.tendency': 'Tendency',
    'label.ner': 'Entities',
    'ner.dropped': 'NER: dropped {n} model answer(s) that do not appear in the source text (nothing is guessed)',
    # ── node type labels (console fallbacks; mirror frontend app.js) ──
    'node.name': 'Workflow Name',
    'node.source': 'Data Source',
    'node.upload': 'Upload File',
    'node.process': 'Process',
    'node.analysis': 'Analysis',
    'node.visualize': 'Visualize',
    'node.tokenize': 'Tokenize',
    'node.output': 'Output',
    'node.resume': 'Resume Run',
    'node.comment': 'Comments',
    'node.compile': 'Compile',
    'node.biblio': 'Bibliometrics',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': 'Searching Zhihu for "{kw}", target {n} results',
    'crawl.zhihu.authorStart': '[Zhihu] collecting answers and articles of "{author}", target {n} rows',
    'crawl.zhihu.authorEmpty': '[Zhihu] no author given (a profile link, or the id after /people/): {author}',
    'crawl.zhihu.authorTabEmpty': (
        '[Zhihu] the "{tab}" tab of "{author}" holds nothing (this kind was never published), skipped'
    ),
    'crawl.zhihu.authorTabDone': '[Zhihu] tab "{tab}" finished, {n} rows so far (stopped because: {reason})',
    'crawl.zhihu.fallbackSearch': (
        'Deep-linked search rendered an empty shell; resubmitting the keyword through the search box'
    ),
    'crawl.zhihu.emptyOrBlocked': (
        'Zhihu search returned nothing (risk control, login wall, or dead page): '
        'turn off headless mode in the run settings, or retry later; collected data is safe'
    ),
    'crawl.cookiesSeeded': 'Cookies seeded: {host} accepted {n}/{total}',
    'crawl.redrive': 'page did not reach the site (parked on {where}), re-driving once',
    'crawl.loginWall': 'Login wall: {platform} redirected {where} to a login page',
    'crawl.riskBlocked': 'Risk control: {platform} answered {where} with a security check instead of content',
    # Neither of the two above: the browser wrote this page itself, so the site never saw
    # the request and the session is not the thing in question.
    'crawl.unreachable': 'The browser refused this visit itself: {platform} at {where}{detail}',
    'crawl.unreachableToken': ' ({token})',
    'crawl.promptDismissed': '{label}: dismissed the first-run dialog by pressing "{button}"',
    'crawl.promptUnmatched': (
        '{label}: the first-run dialog matched no known button (the page offers: {buttons}),'
        ' this run may wait for it to clear on its own'
    ),
    'crawl.zhihu.url': 'Search URL: {url}',
    'crawl.zhihu.loaded': 'Search page loaded, scrolling for more content...',
    'crawl.zhihu.processed': 'Processed result {i}, valid so far: {n}',
    'crawl.zhihu.skipped': 'Result {i} has no usable content, skipped',
    'crawl.zhihu.process_error': 'Error processing result {i}: {err}',
    'crawl.zhihu.finished': 'Search done: {n} valid results (target {total})',
    'crawl.zhihu.scrolling': 'Scroll #{i}, waiting for content...',
    'crawl.zhihu.no_more': 'Reached "no more content", stopping (after {i} scrolls)',
    'crawl.zhihu.scroll_round': 'Scroll #{i} done, {n} cards so far (target: {total})',
    'crawl.zhihu.target_reached': 'Target of {n} reached, stopping scroll',
    'crawl.zhihu.stuck': (
        '{n} rounds with no new cards and no taller page, and no "no more content" marker seen — stopping the scroll'
    ),
    'crawl.zhihu.no_growth': 'Card count did not grow ({n}/3), scrolling once more to confirm...',
    'crawl.zhihu.phase_done': 'Scroll phase done, {n} cards in total',
    'crawl.zhihu.excerpt_only': (
        'Bodies left collapsed: every 正文 is a search-page excerpt (tick "Expand full text" on the data source node)'
    ),
    'crawl.zhihu.bodies_short': '{n} answer(s) did not expand; their 正文 is still a search-page excerpt',
    'crawl.zhihu.hotStart': 'Collecting the zhihu hot board, target {n}',
    'crawl.zhihu.hotDone': 'Hot board finished: {n} rows (target {total})',
    'crawl.zhihu.hotCapped': (
        'The board holds {board} questions in total, so the walk stopped there (the site sets the board size)'
    ),
    'crawl.zhihu.hotRefused': 'The zhihu hot-list endpoint gave no board (answered {answer})',
    'crawl.zhihu.hotWall': 'The zhihu hot board needs a login: the current cookie was held at the sign-in page',
    'crawl.zhihu.expand_stopped': (
        '{n} expansions in a row answered nothing; keeping search-page excerpts for the rest of this crawl'
    ),
    # ── crawlers: weibo ───────────────────────────────────────
    'crawl.weibo.keyword': 'Keyword: {kw}',
    'crawl.weibo.range': 'Time range: {start} to {end}',
    'crawl.weibo.links': 'Built {n} search links (one per hour)',
    'crawl.weibo.keyword_plain': 'Keyword: {kw} (no time range, single search link)',
    'crawl.weibo.processing': 'Processing search link {i}/{total}',
    'crawl.weibo.url': 'URL: {url}',
    'crawl.weibo.link_done': 'Link {i} done, {n} rows collected',
    'crawl.weibo.accumulated': 'Total collected so far: {n}',
    'crawl.weibo.target_reached': 'Reached the target of {n} rows, stopping the walk',
    'crawl.weibo.authorStart': 'Collecting author {uid}\u2019s posts, target {n}',
    'crawl.weibo.authorDone': 'Author walk finished: {n} rows ({reason})',
    'crawl.weibo.hotStart': 'Collecting the weibo hot search board, target {n}',
    'crawl.weibo.hotDone': 'Hot board finished: {n} rows (target {total})',
    'crawl.weibo.hotCapped': (
        'The hot board held only {board} rows this time, so the walk stopped there (the site sets the board size)'
    ),
    'crawl.weibo.hotRefused': 'The weibo hot-search endpoint gave no board (answered {answer})',
    # Said when the request was never issuable: the browser sat on a frame that is not weibo.com, so the
    # same-origin fetch had no host to ask. Blaming the endpoint there convicts it of an answer it never gave.
    'crawl.weibo.hotNoHost': 'weibo hot board not collected: the browser was still on 「{where}」 and never '
    'came back to weibo.com (the visitor bootstrap did not finish, so the in-page '
    'request had no host — an arrival-frame fact, not an endpoint refusal)',
    'crawl.weibo.authorEmpty': (
        '"{author}" is not a weibo author address: give a weibo.com/u/<UID> profile link or the numeric UID'
    ),
    'crawl.weibo.authorWall': (
        'weibo bounced UID {uid}\u2019s profile back to a login page: this session cannot reach the author page'
    ),
    'crawl.weibo.authorMirror': (
        'the first row returned for UID {uid} is not theirs \u2014 the endpoint answered the '
        'home timeline, not this author\u2019s posts; refusing to file it as theirs'
    ),
    'crawl.weibo.authorRefused': (
        'the mymblog endpoint refused (status {status}, UID {uid}): this is a per-session '
        'throttle, the cookie may be fine \u2014 try again later'
    ),
    'crawl.weibo.authorNoPosts': 'UID {uid} returned no posts: this account may genuinely have none',
    'crawl.weibo.visiting': 'Visiting search link: {url}',
    'crawl.weibo.no_result': 'No results in this time window, skipping',
    'crawl.weibo.waiting': 'Waiting for the page to load...',
    'crawl.weibo.page_loaded': 'Page loaded',
    'crawl.weibo.total_pages': 'Detected {n} pages in total',
    'crawl.weibo.page_crawling': '  Crawling page {i}/{total}...',
    'crawl.weibo.page_empty': '  Page {i} has no usable cards, skipping',
    'crawl.weibo.page_done': '  Page {i} done: {n} rows, {total} accumulated',
    'crawl.weibo.link_error': 'Error processing search link: {err}',
    'crawl.weibo.page_timeout': (
        '    Waited {secs}s: this page gave neither a card nor the "no result" plate (navigation {settled})'
        ' — that is all this line can say; it does not mean the window holds nothing'
    ),
    'crawl.weibo.navSettled': 'settled',
    'crawl.weibo.navUnsettled': 'did not settle, which is a slow network, not a refusal',
    'crawl.weibo.page_gave_up': (
        '    This browser has already watched {waits} search pages deliver nothing: the budget is'
        ' not being spent on another window (that is "no page fetched", not "this window is empty")'
    ),
    'crawl.weibo.walk_done': (
        'Weibo search walk closed: {n} rows (target {target}, window {walked} of {total} reached, reason: {reason})'
    ),
    'crawl.weibo.max_page': 'Max page number: {n}',
    'crawl.weibo.pages_fail': 'Could not determine page count: {err}',
    'crawl.weibo.page_cards': '    Found {n} cards on this page',
    'crawl.weibo.card_error': '    Card {i}: error while processing, skipped',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': 'No URLs provided, returning empty results.',
    # ── resume and dedupe (crawler side) ────────────────────────
    'crawl.resume_have': 'Resuming: {n} item(s) already collected, continuing instead of starting over',
    'crawl.sink_failed': 'Incremental save failed (this row is still in the results, but may not be stored): {err}',
    'crawl.wechat.duplicate': 'Skipping a duplicate article link: {url}',
    'crawl.xhs.note_dup': 'Skipping a duplicate note: {url}',
    'crawl.zhihu.duplicate': 'Skipping duplicate answer #{i}',
    'ds.too_many_rows': 'the file has {n} rows, over the dataset limit of {limit} — it cannot be stored',
    'crawl.wechat.batch_start': 'Starting batch scrape of {n} WeChat article(s)',
    'crawl.wechat.processing': 'Scraping article {i} / {total}',
    'crawl.wechat.url': 'URL: {url}',
    'crawl.wechat.success': 'Article {i}/{total} scraped: "{title}" ({author})',
    'crawl.wechat.failed': 'Article {i}/{total} failed: no body was retrieved',
    'crawl.wechat.wait': 'Waiting 1 s before the next article',
    'crawl.wechat.batch_done': 'Batch scrape complete: {n} / {total} succeeded',
    'crawl.wechat.navigating': 'Navigating to article URL',
    'crawl.wechat.wait_title': 'Waiting for article title (#activity-name) to load',
    'crawl.wechat.loaded': 'Article page loaded successfully',
    'crawl.wechat.timeout': 'Page load timed out for: {url}',
    'crawl.wechat.scroll': 'Scrolling to bottom to trigger lazy loading',
    'crawl.wechat.scroll_done': 'Scroll complete',
    'crawl.wechat.extracting': 'Extracting article fields',
    'crawl.wechat.title': 'Title: {title}',
    'crawl.wechat.author': 'Author (official account): {author}',
    'crawl.wechat.pub_time': 'Publish time: {time}',
    'crawl.wechat.content_len': 'Content length: {n} characters',
    'crawl.wechat.preview': 'Content preview: {preview}',
    'crawl.wechat.no_content': 'Content element not found after retry.',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[XHS search] Searching for "{kw}", target {n} notes',
    'crawl.xhs.url': '[XHS search] Opened search URL: {url}',
    'crawl.xhs.page_ready': '[XHS search] Initial results page loaded',
    'crawl.xhs.page_timeout': '[XHS search] Initial content timed out — may be no results, still scrolling',
    'crawl.xhs.links': '[XHS search] Collected {n} note links',
    'crawl.xhs.note_ok': '[XHS search] Extracted: {title}...',
    'crawl.xhs.note_error': '[XHS search] Error processing note: {err}',
    'crawl.xhs.finished': '[XHS search] Done, {n} valid notes collected',
    'crawl.xhs.target_reached': '[Collect links] Target of {n} reached, stopping',
    'crawl.xhs.collect_done': '[Collect links] Done, {n} links collected',
    'crawl.xhs.detail_visit': '[Note detail] Opening detail page: {url}',
    'crawl.xhs.detail_ready': '[Note detail] Detail page loaded',
    'crawl.xhs.detail_timeout': '[Note detail] Detail page timed out',
    'crawl.xhs.deadNote': '[Detail] note blocked by 安全验证 (session is fine) — skipped: {url}',
    'crawl.xhs.content_len': '[Note detail] Content length: {n} characters',
    'crawl.xhs.author': '[Note detail] Author: {author}',
    'crawl.xhs.pub_time': '[Note detail] Publish time: {time}',
    'crawl.xhs.metrics': '[Note detail] Engagement - likes: {likes}, saves: {favs}, comments: {comments}',
    'crawl.xhs.comment_count': '[Note detail] Comments: {n}',
    'crawl.xhs.comment_skip': '[Comments] preview is 0, panel skipped (no wait)',
    'crawl.xhs.comment_start': '[Comments] Extracting up to {n} comments',
    'crawl.xhs.comment_found': '[Comments] Found {n} comment elements',
    'crawl.xhs.comment_error': '[Comments] Error extracting comment {i}: {err}',
    'crawl.xhs.comment_done': '[Comments] Extracted {n} comments',
    # ── analysis / services ───────────────────────────────────
    'export.done': 'Exported {n} rows to {path} ({fmt})',
    'export.parquet_engine_missing': 'Parquet export needs the pyarrow engine — install it: pip install pyarrow',
    'export.window_none': 'the filename wants a time range, but no crawl here set a start/end time',
    'export.window_many': 'the filename wants a time range, but this path has {n} of them',
    'export.window_ignored': (
        'Node {nid}: the file is written as normal and only "append the crawled time range" was ignored — {reason}'
    ),
    'analysis.type_convert_failed': 'Type conversion failed for column {col} -> {dtype}: {err}',
    'analysis.calc_failed': 'Column calc failed for {col} = {expr}: {err}',
    'analysis.bin_failed': 'Binning failed for {col}: {err}',
    'analysis.col_missing': 'Column "{col}" not found',
    'analysis.keyword_pos_no_match': (
        'After the POS filter {tags}, none of the {rows} text rows kept a single keyword — '
        'the tag spelling is likely wrong: use jieba tags (n, v, vn, a), not Chinese POS names'
    ),
    'analysis.dedupe_similar': (
        'Near-duplicate dedupe: SimHash distance ≤{distance} on "{column}", dropped {n} rows (first of each group kept)'
    ),
    'analysis.dedupe_distance': (
        'near-duplicate dedupe supports a distance of 0–{max} bits, got {value}: '
        'a larger one is refused rather than answered with an all-pairs scan'
    ),
    'analysis.time_unparsed': (
        '"{col}" has {n} rows that are not a parseable time (the site only gave a relative label such as '
        '"09月26日 21:00"); they are left empty rather than guessed into a year'
    ),
    'analysis.time_binned': '{col} split done: {detail}',
    'analysis.time_bin_labels': (
        'time binning needs one more boundary than there are phase names: {edges} boundaries and {labels} names'
    ),
    'analysis.time_bin_edges': 'time binning got a boundary that is not a date: {edges}',
    'analysis.time_bin_order': '{op} boundaries must run from earliest to latest',
    # A boundary PROPOSAL: this step rewrites no row and does not decide when an event
    # turned, because that needs the dates the researcher knows (the notice, the apology,
    # the filing) and not the post counts.
    'analysis.stages_sparse': (
        'only {days} days carry records in this column, which cannot be cut into phases ({least} needed)'
    ),
    'analysis.stages_ratio': 'the peak ratio has to be at least 1 (a peak is a day above the usual), got {value}',
    'analysis.stages_no_peak': (
        'the post-count curve has no turning peak {ratio}× above the usual day (median {floor} rows/day): '
        'one stretch of a curve must not be cut into several phases'
    ),
    'analysis.stages_folded': (
        'the curve holds more than {kept} peaks; the tallest {kept} were kept ({dropped} folded away)'
    ),
    'analysis.stages_folded_windows': (
        '{n} window(s) were shorter than the {days}-day minimum and joined their larger neighbour '
        '(a single tall day is not a phase)'
    ),
    'analysis.stages_done': 'phase proposal: {n} candidate windows covering {rows} rows ({span})',
    'analysis.stages_edges': 'suggested edges, left-closed/right-open, the last one is the final day + 1: {edges}',
    'analysis.stages_labels': 'suggested labels, one per window (placeholders — rename them): {labels}',
    'analysis.stages_basis_first': "opens on the curve's first day {day}",
    'analysis.stages_basis_valley': 'opens the day after the valley on {valley}',
    'analysis.topic_count': 'LDA needs at least 2 topics, got {value} (one topic is just "the whole text")',
    'analysis.topic_embed_unavailable': (
        'the embedding topic method is missing optional packages: {packages} '
        '(it does not fall back to LDA; install them or choose LDA)'
    ),
    'analysis.topic_embed_failed': 'embedding model "{model}" failed to load or run: {err}',
    'analysis.topic_embed_done': 'embedding topics: {model}, {n} topics over {rows} texts',
    'analysis.topic_empty_cluster': (
        'embedding topic "{topic}" received no documents: that is the model\'s answer, not a canvas '
        'error — {n} was the requested count and the clustering produced {got}'
    ),
    'analysis.topic_method_auto_embedding': 'topic method auto: encoder detected, using embedding ({model})',
    'analysis.topic_method_auto_lda': (
        'topic method auto: sentence-transformers (or another optional package) is absent, '
        'falling back to LDA — these results are LDA, not embedding'
    ),
    'analysis.bert_fallback': '{op} bert unavailable ({reason}); this run used {used} for the column, not bert',
    'analysis.topic_rows': 'LDA needs at least as many texts as topics: {topics} topics, {rows} usable rows',
    'analysis.topic_features': 'LDA could find no features in this column (punctuation or stopwords only?): {err}',
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
    'analysis.topic_stage_number': 'topics per stage must be a whole number, got "{value}"',
    'analysis.topic_stage_counts': (
        '{stages} stages need one topic count each, got {counts} (a single number means the same for every stage)'
    ),
    'analysis.stage_blank': (
        '{n} rows have no "{col}" value (their timestamp did not parse), so they join no topic model'
    ),
    'analysis.topic_stage_empty': (
        'phase "{stage}" holds no rows at all, so nothing can be modelled (check the boundaries in "{col}")'
    ),
    'analysis.topic_stage_rows': (
        'phase "{stage}" has only {rows} usable texts, which cannot carry {topics} topics '
        '(LDA needs at least as many texts as topics)'
    ),
    'analysis.topic_stage_features': 'phase "{stage}" yielded no feature words: {err}',
    'analysis.topic_stage_words': (
        'nothing could be selected as a feature word for {topic} in phase "{stage}" — no text was assigned to it, '
        "so lower that stage's topic count"
    ),
    'analysis.topic_stage_unused': (
        'no text was assigned to {topic} in phase "{stage}" (doc_n=0), '
        'so its feature words come from the topic distribution'
    ),
    'analysis.topic_stage_done': 'phase "{stage}": {n} topics over {rows} texts, perplexity {perplexity}',
    'analysis.topic_stage_topic_words': '{topic} (phase "{stage}"): {words}',
    'analysis.topic_map_done': (
        'intertopic map: {n} topics over {rows} texts, perplexity {perplexity} '
        '(bubble size = topic share; coordinates = MDS of the Jensen-Shannon distance between word distributions)'
    ),
    'analysis.topic_salience_done': (
        'salient terms: {terms} rows for {n} topics over {rows} texts, λ={value} '
        '(1 ranks by probability within the topic, 0 by over-representation against the corpus)'
    ),
    'analysis.topic_lambda': (
        'λ must sit between 0 and 1 (0 = over-representation only, 1 = within-topic probability only), got {value}'
    ),
    'analysis.label_no_llm': '{op} was handed no model client: only a canvas run carries one',
    'analysis.label_too_many': (
        'the labelling step asks the model once per topic: {rows} rows is over the limit of {limit}, '
        'so filter the topic table first'
    ),
    'analysis.label_no_words': '{topic} has an empty "{col}", and there is nothing to summarise without feature words',
    'analysis.label_failed': 'the summary for {topic} failed: {err}',
    'analysis.label_empty': 'the summary for {topic} came back empty (the model answered with punctuation only)',
    'analysis.label_fallback': 'no model summary for {topic}; labelled from its weighted words ({reason})',
    'analysis.label_fallback_all': 'no model available; {n} topics all labelled from their weighted words',
    'analysis.label_cancelled': 'stopped: {n} topics were never asked, and their summaries are marked 未处理',
    'analysis.label_done': 'topic summaries: {n} written (model {model})',
    'analysis.label_cached': (
        'topic summaries: {asked} new questions to the model, {replayed} answers replayed from the '
        'cache (re-running the same table no longer pays twice)'
    ),
    'analysis.label_prompt': (
        'You are a public-opinion researcher. Below are the feature words and sample posts of one topic '
        'inside one phase of a cyberbullying event. Summarise what this topic is about in at most six words; '
        'output the phrase alone, no explanation, no quotes.\n'
        'Phase: {stage}\nTopic: {topic}\nFeature words: {words}\nSample posts: {samples}'
    ),
    'analysis.cluster_prompt': (
        'You are a public-opinion analyst. Below are several raw posts that fall in the SAME semantic cluster '
        'of a cyberbullying corpus. Summarise what this cluster is about in one short sentence; output the '
        'summary alone, no explanation, no quotes.\n'
        'Cluster: {group}\nSize: {size}\nSample texts:\n{texts}'
    ),
    'analysis.cluster_done': 'cluster summaries: {n} clusters written (model {model})',
    'analysis.cluster_failed': 'the summary for cluster {group} failed: {err}',
    'analysis.cluster_cancelled': 'stopped: {n} clusters were never asked, and their summaries are marked 未处理',
    'analysis.cluster_no_texts': 'cluster {group} has no text to summarise, so the model cannot be asked',
    'analysis.cluster_empty': 'the summary for cluster {group} came back empty',
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
    'analysis.review_fact_size': 'nodes in cluster: {n}',
    'analysis.review_fact_label': 'LLR label: {label}',
    'analysis.review_fact_members': 'strongest members (by frequency): {members}',
    'analysis.review_fact_span': 'year span: {span}',
    'analysis.review_done': 'cluster review: {n} clusters written (model {model})',
    'analysis.review_failed': 'the review of cluster {group} failed: {err}',
    'analysis.review_failed_fallback': (
        'the review of cluster {group} failed; a sentence built from the table facts was used instead: {err}'
    ),
    'analysis.review_failed_blank': 'the review of cluster {group} failed and was left blank as asked: {err}',
    'analysis.review_empty': 'the review for cluster {group} came back empty',
    'analysis.review_cancelled': 'stopped: {n} clusters were never asked, their reviews are marked unprocessed',
    'analysis.review_no_groups': (
        'cluster review cannot find its grouping column {col}: enable clustering upstream first'
    ),
    'analysis.review_fallback_text': (
        '(generated from the table, not by a model) this cluster holds {size} nodes; strongest members: {members}'
    ),
    'analysis.reply_graph_no_edges': (
        'the reply graph found no resolvable reply: check that 评论者 / 楼层 / 父楼层 exist and '
        "that some reply's parent floor matches a top-level comment's floor"
    ),
    'analysis.reply_graph_done': 'reply graph: {edges} edges over {nodes} nodes',
    'analysis.compare_done': 'cross-platform compare: {platforms} platforms (value column {value})',
    'analysis.compare_agg': (
        '{op}: unknown aggregate "{agg}" — the value column supports only sum or mean '
        '(its name declares the aggregate, so the label must match how it was computed)'
    ),
    'analysis.bot_col_missing': 'bot likelihood needs the "{col}" column, which is not in this table',
    'analysis.bot_done': 'bot likelihood: {flagged} of {rows} rows flagged suspect (across {authors} authors)',
    'analysis.bot_limit': (
        'bot likelihood is a recall hint, not a verdict: it only sees cross-account near-duplicate text '
        'and posting bursts inside the table; a coordinated account that varies wording and timing is '
        'missed, and that miss rate is unmeasurable'
    ),
    'analysis.bot_evidence_dup': 'text highly similar to another account ({ratio})',
    'analysis.bot_evidence_burst': 'posting burst: {peak} posts in one 10-minute window (author peaks median {median})',
    'analysis.topic_done': (
        'LDA topic model: {n} topics over {rows} texts, perplexity {perplexity} '
        '(lower fits better, but far too low means it is memorising the corpus)'
    ),
    'analysis.evolution_done': (
        'Sentiment evolution: {n} periods from "period" ({periods}); index = (positive − negative) / total ∈ [-1, 1]'
    ),
    'analysis.evolution_unscored': (
        'no rows of "{col}" carry a score in {periods}, so the sentiment intensity is left empty there'
    ),
    # ── Reads taken after the phases: lifecycles, flow, a topic-count sweep, co-occurrence ──
    'analysis.timeline_stages': (
        'a lifecycle needs at least 2 phases to say "before" and "after", this table has {stages}'
    ),
    'analysis.timeline_overlap': 'the same-topic word overlap has to be between 0 and 1, got {value}',
    'analysis.timeline_blank': '{n} rows of "{col}" belong to no phase, so they join no lifecycle',
    'analysis.timeline_size': '"{col}" holds no number at all, so a peak cannot be measured (blank is not a peak of 0)',
    'analysis.timeline_partial': '{n} rows of "{col}" are not numbers and count as 0 when finding the peak',
    'analysis.timeline_words': '{topic} of phase "{stage}" has no feature words in "{col}", so it cannot be followed',
    'analysis.timeline_done': (
        'topic lifecycles: {topics} subjects over {stages} phases, {multi} spanning more than one phase '
        'and {secondary} flagged as a secondary flare-up (word-overlap threshold {value})'
    ),
    'analysis.timeline_secondary': 'secondary flare-up: {topic} runs {path}',
    'analysis.flow_stages': 'topic flow needs at least 2 adjacent phases, this table has {stages}',
    'analysis.flow_similarity': 'the flow similarity threshold has to be between 0 and 1, got {value}',
    'analysis.flow_weights': (
        '{topic} (phase "{stage}") has no usable word weights in "{col}", so no divergence can be computed'
    ),
    'analysis.flow_stage_empty': 'phase "{stage}" holds no topic rows (check "{col}" first)',
    'analysis.flow_no_edges': (
        'no topic pair reached the similarity threshold {value}: the closest measured pair was {best}, '
        'so lower the threshold below it'
    ),
    'analysis.flow_done': 'topic flow: {edges} edges between {stages} phases (threshold {value}, best measured {best})',
    'analysis.coherence_range': 'the topic-count sweep cannot start above where it ends: {low} > {high}',
    'analysis.coherence_sampled': (
        'the sweep fits {used} sampled texts out of {total} available; a different sample moves the numbers'
    ),
    'analysis.coherence_capped': (
        'only {rows} texts are available, so the sweep stops at {rows} topics instead of {high}'
    ),
    'analysis.coherence_row': 'n_topics={topics}  coherence={coherence}  perplexity={perplexity}',
    'analysis.coherence_pairs': (
        'no pair of the {topn} top words of any topic appears in one text ({pairs} pairs skipped): '
        'coherence is unmeasurable here, only perplexity is readable'
    ),
    'analysis.coherence_best': (
        'topic-count sweep ({low}…{high}): best coherence at {coherence} topics, lowest perplexity at {perplexity}'
    ),
    'analysis.cooccur_topn': (
        'a co-occurrence network caps its candidate words at {cap} (doubling the words '
        'quadruples the edges), got {value}'
    ),
    'analysis.cooccur_count': 'the co-occurrence count threshold has to be at least 1, got {value}',
    'analysis.cooccur_words': (
        'only {found} candidate words were available, which cannot form a pair (asked for the top {topn})'
    ),
    'analysis.cooccur_empty': (
        'no word pair reached the count threshold {floor}: the busiest of {pairs} pairs appeared {top} times, '
        'so lower the threshold or widen the candidates'
    ),
    'analysis.cooccur_done': (
        'co-occurrence network: {words} candidate words over {docs} texts, {edges} of {pairs} pairs at or above {floor}'
    ),
    # ── Looking forward: extrapolating the curve, and the flare-up warning ──
    'analysis.forecast_horizon': 'the horizon has to be at least 1 step, got {value} (0 just copies the last cell)',
    'analysis.forecast_window': 'a moving average needs 2 periods to average, got {value}',
    'analysis.forecast_season': 'a seasonal method needs a cycle length of at least 2 periods, got {value}',
    'analysis.forecast_season_rows': 'seasonal methods need at least {season} observed periods; this column has {rows}',
    'analysis.forecast_smooth': 'the smoothing factor "{name}" has to be strictly between 0 and 1, got {value}',
    'analysis.forecast_dates': '"{col}" is not a period column of dates: a phase NAME cannot be extrapolated',
    'analysis.forecast_rows': (
        'extrapolating needs at least {least} observed periods, this column gives {rows} with both a date and a number'
    ),
    'analysis.forecast_window_rows': (
        'a window of {window} still needs one period left to forecast, this column has {rows}'
    ),
    'analysis.forecast_duplicate': '"{col}" has two rows for the same day: {days} (they read as two steps of a trend)',
    'analysis.forecast_uneven': (
        'the periods are not evenly spaced: {steps} of {rows} gaps are not {gap} days, '
        'so future rows are labelled {gap} days apart'
    ),
    'analysis.forecast_done': (
        '{method} forecast: {rows} observed periods, {horizon} steps ahead, {gap}-day spacing (last {last})'
    ),
    'analysis.alert_streak': 'the streak has to be at least 1 period, got {value}',
    'analysis.alert_threshold': 'the "{name}" threshold has to be above 0, got {value}',
    'analysis.alert_floor': 'the volume-hold ratio cannot exceed 1 (that asks for growth), got {value}',
    'analysis.alert_rows': 'the warning needs one row more than the streak: asked for {least}, this table has {rows}',
    'analysis.alert_skipped': '{n} rows of "{col}" parse to no date, so they join no warning check',
    'analysis.alert_reason': (
        'moves over the last {streak} periods {moves}; intensity slope {intensity}; volume {volume} ({held})'
    ),
    'analysis.alert_none': (
        'nothing fired: the largest swing was {period}, and {streak} consecutive moves stayed under {swing} '
        'while the intensity slope stayed under {heating}'
    ),
    'analysis.alert_none_log': 'warning checked {checked} periods (streak {streak}, swing {swing}) and fired on none',
    'analysis.alert_fired': 'flare-up warning: {period} fired {signal} at {value}',
    'clean.unknown_mode': 'the clean node has no mode named "{mode}" (available: regex, llm)',
    'aggression.lexicon_done': (
        'cyberbullying scan (word list): {violent} of {rows} rows carry violent speech, {severe} severe '
        '(misses cannot be measured here — wording outside the list is invisible)'
    ),
    'clean.regex_done': (
        'Regex clean: kept {kept} rows, marked {dropped} for deletion '
        '(topic relevance is not judged here — that needs the llm mode)'
    ),
    'analysis.need_param': '{op} needs {param}, which is empty',
    'analysis.need_number': '{op}: "{param}" has to be a whole number, got "{value}"',
    'analysis.step_col_missing': '{op}: no column named "{col}" in this table',
    'analysis.step_cols_missing': '{op}: these columns are not in this table: {cols}',
    'analysis.bad_option': '{op} has no "{param}" option "{value}" (available: {allowed})',
    'analysis.need_multi_models': '{op} bert mode needs ≥2 models to compare (now {n})',
    'analysis.multi_models_run': 'multi-model compare: {op} ran over {n} models: {models}',
    'analysis.rename_blank': '{op}: these columns have no new name — set one for: {cols}',
    'cluster.not_enough': 'Not enough valid rows for clustering (need >= 2)',
    'cluster.dbscan': 'DBSCAN found {n} clusters + {noise} noise points',
    'cluster.done': 'Clustering completed: {rows} rows into {clusters} clusters (silhouette={score:.3f})',
    'anomaly.no_numeric': 'No numeric columns available for anomaly detection',
    'anomaly.no_usable_columns': 'Anomaly detection: none of the columns you named holds numbers ({columns})',
    'anomaly.ignored_columns': 'Anomaly detection: skipped the non-numeric columns ({columns})',
    'anomaly.too_few': 'Too few rows ({n} < {min}) — anomaly detection cannot reach a conclusion',
    'anomaly.done': 'Anomaly detection: {n}/{total} rows flagged (contamination={c:.2f})',
    'corr.need_cols': 'Need at least 2 numeric columns for correlation analysis',
    'corr.no_usable_columns': 'Correlation: none of the columns you named holds numbers ({columns})',
    'corr.ignored_columns': 'Correlation: skipped the non-numeric columns ({columns})',
    'corr.done': 'Correlation analysis ({method}): {n} pairs found (min_abs={min_abs:.2f})',
    'sig.no_group_column': 'Significance test: no group column given',
    'sig.no_value_column': 'Significance test: no value column given',
    'sig.group_column_missing': 'Significance test: group column "{col}" is not in the table',
    'sig.value_column_missing': 'Significance test: value column "{col}" is not in the table',
    'sig.value_not_numeric': 'Significance test: value column "{col}" cannot be read as numbers',
    'sig.no_usable_rows': 'Significance test: no usable rows left after dropping blanks/non-numeric (group "{col}")',
    'sig.two_groups_only': 'Significance test: {method} needs exactly 2 groups, found {n} — try ANOVA/Kruskal-Wallis',
    'sig.two_groups_required': 'Significance test: {method} needs at least two groups, found {n}',
    'sig.degenerate': 'Significance test: {method} cannot be computed (few samples or zero variance) — no fake p',
    'sig.unknown_method': 'Significance test: unknown method "{method}"',
    'sig.done': 'Significance test ({method}): {n_groups} groups, {n} rows, statistic={statistic}, p={p}',
    'ml.model_untrained_refused': (
        '"{name}" has no trained model and nothing saved to load — refusing to answer '
        'rather than inventing a neutral verdict for every row'
    ),
    'ml.missing_col': 'DataFrame is missing the required column "{col}". Skipping analysis.',
    'ml.no_rows': 'Nothing to process (the target column is empty).',
    'ml.emotion_failed': 'ML emotion prediction failed: {err} — falling back to Neutral',
    'sentiment.scored': 'Sentiment polarity ({mode}): judged {n} rows',
    'sentiment.scored_failed': 'Sentiment polarity: {n} rows could not be read and are left blank (not neutral)',
    'sentiment.snownlp_failed': 'SnowNLP failed: {err}',
    'sentiment.bert_failed': 'BERT failed: {err}',
    'sentiment.ml_failed': 'ML sentiment polarity prediction failed: {err} — falling back to neutral',
    'sentiment.unknown_mode': 'unknown sentiment polarity mode "{mode}"',
    'sentiment.bad_thresholds': 'the positive threshold {pos} cannot sit below the negative threshold {neg}',
    'sentiment.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'sentiment.bert_no_model': 'BERT mode needs a sentiment model named; empty means nothing can be judged',
    'sentiment.bert_bad_label': 'the BERT model answered an unrecognised label "{label}"',
    'sentiment.bert_loaded': 'BERT sentiment model loaded: {model} ({runtime}/{precision}, on {device}, in batches)',
    'sentiment.bert_need_runtime': 'torch+transformers or onnxruntime+tokenizers',
    'sentiment.bert_no_model_dir': 'no BERT model folder was found: {path}. {remedy}',
    'sentiment.packRemedyFrozen': (
        'the desktop build gets its BERT models from a separate archive: unpack '
        'CaiXiHui-bert-models-win64.zip into a bert_models\\ folder beside the exe and restart'
    ),
    'sentiment.packRemedySource': (
        'a source checkout exports them first: ml_train/scripts/export_onnx_bert.py writes the ONNX '
        "folder from the trained weights, or name an existing folder in the node's model field"
    ),
    'sentiment.bert_no_onnx': 'no loadable ONNX graph in that BERT model folder: {path}',
    'sentiment.bert_no_labels': 'that BERT model folder has no id2label table, so an output is not a class: {path}',
    'sentiment.bert_onnx_inputs': 'this ONNX graph does not expose the four inputs this path expects; found: {found}',
    'sentiment.bert_session_dropped': 'released an earlier BERT model to bound memory: {model} (it reloads if needed)',
    'emotion.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'emotion.bert_no_model': 'BERT mode needs an emotion model named; empty means nothing can be judged',
    'emotion.bert_loaded': 'BERT emotion model loaded: {model} ({runtime}/{precision}, on {device}, in batches)',
    'emotion.bert_failed': 'BERT emotion failed: {err}',
    'emotion.bert_bad_label': 'the BERT model answered an unrecognised emotion label "{label}"',
    'emotion.bert_done': '[BERT] emotion classification done, {n} rows, {failed} failed',
    'tendency.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'tendency.bert_no_model': 'BERT mode needs a tendency model named; empty means nothing can be judged',
    'tendency.bert_loaded': 'BERT tendency model loaded: {model} ({runtime}/{precision}, on {device}, in batches)',
    'tendency.bert_failed': 'BERT tendency failed: {err}',
    'tendency.bert_bad_label': 'the BERT model answered an unrecognised tendency label "{label}"',
    'tendency.bert_done': '[BERT] tendency classification done, {n} rows, {failed} failed',
    'ml.tendency_failed': 'ML tendency prediction failed: {err} — falling back to Objective Statement',
    'ml.emotion_done': '[ML] Emotion classification done, {n} rows, mode: ML',
    'ml.tendency_done': '[ML] Tendency analysis done, {n} rows, mode: ML',
    'cookie.saved': 'Cookies saved for {platform}',
    # {account} is already a word by the time it reaches here (blank → "default account",
    # default2 → "default account 2", a typed label verbatim), so the sentence never prints a key.
    'cookie.savedAccount': 'Cookies saved for {platform} (account: {account})',
    'cookies.accountDefault': 'default account',
    'cookies.accountDefaultNumbered': 'default account {n}',
    'cookie.started': 'Login browser opened — finish the login in that window, then press Done',
    'cookie.jobCancelled': '{platform} login cancelled',
    'cookie.windowClosed': 'The login window was closed before cookies could be captured; start again',
    'cookie.noCookies': 'No cookies captured before the wait ended — retry if the login was unfinished',
    'cookie.droppedForeign': (
        'Ignored {n} cookie(s) that do not belong to {platform}: a login usually passes through a '
        'third-party site, and those cookies do not go into this platform’s file'
    ),
    'cookie.allForeign': (
        'Nothing was saved for {platform}: every cookie in that paste belongs to another site — paste the '
        'cookies of this platform itself'
    ),
    # ── cookie purposes and how to obtain them (shown in the panel) ──
    'cookie.zhihu.purpose': 'Unlocks Zhihu search plus answer and comment bodies; logged out, Zhihu often '
    'returns nothing but a login prompt.',
    'cookie.zhihu.steps': (
        '1. Press "Generate via Browser" and sign in to Zhihu in the Chrome window that opens (QR or phone)\n'
        '2. Browse one page and confirm your own avatar is in the top-right\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.weibo.purpose': 'Unlocks Weibo search (s.weibo.com) and the comment JSON API; logged out you are '
    'bounced back to the passport QR page. Weibo accepts one live session per account: paging in parallel, '
    'or replaying the same cookie from a second browser, is answered with the login page — so always crawl '
    'from the same profile, and never run two Weibo crawls at once.',
    'cookie.weibo.steps': (
        '1. Press "Generate via Browser" and sign in to Weibo in that window\n'
        '2. Search one keyword and confirm the post list renders\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.bilibili.purpose': 'Unlocks Bilibili search, video metadata and comments; logged out, search is '
    'collapsed and only the first few comments show.',
    'cookie.bilibili.steps': (
        '1. Press "Generate via Browser" and sign in to Bilibili in the Chrome window (QR or phone)\n'
        '2. Open any video and scroll to the comment area until the list renders\n'
        '3. Come back here and press "Done \u2014 I logged in"'
    ),
    'cookie.douyin.purpose': 'Unlocks Douyin web search, video captions and comments; logged out you usually '
    'get only the first screen and no comments.',
    'cookie.douyin.steps': (
        '1. Press "Generate via Browser" and sign in to Douyin web in that window (QR or phone)\n'
        '2. Open any video until the comment panel on the right renders\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: Douyin is quick to raise a slider captcha for automated browsers \u2014 finish it in that '
        'window before saving.'
    ),
    'crawl.dy.target_reached': '[Douyin] target of {n} rows reached, stop',
    'crawl.dy.round': '[Douyin] screen {i}: {n} cards ({fresh} new, {done} collected)',
    'crawl.dy.noMore': (
        '[Douyin] the list wrote its own "no more for now": {screens} screens read, last screen held '
        '{cards} cards — that is the supply for this order, not a scroll that failed'
    ),
    'crawl.dy.processed': '[Douyin] stored video {i}, {n} valid rows so far',
    'crawl.dy.authorStart': "[Douyin author] one creator's posts, target {n} (counters read from the in-page overlay)",
    'crawl.dy.authorEmpty': '[Douyin author] no author given (paste a douyin.com/user/… link or the sec_uid): {author}',
    'crawl.dy.authorNoWorks': '[Douyin author] the profile publishes 0 posts, so there is nothing to collect',
    'crawl.dy.authorDone': '[Douyin author] post list finished, {n} rows (the profile publishes {works})',
    'crawl.dy.authorDoneNoCount': '[Douyin author] post list finished, {n} rows (the profile published no count)',
    'crawl.dy.authorNoCards': (
        '[Douyin author] the profile never rendered its post grid, so nothing was collected. The page said: '
        '{page}; URL: {url}. The profile publishes {works} posts, so this is a blocked or broken page — '
        'not an author who posted nothing'
    ),
    'crawl.dy.authorNotMounted': (
        '[Douyin author] the profile rendered no post grid and published no post count, so nothing was collected. '
        'The page said: {page}; URL: {url}. Both defaults at once means blocked or broken'
    ),
    'crawl.dy.wall': (
        '[Douyin] the browser was parked on the captcha interstitial: Douyin web serves it to headless '
        'browsers and to bursty requests. Re-save the cookie through the Cookie panel (visible window) '
        'and retry this keyword a little later'
    ),
    'crawl.dy.detailEmpty': '[Douyin] video {i} rendered no detail data, row skipped',
    'crawl.dy.detailWalled': (
        '[Douyin] video {i} was answered with the captcha interstitial (image-text posts are refused for this '
        'device; video pages are not) — row skipped: the site did not run out of content and the session is not dead'
    ),
    'crawl.dy.detailSwapped': (
        '[Douyin] asked for video {i} but the browser served a different one, {shown} (the site swapped the content)'
        " — row not stored: one row short beats somebody else's caption and counters filed under this link"
    ),
    'crawl.dy.detailNoIdentity': (
        '[Douyin] video {i} rendered only its counter bar — no author and no publish time, row skipped: '
        'a record that cannot say whose it is or when it was posted is not data, just budget spent on a blank row'
    ),
    'crawl.dy.detailSlow': (
        '[Douyin] video {i} did not finish loading inside the page-load timeout, row skipped: that is the '
        'network or the site being slow, a retry may well get it'
    ),
    'crawl.dy.modalDeferred': (
        '[Douyin] the overlay would not open for {n} works cards, skipped this round: that is unreadable, '
        'not the site running out — retry later'
    ),
    # The one refusal on this page that needs no waiting and no probing: the document is
    # the browser's own, and it says which address it refused.
    'crawl.dy.noPageRefused': '[Douyin] the browser refused this page itself, so there can be no cards: {url}{detail}',
    'crawl.dy.hotStart': '[Douyin hot board] collecting the board, target {n} (one answer, no per-row page)',
    'crawl.dy.hotTarget': '[Douyin hot board] the target of {n} rows is already stored, the board is not read again',
    'crawl.dy.hotDone': '[Douyin hot board] finished with {n} rows (target {total})',
    'crawl.dy.hotCapped': (
        '[Douyin hot board] the board held {board} rows this time, so the run ended there '
        '(the site decides how large a board is)'
    ),
    'crawl.dy.hotWall': (
        '[Douyin hot board] the board page was parked on the captcha interstitial, so nothing was collected: '
        'save the douyin cookie through the Cookie panel first'
    ),
    'crawl.dy.hotRefused': '[Douyin hot board] the board endpoint gave no board (answered {answer})',
    'crawl.bili.start': '[Bilibili search] keyword "{kw}", target {n} results',
    'crawl.bili.url': '[Bilibili search] URL: {url}',
    'crawl.bili.page': '[Bilibili search] page {page}: {n} videos ({fresh} new, {done} collected)',
    'crawl.bili.empty_page': '[Bilibili search] page {page} has no video cards, stop paging',
    'crawl.bili.no_more': '[Bilibili search] two pages in a row held nothing new, list exhausted (page {page})',
    'crawl.bili.processed': '[Bilibili search] stored {i}, {n} valid rows so far',
    'crawl.bili.duplicate': '[Bilibili search] {i} already in this run, skipped',
    'crawl.bili.target_reached': '[Bilibili search] target of {n} rows reached, stop paging',
    'crawl.bili.authorStart': '[Bilibili] collecting uploads of UP {mid}, target {n} rows',
    'crawl.bili.hotStart': '[Bilibili] collecting the {board}, target {n} rows (items carry their own figures)',
    'crawl.bili.hotPage': '[Bilibili] board page {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.bili.hotDone': '[Bilibili] board finished, {n} rows (target {total})',
    'crawl.bili.boardPopular': 'popular feed',
    'crawl.bili.boardRanking': 'weekly ranking',
    'crawl.bili.authorEmpty': '[Bilibili] no UP given (a space.bilibili.com link or a numeric mid): {author}',
    'crawl.bili.authorNoVideos': '[Bilibili] the upload list of UP {mid} rendered no video (possibly none published)',
    'crawl.bili.authorDone': '[Bilibili] upload list finished, {n} rows (stopped because: {reason})',
    'crawl.bili.watermarkHit': "[Bilibili] reached the previous run's boundary {i}; stopped paging",
    'crawl.bili.goneVideo': '[Bilibili search] {i} is withdrawn or unavailable ({code}), skipped',
    'crawl.bili.fetchEmpty': '[Bilibili search] {i} returned no readable data (non-JSON or WAF-blocked), skipped',
    'crawl.bili.rankingCapped': "[Bilibili] the {board} had only {n} rows (target {total}): its size is the site's",
    'crawl.bili.finished': '[Bilibili search] done, {n} valid rows (target {total})',
    'crawl.bili.blocked': (
        '[Bilibili] the endpoint refused to answer (code={code}): the cookie likely died or risk control '
        'kicked in — re-save the cookie in the Cookie panel, then resume this run'
    ),
    'crawl.hg.boardHotDrama': 'hot board',
    'crawl.hg.boardRealDrama': 'live-action hot board',
    'crawl.hg.boardAiDrama': 'AI drama hot board',
    'crawl.hg.boardComicDrama': 'comic drama hot board',
    'crawl.hg.boardUnknown': '[Hongguo] there is no such board: {board} (available: {options})',
    'crawl.hg.start': '[Hongguo] collecting the {board}, target {n} rows (paging follows the next link the site gives)',
    'crawl.hg.target_reached': '[Hongguo] target of {n} rows reached, stop paging',
    'crawl.hg.page': '[Hongguo] page {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.hg.lastPage': '[Hongguo] page {page} is the last the site offers, stop paging ({n} collected)',
    'crawl.hg.replay': '[Hongguo] page {page} pointed "next" back at itself ({url}), paging stopped: counted as short',
    'crawl.hg.noFresh': '[Hongguo] two pages in a row held nothing new (page {page}), paging stopped: counted as short',
    'crawl.hg.finished': '[Hongguo] done, {n} rows (target {total})',
    'crawl.hg.noBoard': (
        '[Hongguo] after {seconds}s this page still carried no board data (data keys on the page: {keys}): {url} '
        '\u2014 the site may have changed, or this machine never received the page'
    ),
    'crawl.hg.noPageRefused': '[Hongguo] the browser itself refused this page, so no board can be there: {url}{detail}',
    'crawl.hg.searchUnsupported': '[Hongguo] this site offers only its four hot boards, no keyword search '
    '(received keyword: {keyword})',
    'crawl.hg.noDetail': '[Hongguo] no link-based mode exists for this platform, and its detail page has not '
    'been measured yet ({url})',
    # ─── comment harvest (desktop player behind a local proxy; docs/crawler_notes.md Hongguo) ───
    'crawl.hg.cmt.start': '[Hongguo] harvesting comments: {title} ({episodes} episodes, replies {replies})',
    'crawl.hg.cmt.on': 'on',
    'crawl.hg.cmt.off': 'off',
    'crawl.hg.cmt.episode': '[Hongguo] episode {n}/{total}: {have} comments (the site says {site_total})',
    'crawl.hg.cmt.replyPage': '[Hongguo] replies under floor {floor}: {n}',
    'crawl.hg.cmt.danmakuSkipped': '[Hongguo] dropped {n} danmaku-guide rows (they are not comments)',
    'crawl.hg.cmt.finished': '[Hongguo] comment harvest done, {n} rows ({episodes} episodes)',
    'crawl.hg.cmt.noPlayer': (
        '[Hongguo] the Hongguo desktop player was not found ({path}) \u2014 set its exe location in '
        'Settings \u203a Hongguo player path'
    ),
    'crawl.hg.cmt.noMitmdump': (
        '[Hongguo] mitmdump was not found ({detail}) \u2014 install it with: pip install mitmproxy '
        '(see requirements-optional.txt)'
    ),
    'crawl.hg.cmt.needsExtras': (
        '[Hongguo] the comment harvest is a Windows desktop feature and this machine lacks {missing} '
        '(install per requirements-optional.txt; unavailable in cloud mode)'
    ),
    'crawl.hg.cmt.needsExtrasFrozen': (
        '[Hongguo] the desktop build does not carry {names}: the comment harvest needs mitmdump and '
        'UI Automation over a real desktop window, so that node runs only in a source checkout'
    ),
    'crawl.hg.cmt.caNotTrusted': (
        '[Hongguo] the mitmproxy root certificate is not trusted and auto-install did not succeed. '
        'Manual command (PowerShell): {command}'
    ),
    'crawl.hg.cmt.caInstalled': "[Hongguo] installed the mitmproxy root certificate into the current user's "
    'trusted roots (the player needs it to decrypt)',
    'crawl.hg.cmt.playerBusy': (
        "[Hongguo] the Hongguo player is already running and does not carry this tool's proxy \u2014 close "
        'it first and this node will launch the player through the proxy itself'
    ),
    'crawl.hg.cmt.noTraffic': (
        '[Hongguo] waited {seconds}s and no comment page arrived for this episode ({title}) \u2014 the '
        'player may be logged out, blocked by a dialog, or too old'
    ),
    'crawl.hg.cmt.dramaNotFound': "[Hongguo] the player's search found no such drama: {title}",
    'crawl.hg.cmt.scanningBoard': '[Hongguo] looking for “{title}” in the {label} board…',
    'crawl.hg.cmt.dramaSkipped': "[Hongguo] the player's UI tree never woke, skipping this drama: {title} "
    '(click the player window once, then 继续/Resume to harvest it)',
    # Named because the player's own feed walks away from the drama we entered: measured
    # 2026-10-20, after the first ↓ every following page belonged to the show the account had
    # been watching, and those rows would have been filed under the requested 剧名.
    'crawl.hg.cmt.feedDrifted': (
        '[Hongguo] during {title} episode {ep} the player feed moved to another drama (book {book}); '
        'the rest of this drama is not attempted — the rows already kept belong to the requested drama'
    ),
    # Said from the SCREEN, not the traffic: the player prints the drama it is showing as
    # ``@剧名`` in its header. Asking that before harvesting keeps another show's comments out
    # of this table when a card click lands elsewhere or a ↓ walks off into the account's own
    # queue. The episode counter is NOT readable while the drawer is open (measured), so no
    # message here claims a position the walk cannot see.
    'crawl.hg.cmt.screenMismatch': (
        '[Hongguo] the screen is showing “{have}”, not the requested “{want}” — the rest of this drama '
        'is not attempted (rows already kept belong to the requested show; this is not a search miss, '
        'the player did not put this drama on stage)'
    ),
    'crawl.hg.cmt.repliesExpanded': '[Hongguo] expanded {n} reply thread(s)',
    'crawl.hg.cmt.episodeShort': '[Hongguo] {title} episode {ep}: kept {have} of the {site_total} the site counts '
    '— this episode is incomplete',
    'crawl.hg.cmt.groupShort': '[Hongguo] episode group {group} (episode {ep}): kept {have} of the {site_total} the '
    'site counts — this episode is incomplete',
    # Said because an expanded child thread prints its own total and the walk clicks 展开 once
    # per thread: without this line a thread the site counts at 200 children and delivers 20
    # would still let the node claim the site said it was done.
    'crawl.hg.cmt.replyShort': (
        '[Hongguo] the child thread at floor {floor}: kept {have} of the {site_total} the site counts — '
        'its replies are incomplete'
    ),
    'crawl.hg.cmt.treeCold': (
        '[Hongguo] the player window is open but its UI tree never became walkable '
        '(WebView2 accessibility did not wake up). Click inside the player window once, then rerun this node'
    ),
    'crawl.hg.cmt.titleMissing': '[Hongguo] the detail page printed no drama name, so the player has nothing '
    'to search for: {url}',
    'crawl.hg.cmt.groupMismatch': '[Hongguo] a comment page arrived for {got} instead of the requested {want} '
    'and was dropped',
    'crawl.platformNotCrawlable': 'This platform only supports storing a login cookie so far, not crawling '
    '({platform}) \u2014 use a supported platform, or wait for its crawler to land',
    'cookie.xiaohongshu.purpose': 'Unlocks Xiaohongshu search, note bodies and comments; logged out you hit the '
    'login wall and only the first screen shows.',
    'cookie.xiaohongshu.steps': (
        '1. Press "Generate via Browser" and sign in to Xiaohongshu in that window\n'
        '2. Open any note and confirm the comment area renders\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.twitter.purpose': 'Unlocks X (Twitter) search, user timelines, tweet bodies and replies; logged out '
    'those pages answer with a login wall.',
    'cookie.twitter.steps': (
        '1. Press "Generate via Browser" and sign in to x.com in the Chrome window (password or phone code)\n'
        '2. Open any tweet until the replies render — both auth_token and ct0 have to be present\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: X often asks a new device for one more verification code — finish it in that window before saving.'
    ),
    'cookie.instagram.purpose': 'Unlocks Instagram profiles, hashtag grids and comments; logged out the page shows '
    'a login wall and its endpoints refuse the request.',
    'cookie.instagram.steps': (
        '1. Press "Generate via Browser" and sign in to instagram.com in that window\n'
        '2. Open any post until the comment area renders\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: if the login detours through Facebook, wait until Instagram is back before saving.'
    ),
    'cookie.youtube.purpose': 'Unlocks YouTube subscriptions, playlists, history and comments; public videos play '
    'without a login, but those pages are throttled or collapsed.',
    'cookie.youtube.steps': (
        '1. Press "Generate via Browser" and sign in to YouTube (a Google account) in the Chrome window\n'
        '2. Return to the youtube.com home page and check your avatar is showing\n'
        '3. Come back here and press "Done \u2014 I logged in" — the browser is pulled back to YouTube first, '
        'so the Google account\u2019s own cookies never land in this platform\u2019s file'
    ),
    'cookie.entryRejected': 'That link is not on a {platform} domain, so the platform login page was used instead '
    '(another site\u2019s cookies must never be stored in this platform\u2019s cookie file)',
    'cookie.verifying': 'Probing this platform with the stored cookie\u2026',
    'cookie.verifyFailed': 'Verification failed: {err}',
    'cookie.verify.ok': 'The stored {platform} cookie works',
    'cookie.verify.loginWall': '{platform} still redirects to a login page: log in again and save',
    'cookie.verify.noCookie': 'No {platform} cookie stored yet: log in and save first',
    'cookie.verify.checkedUrl': 'Verified against: {url}',
    # The pre-run check (preflight). Three conclusions, three next steps: merging
    # any pair would send the user off doing the wrong thing — re-logging in, or waiting.
    'cookie.pre.valid': 'The stored {platform} cookie works',
    'cookie.pre.expired': '{platform} rejected the stored cookie: the page bounced to a login page',
    'cookie.pre.unknown': '{platform} could not be checked (that is not a pass, and the run is not blocked)',
    'cookie.pre.noLogin': '{platform} is crawled without a login',
    'cookie.pre.notCrawlable': '{platform} can hold a cookie but cannot be crawled yet',
    'cookie.pre.account': ' (account {account})',
    'cookie.pre.notListed': 'Nothing here knows that platform, so nothing was checked: {platform}',
    'cookie.pre.busy': "{platform}'s browser is already held by something else",
    'cookie.pre.timeout': 'the check ran past {n} seconds',
    'cookie.pre.riskControl': 'the page answered with a captcha / risk control',
    'cookie.verify.cloudHeadless': (
        'this host is a windowless server: the check above could only run a HEADLESS browser, and some '
        'sites answer headless with a captcha or a blank page — that is not proof the cookie expired '
        '(verify on a machine with a window to judge the login state itself)'
    ),
    'cookie.verify.unclear': '{platform} could not be verified: the page answered with a captcha or risk '
    'control, which says nothing about whether the cookie is valid',
    # The page never came from the site at all, so nothing about the cookie was tested —
    # and 「可用」 here would be cached and reused by every later run.
    'cookie.verify.unreachable': '{platform} could not be verified: the browser never opened this address '
    '(this machine\u2019s network or DNS), so the cookie was not tested',
    'cookie.delete.none': 'There is no saved {platform} cookie to delete',
    'cookie.delete.profileHolds': 'Note: {platform}\u2019s browser profile stays logged in — deleting this '
    'file does not sign that device out',
    # Saving IS the update now: the paste plants itself into that account's profile, and the
    # /api/cookies/refresh-profile route with its four refusal sentences went away with the
    # button. One case cannot be done on the spot — that browser is held — and it has to say so,
    # because 「saved」 and 「saved but not in the profile」 look identical from a paste box.
    'cookie.plant.deferred': (
        "{platform}'s browser is held by something else (a crawl may be running), so this cookie "
        'could not be planted into its profile yet — it is saved, and the next crawl will bring it in'
    ),
    'cookie.refresh.failed': 'Could not update the profile session: this platform\u2019s browser did not open ({err})',
    'cookie.refresh.done': 'Saved {platform} cookies were planted into its browser profile ({n} entries)',
    # Measured: a cookie without an expiry is never written to the profile store, so it
    # dies with the window that was opened to plant it.
    'cookie.refresh.sessionOnly': 'Note: {n} of them carry no expiry, so they live only in that window and are not '
    'kept by the profile once it closes',
    'cookie.delete.failed': 'Could not delete the cookie file: {err}',
    'api.platformsRequired': 'platforms must be a list of platform names',
    'api.cookieBusy': 'A {platform} login window is already open — finish or cancel it first',
    'api.bodyNotObject': 'request body must be a JSON object',
    'api.paramInvalid': 'parameter {name} is invalid',
    'api.payloadTooLarge': 'request body exceeds the {limit} MB ceiling — split it up',
    'api.workflowNameRequired': 'a valid workflow name is required',
    'api.workflowMissing': 'No saved workflow by that name: {name}',
    'api.workflowNameTaken': 'A workflow named “{name}” already exists — renaming would overwrite it, pick another',
    'api.workflowNameSame': 'The old and new names are the same file, so there is nothing to rename',
    'api.workflowRenamed': 'Workflow renamed: {old} → {new}',
    'wfHistory.invalid': 'That canvas state cannot be stored: an object with a nodes list is required',
    'wfHistory.labelTooLong': 'The snapshot name is longer than {n} characters',
    'wfHistory.workflowNameTooLong': 'The workflow name is longer than {n} characters',
    'wfHistory.unserializable': 'The canvas contains something that cannot be serialized, so no snapshot was stored',
    'wfHistory.full': 'Canvas history is full ({max} snapshots) — delete older snapshots before saving another',
    'wfHistory.missing': 'No canvas snapshot with that id: {id}',
    'wfHistory.corrupt': 'Canvas snapshot {id} is unreadable and cannot be restored',
    'wfHistory.workflowRequired': 'Save the workflow before choosing a layout baseline',
    'wfHistory.badStrategy': 'Unknown auto-layout strategy: {strategy}',
    'wfHistory.baselineRequired': 'A baseline snapshot is required for baseline layout',
    'project.noWorkflow': 'Save a workflow before exporting a project bundle',
    'project.workflowUnreadable': 'The workflow file cannot be read: {name}',
    'project.datasetMissing': 'A dataset the workflow reads does not exist: {id}',
    'project.templateMissing': 'A referenced reusable template is missing and was skipped: {id}',
    'project.badZip': 'The project bundle is not a valid zip file',
    'project.tooManyEntries': 'The project bundle has too many entries (limit {max})',
    'project.tooLarge': 'The project bundle expands beyond {mb} MB',
    'project.fileTooLarge': 'A file inside the bundle is too large: {file} (limit {mb} MB)',
    'project.badEntry': 'The bundle contains a file path this importer does not accept: {file}',
    'project.entryMissing': 'The bundle is missing a file: {file}',
    'project.badJson': 'A JSON file inside the bundle cannot be read: {file}',
    'project.checksum': 'A bundle file failed its checksum: {file}',
    'project.badFormat': 'This is not a CaiXiHui project bundle',
    'project.badVersion': 'Unsupported project bundle version: {version}',
    'project.badManifest': 'The bundle manifest is missing a list: {section}',
    'project.tooMany': 'The bundle contains too many {section} (limit {max})',
    'project.noWorkflowInBundle': 'The project bundle contains no workflow',
    'project.datasetInvalid': 'A dataset inside the bundle cannot be read: {id}',
    'project.datasetTooLarge': 'Dataset {id} exceeds {max} rows',
    'project.workflowInvalid': 'A workflow inside the bundle cannot be read: {name}',
    'project.datasetRefMissing': 'A dataset the workflow reads is not in the bundle: {id}',
    'project.templateInvalid': 'A reusable template cannot be imported: {name}',
    'project.templateRefMissing': (
        'Workflow “{name}” references a template not in the bundle: {id} (its instance snapshot still works)'
    ),
    'project.lineageMissing': 'A referenced cumulative dataset is missing and was skipped: {name}',
    'project.lineageInvalid': 'The bundle’s cumulative-dataset information cannot be read',
    'project.noFile': 'Choose a project bundle file first',
    'compare.runMissing': 'No such run: {rid}',
    'compare.sameRun': 'A run cannot be compared with itself',
    'compare.nodeMissing': 'Run {rid} has no node {node}',
    'compare.tooManyRows': 'Node {node} has more than {max} rows, too many to compare',
    'reusable.invalid': 'The reusable template could not be read',
    'reusable.nameRequired': 'A reusable node needs a name',
    'reusable.nameTooLong': 'The template name is longer than {n} characters',
    'reusable.descriptionTooLong': 'The template description is longer than {n} characters',
    'reusable.noNodes': 'A reusable node needs at least one node',
    'reusable.tooManyNodes': 'A reusable node can hold at most {n} nodes',
    'reusable.badNode': 'The template contains a node this build cannot read',
    'reusable.badNodeId': 'A node id is missing or repeated: {id}',
    'reusable.badNodeType': 'Node {id} has a type a reusable node cannot hold: {type}',
    'reusable.badNodeParams': 'Node {id} params are not an object',
    'reusable.badConnections': 'The template connections could not be read',
    'reusable.badConnection': 'A wire does not join two template nodes: {a} → {b}',
    'reusable.cycle': 'The template contains a cycle and cannot run in order',
    'reusable.badInputs': 'The template input list could not be read',
    'reusable.badInput': 'An input slot names a node that is not in the template: {id}',
    'reusable.badOutputs': 'The template output list could not be read',
    'reusable.badOutput': 'An output slot names a node that is not in the template: {id}',
    'reusable.oneOutput': 'A reusable node must have exactly one output node ({n} now)',
    'reusable.outputHasNext': 'Output node {id} still has a successor; choose the real terminal node',
    'reusable.nameTaken': 'A reusable template named “{name}” already exists',
    'reusable.full': 'Reusable templates are full ({max}); delete old ones first',
    'reusable.corrupt': 'Reusable template {id} is unreadable',
    'reusable.missing': 'No reusable template with that id: {id}',
    'reusable.badId': 'The reusable template id is malformed: {id}',
    'reusable.noTemplateForRun': 'Reusable node “{name}” has no template to run',
    'reusable.badTemplate': 'Reusable node “{name}” cannot be expanded (a node type or wire is not accepted)',
    'reusable.tooManyInputs': 'Reusable node “{name}” has more incoming wires than input slots',
    'reusable.missingInputs': 'Reusable node “{name}” needs {n} input(s), but only {wired} are wired',
    'api.fieldTypeInvalid': 'field {name} has the wrong type',
    'api.stepsMustBeObjects': 'steps must be a list of objects, each with an "op" and optional "params"',
    'api.noCookieJob': 'No cookie login is currently active',
    'cookie.deleted': 'Cookies deleted for {platform}',
    'cookie.deletedAccount': 'Cookies deleted for {platform} (account: {account})',
    'cookie.renamed': (
        'Renamed the {platform} login “{old}” to “{new}” (its cookie file and its own browser directory moved together)'
    ),
    'cookie.renamedFileOnly': (
        'Renamed the {platform} login “{old}” to “{new}” — that account has never opened a '
        'browser of its own, so only the cookie file moved'
    ),
    'cookie.profileDeleted': (
        'Deleted the browser profile for {platform} · {account} — that device is signed out; '
        'the saved cookie file is untouched'
    ),
    'cookie.profileDelete.none': 'There is no browser profile to delete for {platform} · {account}',
    'store.workflow_saved': 'Workflow saved: {path}',
    'store.dataset_saved': 'File stored: {name} ({rows} rows, id {did})',
    'store.datasets_bound': 'Workflow {wf} bound to {n} uploaded file(s)',
    'ds.corrupt': 'Dataset {did} could not be read (its records are damaged) — upload it again',
    'ds.lineage_name_required': 'A cumulative dataset needs a name',
    'ds.lineage_identity': 'Unknown duplicate policy: {value} (use whole row or named columns)',
    'ds.lineage_keys_required': 'The named-columns policy needs at least one key column',
    'ds.lineage_key_missing': 'Key column(s) not in the table: {cols}',
    'ds.lineage_columns': (
        'Cumulative dataset “{name}” does not match its current version: extra {extra}; missing {missing}'
    ),
    'ds.lineage_too_large': 'Cumulative dataset “{name}” would reach {n} rows, over the limit of {max}',
    'ds.lineage_current_missing': 'The current version {id} of cumulative dataset “{name}” is missing',
    'ds.lineage_missing_dataset': 'The dataset {id} for the cumulative import is missing',
    'accumulate.done': 'Cumulative dataset “{name}”: +{added} rows, {total} total (version {version})',
    'engine.accumulate_no_name': 'Node {nid}: the cumulative dataset node has no name',
    'engine.accumulate_bad_identity': 'Node {nid}: unknown duplicate policy {value}',
    'engine.accumulate_no_keys': 'Node {nid}: the named-columns policy needs key columns',
    'engine.accumulate_one_parent': 'Node {nid}: a cumulative dataset node needs exactly one upstream',
    'engine.accumulate_bad_parent': 'Node {nid}: upstream {up} is not a table node',
    'engine.watermarkUnsupported': 'Node {nid}: cross-run watermark supports only Bilibili author uploads',
    'engine.watermarkRecrawl': 'Node {nid}: cross-run watermark and re-crawl cannot both be on',
    'node.accumulate': 'Cumulative dataset',
    'ds.purged': 'Removed {n} file(s) unused for {days} days and referenced by no workflow',
    'ds.purge_result': 'Removed {n} orphaned file(s), kept {kept} still in use',
    'ds.cleared': 'Emptied the file store: {n} file(s) removed',
    'ds.clearBusy': 'A live run may be reading these datasets — stop it or wait before clearing',
    'ds.rebound': 'Re-attached dataset {name} ({did}) by file name — the workflow can run as-is',
    'ds.missing': 'An uploaded file this workflow refers to is no longer stored: {name}',
    'api.datasetMissing': 'No stored dataset with that id: {did}',
    'api.datasetNameInvalid': 'that name cannot label a dataset (nothing left after cleaning): {name}',
    'lex.unknownKind': 'Unknown lexicon kind: {kind}',
    'lex.needTerms': 'Provide at least one term.',
    'lex.userdictReadFailed': 'Could not read the user lexicon; leaving the tokenizer untouched.',
    'lex.userdictLoadFailed': 'Failed to load the jieba user dictionary.',
    'api.lineageMissing': 'No cumulative dataset with that name: {name}',
    'api.datasetInLineage': (
        'This file is the current version of cumulative dataset “{name}”; '
        'deleting it would break the history (force also resets that lineage)'
    ),
    'api.datasetInUse': 'saved workflows still read this file, and deleting it would leave them empty: {workflows}',
    'api.datasetTooBig': 'That file is too big to store: {err}',
    'api.diffTwoSources': 'Compare needs "a" and "b" (each a dataset_id, node_id+workflow_name, or inline data)',
    'api.diffKeyMissing': 'Compare key "{name}" is not a column in both tables, so rows cannot be matched by it',
    'api.diffKeyNotUnique': 'Compare key "{name}" has duplicate values, so it cannot identify rows uniquely',
    'data.mergeNeedTwo': 'Merging needs at least two datasets',
    'data.mergeMissing': 'A dataset to merge does not exist: {id}',
    'data.mergeNameRequired': 'The merged dataset needs a name',
    'data.mergeNameTooLong': 'The merged dataset name is longer than {n} characters',
    'data.mergeColumns': 'Dataset “{name}” does not match the first table: extra {extra}; missing {missing}',
    'data.mergeTooLarge': 'The merged table has {n} rows, over the limit of {max}',
    'history.recorded': 'Recorded {n} history metric(s) for "{wf}"',
    'history.run_deleted': 'Execution history: deleted {n} row(s) of run {rid}',
    'executor.task_failed': 'Task failed: {err}',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': 'Failed to record execution history (non-fatal)',
    'misc.save_workflow_failed': 'Failed to save workflow',
    'misc.i18nAudit': 'the message catalogue has a problem (harmless to run, please fix): {issue}',
    'misc.exportDeleteFailed': 'could not delete the exported file {name}: {err}',
    'misc.cookie_save_failed': 'Failed to save cookies: {err}',
    'misc.cookie_gen_failed': 'Failed to generate cookies: {err}',
    'misc.studio_source_failed': 'Merged studio load: source failed',
    'misc.source_probe_failed': 'Source probe failed',
    'misc.studio_saved': 'Chart studio saved {path} ({bytes} bytes)',
    'misc.chartPdfSaved': 'Chart PDF compiled: {name} ({bytes} bytes)',
    'misc.browser_open_failed': 'Could not open browser: {err}',
    'misc.browserNotFound': 'This machine has no default browser to hand the address to — open it by hand: {url}',
    'misc.cloudNoBrowser': (
        'cloud mode does not try to open a browser (there is none on a server); reach this address from '
        'your own machine: {url}'
    ),
    'misc.server_starting': 'Starting crawler workflow server on port {port}',
    'misc.consoleUtf8': (
        'the console encoding {streams} of this machine cannot write Han characters — switched to UTF-8 '
        '(each stream is changed once, so no log line is lost to it again)'
    ),
    'misc.visualize_failed': 'Chart rendering failed: {err}',
    'misc.export_failed': 'Writing the export file failed',
    # ── crawler internals (debug level) ───────────────────────
    'crawl.cookies_failed': '{platform}: could not load cookies ({err}) — the run may come back empty without a login',
    'crawl.xhs.untitled': 'untitled',
    'crawl.debug.title_missing': 'Title element not found',
    'crawl.debug.content_missing': 'Content element not found',
    'crawl.debug.author_missing': 'Author element not found',
    'crawl.debug.time_missing': 'Publish-time element not found',
    'crawl.debug.comments_missing': 'Comment area not loaded / not present',
    'crawl.debug.comment_item': 'comment #{i}: {author} - {text}...',
    'crawl.debug.card_skip': 'card {i}: skipped (no author)',
    'crawl.debug.card_author': 'card {i}: author="{v}"',
    'crawl.debug.card_time': 'card {i}: time="{v}"',
    'crawl.debug.card_len': 'card {i}: text length={v}',
    'crawl.debug.card_metrics': 'card {i}: reposts={f} comments={c} likes={l}',
    'crawl.debug.card_images': 'card {i}: images={n}',
    'crawl.debug.pager_missing': 'No pager button found — single page',
    'crawl.debug.content_retry': 'Content not extracted yet — retrying once',
    # ── argument validation / API errors (surfaced in toasts) ──
    'crawl.weibo.bad_date': 'Bad date format: {value} (expected YYYY-MM-DD)',
    'crawl.weibo.need_both_dates': 'Set both a start and an end date — a single one searches a different range',
    'crawl.weibo.bad_range': 'The end date ({end}) must be later than the start date ({start})',
    'chart.count': 'count',
    'chart.noRunData': 'No run data yet — execute the workflow once first.',
    'chart.col.total': 'Total',
    'chart.col.sentiment_index': 'Sentiment index',
    'chart.col.sentiment': 'Sentiment',
    'chart.col.prevalence_pct': 'Prevalence (%)',
    'chart.col.doc_n': 'Topic docs',
    'chart.col.feature_words': 'Feature words',
    'chart.col.topic': 'Topic',
    'chart.col.score': 'Score',
    'chart.col.weights': 'Weight',
    'chart.col.period': 'Period',
    'chart.col.intensity': 'Intensity',
    'chart.col.term': 'Term',
    'chart.col.overall_freq': 'Overall frequency',
    'chart.col.within_freq': 'Within-topic frequency',
    'chart.col.sample_texts': 'Sample posts',
    'chart.col.share': 'Share (%)',
    'chart.col.positive_pct': 'Positive share',
    'chart.col.neutral_pct': 'Neutral share',
    'chart.col.negative_pct': 'Negative share',
    'latex.done': 'LaTeX figure written: {file}',
    'latex.table_done': 'LaTeX three-line table written: {file}',
    'latex.failed': 'LaTeX generation failed: {reason}',
    'chart.value.positive': 'Positive',
    'chart.value.negative': 'Negative',
    'chart.value.neutral': 'Neutral',
    'chart.col.emotion': 'Emotion',
    'chart.col.tendency': 'Tendency',
    'chart.col.confidence': 'Confidence',
    'chart.col.tendency_confidence': 'Tendency confidence',
    'chart.col.aggression_score': 'Aggression score',
    'chart.value.anger': 'Anger',
    'chart.value.fear': 'Fear',
    'chart.value.joy': 'Joy',
    'chart.value.sadness': 'Sadness',
    'chart.value.surprise': 'Surprise',
    'chart.value.tendency_objective': 'Objective Statement',
    'chart.value.tendency_praise': 'Praise/Affirmation',
    'chart.value.tendency_criticism': 'Criticism/Questioning',
    'chart.value.tendency_controversy': 'Controversy/Reflection',
    'chart.value.tendency_advocacy': 'Advocacy/Call-to-action',
    'chart.value.tendency_satire': 'Satire/Mockery',
    'chart.series.topics': 'Topics',
    'chart.axis.pc1': 'PC1',
    'chart.axis.pc2': 'PC2',
    'chart.range.high': 'High',
    'chart.range.low': 'Low',
    'ml.no_training_rows': 'No training data: every row has an empty text or label',
    'ml.need_two_labels': 'Training needs at least 2 distinct labels; this data only has: {label}',
    'ml.bad_model_name': 'Model name "{name}" is invalid: must be one path-safe component, no separators',
    'cluster.no_features': 'Text could not be segmented (symbols only?) — clustering skipped: {err}',
    'engine.source_no_platform': 'Node {nid}: source node has no platform',
    'engine.source_unknown_platform': 'Node {nid}: {platform} has no crawler yet — pick a supported platform',
    'engine.source_unknown_mode': 'Node {nid}: {platform} has no such collection mode — pick one under Collect',
    'engine.source_missing': 'Node {nid}: the required field {field} is empty',
    'engine.source_bad_option': 'Node {nid}: {field} has no option "{value}" — pick one of the choices in that node',
    'engine.source_no_cookie_account': (
        'Node {nid}: no cookie for the {platform} account "{account}" — save one in the Cookie panel, '
        'or pick an account that has a login (this never borrows another account and never '
        'silently under-collects)'
    ),
    'engine.source_link_mismatch': 'Node {nid}: {n} link(s) do not match the selected platform ({platform})',
    'engine.source_needs_machine': (
        'Node {nid}: this machine cannot run that collection mode ({reason}) — choose another mode or '
        'run the canvas on a machine that can'
    ),
    'engine.source_bad_backend': 'Node {nid}: the crawl backend "{backend}" does not exist — pick Selenium or CatBus',
    'engine.source_catbus': 'Node {nid}: the CatBus engine cannot crawl this cell: {detail}',
    'catbus.noRunnableCell': 'CatBus has no runnable read function for this platform',
    'cap.requiresWindowsDesktop': 'it needs the Windows desktop build (a local player or window to drive)',
    'engine.source_feed_no_mode': (
        'Node {nid}: this collection mode cannot be fed from an upstream table — '
        'only link-list forms take a fed column; disconnect the wire or pick another mode'
    ),
    'engine.source_feed_no_column': (
        'Node {nid}: an upstream table is wired in but no column was named for {field} to read row by row'
    ),
    'engine.source_feed_no_input': (
        'Node {nid}: a fed column is named but this node has no data input wired (a name-label wire does not count)'
    ),
    'source.feed_column_missing': 'Node {nid}: the upstream table has no column named {col}',
    'source.feed_skipped': 'upstream feed: skipped {n} empty cell(s) (no link to read)',
    'field.keyword': 'keyword',
    'field.urls': 'article URLs',
    'field.author': 'creator',
    'field.board': 'board',
    'field.account': 'account',
    'field.backend': 'backend',
    'field.catbusAccount': 'CatBus account',
    'field.catbusRoom': 'live room',
    'field.catbusFolder': 'collection folder',
    'field.catbusSeries': 'series',
    'field.catbusConversation': 'conversation ID',
    'field.catbusProduct': 'product',
    'field.catbusCommentId': 'comment ID',
    'field.format': 'format',
    'engine.upload_no_file': 'Node {nid}: upload node has no file selected',
    'engine.comment_no_urls': 'Node {nid}: comment node has no article URLs yet',
    'comment.no_urls': 'comment node has no crawlable URLs (supported: {platforms})',
    'comment.unsupported': 'comment node ignored {n} unsupported link(s) (supported: {platforms})',
    # Named because a count of dropped 「links」 sends the user hunting for a typo in a URL,
    # when what the node actually lacks is the platform that declared it takes plain names.
    'comment.unsupportedNames': (
        '{n} of them are names rather than links: feeding names needs the node to name its platform first '
        "(红果短剧's 评论 mode walks the player's own boards by title)"
    ),
    'comment.noAdapter': '{platform} has no comment crawler, so this link cannot be handled: {url}',
    'comment.commentsClosed': 'this content has no open comment section (or none yet): {url}',
    'comment.ytNoPage': 'the YouTube page never loaded as a video page (login or interception?): {url}',
    'comment.xNoList': '[X comments] the post page rendered nothing at all (dead, deleted, or blocked link): {url}',
    # YouTube is crawled as JSON from inside its own page, so these lines talk
    # about rounds and answers rather than about scrolling a list.
    'crawl.yt.noContext': '[YouTube] the page exposed no innertube config (intercepted, or the DOM changed): {url}',
    'crawl.yt.callFailed': '[YouTube] the {endpoint} call failed',
    'crawl.yt.badAnswer': '[YouTube] {endpoint} answered {status}, not JSON',
    'crawl.yt.wall': '[YouTube] a human-verification page was served: {url}',
    'crawl.yt.searchStart': '[YouTube] keyword "{kw}", target {n} results',
    'crawl.yt.authorStart': '[YouTube] creator "{author}" uploads, target {n} results',
    'crawl.yt.authorEmpty': '[YouTube] no creator given (@handle, channel link or UC… id): {author}',
    'crawl.yt.authorNotFound': '[YouTube] that address is not a channel page, so no channel id: {author}',
    'crawl.yt.authorNoVideos': "[YouTube] this creator's video tab holds nothing: {author}",
    'crawl.yt.page': '[YouTube] round {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.yt.noPage': '[YouTube] round {page} returned no items, stop paging',
    'crawl.yt.processed': '[YouTube] stored {i}: {title}',
    'crawl.yt.targetReached': '[YouTube] target of {n} rows reached, stop paging',
    'crawl.yt.drained': '[YouTube] the API stopped handing out a cursor, the list is exhausted',
    'crawl.yt.replay': '[YouTube] round {page} added nothing new, list treated as exhausted',
    'crawl.yt.noResults': '[YouTube] no public video matches "{kw}" (or this session is throttled)',
    'crawl.yt.finished': '[YouTube] collected {n} rows (target {total})',
    # X renders a virtualized timeline: the card count never grows while tweets
    # stream through it, so its log lines speak of rows kept, not cards on screen.
    'crawl.x.start': '[X] keyword "{kw}", target {n} posts (latest first)',
    'crawl.x.target_reached': '[X] target of {n} rows reached, stop scrolling',
    'crawl.x.authorStart': '[X] author "{author}" posts, target {n} posts',
    'crawl.x.authorEmpty': '[X] no author given (@handle or profile link): {author}',
    'crawl.x.wall': '[X] access was refused (login wall or 403): {url}',
    'crawl.x.loadSlow': '[X] the page did not finish loading in time; continuing with what rendered: {url}',
    'crawl.x.no_cards': '[X] no tweet rendered at all (blocked, too narrow, or an empty account): {url}',
    'crawl.x.finished': '[X] kept {n} posts (stopped because: {reason})',
    'comment.biliBadAnswer': 'bilibili comment endpoint returned no data (code={code}): {url}',
    'comment.biliShort': '[bilibili] cursor got {rows} of {declared} per the site (deep-page throttling): {url}',
    'comment.dyNoId': 'the link carries no video id, so comments cannot be fetched: {url}',
    'comment.dyNoPanel': 'the comment panel never rendered (collapsed, or login required): {url}',
    'comment.dyGone': (
        '[douyin comments] the site answered this link with a different video ({shown}); '
        'this link counts as dead, not as a wall: {url}'
    ),
    'comment.dyNone': 'this video reports {n} comments but the list did not open: {url}',
    'comment.dyShort': (
        '[douyin comments] {url}: the page says {declared}, this table holds {rows} plus {nested} counted '
        'replies ({gap} still not collected) — this walk ended because: {reason}, so the gap is not a claim '
        'that the thread is that short'
    ),
    'comment.weiboShowFailed': '[weibo comments] the comment endpoint answered nothing (dead cookie, limited): {url}',
    'comment.weiboReplay': (
        '[weibo comments] page {page} added no new row while the cursor was still live: '
        'the walk calls the thread replayed and stops, at {rows} rows'
    ),
    'comment.weiboShort': (
        '[weibo comments] the page says {declared}, this table holds {rows} (a gap of {gap})'
        ' — the missing rows are nested replies: this endpoint does not return them as a list in the'
        ' current session, and only the one preview each parent row carries is in the table'
    ),
    'comment.weiboFetchDied': (
        '[weibo comments] the comment request failed on page {page}, so the walk ended: {rows} rows kept'
        ' (the thread is labelled {declared}, {gap} of them unfetched; the cursor stayed on the page that'
        ' failed, so 继续 can pick it up)'
    ),
    'comment.zhihuNoPanels': '[zhihu comments] no comment panel on this answer (closed, or never loaded): {url}',
    'comment.zhihuNoAuthor': (
        '[zhihu comments] {n} of {total} rows carry no author link inside their own subtree (anonymous or collapsed)'
    ),
    'comment.zhihuPanelCapped': (
        '[zhihu comments] stopped after {n} scroll rounds (reply threads opened) with the panel still '
        'growing; took {rows} rows'
    ),
    'comment.zhihuRound': '[zhihu comments] round {r} added {n} rows ({total} so far)',
    'comment.zhihuPanelShort': '[zhihu comments] the page says {declared} comments, {rows} were taken',
    'comment.xhsPanelCapped': (
        '[xiaohongshu comments] stopped after {rounds} scroll rounds with the panel still growing; '
        'took {rows} rows: {url}'
    ),
    'comment.prefix': '[comments]',
    'comment.platformMismatch': 'skipped {n} link(s) that do not match the selected platform ({platform})',
    'comment.allMismatched': 'every link conflicts with the selected platform ({platform}) — check the article URLs',
    'comment.article': 'comments: {url} added {n} ({status})',
    'comment.done': (
        'comment crawl finished: {urls} links (ok {ok}, blocked {blocked}, '
        'dead {dead}), {rows} comments, {files} file(s)'
    ),
    'comment.status.ok': 'ok',
    'comment.status.blocked': 'login/risk-control wall',
    'comment.status.dead': 'link unreadable',
    'engine.process_no_op': 'Node {nid}: process node has no operation',
    'engine.output_no_op': 'Node {nid}: output node has no operation',
    'engine.output_no_upstream': 'Node {nid}: output node has no incoming connection, so there is no table to save',
    'engine.output_no_table': (
        "Node {nid}: none of the output node's upstreams produces a table "
        '(a name node is metadata, a visualize node answers a chart spec)'
    ),
    'engine.output_needs_pdf': (
        'Node {nid}: the upstream is a visualize/compile node, so the output format must be PDF'
    ),
    'engine.output_pdf_mixed': (
        'Node {nid}: a PDF output cannot mix with tabular upstreams — '
        'use only a visualize or compile node as the source'
    ),
    'engine.output_pdf_only_pdfable': 'Node {nid}: a PDF output must be fed by a visualize or compile node',
    'engine.output_pdf_two_sources': (
        'Node {nid}: a PDF output cannot take both a visualize node and a compile node — pick one'
    ),
    'engine.compile_no_upstream': 'Node {nid}: the compile node has no incoming connection (it needs a visualize node)',
    'engine.compile_bad_parent': (
        'Node {nid}: the compile node only accepts a visualize node’s LaTeX; upstream "{up}" is not one'
    ),
    'engine.compile_source_both_off': (
        'Node {nid}: the upstream visualize "{up}" has neither the LaTeX figure nor the three-line table box checked, '
        'so there is nothing to compile'
    ),
    'engine.analysis_no_op': 'Node {nid}: analysis node has no operation/steps configured',
    'engine.cycle': 'the workflow contains a cycle; these nodes cannot be ordered: {nodes}',
    'engine.dangling_connection': 'a connection points at a node the canvas does not hold: {src} → {dst}',
    'engine.empty_canvas': 'the canvas holds no nodes, so there is no workflow to run',
    'engine.unknown_node_type': 'Node {nid}: unknown node type "{type}", the workflow engine cannot execute it',
    'engine.tokenize_no_column': 'Node {nid}: tokenize node is missing its text column',
    'engine.visualize_no_chart': 'Node {nid}: visualize node has no chart type',
    'engine.visualize_no_x': 'Node {nid}: visualize node is missing the x field',
    'engine.name_no_label': 'Node {nid}: the name node needs a workflow name',
    'engine.name_not_head': 'Node {nid}: the name node must lead — nothing may feed into it',
    'engine.name_no_downstream': 'Node {nid}: the name node must connect to a downstream node',
    'wf.unknown_process_op': 'unknown process operation "{op}"',
    'wf.join_no_right_table': 'A join needs two incoming connections (left table first, right table second)',
    'analysis.join_no_right': "Join failed: no right-hand table — connect it as this node's second input",
    'analysis.join_need_keys': 'Join failed: set both the left and the right key column',
    'analysis.join_missing_cols': 'Join failed — no such column: {cols}',
    'api.alreadyRunning': 'A workflow is already running — stop it or wait for it to finish',
    'api.needConfirm': 'This acts on every record — send confirm=true explicitly to do it',
    'api.foreignOriginRefused': (
        'This server answers the local browser only: the request came from "{origin}" '
        'and is refused — the API is unauthenticated and holds real accounts'
    ),
    'api.killNoIdent': 'missing thread ident',
    'api.killNotFound': 'thread not found',
    'api.killProtected': 'cannot kill protected thread: {name}',
    'api.killLiveWorker': 'this is a live crawl worker; use Stop rather than killing it',
    'api.killNotAlive': 'thread is not alive',
    'api.killInvalidId': 'invalid thread ID',
    'api.killFailedGeneric': 'failed to kill thread',
    'api.killDone': 'thread "{name}" terminated',
    'run.cleared': 'Run records cleared: {runs} removed, and {claims} "already crawled" claims handed back',
    'exports.cleared': 'Export folder cleared: {n} file(s) removed',
    'exports.notAPart': '「{name}」 is not a shard file, so there is no batch to clear',
    'exports.clearBusy': 'A live run is writing part files into the export folder — stop it or wait before clearing',
    'lock.refuse': 'This item is locked — unlock it before deleting or clearing',
    'lock.badKey': 'The lock request is missing a valid panel or entry name',
    'api.needApiKey': 'The OpenRouter API key is missing (Settings → AI)',
    'api.needModel': 'No OpenRouter model selected (Settings → AI)',
    'api.needOllamaModel': 'No Ollama model selected (Settings → AI → Model; hit Refresh to list local ones)',
    'api.cloudNoLocalModel': (
        'This server has no local model to talk to ("{provider}" wants an Ollama daemon on its own '
        'host): a cloud deployment only supports OpenRouter — pick OpenRouter under Settings → AI and '
        'fill in the model and API key'
    ),
    'api.cloudNoLoginWindow': (
        'This server has no window to log into: paste the Cookies JSON into the Cookie panel and save, '
        "which builds that account's profile and plants the session into it"
    ),
    'api.platformRequired': 'Platform is required',
    'api.cookiesRequired': 'Cookies data is required',
    'api.unsupportedPlatform': 'Unsupported platform: {platform}',
    'api.badAccount': (
        'Invalid account name: {account} (letters, digits, _ and -, 1-24 of them; case does not '
        'make a second account — names are stored lowercase)'
    ),
    'api.cookieRenameEmptyTarget': 'The new name cannot be blank',
    'api.cookieRenameBadName': (
        'Invalid new name: letters, digits, _ and -, 1-24 of them (case does not make a second '
        'account — names are stored lowercase)'
    ),
    'api.cookieRenameDefault': (
        'The default account cannot be renamed: its browser directory IS the platform’s '
        'directory, with every other account inside it'
    ),
    'api.cookieRenameSameName': 'The old and new names are the same, so nothing was renamed',
    'api.cookieRenameNoSource': 'That account has no saved login to rename',
    'api.cookieRenameTaken': 'Another login already uses that name — pick a different one',
    'api.cookieRenameBusy': 'That account’s browser is in use; rename it after the current crawl ends',
    'api.cookieRenameFailed': 'Renaming failed: {err}',
    'api.profileDeleteBadName': (
        'Invalid account name: {account} (the default account has no separate profile directory to delete; '
        'letters, digits, underscore or hyphen, 1-24, stored lowercase)'
    ),
    'api.profileDeleteDefault': (
        'The default account has no browser profile to delete — its browser data IS the platform directory, '
        'and every other account is nested inside it'
    ),
    'api.profileDeleteBusy': (
        '{platform} · {account}’s browser is in use — wait for the running crawl to finish before deleting its profile'
    ),
    'api.llmModelsFailed': 'Could not fetch the OpenRouter model list: {err}',
    'api.ollamaModelsFailed': 'Could not list local Ollama models at {host} (running? address right?): {err}',
    'api.parseFailed': 'Could not parse the file: {err}',
    'api.unsupportedUpload': 'unsupported file type: {name} (accepted: .csv .tsv .json .txt .xlsx .xls)',
    'api.excelMultiSheet': (
        'workbook "{name}" has several non-empty sheets ({sheets}); one upload imports one sheet — split it first'
    ),
    'api.columnMissing': 'No such column in the data: {column}',
    'api.needLabeledRows': 'At least 10 labelled rows are needed, this data has {n}',
    'api.noSourceTable': 'None of the selected nodes could supply a table',
    'api.badRequest': 'Malformed request: {what}',
    'api.svgNotSvg': 'SVG refused: the content does not start with <svg or has no xmlns declaration',
    'api.svgTruncated': 'SVG refused: the file does not end with </svg> (it looks truncated)',
    'api.svgRefused': 'SVG refused: the markup carries {found}, which can smuggle a script or an external reference',
    'api.svgTooLarge': 'SVG refused: {cap} bytes is the cap, and that is not a drawn chart',
    'api.pdfNeedsName': 'PDF refused: name the registered LaTeX source of this chart',
    'api.pdfUnregistered': (
        'PDF refused: {name} is not in the run ledger, so this program never wrote it and xelatex will not be handed it'
    ),
    'api.pdfWrongKind': 'PDF refused: {kind} is not a LaTeX source; only a .txt this program registered is compiled',
    'api.pdfMissingFile': (
        'PDF refused: the ledger knows {name}, but the export folder no longer has it (it was cleared)'
    ),
    # ── runtime settings validation ───────────────────────────
    'set.driverMissing': 'Driver file does not exist: {path}',
    'set.driverEmpty': (
        'Driver path was empty — nothing is forced on it: Selenium fetches the driver matching the '
        'installed Chrome (the first time needs network)'
    ),
    'set.browserMissing': 'Browser executable does not exist: {path}',
    'set.latexMissing': 'LaTeX compiler (xelatex) does not exist: {path}',
    'set.harvestMissing': 'Hongguo harvest component ({tool}) is not an existing file: {path}',
    'set.catbusMissing': 'The CatBus component ({tool}) does not exist at that location: {path}',
    'set.catbusNeedFile': '{tool} wants the executable itself, not the folder holding it: {path}',
    'set.badWindow': 'Window size must look like WIDTHxHEIGHT (e.g. 1920x1080) — restored the default {default}',
    'set.badNumber': '{setting} is not a number — restored the default {value}',
    'set.outOfRange': '{setting} is outside {lo}-{hi} — restored the default {value}',
    'set.badOllamaHost': 'The Ollama address must start with http:// or https:// — restored the default',
    'set.badFlag': '{setting} needs a true/false value — restored the default',
    'set.badProfileDir': 'The profile directory must be an absolute path (got: {value}) — restored the built-in one',
    'set.saveFailed': 'Settings could not be written to disk (still active for this session): {err}',
    # ── resumable runs ────────────────────────────────────────
    'run.row_limit': 'Node {nid} hit its {limit}-row safety cap — further rows are not stored',
    'run.interrupted_by_restart': 'Interrupted by a service restart',
    'run.interrupted_by_dead_worker': 'Its worker thread is gone, so the record was settled as interrupted',
    'run.promoted': '{n} unfinished run(s) from an earlier session marked resumable',
    'run.claims_released': (
        'Rerun: handed back {n} "already crawled" claim(s) for run {rid} — those items will be crawled again'
    ),
    'run.reconciled': '{n} record(s) whose worker had already gone were settled as interrupted',
    'run.recordWriteFailed': (
        'Could not write the verdict for record {rid} ({err}): the run list settles it on the next refresh'
    ),
    'run.start_failed': 'Could not start the run worker ({err}): this run is dropped and the queue moves to the next',
    'run.nodeStopped': 'Node {nid} ended on Stop: {n} row(s) kept',
    'run.finished.stopped': ', {n} stopped',
    'crawl.chromeMissing': (
        'No Chrome on this machine, so a crawl has no browser to open. Install Chrome, or point '
        'Settings → browser path at it (the executable name on this system is {browser})'
    ),
    'crawl.browserBinaryMissing': (
        'The configured browser path does not exist: {path}. Correct it, or clear it and let the app find Chrome'
    ),
    'crawl.disguiseUnreadable': (
        'The headless disguise did not take: this browser could not read back its own User-Agent ({err}). '
        'This run continues as a bare headless Chrome, and some sites answer that with a page of nothing'
    ),
    'crawl.disguisePartial': (
        'The headless disguise was only partly applied ({err}). '
        'This run may still be recognised as headless — check here first when a crawl comes back short'
    ),
    'crawl.driverMissing': (
        'The configured chromedriver path does not exist: {path}. It usually went stale against a Chrome update — '
        'point it at the matching driver, or clear it and let Selenium fetch one (needs network the first time)'
    ),
    'crawl.browserStartFailed': (
        'The browser did not start: {err}. Usual causes: chromedriver does not match this Chrome build, the first '
        'automatic driver fetch needs network, or that Chrome profile directory is held by another Chrome'
    ),
    'crawl.stopped': 'Stop received — this crawl ends here',
    # Said by a session whose browser process was already reaped, so it must not claim a person did
    # anything: the same object answers a cookie window that was closed after its grace ran out.
    'crawl.driverDead': 'This browser process is already closed, so no further commands are sent to it',
    'run.started': 'This run is checkpointed as {rid} — every row lands in the database as it is produced',
    'run.resume_from': 'Resuming the run interrupted at {at} — {rows} rows already stored',
    'run.restored': 'Node {nid} reuses its previous result ({n} rows) instead of running again',
    'run.resume_crawl': 'Node {nid} continues crawling from where it stopped ({have} rows already saved)',
    'run.heavy_result': (
        'Memory note: node "{nid}" produced {n} rows, and every node\'s rows are held in memory until the run ends'
    ),
    'comment.need_both': (
        'Node {nid}: filtering comments by time needs BOTH a start and an end (a half range cannot bound the window)'
    ),
    'comment.bad_date': 'Node {nid}: the comment time range could not be parsed (use YYYY-MM-DD)',
    'comment.bad_range': 'Node {nid}: the comment time range ends before it starts',
    'comment.time_filtered': 'Node {nid}: filtered comments by time {start} ~ {end}: kept {kept}, dropped {dropped}',
    'run.recrawl': 'Re-crawl: released {n} dedupe records; this node will collect again',
    'run.watermarkUnsupported': (
        'Cross-run watermark supports only Bilibili author uploads (this platform/mode: {platform} / {mode})'
    ),
    'run.watermarkNoScope': (
        'A cross-run watermark needs the node fingerprint from a run context; a direct executor call cannot enable it'
    ),
    'run.watermarkLoaded': (
        'Cross-run watermark: starting from the previous boundary {boundary}; stop when it is reached'
    ),
    'run.watermarkFirst': 'Cross-run watermark: first run; the boundary is saved on success',
    'run.watermarkSaved': 'Cross-run watermark updated: {boundary} ({n} new rows this run)',
    'run.watermarkNoNew': 'Reached the previous boundary {boundary}; no newer items this run',
    'run.dedupe_skipped': (
        'Incremental: {n} already-collected items were skipped (enable Recrawl on the source node to re-collect)'
    ),
    'run.dedupe_all_skipped': (
        'every item of this node was already collected — nothing new flows downstream; '
        'enable Recrawl on the source node to re-collect, or reach the stored rows through '
        'the run records / a Resume node'
    ),
    'run.progress_file': 'progress export: {file} ({rows} rows in {parts} part files)',
    'run.live_export': 'live export: {file} (rewritten after every batch; kept when the run ends)',
    'run.live_export_failed': 'live export write failed: {err}',
    'run.cookieExpired': (
        'login session looks expired: the {platform} crawl was bounced to a login page '
        '(the cookie may have gone stale). Everything collected so far is kept — refresh '
        'the cookie under Settings -> Cookie, then resume the run from its checkpoint'
    ),
    'run.cookieExpiredOk': (
        'note: {platform} hit the login wall only after the target was met — the data is complete, nothing to resume'
    ),
    # A 风控 refusal is the OPPOSITE advice from a dead cookie: the session may be fine and
    # re-running straight into it only deepens the block, so the console names risk control,
    # says it is not a login problem, and tells the user to wait (继续 later), never re-save.
    'run.riskControlled': (
        '{platform} was stopped by a security check (risk control) before the target was met — this is NOT an expired '
        'login, and re-running immediately only deepens the block. Everything collected so far is kept; you can enable '
        'Settings -> Gentle crawling, then use 继续 / Resume later to pick up from the checkpoint'
    ),
    # U1: a crawl under its target that named no licensed end (site ran out / wall / risk /
    # the user's Stop) is a real under-collect, refused by name and left resumable — never
    # settled clean DONE. The walk funnel rides along because "refused N of M" is what tells
    # "the site had no more" from "our scraper dropped what it got" (§6 silent-under-collect).
    'run.underTargetShort': (
        '{platform} stopped at {have}/{want} rows without the site saying it ran out — that is not "finished". '
        '{have} rows are kept; press Continue to pick up the rest from the cursor{walk}'
    ),
    # The funnel clause only when the crawler reported counts; a convicted short without them
    # omits it rather than printing a fake measurement of zeros.
    'run.underTargetWalk': ' (walk: scanned {scanned}, kept {kept}, refused {refused})',
    'run.commentsSkipped': (
        '{platform}: {n} drama(s) were not harvested completely (never opened in the player, or the feed '
        'moved to another drama mid-walk): {names} — the other dramas’ rows are kept; Resume re-walks from '
        'the first incomplete one (comments already stored are deduped by 评论ID, so nothing double-stores)'
    ),
    # Said out loud because the alternative is silence that reads as "closed", while the
    # user may be looking at the window that is still open.
    'run.browserStuck': (
        'warning: {platform}\u2019s browser could not be closed (no readable process id); it may still be '
        'open and holds that platform\u2019s directory for up to {seconds} seconds'
    ),
    # A page that never arrived, said once with the one thing the crawler cannot know:
    # whether this machine can reach anything at all. ``{advice}`` is empty when the page
    # already named its own cause, so the sentence has to read in both shapes.
    'run.pagePending': '{page}{streak}{advice}',
    'run.pageStreak': '; this is the {n}th page in a row this machine has not delivered',
    'net.region': (
        '. Diagnosis: this machine cannot reach the side of the internet that platform lives on (the control host '
        'for it fails while the other answers) — switch network and run it again'
    ),
    'net.offline': (
        '. Diagnosis: this machine has no outbound connection at all right now (both control hosts fail), '
        'so restore the network before running again'
    ),
    'net.blocked': (
        '. Diagnosis: this machine routes normally but the platform host itself does not answer, '
        'which is a site outage or a local interception rather than a slow page'
    ),
    'net.slow': (
        '. Diagnosis: both sides connect, so there is no evidence for why this page did not arrive; '
        'run it again, or press Stop to end the run'
    ),
    'net.speed': ' (measured about {speed} kB/s)',
    'run.cookieAnyPlatform': 'the platform being crawled',
    'run.platformQueued': (
        '{platform} is being crawled by another workflow, so this one queued and starts in {n}s: two '
        'searches from one account in the same second are what gets bounced to the login page'
    ),
    'run.serialForced': (
        '{platform} crawls are forced to run one at a time: parallel paging on one account always draws the '
        "login wall, so this platform serializes by the site's rule, not by the 错峰 setting"
    ),
    'run.platformGateTimeout': (
        '{platform} waited {n}s for its turn to crawl and gave up: a browser window that never closed may be holding it'
    ),
    'run.platformStaggered': (
        '{platform} starts {n}s after the last same-platform crawl: this one queued behind nothing, so '
        'the two may still overlap — only their departures are kept apart, which is what stops one '
        'account issuing two searches in the same second'
    ),
    'run.queueAbandoned': 'the queue wait for {platform} was cancelled (this run stopped)',
    'run.wallRetry': (
        '{platform} was bounced to its login page before its first row, which reads as two concurrent '
        'searches from one account colliding: retrying once in {n}s'
    ),
    'crawl.profile_wait': 'queued {seconds} s: this profile runs one browser at a time — {dir}',
    'run.profileOff': (
        'this run uses no browser profile: every crawl is a brand-new device (so same-platform workflows '
        'really do run side by side), and the saved cookie snapshot is planted as usual'
    ),
    'run.skippedWorkflows': 'skipped this run (disabled, will not run): {names}',
    'crawl.profile_stuck': (
        'timed out waiting {seconds} s for the profile to free up: {dir} — a browser may have been left '
        'open; end the stray Chrome in the process panel and try again'
    ),
    'crawl.profile_gave_up': 'this run was stopped: no longer waiting for the profile ({dir}), this crawl stands down',
    'run.notCrawlable': (
        'the platform behind "{label}" ({platform}) can store a login cookie but has no crawler yet, so it cannot '
        'run as a data source — pick a supported platform, or wait for this one to land'
    ),
    'run.partial_down': 'Node {nid} interrupted — its {n} finished rows are handed downstream',
    'run.failed_down': 'Node {nid} failed with nothing usable — downstream sees an empty table',
    'run.skipped_empty': 'Node {nid} skipped: no data arrived from upstream',
    'run.finished': 'Run finished ({done}/{total} nodes)',
    'run.finished.skipped': ', {n} skipped',
    'run.finished.failed': ', {n} failed',
    'run.rejected': 'Nothing ran: the workflow has {n} problem(s), see the messages above',
    'resume.no_run': 'Resume node: no run selected, and no resumable run was found',
    'resume.empty': 'Resume node: "{nid}" of run {rid} has no stored rows',
    'resume.unpicked': 'no node picked',
    'resume.loaded': 'Resume node: loaded {n} rows from node {nid} of run {rid}',
    'api.runNotFound': 'No such run: {rid}',
    'api.runSettingOption': 'The canvas setting "{setting}" has no value "{value}" (available: {allowed})',
    'api.runLogTruncated': '(log too long — downloaded the first {n} lines only)',
    'api.exportNotFound': 'export file not found (or not downloadable): {name}',
    # ── one-click HTML report ───────────────────────────────────
    'report.generated': 'Generated',
    'report.default_title': '{name} · run report',
    'report.summary': 'This run had {nodes} node(s) and produced {rows} row(s); {tables} of them hold a table.',
    'report.charts': 'Charts',
    'report.run_facts': 'Run details',
    'report.tables': 'Tables',
    'report.conclusion': 'Conclusion',
    'report.no_charts': 'Nothing in these tables was chartable yet.',
    'report.chart_failed': 'Chart rendering failed: {err}',
    'report.chartsFailed': 'the report charts failed; its text and tables still came out',
    'report.no_rows': 'this node produced no rows',
    'report.more_rows': 'First {shown} of {total} rows shown; export the table as CSV for the rest.',
    'report.method_section': 'Method',
    'report.figure_section': 'Figures and tables',
    'report.table_suffix': ' (three-line table)',
    'report.table_continued': ' (continued)',
    'report.method_biblio': "{title}: {entity} as the unit of analysis. Parameters (this system's own enum names, "
    'identical to the run record and the exported tables): {body}.',
    'report.method_fuse': '{title}: folded several upstream tables into one canonical record table (each role tried '
    'against its candidate columns in order).',
    'report.method_analysis': '{title}: analysis steps {ops}.',
    'report.method_source': '{title}: collected {collect} from {platform}, target {target} items.',
    'report.method_upload': '{title}: dataset {name}.',
    'report.method_unverified': "These nodes' parameters could not be checked against the fingerprints the run "
    'recorded (the canvas changed, or its file is gone): {names}.',
    'report.method_no_canvas': 'This run has no saved canvas to read, so the document gives the run id and the time '
    'window only, with no parameters; save the canvas and run it again for a method section.',
    'report.method_provenance': 'This document was assembled from one run of workflow "{workflow}", run id {run_id}.',
    'report.method_window': 'Run window: {started} to {finished}.',
    'report.method_counts': '{figures} figures and {tables} three-line tables; each figure and its table come from '
    'the same table of rows the run filed.',
    'report.missing_charts': '{count} chart node(s) filed no LaTeX source, so this document holds no figure or '
    'table for them: {names}.',
    'report.latex_no_run': 'That run cannot be found ({rid}), so there is nothing to assemble.',
    'report.latex_no_sources': 'This run filed no LaTeX figure or table sources, so there is no document to build: '
    'tick "生成 LaTeX" on the visualize nodes and run it again.',
    'report.row_count': '{n} rows · {cols} columns',
    'report.fact.workflow': 'Workflow',
    'report.fact.run': 'Run id',
    'report.fact.status': 'Status',
    'report.fact.started': 'Started',
    'report.fact.finished': 'Finished',
    'api.reportNoData': 'nothing to report: run the workflow first, or pick a stored run',
    # ── run queue ─────────────────────────────────────────────
    'api.queued': 'Queued: it starts when the current run finishes (position {at})',
    'api.queueFull': 'the queue is full ({n} waiting) — wait for the current run, or cancel some',
    'run.queued': 'Queued (position {at}): {name}',
    'run.queuedUnnamed': 'an unnamed workflow',
    'run.queue_started': 'Queue: {name} started ({rid})',
    'run.queue_waited': 'Queue could not start {name} (a run is active), it waits again',
    'run.queue_broken': 'the queued request {name} could not start; skipped, the next one continues: {err}',
    'run.queue_restored': 'Restored {n} waiting run(s) after a restart',
    'run.queueMirrorFailed': 'failed to mirror the waiting-run queue (the in-memory queue is still authoritative)',
    'run.queueLoadFailed': 'failed to load the persisted run queue at startup (starting from an empty queue)',
    'run.queueStartFailed': 'a queued run could not be started',
    'run.browserReapFailed': (
        'the browser process still did not die after the stop timeout (PID {pid}): {err} — its profile '
        'directory stays claimed, so the next crawl of that platform waits for the lock to time out'
    ),
    'history.cleared': 'Execution history cleared',
    'api.workflowShapeInvalid': 'the workflow could not be read: an object with a nodes list is required',
    'api.workflowNodeNoId': (
        'a node on the canvas has no id, so it cannot run (the id is a node storage key) — '
        're-add the node or repair the workflow file'
    ),
    'api.resumeMissing': (
        'cannot continue: run {rid} has been purged, so it would re-crawl everything — press Run instead'
    ),
    'api.rerunNoRun': 'no saved run for this workflow was found; run it once before re-running a node',
    'api.rerunNoNode': 'node "{node}" is not on the current canvas, so it cannot be re-run',
    'api.rerunNoRows': 'node "{node}" has no completed result in the last run, so there is nothing to re-run from',
    'api.rerunRunLive': (
        'this run is still executing (or stopping), so none of its nodes can be re-run — '
        'wait for it to finish or stop it first'
    ),
    'api.rerunBusy': (
        "another run is still executing: a re-run deletes this subtree's saved rows first, "
        'so wait for it to finish before trying again'
    ),
    'api.rerunFingerprintMismatch': 'the canvas is not the same workflow as the chosen run, so its results cannot be '
    'reused safely — re-run the node from the run details',
    'api.historyNoRunId': 'no run id given, so no execution history was deleted',
    'run.store_unavailable': 'this run could not begin: the run record store would not open (disk full, corrupt or '
    'locked file) — nothing was recorded',
    'run.reportSaved': 'Report written: {name} ({size} bytes)',
    'run.reportFailed': 'Report failed: {err}',
    'run.reportConclusionFailed': 'The conclusion could not be generated, so the report omits it: {err}',
    'run.reportLatexSaved': 'Paper document compiled: {name} ({figures} figures / {tables} tables)',
    'run.reportLatexFailed': 'Paper document failed: {err}',
    'run.compileSaved': 'PDF compiled: {name} ({size} bytes)',
    'run.compileFailed': 'LaTeX compilation failed: {err}',
    'api.compilePdfFailed': 'LaTeX to PDF compilation failed: {err}',
    'api.compilePdfNoPackage': 'LaTeX is missing the package {package}.sty: {remedy}',
    'api.compilePdfNoFont': 'LaTeX cannot find the font {font}: {remedy}',
    # ── housekeeping ──────────────────────────────────────────
    'housekeeping.done': (
        'Housekeeping: dropped {runs} expired run record(s) and {files} orphaned file(s) '
        '(plus {cache} cached model answer(s) and {seen} stale dedupe key(s))'
    ),
    'housekeeping.runStoreFailed': 'Automatic run-record cleanup failed (the run itself is unaffected)',
    'housekeeping.datasetStoreFailed': 'Automatic orphan-file cleanup failed (the run itself is unaffected)',
    'crawl.stopReason.target': 'reached the target count',
    'crawl.stopReason.end': 'reached the end of the list',
    'crawl.stopReason.no_new': 'no new rows after paging',
    'crawl.stopReason.stuck': 'scrolling produced nothing new',
    'crawl.stopReason.no_cards': 'the page rendered no list',
    'crawl.stopReason.empty_page': 'a page came back empty',
    'crawl.stopReason.fetch_failed': 'the list request failed',
    'crawl.stopReason.stopped': 'the run was stopped',
    'crawl.stopReason.wall': 'a login wall stopped the walk',
    'crawl.stopReason.risk': "the site's risk control stopped the walk (not a dead cookie)",
    'crawl.stopReason.unreachable': 'the browser never fetched a page at all (network or DNS),'
    ' so the site never saw this session',
    # ── scheduled tasks ───────────────────────────────────────
    'sched.notWired': 'the scheduler is not wired up (a server start-up order problem, not this task)',
    'sched.badTask': 'this task is not an object, so it cannot be saved',
    'sched.nameRequired': 'give this scheduled task a name',
    'sched.nameTooLong': 'a name is at most {n} characters',
    'sched.workflowRequired': 'choose the canvas this task should run',
    'sched.canvasMissing': 'no canvas named "{name}" (it was renamed or deleted)',
    'sched.canvasNeedsModel': 'canvas "{name}" has steps that need a model — a scheduled task never '
    'touches one (the credential only lives in the browser)',
    'sched.canvasReadFailed': 'reading canvas "{name}" failed, so this task was skipped',
    'sched.taskMissing': 'no such scheduled task: {id}',
    'sched.storeUnreadable': 'the scheduled-task file could not be read; it was kept aside as .corrupt: {path}',
    'sched.badTrigger': 'unknown trigger: {kind}',
    'sched.badClock': 'a time is written HH:MM (for example 08:30); got "{at}"',
    'sched.badWeekday': 'pick a weekday from Monday to Sunday; got "{value}"',
    'sched.badInterval': 'the interval must be between 1 and {hi} minutes; got "{value}"',
    'sched.badTimezone': 'unknown time zone: {name} (use an IANA name such as Asia/Shanghai; leave it '
    "blank for the server's own zone)",
    'sched.neverFires': 'this rule never fires: {expr}',
    'sched.cronMinute': 'minute',
    'sched.cronHour': 'hour',
    'sched.cronDay': 'day-of-month',
    'sched.cronMonth': 'month',
    'sched.cronWeekday': 'day-of-week',
    'sched.cronBadCount': 'a cron expression has 5 fields (minute hour day month weekday); got {n}: {expr}',
    'sched.cronBadField': 'the {field} field could not be read: {value}',
    'sched.cronBadRange': 'the {field} field has a backwards range: {value}',
    'sched.cronBadStep': "the {field} field's step must be an integer of 1 or more: {value}",
    'sched.cronBadStepBase': "the {field} field's '/' may only follow * or a-b: {value}",
    'sched.cronOutOfRange': 'the {field} field is out of range ({lo}-{hi}): {value}',
    'sched.weekday1': 'Monday',
    'sched.weekday2': 'Tuesday',
    'sched.weekday3': 'Wednesday',
    'sched.weekday4': 'Thursday',
    'sched.weekday5': 'Friday',
    'sched.weekday6': 'Saturday',
    'sched.weekday7': 'Sunday',
    'sched.zoneLocal': 'server local',
    'sched.everyDay': 'every day at {at}',
    'sched.everyWeek': 'every {weekday} at {at}',
    'sched.everyMinutes': 'every {n} minutes',
    'sched.cronAt': 'cron: {expr}',
    'sched.fired': 'scheduled task "{name}" came due — the run has started',
    'sched.firedManual': 'scheduled task "{name}" was triggered by hand — the run has started',
    'sched.startFailed': 'scheduled task "{name}" could not start; it was written into its own history',
    'sched.missedLine': (
        'scheduled task "{name}" missed a moment (the server was not running) — skipped and rescheduled'
    ),
    'sched.tickFailed': 'the scheduled-task clock hit an error (this check was skipped; the next one runs)',
    # The second crawl backend, CatBus (services/catbus_bridge.py). Every sentence names which part
    # is missing: an answer this side cannot read must never arrive as an empty table, because a node
    # settles DONE on an empty table.
    'catbus.noNode': 'this machine has no Node runtime, so the CatBus backend is unavailable (CIXI_NODE_BIN names one)',
    'catbus.noCli': (
        'this machine has Node but no CatBus adapter for 采析绘 — point CIXI_CATBUS_CLI at the entry file, '
        'or CATBUS_HOME at a source checkout'
    ),
    'catbus.oldNode': 'CatBus will not run on this Node: {node} reports {version} (needs 22.22.2 / 24.15.0 / 26.0.0)',
    'catbus.probeFailed': 'the CatBus adapter could not report its capability list: {detail}',
    'catbus.probeUnreadable': 'the CatBus adapter answered with something unreadable: {detail}',
    'catbus.notInManifest': 'the CatBus manifest has no {platform} / {mode} entry, so it cannot crawl that cell',
    'catbus.timeout': 'CatBus did not return within {seconds} seconds; the process was terminated',
    'catbus.stopped': '{platform} / {mode} was stopped through CatBus; the rows already stored are kept',
    'catbus.columnDrift': 'the columns CatBus returned do not match the manifest: missing {missing}, extra {extra}',
    'catbus.noDetail': 'this backend does not fetch a detail on its own (the adapter resolves each card): {url}',
    'catbus.targetReached': 'the target of {n} rows is already in the table, so CatBus asks for nothing',
    'catbus.start': 'CatBus starts crawling: {mode}, target {n} rows',
    'catbus.startOnce': 'CatBus starts: {mode}',
    'catbus.watermarkNote': (
        'CatBus has no offset: the watermark bounds which rows are filed, while older items are still asked for'
    ),
    'catbus.watermarkHit': 'CatBus reached the watermark {i}; the older rows are not filed',
    'catbus.finished': 'CatBus finished: {n} new rows (target {want})',
    'catbus.finishedOnce': 'CatBus finished: {mode}, {n} new rows',
    'catbus.warning': 'CatBus reported: {text}',
    'catbus.refused': '{platform} / {mode} could not be crawled through CatBus: {detail}',
    'catbus.noIdentity': (
        '{platform} / {mode} declares no identity column to CatBus, so the cross-run watermark has '
        'nothing to bound — refused'
    ),
    'catbus.paramUnsupported': (
        'CatBus {platform} / {mode} does not accept these collection conditions: {params}. '
        'The adapter would ignore them, and a table that looks like the condition ran is worse than '
        'a refusal — switch to Selenium or remove those conditions'
    ),
    'catbus.pre.login': '{platform} has no logged-in CatBus account',
}

MESSAGES = {'zh': _ZH, 'en': _EN}


# ─── Runtime language ───────────────────────────────────────────


def normalize(value) -> str:
    """Map any accepted spelling ('zh-CN', 'en-US', 'ZH', None) onto a
    catalogue language, falling back to the default for anything unknown."""
    text = str(value or '').strip().lower().replace('_', '-')
    for lang in LANGS:
        if text == lang or text.startswith(lang + '-'):
            return lang
    return DEFAULT_LANG


def get_lang() -> str:
    """Thread-local language; defaults to zh for anything not driven by a
    request (startup messages, manual runs, tests)."""
    return getattr(_local, 'lang', None) or DEFAULT_LANG


def set_lang(value):
    """Pin the language for this thread. Workflow worker threads must call
    this themselves — thread-locals are not inherited from the starter."""
    _local.lang = normalize(value)
    return _local.lang


#: What a message carries in ``{platform}`` is a **storage key** — that is what the crawl
#: matrix, the cookie files, the browser profiles and the run records are all addressed by.
#: Printed as-is it put a bare ``zhihu`` into a Chinese console and into the pre-run dialog,
#: so the key is named in the language the message is already answering in. One rule here,
#: so every line that mentions a platform is translated — including lines written later.
#: The values are pinned equal to the frontend's ``platform.*`` catalogue by
#: ``test_frontend_contract.py::TestPlatformLabelParity``.
_PLATFORM_LABELS = {
    'zh': {
        'zhihu': '知乎',
        'weibo': '微博',
        'xiaohongshu': '小红书',
        'wechat': '微信',
        'bilibili': '哔哩哔哩',
        'douyin': '抖音',
        'hongguo': '红果短剧',
        'twitter': 'X（推特）',
        'instagram': 'Instagram',
        'youtube': 'YouTube',
        'kuaishou': '快手',
        'tiktok': 'TikTok',
        'jd': '京东',
        'taobao': '淘宝',
        'xianyu': '闲鱼',
    },
    'en': {
        'zhihu': 'Zhihu',
        'weibo': 'Weibo',
        'xiaohongshu': 'Xiaohongshu',
        'wechat': 'WeChat',
        'bilibili': 'Bilibili',
        'douyin': 'Douyin',
        'hongguo': 'Hongguo Short Drama',
        'twitter': 'X (Twitter)',
        'instagram': 'Instagram',
        'youtube': 'YouTube',
        'kuaishou': 'Kuaishou',
        'tiktok': 'TikTok',
        'jd': 'JD',
        'taobao': 'Taobao',
        'xianyu': 'Xianyu',
    },
}


def platform_label(key, lang: str | None = None) -> str:
    """The word a user reads for a platform key, or the key itself when it is not one.

    Domains (``weibo.com``) and free text pass through untouched: this names keys, it does
    not judge whether a string was meant to be one.
    """
    table = _PLATFORM_LABELS.get(lang or get_lang()) or {}
    return table.get(str(key), str(key))


def _name_platforms(params: dict) -> dict:
    """Localize ``platform`` / ``platforms`` placeholders on the way into a template.

    Callers hand this slot either one key, a list of them, or a string they joined
    themselves — all three are answered, because a half-translated list is the same bug
    with a comma in it. A value that is not made of platform keys (a domain, a free-text
    reason) is passed through untouched.
    """
    named = dict(params)
    # The enumeration comma is language-specific: '、' reads right in Chinese and wrong
    # in English ("Zhihu、Weibo"). Pick the joiner by the reader's language.
    sep = '、' if get_lang() == 'zh' else ', '
    for slot in ('platform', 'platforms'):
        value = named.get(slot)
        if isinstance(value, str):
            # Split on a list separator and nothing else. Splitting on whitespace or on
            # `/` looked harmless and was not: a refusal that names what it refused
            # (`../x`) came back mangled, and a sentence would have been re-joined with
            # 、. An unknown token is passed through whole, which is the safe answer for
            # every value that was never a platform key.
            named[slot] = sep.join(
                platform_label(part.strip()) for part in re.split(r'[,、]', value.strip()) if part.strip()
            )
        elif isinstance(value, (list, tuple, set)):
            named[slot] = sep.join(platform_label(item) for item in value)
    return named


def t(key: str, **params) -> str:
    """Render ``key`` in the current thread's language.

    Missing key -> the key itself (so gaps are visible in the console).
    Missing parameter -> the raw template, never a crash mid-crawl.
    """
    lang = get_lang()
    table = MESSAGES.get(lang) or {}
    template = table.get(key)
    if template is None:
        template = MESSAGES.get(DEFAULT_LANG, {}).get(key)
    if template is None:
        logger.debug('i18n: missing message key "%s"', key)
        return key
    if not params:
        return template
    params = _name_platforms(params)
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.debug('i18n: bad params for "%s": %r', key, params)
        return template


#: Machine stop-tokens a crawl walk can end on (``engine/feed.py`` / ``engine/pager.py`` return
#: these). The engine stays language-free; a log line wraps the token here so the console reads a
#: reason, not a code word like ``stuck``. An unknown token falls through unchanged rather than
#: inventing a sentence, so a new engine reason is visible, never silently swallowed.
STOP_REASONS = {
    'target': 'crawl.stopReason.target',
    'end': 'crawl.stopReason.end',
    'no_new': 'crawl.stopReason.no_new',
    'stuck': 'crawl.stopReason.stuck',
    'no_cards': 'crawl.stopReason.no_cards',
    'empty_page': 'crawl.stopReason.empty_page',
    'fetch_failed': 'crawl.stopReason.fetch_failed',
    'stopped': 'crawl.stopReason.stopped',
    # Not an engine token: a walk over a *list of URLs* (weibo's hourly windows) ends on the wall
    # itself, not on one page's shape, and it must still read as a reason rather than as a code word.
    'wall': 'crawl.stopReason.wall',
    'risk': 'crawl.stopReason.risk',
    'unreachable': 'crawl.stopReason.unreachable',
}


def stop_reason_label(reason: str) -> str:
    """Render a crawl walk's stop token as a user-readable phrase in the current language."""
    key = STOP_REASONS.get(str(reason or '').strip())
    return t(key) if key else str(reason)


def missing_keys() -> dict:
    """Catalogue gaps per language — used by the tests so a half-translated
    message cannot ship."""
    zh, en = set(_ZH), set(_EN)
    return {'en_only': sorted(en - zh), 'zh_only': sorted(zh - en)}


def audit() -> list[str]:
    """Self-check the catalogue; an empty list means it is healthy.

    Worth calling at startup: a leftover printf placeholder ('端口 %s') does
    not raise — ``str.format`` just fails and ``t()`` hands back the raw
    template, so the user sees a literal ``%s`` in the console and nothing
    points at the cause. This turns that into a warning that names the key.
    """
    problems = []
    for key in sorted(set(_ZH) | set(_EN)):
        for lang, table in MESSAGES.items():
            template = table.get(key)
            if template is None:
                problems.append(f'{key}: missing translation for {lang}')
                continue
            if _BAD_PLACEHOLDER.search(template):
                problems.append(f'{key} [{lang}]: printf-style placeholder in "{template}"')
    return problems
