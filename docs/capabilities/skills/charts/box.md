# chart.box

箱线图：按类别展示数值的中位数、四分位与离群值。

## When to use

比较不同类别的分布形状，而不只是均值：各平台点赞分布。

Do not use it when:

- 只需要均值或总量时用柱状图；样本极少时箱线图没有意义。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，可选（y_field 已填时必填））, `y_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `box`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "box",
    "x_field": "分类",
    "y_field": "数值"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "box",
    "x_field": "分类",
    "y_field": "数值"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | category | when y_field |  |  |
| `y_field` | value |  |  | agg |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.
- A required group left entirely blank: engine.chart_field_group_missing.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/box.md`
Skill page: `docs/capabilities/skills/charts/box.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
