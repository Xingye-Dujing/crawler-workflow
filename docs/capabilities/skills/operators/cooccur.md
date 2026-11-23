# operator.cooccur

统计同一文本窗口内共同出现的词对，输出 source/target/value 边表。

## When to use

要画词语共现网络，看概念如何绑定在一起。

Do not use it when:

- 要主题的特征词用 topic_model 或 topic_salience。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "cooccur", …}` in the analysis node’s `steps`, or set `operation` to `cooccur`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `source`, `target`, `value`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "cooccur",
    "steps": "[{\"op\": \"cooccur\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "cooccur",
    "steps": "[{\"op\": \"cooccur\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `topn` | integer | `30` |  |  |
| `min_count` | integer | `2` |  |  |
| `window` | integer | `0` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: source, target, value.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/cooccur.md`
Skill page: `docs/capabilities/skills/operators/cooccur.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
