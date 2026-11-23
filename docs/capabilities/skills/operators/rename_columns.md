# operator.rename_columns

把一列改名为另一个名字（旧列 -> 新列）。

## When to use

上游列名与下游图表/算子约定的列名不一致时对齐一次。

Do not use it when:

- 要移动/挑选列的集合用 select_columns。

## Prerequisites

- An upstream table (the analysis node’s input).
- `mapping` maps existing columns to their new names.

## Steps

1. Put a step `{"op": "rename_columns", …}` in the analysis node’s `steps`, or set `operation` to `rename_columns`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The output columns depend on the data; read them from the node’s result.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "rename_columns",
    "steps": "[{\"op\": \"rename_columns\", \"params\": {\"mapping\": {\"正文\": \"文本\"}}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "rename_columns",
    "steps": "[{\"op\": \"rename_columns\", \"params\": {\"mapping\": {\"正文\": \"文本\"}}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `mapping` | object | `{}` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.
- The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.

## Acceptance

- The console reports the output shape; a downstream step that names a column is checked against it.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/rename_columns.md`
Skill page: `docs/capabilities/skills/operators/rename_columns.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
