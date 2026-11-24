# chart.graph3d

三维共现图：在三个坐标上展开节点，用深度缓解平面拥挤。

## When to use

共现关系密集、二维图互相遮挡时。

Do not use it when:

- 要印刷或静态截图时用二维知识图谱，三维在纸上无法阅读。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `x`, `y`, `连接`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `graph3d`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "graph3d"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "graph3d"
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
Documentation: `docs/capabilities/charts/graph3d.md`
Skill page: `docs/capabilities/skills/charts/graph3d.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
