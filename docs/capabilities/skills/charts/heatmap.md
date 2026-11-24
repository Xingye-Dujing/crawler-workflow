# chart.heatmap

热力图：两个类别轴交叉成单元格，颜色深浅表示聚合值。

## When to use

两个维度交叉的强度：阶段 × 主题、平台 × 情感。

Do not use it when:

- 只有一个维度时用柱状图或折线图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category2，必填）, `y_field`（category2，必填）, `value_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `heatmap`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category2 column.
4. `y_field` reads a category2 column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "heatmap",
    "x_field": "分类2",
    "y_field": "分类2"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "heatmap",
    "x_field": "分类2",
    "y_field": "分类2"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | category2 | yes |  |  |
| `y_field` | category2 | yes |  |  |
| `value_field` | value |  |  | agg |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/heatmap.md`
Skill page: `docs/capabilities/skills/charts/heatmap.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
