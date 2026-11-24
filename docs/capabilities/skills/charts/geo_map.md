# chart.geo_map

文献地理分布图：把各节点的频次铺到内置底图的分区上。

## When to use

文献数据带有地区维度时。

Do not use it when:

- 普通语料的地区热度用地图图，它读的是你自己的地区列。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `geo_map`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "geo_map"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "geo_map"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/geo_map.md`
Skill page: `docs/capabilities/skills/charts/geo_map.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
