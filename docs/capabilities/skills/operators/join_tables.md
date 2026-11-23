# operator.join_tables

把第二条输入的表格按连接键拼到第一条上（left/right/inner/outer/cross）。

## When to use

把主题表、统计表或另一平台的结果按共同键合并成一张宽表。

Do not use it when:

- 只想剔除已在另一张表里的行用 anti_join；同表内改列用 rename_columns。

## Prerequisites

- An upstream table (the analysis node’s input).
- `left_on` is a key of one of the two incoming tables.
- `right_on` is a key of one of the two incoming tables.

## Steps

1. Put a step `{"op": "join_tables", …}` in the analysis node’s `steps`, or set `operation` to `join_tables`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The output columns depend on the data; read them from the node’s result.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "join_tables",
    "steps": "[{\"op\": \"join_tables\", \"params\": {\"left_on\": \"正文\", \"right_on\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "join_tables",
    "steps": "[{\"op\": \"join_tables\", \"params\": {\"left_on\": \"正文\", \"right_on\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `how` | string | `left` |  | left, right, inner, outer, cross |
| `left_on` | string |  |  |  |
| `right_on` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.
- The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.

## Acceptance

- The console reports the output shape; a downstream step that names a column is checked against it.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/join_tables.md`
Skill page: `docs/capabilities/skills/operators/join_tables.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
