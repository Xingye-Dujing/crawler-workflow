# chart.biblio_heatmap

文献热力图：聚类 × 年份的单元格热度，看各板块何时活跃。

## When to use

比较多个聚类在不同年份的强度。

Do not use it when:

- 只看单个节点逐年出现用时区图。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `聚类`, `聚类标签`, `年份序列`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `biblio_heatmap`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "biblio_heatmap"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "biblio_heatmap"
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
Documentation: `docs/capabilities/charts/biblio_heatmap.md`
Skill page: `docs/capabilities/skills/charts/biblio_heatmap.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
