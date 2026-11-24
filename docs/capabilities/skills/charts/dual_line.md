# chart.dual_line

双轴折线图：左右两条 Y 轴各画一条曲线，量纲不同也能同图比较。

## When to use

同时看“热度（条数）”与“情感指数（-1~1）”这类量纲不同的两条曲线。

Do not use it when:

- 两条曲线量纲相同时用普通折线，双轴容易被误读成同一刻度。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，必填）, `y_field`（value，可选）, `y2_field`（value，必填）.

## Steps

1. Set the visualize node’s `chart_type` to `dual_line`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category column.
4. `y2_field` reads a value column.
5. Optional controls: annotations.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "dual_line",
    "x_field": "分类",
    "y2_field": "数值"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "dual_line",
    "x_field": "分类",
    "y2_field": "数值"
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
| `y2_field` | value | yes |  | agg2 |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/dual_line.md`
Skill page: `docs/capabilities/skills/charts/dual_line.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
