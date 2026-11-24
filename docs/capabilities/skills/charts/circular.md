# chart.circular

环形共现图：节点沿圆周排布，连线表示共现关系。

## When to use

共现关系多、力导向布局容易挤成一团时。

Do not use it when:

- 要看聚类分组用知识图谱或聚类景观图。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `连接`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `circular`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "circular"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "circular"
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
Documentation: `docs/capabilities/charts/circular.md`
Skill page: `docs/capabilities/skills/charts/circular.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
