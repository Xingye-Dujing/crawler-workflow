# chart.histogram

直方图：把一个数值列分箱，画出每个区间的数量分布。

## When to use

看一个数值的分布形状：点赞数的长尾、长度的集中区间。

Do not use it when:

- 要看两个数值的关系用散点图；要按类别比较用柱状图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（value，必填）.

## Steps

1. Set the visualize node’s `chart_type` to `histogram`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a value column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "histogram",
    "x_field": "数值"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "histogram",
    "x_field": "数值"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | value | yes |  |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/histogram.md`
Skill page: `docs/capabilities/skills/charts/histogram.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
