# node.python

Python 节点 runs one saved script from the account’s script library over the upstream rows. The script reads CIXI_INPUT and writes CIXI_OUTPUT (JSON Lines); the node stores its id, not code.

## When to use

When a transformation is not one of the built-in operations and should be reused as a script.

Do not use it when:

- When a built-in operation exists, use node.process first (capability-first policy).
- Cloud mode has no Python and refuses this node by name.

## Prerequisites

- A script saved in the account script library.
- Local or desktop mode with ai_allow_python on.
- Upstream rows in the CIXI_INPUT JSONL contract.

## Steps

1. Save or pick a script in the Python panel.
2. Wire the rows in and set args (a JSON object the script reads from CIXI_ARGS).
3. Keep timeout/max_rows within the script’s needs; the runtime caps the output rows.

## Examples

```json
{
  "type": "python",
  "params": {
    "script_id": "clean_links",
    "args": "{\"drop_empty\": true}",
    "timeout": 120,
    "max_rows": 200000
  }
}
```

## Template JSON

```json
{
  "type": "python",
  "params": {
    "script_id": "clean_links",
    "args": "{}",
    "timeout": 120
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `script_id` | string |  |  |  |
| `args` | string | `{}` |  |  |
| `timeout` | integer | `120` |  |  |
| `max_rows` | integer | `200000` |  |  |

## Failure modes

- Cloud mode: refused by name (ai.pythonCloud).
- No/unknown script: refused with ai.pythonUnknown.
- Bad args JSON: ai.pythonArgs; bad timeout/max_rows: ai.pythonBadNumber.

## Acceptance

- The node returns rows written to CIXI_OUTPUT and a zero exit code.
- A failed script names its stderr instead of settling an empty table.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/python.md`
Skill page: `docs/capabilities/skills/nodes/python.md`
Contract tests: `tests/unit/capabilities/test_python_manifest.py`
