# chart.bar

柱状图：每个类别一根柱子，柱长表示聚合后的数值。

## When to use

类别之间比大小：各平台发帖量、高频词、各主题文档数。

Do not use it when:

- 类别多到看不清（十几类以上）时改用表格或折线；看份额用饼图/百分比堆叠。
- 时间连续且点多时用折线图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，必填）, `y_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `bar`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category column.
4. Optional controls: annotations.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "bar",
    "x_field": "分类"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "bar",
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
Documentation: `docs/capabilities/charts/bar.md`
Skill page: `docs/capabilities/skills/charts/bar.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
