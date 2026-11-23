# operator.topic_map

把主题投射到二维平面（pc1/pc2），并给出每主题的占比与特征词。

## When to use

要画主题距离图（气泡位置=主题距离，大小=占比）。

Do not use it when:

- 只想看特征词的重要性用 topic_salience。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "topic_map", …}` in the analysis node’s `steps`, or set `operation` to `topic_map`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `topic`, `pc1`, `pc2`, `prevalence_pct`, `doc_n`, `feature_words`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_map",
    "steps": "[{\"op\": \"topic_map\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_map",
    "steps": "[{\"op\": \"topic_map\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `n_topics` | integer | `5` |  |  |
| `max_features` | integer | `2000` |  |  |
| `topn` | integer | `6` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: topic, pc1, pc2, prevalence_pct, doc_n, feature_words.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_map.md`
Skill page: `docs/capabilities/skills/operators/topic_map.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
