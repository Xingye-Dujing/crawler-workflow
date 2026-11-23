# operator.cluster_review

按文献聚类分组，汇总成员、频次与年份跨度，并让模型写簇综述。

## When to use

知识图谱聚类已生成，需要逐簇的文献计量解读。

Do not use it when:

- 要给普通文本聚类写摘要用 cluster_label。

## Prerequisites

- An upstream table (the analysis node’s input).
- `group_col` names a column that must exist (default: 聚类).
- `name_col` names a column that must exist (default: 节点).

## Steps

1. Put a step `{"op": "cluster_review", …}` in the analysis node’s `steps`, or set `operation` to `cluster_review`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The output columns depend on the data; read them from the node’s result.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "cluster_review",
    "steps": "[{\"op\": \"cluster_review\", \"params\": {\"group_col\": \"聚类\", \"name_col\": \"节点\", \"summary_col\": \"簇综述\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "cluster_review",
    "steps": "[{\"op\": \"cluster_review\", \"params\": {\"group_col\": \"聚类\", \"name_col\": \"节点\", \"summary_col\": \"簇综述\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `group_col` | string | `聚类` |  |  |
| `label_col` | string | `聚类标签` |  |  |
| `name_col` | string | `节点` |  |  |
| `freq_col` | string | `频次` |  |  |
| `first_col` | string | `首年` |  |  |
| `last_col` | string | `末年` |  |  |
| `summary_col` | string | `簇综述` |  |  |
| `members` | integer | `12` |  |  |
| `on_fail` | string | `abort` |  | abort, blank, fallback |
| `max_groups` | integer | `60` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.
- The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.

## Acceptance

- The console reports the output shape; a downstream step that names a column is checked against it.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/cluster_review.md`
Skill page: `docs/capabilities/skills/operators/cluster_review.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
