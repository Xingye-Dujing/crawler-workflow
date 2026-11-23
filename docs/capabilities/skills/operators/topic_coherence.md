# operator.topic_coherence

在给定主题数区间上扫一遍 LDA，输出每个主题数的连贯度，帮助选择主题数。

## When to use

不确定 n_topics 取几时，用连贯度曲线给依据。

Do not use it when:

- 已有确定主题数就直接 topic_model，不必再扫。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "topic_coherence", …}` in the analysis node’s `steps`, or set `operation` to `topic_coherence`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The output columns depend on the data; read them from the node’s result.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_coherence",
    "steps": "[{\"op\": \"topic_coherence\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_coherence",
    "steps": "[{\"op\": \"topic_coherence\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `min_topics` | integer | `2` |  |  |
| `max_topics` | integer | `8` |  |  |
| `topn` | integer | `10` |  |  |
| `max_features` | integer | `2000` |  |  |
| `max_documents` | integer | `2000` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.
- The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.

## Acceptance

- The console reports the output shape; a downstream step that names a column is checked against it.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_coherence.md`
Skill page: `docs/capabilities/skills/operators/topic_coherence.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
