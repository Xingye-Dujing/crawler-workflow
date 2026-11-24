# chart.line

折线图：按有序类别（通常是时间）连成趋势线。

## When to use

看随时间或阶段的走势：每日发帖量、情感指数曲线。

Do not use it when:

- 类别之间没有顺序时用柱状图；两条量纲不同的曲线用双轴折线。
- 只有一个时间点或类别时用柱状图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，必填）, `y_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `line`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category column.
4. Optional controls: annotations.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "line",
    "x_field": "分类"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "line",
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
Documentation: `docs/capabilities/charts/line.md`
Skill page: `docs/capabilities/skills/charts/line.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
