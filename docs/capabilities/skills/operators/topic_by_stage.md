# operator.topic_by_stage

按阶段列分别做主题建模，输出阶段、主题、特征词、权重、文档数与困惑度。

## When to use

要比较“发酵期”和“爆发期”的议题差异，就需要每阶段一套主题。

Do not use it when:

- 不关心阶段差异时用 topic_model；阶段本身要先由 bin_time 生成。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).
- `stage_col` names a column that must exist (default: 阶段).

## Steps

1. Put a step `{"op": "topic_by_stage", …}` in the analysis node’s `steps`, or set `operation` to `topic_by_stage`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `stage`, `stage_order`, `topic`, `feature_words`, `weights`, `doc_n`, `perplexity`, `sample_texts`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_by_stage",
    "steps": "[{\"op\": \"topic_by_stage\", \"params\": {\"column\": \"正文\", \"stage_col\": \"阶段\", \"topics\": []}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_by_stage",
    "steps": "[{\"op\": \"topic_by_stage\", \"params\": {\"column\": \"正文\", \"stage_col\": \"阶段\", \"topics\": []}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `stage_col` | string | `阶段` |  |  |
| `order_col` | string |  |  |  |
| `topics` | array | `[]` |  |  |
| `topn` | integer | `10` |  |  |
| `max_features` | integer | `2000` |  |  |
| `word_source` | string | `tfidf` |  | tfidf, lda |
| `sample_n` | integer | `5` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: stage, stage_order, topic, feature_words, weights, doc_n, perplexity, sample_texts.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_by_stage.md`
Skill page: `docs/capabilities/skills/operators/topic_by_stage.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
