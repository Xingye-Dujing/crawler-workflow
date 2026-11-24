# chart.map

地图图：按地区名称把数值铺到地图上，颜色深浅表示大小。

## When to use

语料带地区维度（IP 归属、用户城市）时。

Do not use it when:

- 地区名与内置底图不一致时会落空；没有地区列时用柱状图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（geo，必填）, `value_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `map`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a geo column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "map",
    "x_field": "地区"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "map",
    "x_field": "地区"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | geo | yes |  |  |
| `value_field` | value |  |  |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/map.md`
Skill page: `docs/capabilities/skills/charts/map.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
