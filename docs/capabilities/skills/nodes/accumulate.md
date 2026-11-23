# node.accumulate

数据累积 appends the rows passing through it into a named lineage. ``identity=row`` appends every row; ``identity=columns`` appends only rows whose key columns are not already present.

## When to use

When repeated runs should accumulate into one growing dataset instead of separate files.

Do not use it when:

- A standalone file belongs on node.output; a one-off result should not grow a lineage.

## Prerequisites

- Exactly one table producer upstream.
- A lineage name that stays the same across runs.
- Key columns when identity is columns.

## Steps

1. Name the lineage (the same name across runs accumulates together).
2. Choose row identity or key columns; key columns are required for the column mode.
3. Wire exactly one table producer in.

## Examples

```json
{
  "type": "accumulate",
  "params": {
    "lineage_name": "知乎评论",
    "identity": "row",
    "key_columns": ""
  }
}
```

## Template JSON

```json
{
  "type": "accumulate",
  "params": {
    "lineage_name": "example-lineage",
    "identity": "row",
    "key_columns": ""
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `lineage_name` | string |  | yes |  |
| `identity` | string | `row` |  | row, columns |
| `key_columns` | string |  |  |  |

## Failure modes

- Blank lineage name: engine.accumulate_no_name.
- Unknown identity or column mode without keys: engine.accumulate_bad_identity/no_keys.
- Not exactly one parent, or a non-table parent: engine.accumulate_one_parent/bad_parent.

## Acceptance

- The lineage grows by the rows (or the new keys) of this run.
- A non-table or second parent is refused by name.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/accumulate.md`
Skill page: `docs/capabilities/skills/nodes/accumulate.md`
Contract tests: `tests/unit/capabilities/test_accumulate_manifest.py`
