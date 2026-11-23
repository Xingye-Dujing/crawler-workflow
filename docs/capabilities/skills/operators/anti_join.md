# operator.anti_join

按连接键排除已出现在第二张表里的行（内容去重），可只保留交集。

## When to use

新一轮采集前先剔掉上一轮已抓过的链接/内容。

Do not use it when:

- 要合并两张表的列用 join_tables；同一张表内去重用 drop_duplicates。

## Prerequisites

- An upstream table (the analysis node’s input).
- `left_on` is a key of one of the two incoming tables.
- `right_on` is a key of one of the two incoming tables.

## Steps

1. Put a step `{"op": "anti_join", …}` in the analysis node’s `steps`, or set `operation` to `anti_join`.
2. A missing column, a blank required box or a value outside a declared select refuses by name.
3. The output columns depend on the data; read them from the node’s result.

## Examples

```json
{
  "type": "analysis",
  "params": {
    "operation": "anti_join",
    "steps": "[{\"op\": \"anti_join\", \"params\": {\"left_on\": \"正文\", \"right_on\": \"正文\"}}]"
  }
}
```

## Template JSON

```json
{
  "type": "analysis",
  "params": {
    "operation": "anti_join",
    "steps": "[{\"op\": \"anti_join\", \"params\": {\"left_on\": \"正文\", \"right_on\": \"正文\"}}]"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `left_on` | string |  |  |  |
| `right_on` | string |  |  |  |
| `mode` | string | `trim` |  | exact, trim, url, text, similar |
| `keep` | string | `exclude` |  | exclude, keep |
| `ignore_case` | boolean | `False` |  |  |
| `max_distance` | integer | `8` |  |  |
| `swap_tables` | boolean | `False` |  |  |

## Failure modes

- A named column the table does not hold: `analysis.step_col_missing`.
- A blank required parameter: `analysis.need_param`.
- A value outside a declared select: `analysis.bad_option`.
- The lineage cannot name this step’s columns without the data; a chart fed by it is unprovable.

## Acceptance

- The console reports the output shape; a downstream step that names a column is checked against it.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/operators/anti_join.md`
Skill page: `docs/capabilities/skills/operators/anti_join.md`
Contract tests: `tests/unit/capabilities/test_operator_manifests.py`
