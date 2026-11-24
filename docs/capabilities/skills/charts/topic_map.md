# chart.topic_map

主题距离图：每个主题一个气泡，位置是主题间距离，大小是文档占比。

## When to use

主题距离图：看哪些主题彼此接近、哪个主题占比最大。

Do not use it when:

- 要看每个主题的词用显著词图；没有 pc1/pc2 列时先用分析节点生成。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（coordinate，必填）, `y_field`（coordinate，必填）, `label_field`（label，可选）, `value_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `topic_map`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a coordinate column.
4. `y_field` reads a coordinate column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "topic_map",
    "x_field": "pc1",
    "y_field": "pc2",
    "label_field": "topic",
    "value_field": "prevalence_pct"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "topic_map",
    "x_field": "pc1",
    "y_field": "pc2",
    "label_field": "topic",
    "value_field": "prevalence_pct"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | coordinate | yes | `pc1` |  |
| `y_field` | coordinate | yes | `pc2` |  |
| `label_field` | label |  | `topic` |  |
| `value_field` | value |  | `prevalence_pct` |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/topic_map.md`
Skill page: `docs/capabilities/skills/charts/topic_map.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
