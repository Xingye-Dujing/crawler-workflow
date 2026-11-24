# chart.network

关系网络：来源/目标/权重三列画成节点与连线，可居中一个关键节点。

## When to use

回复网络、词语共现、作者互动。

Do not use it when:

- 只要看两两流向的带宽用桑基图；边太多时网络会变成毛线球。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（source，必填）, `y_field`（target，必填）, `value_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `network`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a source column.
4. `y_field` reads a target column.
5. Optional controls: center_node.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "network",
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
    "chart_type": "network",
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
Documentation: `docs/capabilities/charts/network.md`
Skill page: `docs/capabilities/skills/charts/network.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
