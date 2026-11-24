# chart.variation

变化图：每个节点的起止年与结构变化，用颜色标记上升/下降。

## When to use

看关键词在研究周期内是升温还是退场。

Do not use it when:

- 要看突现强度与区间用突现词图。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `起始年`, `结束年`, `结构变化`.

## Steps

1. Set the visualize node’s `chart_type` to `variation`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "variation"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "variation"
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
Documentation: `docs/capabilities/charts/variation.md`
Skill page: `docs/capabilities/skills/charts/variation.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
