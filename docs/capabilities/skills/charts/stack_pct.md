# chart.stack_pct

百分比堆叠柱：每个类别的几列占比堆成 100%，看构成变化。

## When to use

正/中/负情感占比随时间或阶段的变化。

Do not use it when:

- 没有被拆成几列占比时用普通柱状图；要看总量而不是构成时不适合。

## Prerequisites

- An upstream table (the visualize node’s input).
- These boxes: `x_field`（category，必填）, `stack_fields`（list，必填）.

## Steps

1. Set the visualize node’s `chart_type` to `stack_pct`.
2. Fill each required box with a column of the upstream table.
3. `x_field` reads a category column.
4. `stack_fields` reads a list column.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "stack_pct",
    "x_field": "分类",
    "stack_fields": "积极占比, 中性占比, 消极占比"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "stack_pct",
    "x_field": "分类",
    "stack_fields": "积极占比, 中性占比, 消极占比"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Fields

| field | role | required | default | control |
|---|---|---|---|---|
| `x_field` | category | yes |  |  |
| `stack_fields` | list | yes |  |  |

## Failure modes

- A required box is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A value/coordinate column that holds no number at all: engine.chart_column_not_numeric.

## Acceptance

- The chart option or image exists for the run.
- A missing required box is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/charts/stack_pct.md`
Skill page: `docs/capabilities/skills/charts/stack_pct.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
