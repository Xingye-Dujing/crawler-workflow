# chart.topic_terms

显著词图：每个主题里最有区分度的词，及其总体频率与主题内频率。

## When to use

显著词图：说明每个主题真正独特的词，而不是全语料高频词。

Do not use it when:

- 要看主题在平面上的位置用主题距离图。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，必填）, `y_field`（value，必填）, `y2_field`（value，必填）.

## Steps

1. Set the visualize node’s `chart_type` to `topic_terms`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category column.
4. `y_field` reads a value column.
5. `y2_field` reads a value column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "topic_terms",
    "x_field": "term",
    "y_field": "overall_freq",
    "y2_field": "within_freq"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "topic_terms",
    "x_field": "term",
    "y_field": "overall_freq",
    "y2_field": "within_freq"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | category | yes | `term` |  |
| `y_field` | value | yes | `overall_freq` |  |
| `y2_field` | value | yes | `within_freq` | agg2 |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/topic_terms.md`
Skill page: `docs/capabilities/skills/charts/topic_terms.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
