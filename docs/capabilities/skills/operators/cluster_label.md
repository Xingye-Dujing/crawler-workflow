# operator.cluster_label

按聚类列分组，让本地模型为每个簇写摘要，输出每簇一行。

## When to use

已按主题/相似度聚好类，需要给每类一句可读的概括。

Do not use it when:

- 要保留明细行只在旁边加一列用 topic_label。

## Prerequisites

- An upstream table (the analysis node’s input).
- `group_col` names a column that must exist (default: cluster).
- `text_col` names a column that must exist (default: 正文).

## Steps

1. Put a step `{"op": "cluster_label", …}` in the analysis node’s `steps`, or set `operation` to `cluster_label`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a fresh table whose column names come from the step’s own parameters.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "cluster_label",
    "steps": "[{\"op\": \"cluster_label\", \"params\": {\"group_col\": \"cluster\", \"text_col\": \"正文\", \"summary_col\": \"摘要\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "cluster_label",
    "steps": "[{\"op\": \"cluster_label\", \"params\": {\"group_col\": \"cluster\", \"text_col\": \"正文\", \"summary_col\": \"摘要\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `group_col` | string | `cluster` |  |  |
| `text_col` | string | `正文` |  |  |
| `summary_col` | string | `摘要` |  |  |
| `on_fail` | string | `abort` |  | abort, blank, fallback |
| `max_groups` | integer | `60` |  |  |
| `sample_n` | integer | `8` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output column names equal the parameters the step was given.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/cluster_label.md`
Skill page: `docs/capabilities/skills/operators/cluster_label.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
