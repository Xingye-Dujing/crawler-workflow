# operator.similar_to

用本地句向量找出与给定文字最相似的前 K 行，输出新的相似度表。

## When to use

围绕一个说法找相关评论/帖子，而不是按关键词精确过滤。

Do not use it when:

- 要删除重复内容用 semantic_dedupe；按列值精确筛选用 filter_rows。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "similar_to", …}` in the analysis node’s `steps`, or set `operation` to `similar_to`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The step returns a NEW table with columns `rank`, `row_index`, `text`, `similarity`.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "similar_to",
    "steps": "[{\"op\": \"similar_to\", \"params\": {\"column\": \"正文\", \"query\": \"关键词\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "similar_to",
    "steps": "[{\"op\": \"similar_to\", \"params\": {\"column\": \"正文\", \"query\": \"关键词\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `query` | string |  |  |  |
| `top_k` | integer | `10` |  |  |
| `model` | string | `BAAI/bge-small-zh-v1.5` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- The output table carries exactly: rank, row_index, text, similarity.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/similar_to.md`
Skill page: `docs/capabilities/skills/operators/similar_to.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
