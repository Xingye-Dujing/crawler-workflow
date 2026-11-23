# operator.reply_graph

按评论者、楼层与父楼层还原“谁回复谁”的关系，输出带权重的边表。

## When to use

要画互动网络、找关键传播者或社区结构时。

Do not use it when:

- 表里没有楼层/父楼层字段时无法还原回复关系，请先确认采集列。

## Prerequisites

- An upstream table (the analysis node’s input).
- `author_col` names a column that must exist (default: 评论者).
- `floor_col` names a column that must exist (default: 楼层).
- `parent_floor_col` names a column that must exist (default: 父楼层).

## Steps

1. Put a step `{"op": "reply_graph", …}` in the analysis node’s `steps`, or set `operation` to `reply_graph`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `src_author`, `dst_author`, `weight`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "reply_graph",
    "steps": "[{\"op\": \"reply_graph\", \"params\": {\"author_col\": \"评论者\", \"floor_col\": \"楼层\", \"parent_floor_col\": \"父楼层\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "reply_graph",
    "steps": "[{\"op\": \"reply_graph\", \"params\": {\"author_col\": \"评论者\", \"floor_col\": \"楼层\", \"parent_floor_col\": \"父楼层\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `author_col` | string | `评论者` |  |  |
| `floor_col` | string | `楼层` |  |  |
| `parent_floor_col` | string | `父楼层` |  |  |
| `article_col` | string | `文章URL` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: src_author, dst_author, weight.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/reply_graph.md`
Skill page: `docs/capabilities/skills/operators/reply_graph.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
