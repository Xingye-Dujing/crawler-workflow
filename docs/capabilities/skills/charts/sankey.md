# chart.sankey

桑基图：来源到目标的带权流向，带宽表示流量。

## When to use

主题流向、平台到情感的去向、阶段之间的转移。

Do not use it when:

- 没有“从哪到哪”的两列时用柱状图或热力图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（source，必填）, `y_field`（target，必填）, `value_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `sankey`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a source column.
4. `y_field` reads a target column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "sankey",
    "x_field": "来源",
    "y_field": "目标"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "sankey",
    "x_field": "来源",
    "y_field": "目标"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | source | yes |  |  |
| `y_field` | target | yes |  |  |
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
Documentation: `docs/capabilities/charts/sankey.md`
Skill page: `docs/capabilities/skills/charts/sankey.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
