# operator.fill_null

用固定值或上/下一行的值填补所选列的空单元格。

## When to use

缺失值是“未填写”而不是“不存在”时，保留行并补上占位值。

Do not use it when:

- 行本身没有意义（缺了关键字段就该丢弃）时用 drop_null。

## Prerequisites

- An upstream table (the analysis node’s input).
- `columns` names existing columns; blank means every column.

## Steps

1. Put a step `{"op": "fill_null", …}` in the analysis node’s `steps`, or set `operation` to `fill_null`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "fill_null",
    "steps": "[{\"op\": \"fill_null\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "fill_null",
    "steps": "[{\"op\": \"fill_null\", \"params\": {}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |
| `value` | string |  |  |  |
| `method` | string |  |  | ffill, pad, bfill, backfill |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/fill_null.md`
Skill page: `docs/capabilities/skills/operators/fill_null.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
