"""The bibliometrics node and the cross-source fuse — entity types, output shapes, clusters,
bursts and the workspace panel.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/test_i18n.py``).
"""

ZH = {
    'biblio.aliases_applied': '别名合并：{n} 个节点标签已按用户映射归一',
    'biblio.bad_option': '{nid}：{param} 的值「{value}」无效（可选：{allowed}）',
    'biblio.betweenness_sampled': '节点数 {n} 超过 2000，中介中心性使用 {k} 个源点采样',
    'biblio.build_done': '文献计量完成：{entity}，{nodes} 个节点 / {edges} 条边（{start}–{end}）',
    'biblio.burst_done': '突现检测：{nodes}/{total} 个节点有突现',
    'biblio.burst_truncated': (
        '节点表只标记最强 {kept}/{total} 段突现（图上展示上限来自 burst_top；完整突现表仍在 CSV 产物中）'
    ),
    'biblio.citation_expansion_done': '引文扩展 depth={depth}：通过数据集内已有文献新增 {added} 条可解析引文',
    'biblio.cluster_label_unmatched': '簇 {cluster}：本次运行没有这个簇，该行标签未生效',
    'biblio.cluster_labels_applied': '人工簇标签已应用：{n} 条',
    'biblio.cluster_labels_need_cluster': '{nid}：填写了人工簇标签但未开启聚类，请开启聚类或清空该框',
    'biblio.cluster_too_many': '节点数 {n} 超过谱聚类上限 {cap}：请收紧 TopN/时间范围，或关闭聚类',
    'biblio.col.主导话题': '主导话题',
    'biblio.col.前邻居': '前邻居',
    'biblio.col.后邻居': '后邻居',
    'biblio.col.情感倾向': '情感倾向',
    'biblio.col.情感分布': '情感分布',
    'biblio.col.新增邻居': '新增邻居',
    'biblio.col.消失邻居': '消失邻居',
    'biblio.col.结束年': '结束年',
    'biblio.col.结构变化': '结构变化',
    # The paper's three-line table prints the variation columns by name, so the server needs the
    # words too — same keys the browser catalogue uses for the panel's table headers.
    'biblio.col.节点': '节点',
    'biblio.col.话题分布': '话题分布',
    'biblio.col.起始年': '起始年',
    'biblio.column_missing': '文献计量需要「{col}」列（{entity}），当前表没有该列',
    'biblio.compare_needs_two': '对比需要两个不同的快照（基准与当前）',
    'biblio.counting_fractional': '分数计数：每篇文档把 1 份信用均分给它承载的实体，{docs} 篇文档参与折算',
    'biblio.counting_no_coupling': (
        '{nid}：耦合网络（{entity}）里两篇施引文献就是连边的两端，没有第三方文档的信用可拆分，'
        '分数计数（fractional）不适用；请改回 full 或换用共被引/共现类型'
    ),
    'biblio.coupling_no_burst': '{nid}：文献耦合的节点是施引文献本身，突现检测在此没有意义；请关闭突现',
    'biblio.dual_map_columns': '双图叠加 basemap 需要期刊列（{journal}）和学科列（{category}）',
    'biblio.dual_map_done': '双图叠加已生成：期刊 {journals} 个 / 学科 {categories} 个',
    'biblio.dual_map_needs_basemap': '{nid}：输出形态 dual_map 需要选择期刊—学科 basemap 数据集',
    'biblio.eigen_failed': '特征向量中心性未收敛，已改用归一化加权度（0–1）作为回退并播报',
    'biblio.entity.article': '被引文献（Article）',
    'biblio.entity.author': '作者',
    'biblio.entity.author_cocitation': '作者共被引',
    'biblio.entity.bibliographic_coupling': '文献耦合',
    'biblio.entity.category': '学科',
    'biblio.entity.country': '国家/地区',
    'biblio.entity.document': '文献（耦合）',
    'biblio.entity.document_cocitation': '文献共被引',
    'biblio.entity.funder': '基金/资助机构',
    'biblio.entity.grant': '基金（Grant）',
    'biblio.entity.institution': '机构',
    'biblio.entity.journal': '来源期刊（耦合）',
    'biblio.entity.journal_cocitation': '期刊共被引',
    # ── bibliometrics / knowledge graph ───────────────────────
    'biblio.entity.keyword': '关键词',
    'biblio.entity.source': '来源期刊（Source）',
    'biblio.entity.term': '主题词',
    'biblio.exclusions_applied': '排除列表：{n} 个节点标签已按用户设置移除',
    'biblio.export_failed': '文献计量导出失败：{err}',
    'biblio.import_duplicates': '{n} 条重复文献已合并',
    'biblio.import_no_year': '{n} 条文献缺少年份',
    'biblio.import_ok': '已识别 {format} 文献导出：{n} 条记录',
    'biblio.import_skipped': '{n} 条空记录已跳过',
    'biblio.isolates_dropped': '{n} 个孤立节点在成图后没有连边，已从节点表移除',
    'biblio.label_fallback': '聚类标签方法 {asked} 没有可用文本，实际使用 {used}（已在运行摘要中如实标明）',
    'biblio.largest_component': '已保留最大连通分量：节点 {before} → {after}，其余分量已剪除',
    'biblio.links_too_large': '节点「{node}」的连接 JSON 超过 {cap} 字节：请降低最大连边数',
    'biblio.mst_done': 'MST 剪枝（{scope}）：{before} → {after} 条边',
    'biblio.no_edges': '{start}–{end} 年没有共现边：请降低阈值、扩大时间范围或换一种实体类型',
    'biblio.no_edges_after_component': '保留最大连通分量后没有边：请关闭该选项或降低筛选阈值',
    'biblio.no_edges_after_prune': '{pruning} 剪枝后没有边：请减少最大连边数或改用 none',
    'biblio.no_edges_after_threshold': '阈值 (c, cc, ccv) 过滤后没有边：请降低 cc/ccv 或扩大时间范围',
    'biblio.no_records': '没有可用文献记录：请确认年份列可解析',
    'biblio.no_records_in_range': '{start}–{end} 范围内没有文献记录',
    'biblio.overlay_no_labels': (
        '「{col}」列没有任何标签（{n} 条记录全为空）：无法叠加，请先检查上游情感/情绪/话题步骤是否真的写出了这一列'
    ),
    'biblio.overlay_no_nodes': '「{col}」有标签，但没有任何留下来的节点带标签，叠加列为空',
    'biblio.overlay_partial': '「{col}」：{n}/{total} 条记录没有标签，未计入叠加（分母只含已标注文档）',
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
    'biblio.project_needs_name': '项目需要一个名字（重命名同样如此）',
    'biblio.project_not_found': '找不到项目 {pid}：它可能已被删除',
    'biblio.pruning_scope.merged': '合并网络',
    'biblio.pruning_scope.slices': '逐切片',
    'biblio.records_skipped': '{n} 条记录没有可分析的实体，已跳过',
    'biblio.refs_field_low': '{field} 解析率 {rate} 低于 {floor}：无法可靠构建引文图谱',
    'biblio.refs_low_rate': '参考文献解析率 {rate} 低于 {floor}：无法可靠构建引文图谱',
    'biblio.refs_missing': (
        '{type} 需要参考文献：每条记录至少 2 条【参考文献】；CNKI RefWorks 通常不含参考文献，请改用 CSSCI 导出'
    ),
    'biblio.shape_needs_burst': '{nid}：输出形态 bursts 需要开启突现检测，请先开启或改回 nodes/edges',
    'biblio.shape_needs_cluster': '{nid}：输出形态 clusters 需要开启聚类，请先开启或改回 nodes/edges',
    'biblio.shape_needs_variation': '{nid}：输出形态 variation 需要开启结构变异检测，请先开启或改回其它形态',
    'biblio.snapshot_done': '[文献计量] 已存快照「{label}」：{nodes} 个节点 / {edges} 条连边（参数已核对：{verified}）',
    'biblio.snapshot_not_found': '找不到快照 {sid}：它可能已被删除',
    'biblio.time_range': '{nid}：时间范围无效：{start} > {end}',
    'biblio.too_many_edges': '边数 {n} 超过上限 {cap}：请收紧 TopN/最大连边数',
    'biblio.too_many_nodes': '节点数 {n} 超过上限 {cap}：请收紧 TopN 或缩短时间范围',
    'biblio.variation_done': '结构变异：{rows} 行（最高 {node} {pair} = {score} bit，阈值 {floor}）',
    'biblio.variation_empty': '结构变异：没有节点在相邻切片间的连接模式变化达到阈值 {floor} bit',
    'biblio.variation_needs_slices': (
        '结构变异要比较相邻两个切片，本次只有 {n} 个切片可比（请缩小 slice_years 或放宽年份范围）'
    ),
    'biblio.variation_no_coupling': (
        '结构变异只适用于按年切片的关系网络：耦合网络（{entity}）的连边属于两篇施引文献、不属于某一年，'
        '没有切片间的变化可测'
    ),
    'biblio.watch.burst_added': '新突现',
    'biblio.watch.burst_removed': '突现结束',
    'biblio.watch.burst_strength': '突现强度变化',
    'biblio.watch.cluster_added': '新簇',
    'biblio.watch.cluster_relabeled': '簇改名',
    'biblio.watch.cluster_removed': '簇消失',
    'biblio.watch.cluster_size': '簇规模变化',
    'biblio.watch.edge_added': '连边新增',
    'biblio.watch.edge_removed': '连边消失',
    'biblio.watch.edge_weight': '连边强度变化',
    'biblio.watch.first': '首次建档（节点数/连边数）',
    'biblio.watch.node_added': '节点新增',
    'biblio.watch.node_changed': '节点属性变化',
    'biblio.watch.node_removed': '节点消失',
    'biblio.watch.nothing': '无变化',
    'biblio.watch.param': '参数变化',
    'biblio.watch_baseline_missing': '{nid}：监测项目里找不到基准「{label}」（现有：{known}）',
    'biblio.watch_done': '[监测] 项目「{project}」：「{baseline}」→「{label}」，{detail}'
    '（每类最多列 {limit} 条，总数见括号）',
    'biblio.watch_empty': '{nid}：本次图谱没有任何节点或连边，无法建档监测（空表会让下次对比把全部实体报成消失）',
    'biblio.watch_first_done': '[监测] 项目「{project}」已建档「{label}」：{nodes} 个节点 / {edges} 条连边；'
    '无更早的快照可比',
    'biblio.watch_needs_entity_table': '{nid}：监测需要一行一实体的输出形态，{shape} 的行不是实体表',
    'biblio.watch_needs_project': '{nid}：填了监测基准或捕获名却没填监测项目，请先写项目名或清空这两个框',
    'biblio.watch_params_differ': '[监测] 有 {n} 项参数与基准不同（{names}）——先排除是节点被改过，再读成领域变了',
    'biblio.watch_project_created': '[监测] 项目「{name}」不存在，已新建（本次为该项目的第一个快照）',
    'biblio.watch_project_note': '由文献计量节点的跨 run 监测自动建档',
    'biblio.watch_shape_differs': '[监测] 基准是 {a} 形态、本次是 {b} 形态，两者的行数差不是领域的变化',
    'biblio.watch_unchanged': '[监测] 图谱与基准完全一致（{nodes} 个节点 / {edges} 条连边）：上游没有新数据时会这样',
    'biblio.wide_ref_skipped': '{n} 条参考文献被超过 {cap} 篇文献同时引用，已跳过其两两配对（过大团会淹没图）',
    'biblio.workspace_empty_table': '{nid}：该节点没有已存行（可能被停止、失败或已被清理策略删除）',
    'biblio.workspace_no_node': '运行 {rid} 中没有节点 {nid}：请重新选择运行',
    'biblio.workspace_not_biblio': '{nid}：该节点不是文献计量节点，工作区只读文献计量产出表',
    'biblio.year_missing': '{n} 条记录缺少年份，已跳过（时间切片需要年份）',
    'fuse.build_done': '[跨源融合] {parents} 张表 → {rows} 条记录，来源：{sources}',
    'fuse.empty_parent': '{nid}：上游 {pid} 没有行，无法参与融合',
    'fuse.needs_entity': '{nid}：跨源融合需要至少一个实体候选列（如 关键词,话题）',
    'fuse.no_entity_column': '{nid}：上游 {pid} 没有可作实体的列（试过：{wanted}）',
    'fuse.no_input': '{nid}：跨源融合需要至少一个输入表',
    'fuse.no_rows': '{nid}：上游 {pid} 的「{column}」列没有提出任何实体',
    'fuse.source_named': '[跨源融合] 来源「{source}」：{pid} 贡献 {rows} 条',
}

