# operator.select_columns

只保留列出的列（按此顺序），其余列丢弃。

## When to use

导出或画图前把表收窄到需要的几列。

Do not use it when:

- 要改列名用 rename_columns；要新增计算列用 column_calc。

## Prerequisites

- An upstream table (the analysis node’s input).
- `columns` names existing columns; blank means every column.

## Steps

1. Put a step `{"op": "select_columns", …}` in the analysis node’s `steps`, or set `operation` to `select_columns`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "select_columns",
    "steps": "[{\"op\": \"select_columns\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "select_columns",
    "steps": "[{\"op\": \"select_columns\", \"params\": {}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/select_columns.md`
Skill page: `docs/capabilities/skills/operators/select_columns.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
