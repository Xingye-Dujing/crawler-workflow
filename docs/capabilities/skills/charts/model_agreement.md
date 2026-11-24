# chart.model_agreement

模型一致性矩阵：每个模型对每条数据给出的标签是否一致。

## When to use

多个情感/倾向模型对同一份语料比较，找出分歧样本。

Do not use it when:

- 只用一个模型时没有“一致性”可看。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `model_field`（column，必填）, `agreement_label_field`（column，可选）, `id_field`（column，必填）.

## Steps

1. Set the visualize node’s `chart_type` to `model_agreement`.
2. Fill each required box with a column of the upstream table.
3. `model_field` reads a column column.
4. `id_field` reads a column column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "model_agreement",
    "model_field": "模型",
    "id_field": "原行"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "model_agreement",
    "model_field": "模型",
    "id_field": "原行"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `model_field` | column | yes | `模型` |  |
| `agreement_label_field` | column |  |  |  |
| `id_field` | column | yes | `原行` |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/model_agreement.md`
Skill page: `docs/capabilities/skills/charts/model_agreement.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
