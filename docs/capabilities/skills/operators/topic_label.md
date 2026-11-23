# operator.topic_label

让本地模型读每主题的特征词与样本文本，写出一句主题概括。

## When to use

主题表只有“词1 词2”时，需要给人读得懂的主题名或摘要。

Do not use it when:

- 没有可用模型时不要调用：本步按名拒绝，绝不静默换成别的模型。

## Prerequisites

- An upstream table (the analysis node’s input).
- `words_col` names a column that must exist (default: feature_words).

## Steps

1. Put a step `{"op": "topic_label", …}` in the analysis node’s `steps`, or set `operation` to `topic_label`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step keeps the upstream columns and appends the column(s) it names.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_label",
    "steps": "[{\"op\": \"topic_label\", \"params\": {\"words_col\": \"feature_words\", \"summary_col\": \"主题概括\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "topic_label",
    "steps": "[{\"op\": \"topic_label\", \"params\": {\"words_col\": \"feature_words\", \"summary_col\": \"主题概括\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `words_col` | string | `feature_words` |  |  |
| `samples_col` | string | `sample_texts` |  |  |
| `summary_col` | string | `主题概括` |  |  |
| `on_fail` | string | `abort` |  | abort, blank, fallback |
| `max_topics` | integer | `30` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Every upstream column is still present, plus the column the step names.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/topic_label.md`
Skill page: `docs/capabilities/skills/operators/topic_label.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
