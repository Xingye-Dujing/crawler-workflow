# chart.scatter

散点图：两个数值列做坐标，看相关关系与离群点。

## When to use

两个数值的关系：点赞与评论、两个模型的得分、热度与情感指数。

Do not use it when:

- 只有一个数值列时看分布用直方图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（value，必填）, `y_field`（value，必填）.

## Steps

1. Set the visualize node’s `chart_type` to `scatter`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a value column.
4. `y_field` reads a value column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "scatter",
    "x_field": "数值",
    "y_field": "数值"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "scatter",
    "x_field": "数值",
    "y_field": "数值"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | value | yes |  |  |
| `y_field` | value | yes |  |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/scatter.md`
Skill page: `docs/capabilities/skills/charts/scatter.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
