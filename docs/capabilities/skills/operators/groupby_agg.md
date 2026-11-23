# operator.groupby_agg

按一列分组，对另一列求和/均值/计数等，输出每组一行。

## When to use

把明细表变成“每个平台/每天/每个主题一行”的统计表再画图。

Do not use it when:

- 要保留明细只用 filter_rows；要比较两个平台的整体分布用 compare_platform。

## Prerequisites

- An upstream table (the analysis node’s input).
- `group_col` names a column that must exist (default: none — required).
- `agg_col` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "groupby_agg", …}` in the analysis node’s `steps`, or set `operation` to `groupby_agg`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The output columns depend on the data; read them from the node’s result.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "groupby_agg",
    "steps": "[{\"op\": \"groupby_agg\", \"params\": {\"group_col\": \"正文\", \"agg_col\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "groupby_agg",
    "steps": "[{\"op\": \"groupby_agg\", \"params\": {\"group_col\": \"正文\", \"agg_col\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `group_col` | string |  |  |  |
| `agg_col` | string |  |  |  |
| `agg_func` | string | `sum` |  | sum, mean, median, min, max, count, nunique, std, var |
| `order_col` | string |  |  |  |
| `agg_metrics` | array | `[]` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.
- The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.

## Acceptance

- The console reports the output shape; a downstream step that names a column is checked against it.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/groupby_agg.md`
Skill page: `docs/capabilities/skills/operators/groupby_agg.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
