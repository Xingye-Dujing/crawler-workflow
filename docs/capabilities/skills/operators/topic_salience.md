# operator.topic_salience

为每主题的词按“总体频率 + 主题内频率”的加权相关度排序，输出显著词表。

## When to use

要画显著词图，或说明每个主题真正有区分度的词（而不是全语料高频词）。

Do not use it when:

- 要主题距离图用 topic_map；要共现网络用 cooccur。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "topic_salience", …}` in the analysis node’s `steps`, or set `operation` to `topic_salience`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `topic`, `rank`, `term`, `overall_freq`, `within_freq`, `relevance`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_salience",
    "steps": "[{\"op\": \"topic_salience\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_salience",
    "steps": "[{\"op\": \"topic_salience\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `n_topics` | integer | `5` |  |  |
| `max_features` | integer | `2000` |  |  |
| `topn` | integer | `30` |  |  |
| `relevance` | number | `1.0` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: topic, rank, term, overall_freq, within_freq, relevance.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_salience.md`
Skill page: `docs/capabilities/skills/operators/topic_salience.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
