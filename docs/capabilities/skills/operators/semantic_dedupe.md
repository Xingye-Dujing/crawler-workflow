# operator.semantic_dedupe

用本地句向量比较一列文本，删掉语义重复的行（同义改写也算）。

## When to use

同一观点被换词重写多次，需要按意思去重时。

Do not use it when:

- 只是字面相近用 dedupe_similar；要按关键词找相似行用 similar_to。

## Prerequisites

- An upstream table (the analysis node’s input).
- `column` names a column that must exist (default: none — required).

## Steps

1. Put a step `{"op": "semantic_dedupe", …}` in the analysis node’s `steps`, or set `operation` to `semantic_dedupe`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "semantic_dedupe",
    "steps": "[{\"op\": \"semantic_dedupe\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "semantic_dedupe",
    "steps": "[{\"op\": \"semantic_dedupe\", \"params\": {\"column\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `model` | string | `BAAI/bge-small-zh-v1.5` |  |  |
| `threshold` | number | `0.92` |  |  |
| `batch_size` | integer | `64` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/semantic_dedupe.md`
Skill page: `docs/capabilities/skills/operators/semantic_dedupe.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
