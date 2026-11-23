# node.resume

断点续采 adopts rows an earlier run already stored. Blank ids mean “newest unfinished run of this workflow shape, fullest node”; a limit truncates the adopted table.

## When to use

When the original source cannot run again but its rows are already paid for.

Do not use it when:

- Not a repair: a source that can run again is cheaper than adopting an older result.
- Not for copying one node between canvases.

## Prerequisites

- An earlier run of this workflow shape that stored rows.
- Optionally the run id and node id to adopt; blank means the automatic choice.

## Steps

1. Pick a resumable run and node, or leave both blank for the automatic choice.
2. Optionally set a row limit.
3. Wire the adopted rows into the rest of the chain.

## Examples

```json
{
  "type": "resume",
  "params": {
    "resume_run_id": "",
    "resume_node_id": "",
    "resume_limit": 0
  }
}
```

## Template JSON

```json
{
  "type": "resume",
  "params": {
    "resume_run_id": "",
    "resume_node_id": "",
    "resume_limit": 0
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `resume_run_id` | string |  |  |  |
| `resume_node_id` | string |  |  |  |
| `resume_limit` | integer | `0` |  |  |

## Failure modes

- No resumable run: the executor logs resume.no_run and returns no rows.
- The picked node holds nothing and no node has rows: resume.empty.

## Acceptance

- The node emits the adopted rows and the run shows them as this node's output.
- A run without stored rows reports resume.empty instead of zero rows.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/resume.md`
Skill page: `docs/capabilities/skills/nodes/resume.md`
Contract tests: `tests/unit/capabilities/test_resume_manifest.py`
