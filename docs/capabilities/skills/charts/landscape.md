# chart.landscape

聚类景观图：把每个聚类画成一块区域，块内是它的成员节点。

## When to use

用一页说明文献由哪几个研究板块构成。

Do not use it when:

- 要看板块随年代的变化用聚类时间线或热力图。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `聚类`, `聚类标签`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `landscape`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "landscape"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "landscape"
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
Documentation: `docs/capabilities/charts/landscape.md`
Skill page: `docs/capabilities/skills/charts/landscape.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
