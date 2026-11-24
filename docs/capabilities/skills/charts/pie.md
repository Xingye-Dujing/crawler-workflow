# chart.pie

饼图：一个整体被分成几份，扇面角度表示占比。

## When to use

少量类别（约 6 个以内）的份额构成，如情感分布。

Do not use it when:

- 类别多或需要精确比较大小时用柱状图；份额为负无法画面积。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，必填）, `y_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `pie`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "pie",
    "x_field": "分类"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "pie",
    "x_field": "分类"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | category | yes |  |  |
| `y_field` | value |  |  | agg |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/pie.md`
Skill page: `docs/capabilities/skills/charts/pie.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
