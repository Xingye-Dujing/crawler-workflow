# 文献计量（biblio）

文献计量把一张记录表变成文献计量网络或表格：共现、共被引、文献耦合、突现词、结构变化、双图叠印。
它读上游记录（文献融合的输出或 CNKI 导入表），输出普通行表，因此可以被“可视化”继续画图。

- 清单：`backend/capabilities_kernel/nodes/biblio/manifest.py`
- 行为：`backend/nodes/executors/biblio.py`
- 参数与校验：`backend/services/biblio/schema.py`（默认值与选项取自清单）
- 契约测试：`tests/unit/capabilities/test_biblio_manifest.py`

## 参数（按用途分组）

**实体与列映射**：`entity_type`（关键词/作者/机构/国家/主题词/学科/期刊/来源/基金/项目，
以及共被引、耦合类的 `document_cocitation`/`author_cocitation`/`journal_cocitation`/`article`/
`document`/`bibliographic_coupling`）、`entity_column`、`year_column`、`title_column`、
`abstract_column`、`reference_column`、`tc_column`、`usage_column`、`sentiment_column`、
`topic_column`。

- 实体列留空 = 用该实体的规范列（关键词/作者/作者单位……）；其余列留空 = 用规范列名。
- `sentiment_column`/`topic_column` 是可选叠加：留空时行为与没有这两个参数时完全相同；
  填了但上游没有该列会在运行前按名拒绝。

**时间切片**：`time_start`、`time_end`（四位年份或留空）、`slice_years`（1–50）、
`look_back_years`（0–50）。

**筛选**：`selection`（`top_n`/`top_pct`/`g_index`/`threshold`）及 `top_n`、`top_pct`、
`g_index`、`min_count`、`threshold_c`、`threshold_cc`、`threshold_ccv`、`min_tc`、`min_usage`、
`largest_component`。

**连边与剪枝**：`link_measure`（cosine/dice/jaccard/association）、`counting`（full/fractional）、
`citation_expansion`、`max_links_per_node`、`lrf`、`pruning`（none/mst/pathfinder）、
`pruning_scope`（slices/merged），以及 Pathfinder 的 `pathfinder_r`（1/2/inf）、
`pathfinder_lmax`、`pathfinder_dmax`。

**聚类、标签与突现**：`cluster`、`cluster_count`、`label_method`（llr/lsi/mi/tfidf）、
`label_source`（all/title/abstract/keywords/author）、`top_terms`、`burst`、`burst_gamma`、
`burst_min_duration`、`burst_weight`、`burst_top`。

**结构变化**：`variation`、`variation_min`（以 bit 计的散度下限）。

**清洗与叠印**：`aliases`、`exclude_values`、`cluster_labels`、`basemap_dataset_id`。

**跨运行监控**：`watch_project`、`watch_baseline`、`watch_label`。

**输出**：`output_shape`（nodes/edges/clusters/bursts/variation/dual_map）、`export_files`。

## 运行前校验

- `biblio.bad_option`：某个选项不在清单声明的列表里，或某个数字超出范围；消息带参数名、原值和允许值。
- `biblio.time_range`：起始年份晚于结束年份。
- `biblio.counting_no_coupling`：耦合网络里用 fractional 计数（两个端点就是施引文献，没有第三方可分摊）。
- `biblio.coupling_no_burst`：耦合网络开启突现检测。
- `biblio.shape_needs_cluster` / `shape_needs_burst` / `shape_needs_variation`：要求某输出形状但对应开关关着。
- `biblio.dual_map_needs_basemap`：`dual_map` 但没有选择 basemap 数据集。
- `biblio.cluster_labels_need_cluster`：写了人工聚类标签但没开聚类。
- `biblio.watch_needs_project`：只填了基线/标签却没有项目名；`biblio.watch_needs_entity_table`：
  对非“一实体一行”的输出形状做跨运行监控。
- `engine.biblio_no_input`：没有数据上游；`engine.biblio_multi_input`：接了多张表。

## 典型画布

```text
CNKI 导出 → 清洗 → 文献计量（关键词共现，2015–2024）→ 可视化（网络图）
文献融合 → 文献计量（文献耦合，输出 clusters）→ 保存
```
