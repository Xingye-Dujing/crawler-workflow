# operator.topic_timeline

跨阶段追踪主题：首次出现、峰值、最后出现的阶段与规模，识别二次爆发。

## When to use

要讲“议题如何随事件推进”的故事，需要每主题的生命周期轨迹。

Do not use it when:

- 要看阶段之间的主题流动用 topic_flow。

## Prerequisites

- An upstream table (the analysis node’s input).
- `stage_col` names a column that must exist (default: stage).
- `words_col` names a column that must exist (default: feature_words).
- `size_col` names a column that must exist (default: doc_n).

## Steps

1. Put a step `{"op": "topic_timeline", …}` in the analysis node’s `steps`, or set `operation` to `topic_timeline`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `topic`, `topic_words`, `first_stage`, `peak_stage`, `last_stage`, `stages_present`, `stage_path`, `size_total`, `peak_size`, `is_secondary`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_timeline",
    "steps": "[{\"op\": \"topic_timeline\", \"params\": {\"stage_col\": \"stage\", \"words_col\": \"feature_words\", \"size_col\": \"doc_n\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_timeline",
    "steps": "[{\"op\": \"topic_timeline\", \"params\": {\"stage_col\": \"stage\", \"words_col\": \"feature_words\", \"size_col\": \"doc_n\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `stage_col` | string | `stage` |  |  |
| `words_col` | string | `feature_words` |  |  |
| `size_col` | string | `doc_n` |  |  |
| `topic_col` | string | `topic` |  |  |
| `order_col` | string |  |  |  |
| `min_overlap` | number | `0.5` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: topic, topic_words, first_stage, peak_stage, last_stage, stages_present, stage_path, size_total, peak_size, is_secondary.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_timeline.md`
Skill page: `docs/capabilities/skills/operators/topic_timeline.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
