# operator.drop_null

删除所选列中含空值的行（任一为空或全部为空）。

## When to use

在分析前去掉缺字段的行，或只保留每一列都填写完整的行。

Do not use it when:

- 只想填补空值而不是删除行时用 fill_null；要按列去重用 drop_duplicates。

## Prerequisites

- An upstream table (the analysis node’s input).
- `columns` names existing columns; blank means every column.

## Steps

1. Put a step `{"op": "drop_null", …}` in the analysis node’s `steps`, or set `operation` to `drop_null`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "drop_null",
    "steps": "[{\"op\": \"drop_null\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "drop_null",
    "steps": "[{\"op\": \"drop_null\", \"params\": {}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |
| `how` | string | `any` |  | any, all |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/drop_null.md`
Skill page: `docs/capabilities/skills/operators/drop_null.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
