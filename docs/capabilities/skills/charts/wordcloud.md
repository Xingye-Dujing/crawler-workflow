# chart.wordcloud

词云：词语按权重放大排布，一眼看出高频词。

## When to use

分词结果的直观展示，尤其是报告首页的“关键词印象”。

Do not use it when:

- 要精确比较词频用柱状图或表格；词太多时词云会看不清。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（text，必填）, `value_field`（value，可选）.

## Steps

1. Set the visualize node’s `chart_type` to `wordcloud`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a text column.
4. Optional controls: tokenize, wordcloud_style.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "wordcloud",
    "x_field": "文本"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "wordcloud",
    "x_field": "文本"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | text | yes |  |  |
| `value_field` | value |  |  |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/wordcloud.md`
Skill page: `docs/capabilities/skills/charts/wordcloud.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
