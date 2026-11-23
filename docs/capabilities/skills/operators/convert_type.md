# operator.convert_type

把一列转换为文本/整数/小数/布尔/日期时间类型。

## When to use

CSV 里数字被读成文本、时间戳需要变成 datetime 以按时间排序时。

Do not use it when:

- 只想去空格用 strip_whitespace；要派生日期列用 extract_time。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "convert_type", …}` in the analysis node’s `steps`, or set `operation` to `convert_type`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "convert_type",
    "steps": "[{\"op\": \"convert_type\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "convert_type",
    "steps": "[{\"op\": \"convert_type\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `dtype` | string | `str` |  | str, int, float, bool, datetime |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/convert_type.md`
Skill page: `docs/capabilities/skills/operators/convert_type.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