EN = {
    'biblio.aliases_applied': 'Alias merge: {n} node labels were normalized by the user mapping',
    'biblio.bad_option': '{nid}: {param} = "{value}" is not valid (allowed: {allowed})',
    'biblio.betweenness_sampled': 'More than {n} nodes; betweenness uses {k} sampled sources',
    'biblio.build_done': 'Bibliometrics done: {entity}, {nodes} nodes / {edges} edges ({start}–{end})',
    'biblio.burst_done': 'Burst detection: {nodes}/{total} nodes have a burst',
    'biblio.burst_truncated': (
        'The node table marks only the strongest {kept}/{total} bursts (burst_top controls the chart; '
        'the full burst table is still in the CSV artifact)'
    ),
    'biblio.citation_expansion_done': (
        'Citation expansion depth={depth}: added {added} parseable references from records in this table'
    ),
    'biblio.cluster_label_unmatched': 'Cluster {cluster}: this run has no such cluster, that line did nothing',
    'biblio.cluster_labels_applied': 'Manual cluster labels applied: {n}',
    'biblio.cluster_labels_need_cluster': '{nid}: manual cluster labels without clustering; enable it or clear the box',
    'biblio.cluster_too_many': (
        'Node count {n} exceeds the spectral-clustering cap ({cap}): narrow TopN/the time range, or turn clustering off'
    ),
    'biblio.col.主导话题': 'Dominant topic',
    'biblio.col.前邻居': 'Neighbours before',
    'biblio.col.后邻居': 'Neighbours after',
    'biblio.col.情感倾向': 'Dominant sentiment',
    'biblio.col.情感分布': 'Sentiment distribution',
    'biblio.col.新增邻居': 'Gained neighbours',
    'biblio.col.消失邻居': 'Lost neighbours',
    'biblio.col.结束年': 'To year',
    'biblio.col.结构变化': 'Structural change (bits)',
    'biblio.col.节点': 'Node',
    'biblio.col.话题分布': 'Topic distribution',
    'biblio.col.起始年': 'From year',
    'biblio.column_missing': 'Bibliometrics needs the "{col}" column ({entity}); this table has no such column',
    'biblio.compare_needs_two': 'Comparing needs two different snapshots (baseline and current)',
    'biblio.counting_fractional': (
        'Fractional counting: each document spreads one unit of credit over the entities it carries '
        '({docs} documents contributed)'
    ),
    'biblio.counting_no_coupling': (
        '{nid}: in a coupling network ({entity}) the two citing documents ARE the endpoints of the link, so there '
        'is no third document whose credit could be split — fractional counting does not apply; use full counting '
        'or a co-citation / co-occurrence node type'
    ),
    'biblio.coupling_no_burst': (
        '{nid}: bibliographic-coupling nodes are the citing papers themselves; burst detection has no meaning '
        'there — turn burst off'
    ),
    'biblio.dual_map_columns': (
        'The dual-map basemap needs a journal column ({journal}) and a category column ({category})'
    ),
    'biblio.dual_map_done': 'Dual map built: {journals} journals / {categories} categories',
    'biblio.dual_map_needs_basemap': '{nid}: output_shape dual_map needs a journal-category basemap dataset',
    'biblio.eigen_failed': (
        'Eigenvector centrality did not converge; normalized weighted degree (0–1) was used and printed'
    ),
    'biblio.entity.article': 'Cited article',
    'biblio.entity.author': 'Author',
    'biblio.entity.author_cocitation': 'Author co-citation',
    'biblio.entity.bibliographic_coupling': 'Bibliographic coupling',
    'biblio.entity.category': 'Category',
    'biblio.entity.country': 'Country/Region',
    'biblio.entity.document': 'Document (coupling)',
    'biblio.entity.document_cocitation': 'Document co-citation',
    'biblio.entity.funder': 'Funder/Grant',
    'biblio.entity.grant': 'Grant (funder)',
    'biblio.entity.institution': 'Institution',
    'biblio.entity.journal': 'Source journal (coupling)',
    'biblio.entity.journal_cocitation': 'Journal co-citation',
    # ── bibliometrics / knowledge graph ───────────────────────
    'biblio.entity.keyword': 'Keyword',
    'biblio.entity.source': 'Source (journal coupling)',
    'biblio.entity.term': 'Term',
    'biblio.exclusions_applied': 'Exclusion list: {n} node labels were removed by the user setting',
    'biblio.export_failed': 'Bibliometric export failed: {err}',
    'biblio.import_duplicates': '{n} duplicate records were merged',
    'biblio.import_no_year': '{n} records have no year',
    'biblio.import_ok': 'Recognised a {format} export: {n} records',
    'biblio.import_skipped': '{n} empty records were skipped',
    'biblio.isolates_dropped': '{n} isolated nodes had no edge after graph construction and were removed',
    'biblio.label_fallback': (
        'Cluster-label method {asked} had no usable text; {used} was used and is named in the run summary'
    ),
    'biblio.largest_component': (
        'Kept the largest connected component: nodes {before} → {after}; smaller components were removed'
    ),
    'biblio.links_too_large': 'Node "{node}" has a link JSON larger than {cap} bytes: lower max links per node',
    'biblio.mst_done': 'MST pruning ({scope}): {before} → {after} edges',
    'biblio.no_edges': (
        'No co-occurrence edges in {start}–{end}: lower the threshold, widen the time range, or choose another entity'
    ),
    'biblio.no_edges_after_component': (
        'Keeping the largest connected component left no edges: disable it or lower the threshold'
    ),
    'biblio.no_edges_after_prune': '{pruning} pruning left no edges: lower max links per node or use none',
    'biblio.no_edges_after_threshold': (
        'The (c, cc, ccv) thresholds left no edges: lower cc/ccv or widen the time range'
    ),
    'biblio.no_records': 'No usable bibliographic records: check that the year column is parseable',
    'biblio.no_records_in_range': 'No records in {start}–{end}',
    'biblio.overlay_no_labels': (
        'Column "{col}" holds no labels at all ({n} records are blank), so nothing can be overlaid — '
        'check that the upstream sentiment/emotion/topic step really wrote this column'
    ),
    'biblio.overlay_no_nodes': 'Column "{col}" has labels, but no surviving node carries one; '
    'the overlay columns are empty',
    'biblio.overlay_partial': (
        'Column "{col}": {n} of {total} records carry no label and are left out of the overlay '
        '(the denominator is labelled documents only)'
    ),
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
    'biblio.project_needs_name': 'A project needs a name (so does a rename)',
    'biblio.project_not_found': 'No project {pid}: it may have been deleted',
    'biblio.pruning_scope.merged': 'merged network',
    'biblio.pruning_scope.slices': 'per slice',
    'biblio.records_skipped': '{n} records had no analysable entity and were skipped',
    'biblio.refs_field_low': '{field} parse rate {rate} is below {floor}; a citation graph cannot be built reliably',
    'biblio.refs_low_rate': 'Reference parse rate {rate} is below {floor}; a citation graph cannot be built reliably',
    'biblio.refs_missing': (
        '{type} needs cited references: at least 2 【参考文献】 entries per record. CNKI RefWorks usually has none — '
        'use a CSSCI export instead'
    ),
    'biblio.shape_needs_burst': (
        '{nid}: output_shape bursts needs burst detection enabled; enable it or use nodes/edges'
    ),
    'biblio.shape_needs_cluster': '{nid}: output_shape clusters needs clustering enabled; enable it or use nodes/edges',
    'biblio.shape_needs_variation': (
        '{nid}: output_shape variation needs structural-variation detection enabled; enable it or use another shape'
    ),
    'biblio.snapshot_done': '[bibliometrics] saved "{label}": {nodes} nodes / {edges} links (params {verified})',
    'biblio.snapshot_not_found': 'No snapshot {sid}: it may have been deleted',
    'biblio.time_range': '{nid}: invalid time range: {start} > {end}',
    'biblio.too_many_edges': '{n} edges exceed the cap ({cap}): narrow TopN or max links per node',
    'biblio.too_many_nodes': '{n} nodes exceed the cap ({cap}): narrow TopN or the time range',
    'biblio.variation_done': 'Structural variation: {rows} rows (highest {node} {pair} = {score} bits, floor {floor})',
    'biblio.variation_empty': (
        'Structural variation: no node moved its connection pattern by {floor} bits between consecutive slices'
    ),
    'biblio.variation_needs_slices': (
        'Structural variation compares consecutive slices, and this run has only {n} slice to compare '
        '(narrow slice_years or widen the year range)'
    ),
    'biblio.variation_no_coupling': (
        'Structural variation needs a network sliced by year: in a coupling network ({entity}) a link belongs to '
        'two citing papers rather than to one year, so there is no slice-to-slice change to measure'
    ),
    'biblio.watch.burst_added': 'new burst',
    'biblio.watch.burst_removed': 'burst ended',
    'biblio.watch.burst_strength': 'burst strength changed',
    'biblio.watch.cluster_added': 'cluster added',
    'biblio.watch.cluster_relabeled': 'cluster relabeled',
    'biblio.watch.cluster_removed': 'cluster gone',
    'biblio.watch.cluster_size': 'cluster size changed',
    'biblio.watch.edge_added': 'link added',
    'biblio.watch.edge_removed': 'link gone',
    'biblio.watch.edge_weight': 'link weight changed',
    'biblio.watch.first': 'first capture (nodes/links)',
    'biblio.watch.node_added': 'node added',
    'biblio.watch.node_changed': 'node attribute changed',
    'biblio.watch.node_removed': 'node gone',
    'biblio.watch.nothing': 'no change',
    'biblio.watch.param': 'parameter',
    'biblio.watch_baseline_missing': '{nid}: no capture named "{label}" in the watch project (known: {known})',
    'biblio.watch_done': '[watch] "{project}": "{baseline}" → "{label}", {detail} '
    '(at most {limit} names per category; totals in brackets)',
    'biblio.watch_empty': '{nid}: this network has no nodes and no links, so there is nothing to watch '
    '(an empty capture would report every entity as gone next time)',
    'biblio.watch_first_done': '[watch] filed "{label}" in "{project}": {nodes} nodes / {edges} links; '
    'nothing older to compare with',
    'biblio.watch_needs_entity_table': '{nid}: monitoring needs a one-row-per-entity output shape; '
    '{shape} rows are not entities',
    'biblio.watch_needs_project': '{nid}: a watch baseline or capture name without a project; '
    'name the project or clear both',
    'biblio.watch_params_differ': '[watch] {n} parameter(s) differ from the baseline ({names}) — '
    'rule out an edited node before reading this as the field moving',
    'biblio.watch_project_created': '[watch] project "{name}" did not exist, so it was created '
    '(this run is its first capture)',
    'biblio.watch_project_note': 'created automatically by cross-run bibliometric monitoring',
    'biblio.watch_shape_differs': '[watch] the baseline is a {a} table and this run is a {b} one, '
    'so a row-count gap is not a change in the field',
    'biblio.watch_unchanged': '[watch] identical to the baseline ({nodes} nodes / {edges} links): '
    'that is what a run with no new upstream data looks like',
    'biblio.wide_ref_skipped': (
        '{n} references were cited by more than {cap} papers; their pairwise links were skipped '
        '(a giant clique would bury the graph)'
    ),
    'biblio.workspace_empty_table': '{nid}: this node stored no rows (stopped, failed, or cleared by retention)',
    'biblio.workspace_no_node': 'Run {rid} has no node {nid}: pick another run',
    'biblio.workspace_not_biblio': '{nid}: not a bibliometrics node; the workspace reads bibliometric tables only',
    'biblio.year_missing': '{n} records have no year and were skipped (time slicing needs a year)',
    'fuse.build_done': '[fusion] {parents} tables → {rows} records, sources: {sources}',
    'fuse.empty_parent': '{nid}: upstream {pid} has no rows, so it cannot be fused',
    'fuse.needs_entity': '{nid}: fusion needs at least one entity candidate column (e.g. 关键词,话题)',
    'fuse.no_entity_column': '{nid}: upstream {pid} has no column usable as entities (tried: {wanted})',
    'fuse.no_input': '{nid}: cross-source fusion needs at least one input table',
    'fuse.no_rows': '{nid}: upstream {pid} yielded no entity at all from its "{column}" column',
    'fuse.source_named': '[fusion] source "{source}": {pid} contributed {rows} records',
}
