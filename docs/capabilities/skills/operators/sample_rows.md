# operator.sample_rows

随机抽取 n 行或比例的样本（可固定随机种子）。

## When to use

大表先抽样看效果，或做对照实验时取固定样本。

Do not use it when:

- 要按条件挑行用 filter_rows。

## Prerequisites

- An upstream table (the analysis node’s input).

## Steps

1. Put a step `{"op": "sample_rows", …}` in the analysis node’s `steps`, or set `operation` to `sample_rows`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "sample_rows",
    "steps": "[{\"op\": \"sample_rows\", \"params\": {}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "sample_rows",
    "steps": "[{\"op\": \"sample_rows\", \"params\": {}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `n` | integer |  |  |  |
| `frac` | number |  |  |  |
| `seed` | integer |  |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.

## Acceptance

- Rows are filtered or reordered; the upstream columns are unchanged.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/sample_rows.md`
Skill page: `docs/capabilities/skills/operators/sample_rows.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
