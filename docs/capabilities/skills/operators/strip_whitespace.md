# operator.strip_whitespace

去掉所选列文本首尾的空白（含全角空格），行数不变。

## When to use

采集文本带换行/缩进，导致去重、分词或图表标签不一致时。

Do not use it when:

- 要改数据类型用 convert_type。

## Prerequisites

- An upstream table (the analysis node’s input).
- `columns` names existing columns; blank means every column.

## Steps

1. Put a step `{"op": "strip_whitespace", …}` in the analysis node’s `steps`, or set `operation` to `strip_whitespace`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "strip_whitespace",
    "steps": "[{\"op\": \"strip_whitespace\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "strip_whitespace",
    "steps": "[{\"op\": \"strip_whitespace\", \"params\": {}}]"
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
Documentation: `docs/capabilities/operators/strip_whitespace.md`
Skill page: `docs/capabilities/skills/operators/strip_whitespace.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
