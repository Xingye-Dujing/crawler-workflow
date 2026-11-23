# operator.topic_model

对一列文本做主题建模（LDA 或句向量聚类），输出主题号、排名、特征词与权重。

## When to use

要看语料由哪些议题构成，并得到每主题的特征词表。

Do not use it when:

- 要按阶段分别建模用 topic_by_stage；只要词频共现用 cooccur。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "topic_model", …}` in the analysis node’s `steps`, or set `operation` to `topic_model`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `topic`, `rank`, `keyword`, `weight`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_model",
    "steps": "[{\"op\": \"topic_model\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_model",
    "steps": "[{\"op\": \"topic_model\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `n_topics` | integer | `5` |  |  |
| `topn` | integer | `10` |  |  |
| `max_features` | integer | `2000` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: topic, rank, keyword, weight.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_model.md`
Skill page: `docs/capabilities/skills/operators/topic_model.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
