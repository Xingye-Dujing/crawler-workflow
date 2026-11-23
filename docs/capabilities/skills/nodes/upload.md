# node.upload

文件上传 turns one stored dataset into the same row table a crawl produces. Downstream nodes never know the difference; the dataset id is the binding.

## When to use

When the corpus is a file rather than a crawl: the one place a file enters a workflow.

Do not use it when:

- A crawl belongs on node.source; a file outside the dataset store belongs on workspace_import first.

## Prerequisites

- A stored dataset id (upload, paste or import in the data panel).

## Steps

1. Upload or paste a file in the data panel and note its dataset id.
2. Create 文件上传 and pick the dataset.
3. Wire it into 清洗/分词/分析 as if it were a crawl.

## Examples

```json
{
  "type": "upload",
  "params": {
    "dataset_id": "ds_123",
    "dataset_name": "comments.csv",
    "row_count": ""
  }
}
```

## Template JSON

```json
{
  "type": "upload",
  "params": {
    "dataset_id": "ds_example",
    "dataset_name": "comments.csv"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `dataset_id` | string |  | yes |  |
| `dataset_name` | string |  |  |  |
| `row_count` | string |  |  |  |

## Failure modes

- No dataset_id: refused with engine.upload_no_file before the run.
- The dataset was deleted and no name/row-count replacement exists: the executor refuses instead of returning [].

## Acceptance

- The node emits as many rows as the dataset holds.
- A missing dataset settles with a named refusal, not an empty table.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/upload.md`
Skill page: `docs/capabilities/skills/nodes/upload.md`
Contract tests: `tests/unit/capabilities/test_upload_manifest.py`
