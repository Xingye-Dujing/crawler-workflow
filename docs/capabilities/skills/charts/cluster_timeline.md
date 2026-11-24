# chart.cluster_timeline

聚类时间线：每条聚类一行，横轴是首年到末年。

## When to use

看各主题簇的活跃年代与延续长度。

Do not use it when:

- 需要单节点的突现年份用突现图。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `聚类`, `聚类标签`, `首年`, `末年`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `cluster_timeline`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "cluster_timeline"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "cluster_timeline"
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
Documentation: `docs/capabilities/charts/cluster_timeline.md`
Skill page: `docs/capabilities/skills/charts/cluster_timeline.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
