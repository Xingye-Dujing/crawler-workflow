# node.verify

采集校验 reads two tables: the promised list and the crawled result. It matches keys, compares the expected count (评论数) with the actual rows, and emits 采集状态/期望条数/实际条数/缺失条数/完成度.

## When to use

After a comment crawl, when the list says how many comments each post should have.

Do not use it when:

- For an exact count over one table use dataset_query; this node compares two tables.

## Prerequisites

- Two tables: the promised list first and the crawl result second (or swap_tables).
- Key columns that exist in both tables.

## Steps

1. Wire the promised list in first and the crawl result in second (or set swap_tables).
2. Name the list key, the result key and the expected-count column.
3. Choose gaps for the re-crawl feed or all for the audit.

## Examples

```json
{
  "type": "verify",
  "params": {
    "input_key_column": "链接",
    "result_key_column": "文章URL",
    "expected_count_column": "评论数",
    "output_mode": "gaps"
  }
}
```

## Template JSON

```json
{
  "type": "verify",
  "params": {
    "input_key_column": "链接",
    "result_key_column": "文章URL",
    "expected_count_column": "期望条数",
    "output_mode": "gaps"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `input_key_column` | string | `链接` | yes |  |
| `result_key_column` | string | `文章URL` | yes |  |
| `expected_count_column` | string | `评论数` |  |  |
| `match_mode` | string | `url` |  |  |
| `tolerance` | integer | `0` |  |  |
| `per_link_limit` | string |  |  |  |
| `output_mode` | string | `gaps` |  | gaps, all |
| `swap_tables` | boolean | `False` |  |  |
| `ignore_case` | boolean | `False` |  |  |

## Failure modes

- Not exactly two data parents: engine.verify_two_inputs.
- Missing list/result key: engine.verify_need_list_col/result_col.
- A key column absent from its table: the executor names the column.

## Acceptance

- The output counts missing and short items per key.
- Both key columns are named when absent.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/verify.md`
Skill page: `docs/capabilities/skills/nodes/verify.md`
Contract tests: `tests/unit/capabilities/test_verify_manifest.py`
