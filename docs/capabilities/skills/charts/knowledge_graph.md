# chart.knowledge_graph

文献知识图谱：节点按共现坐标布局，连线宽度表示共现强度。

## When to use

文献分析之后的主题/关键词共现图谱。

Do not use it when:

- 普通评论语料的词共现用关系网络；没有 biblio 节点写出的列时无法绘制。

## Prerequisites

- An upstream table (the visualize node’s input).
- Columns written by 文献分析: `节点`, `x`, `y`, `连接`, `频次`.

## Steps

1. Set the visualize node’s `chart_type` to `knowledge_graph`.
2. Fill each required box with a column of the upstream table.

## Examples

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "knowledge_graph"
  }
}
```

## Template JSON

```json
{
  "type": "visualize",
  "params": {
    "chart_type": "knowledge_graph"
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
Documentation: `docs/capabilities/charts/knowledge_graph.md`
Skill page: `docs/capabilities/skills/charts/knowledge_graph.md`
Contract tests: `tests/unit/capabilities/test_chart_manifests.py`
