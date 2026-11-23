# node.visualize

可视化 builds one chart from the upstream rows: an ECharts option or a matplotlib image, plus optional LaTeX figure/table. The chart type decides which fields it reads; the fields it requires are refused before a run.

## When to use

When rows should become a chart; a PDF document belongs on PDF 编译.

Do not use it when:

- Several charts into one PDF belong on node.compile.
- A table export belongs on node.output; a chart is not a file save.

## Prerequisites

- An upstream table.
- The fields the chosen chart declares; validate names a blank required box.
- The engine this build serves (echarts or matplotlib).

## Steps

1. Pick the chart type (词云, 柱状图, 主题距离图, 文献共现, …).
2. Pick the x/y/value/label fields; a chart that needs no x says so.
3. Turn on LaTeX outputs only when a PDF 编译/保存 will consume them.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "bar",
    "x_field": "word",
    "y_field": "frequency",
    "engine": "echarts"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "bar",
    "x_field": "word",
    "y_field": "frequency",
    "engine": "echarts"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `chart_type` | string | `bar` |  |  |
| `x_field` | string |  |  |  |
| `y_field` | string |  |  |  |
| `value_field` | string |  |  |  |
| `agg` | string | `sum` |  |  |
| `engine` | string | `echarts` |  |  |
| `title` | string |  |  |  |
| `tokenize` | boolean | `False` |  |  |
| `emit_latex` | boolean | `True` |  |  |
| `emit_latex_table` | boolean | `True` |  |  |

## Failure modes

- A required field is blank: engine.chart_field_missing names the chart and the box.
- A chart type this build does not serve: engine.chart_unknown (the declared default is the fix).
- A box plot with neither x nor y: engine.chart_field_group_missing.

## Acceptance

- The chart option or image exists for the run and the LaTeX switches match the request.
- A missing required field is named before the run.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/visualize.md`
Skill page: `docs/capabilities/skills/nodes/visualize.md`
Contract tests: `tests/unit/capabilities/test_visualize_manifest.py`
