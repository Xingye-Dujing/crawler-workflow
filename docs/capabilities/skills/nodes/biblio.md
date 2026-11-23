# node.biblio

文献计量 builds a bibliometric network from a record table: co-occurrence, co-citation or coupling, with slice/look-back windows, top-N/G-index/threshold selection, LRF/MST/Pathfinder pruning, cluster labels (LLR/LSI/MI/TF-IDF), burst detection, structural variation, and five output shapes (nodes/edges/clusters/bursts/variation/dual_map).

## When to use

After 文献融合 or a CNKI import, when the records should become a citation/co-word map.

Do not use it when:

- Merging several record tables belongs on node.fuse first.
- Drawing the network belongs on node.visualize.

## Prerequisites

- A record table with the entity column the chosen network reads.
- The year/title/reference columns only when the chosen network reads them.

## Steps

1. Pick the entity type and the columns the record table really has.
2. Choose the selection rule and the link measure; pruning is for a graph too dense to read.
3. Pick the output shape: nodes/edges for a graph, clusters/bursts/variation for their tables, dual_map for a basemap overlay.

## Examples

```json
{
  "type": "biblio",
  "params": {
    "entity_type": "keyword",
    "time_start": "2015",
    "time_end": "2024",
    "slice_years": 2,
    "selection": "top_n",
    "top_n": 50,
    "link_measure": "cosine",
    "cluster": true,
    "output_shape": "nodes"
  }
}
```

## Template JSON

```json
{
  "type": "biblio",
  "params": {
    "entity_type": "keyword",
    "selection": "top_n",
    "top_n": 50,
    "output_shape": "nodes"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `entity_type` | string | `keyword` |  | keyword, author, institution, country, term, category, journal, source, funder, grant, document_cocitation, author_cocitation, journal_cocitation, article, document, bibliographic_coupling |
| `entity_column` | string |  |  |  |
| `year_column` | string | `年份` |  |  |
| `title_column` | string | `题名` |  |  |
| `abstract_column` | string | `摘要` |  |  |
| `reference_column` | string | `参考文献` |  |  |
| `tc_column` | string | `引用次数` |  |  |
| `usage_column` | string | `使用次数` |  |  |
| `sentiment_column` | string |  |  |  |
| `topic_column` | string |  |  |  |
| `time_start` | string |  |  |  |
| `time_end` | string |  |  |  |
| `slice_years` | integer | `1` |  |  |
| `look_back_years` | integer | `0` |  |  |
| `selection` | string | `top_n` |  | top_n, top_pct, g_index, threshold |
| `top_n` | integer | `50` |  |  |
| `top_pct` | integer | `10` |  |  |
| `g_index` | integer | `25` |  |  |
| `min_count` | integer | `2` |  |  |
| `threshold_c` | integer | `0` |  |  |
| `threshold_cc` | integer | `1` |  |  |
| `threshold_ccv` | number | `0.0` |  |  |
| `min_tc` | string |  |  |  |
| `min_usage` | string |  |  |  |
| `largest_component` | boolean | `False` |  |  |
| `link_measure` | string | `cosine` |  | cosine, dice, jaccard, association |
| `counting` | string | `full` |  | full, fractional |
| `citation_expansion` | integer | `0` |  |  |
| `max_links_per_node` | integer | `10` |  |  |
| `lrf` | number | `2.5` |  |  |
| `pruning` | string | `none` |  | none, mst, pathfinder |
| `pruning_scope` | string | `slices` |  | slices, merged |
| `pathfinder_r` | string | `inf` |  | 1, 2, inf |
| `pathfinder_lmax` | integer | `0` |  |  |
| `pathfinder_dmax` | number | `1.0` |  |  |
| `cluster` | boolean | `True` |  |  |
| `cluster_count` | string |  |  |  |
| `label_method` | string | `llr` |  | llr, lsi, mi, tfidf |
| `label_source` | string | `all` |  | all, title, abstract, keywords, author |
| `top_terms` | integer | `5` |  |  |
| `burst` | boolean | `True` |  |  |
| `burst_gamma` | number | `1.0` |  |  |
| `burst_min_duration` | integer | `2` |  |  |
| `burst_weight` | number | `2.0` |  |  |
| `burst_top` | integer | `20` |  |  |
| `variation` | boolean | `False` |  |  |
| `variation_min` | number | `0.05` |  |  |
| `aliases` | string |  |  |  |
| `exclude_values` | string |  |  |  |
| `cluster_labels` | string |  |  |  |
| `basemap_dataset_id` | string |  |  |  |
| `watch_project` | string |  |  |  |
| `watch_baseline` | string |  |  |  |
| `watch_label` | string |  |  |  |
| `output_shape` | string | `nodes` |  | nodes, edges, clusters, bursts, variation, dual_map |
| `export_files` | boolean | `True` |  |  |

## Failure modes

- An option outside its list: biblio.bad_option names the parameter and the allowed values.
- A number outside its range: biblio.bad_option (the validator states the range).
- A start year after the end year: biblio.time_range.
- Fractional counting on a coupling network: biblio.counting_no_coupling.
- Bursts on a coupling network: biblio.coupling_no_burst.
- An output shape whose switch is off: biblio.shape_needs_cluster/burst/variation.
- A baseline without a project: biblio.watch_needs_project; monitoring a non-entity shape: biblio.watch_needs_entity_table.

## Acceptance

- The chosen output shape exists and its node/edge/cluster/burst counts are reported.
- An option outside its list is named with the allowed values.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/biblio.md`
Skill page: `docs/capabilities/skills/nodes/biblio.md`
Contract tests: `tests/unit/capabilities/test_biblio_manifest.py`
