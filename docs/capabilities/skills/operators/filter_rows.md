# operator.filter_rows

按一列与给定值的比较（等于/包含/大于/为空…）保留或删除行。

## When to use

把分析限定在一个子集：某平台、某时间段、包含某个词。

Do not use it when:

- 要按另一张表的键去重/剔除用 anti_join；只挑列用 select_columns。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "filter_rows", …}` in the analysis node’s `steps`, or set `operation` to `filter_rows`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "filter_rows",
    "steps": "[{\"op\": \"filter_rows\", \"params\": {\"column\": \"正文\", \"op\": \"eq\", \"value\": \"示例\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "filter_rows",
    "steps": "[{\"op\": \"filter_rows\", \"params\": {\"column\": \"正文\", \"op\": \"eq\", \"value\": \"示例\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `op` | string |  | yes | eq, ne, gt, gte, lt, lte, contains, not_contains, in, not_in, is_null, not_null |
| `value` | string |  |  |  |
| `keep` | string | `keep` |  | keep, exclude |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/filter_rows.md`
Skill page: `docs/capabilities/skills/operators/filter_rows.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
