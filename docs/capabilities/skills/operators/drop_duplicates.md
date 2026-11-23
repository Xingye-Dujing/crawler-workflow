# operator.drop_duplicates

按所选列删除重复行；exact 逐字比较，normalized 先做全半角/空白归一。

## When to use

同一行被采集了两次（翻页重叠、导出合并）时去重。

Do not use it when:

- 两段文字意思相同但写法不同时用 dedupe_similar 或 semantic_dedupe。

## Prerequisites

- An upstream table (the analysis node’s input).
- `columns` names existing columns; blank means every column.

## Steps

1. Put a step `{"op": "drop_duplicates", …}` in the analysis node’s `steps`, or set `operation` to `drop_duplicates`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "drop_duplicates",
    "steps": "[{\"op\": \"drop_duplicates\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "drop_duplicates",
    "steps": "[{\"op\": \"drop_duplicates\", \"params\": {}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |
| `keep` | string | `first` |  |  |
| `mode` | string | `exact` |  | exact, normalized |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/drop_duplicates.md`
Skill page: `docs/capabilities/skills/operators/drop_duplicates.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
