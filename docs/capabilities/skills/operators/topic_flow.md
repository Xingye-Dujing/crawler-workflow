# operator.topic_flow

按特征词相似度把相邻阶段的主题配对，输出来源/目标、相似度与分歧度的流向边。

## When to use

要画主题流向桑基图，说明“发酵期哪个议题变成了爆发期的什么议题”。

Do not use it when:

- 只看单个主题的生命周期用 topic_timeline。

## Prerequisites

- An upstream table (the analysis node’s input).
- `stage_col` names a column that must exist (default: stage).
- `topic_col` names a column that must exist (default: topic).
- `weights_col` names a column that must exist (default: weights).

## Steps

1. Put a step `{"op": "topic_flow", …}` in the analysis node’s `steps`, or set `operation` to `topic_flow`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `source`, `target`, `source_topic`, `target_topic`, `similarity`, `divergence`, `from_stage`, `to_stage`, `source_words`, `target_words`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_flow",
    "steps": "[{\"op\": \"topic_flow\", \"params\": {\"stage_col\": \"stage\", \"topic_col\": \"topic\", \"weights_col\": \"weights\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_flow",
    "steps": "[{\"op\": \"topic_flow\", \"params\": {\"stage_col\": \"stage\", \"topic_col\": \"topic\", \"weights_col\": \"weights\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `stage_col` | string | `stage` |  |  |
| `topic_col` | string | `topic` |  |  |
| `words_col` | string | `feature_words` |  |  |
| `weights_col` | string | `weights` |  |  |
| `order_col` | string |  |  |  |
| `min_similarity` | number | `0.5` |  |  |
| `label_col` | string |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: source, target, source_topic, target_topic, similarity, divergence, from_stage, to_stage, source_words, target_words.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_flow.md`
Skill page: `docs/capabilities/skills/operators/topic_flow.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
