# operator.sort_rows

按一列升序或降序重排行（行集合不变）。

## When to use

图表 X 轴或分阶段分析要求按时间/热度排序时。

Do not use it when:

- 要按分组聚合用 groupby_agg；要取子集用 sample_rows 或 filter_rows。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "sort_rows", …}` in the analysis node’s `steps`, or set `operation` to `sort_rows`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "sort_rows",
    "steps": "[{\"op\": \"sort_rows\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "sort_rows",
    "steps": "[{\"op\": \"sort_rows\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `ascending` | boolean | `True` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/sort_rows.md`
Skill page: `docs/capabilities/skills/operators/sort_rows.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
