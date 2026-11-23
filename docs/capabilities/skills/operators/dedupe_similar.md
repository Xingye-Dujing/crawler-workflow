# operator.dedupe_similar

按一列文本的 SimHash 距离删除近似重复行（改写、加表情、换标点）。

## When to use

评论/转发里同一句话被改写多次时，保留一条代表。

Do not use it when:

- 需要语义相似（同义改写）时用 semantic_dedupe；逐字重复用 drop_duplicates。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "dedupe_similar", …}` in the analysis node’s `steps`, or set `operation` to `dedupe_similar`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "dedupe_similar",
    "steps": "[{\"op\": \"dedupe_similar\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "dedupe_similar",
    "steps": "[{\"op\": \"dedupe_similar\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `max_distance` | integer | `8` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/dedupe_similar.md`
Skill page: `docs/capabilities/skills/operators/dedupe_similar.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
