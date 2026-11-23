# node.name

工作流命名 is pure metadata: it names the run and must feed a real node.

## When to use

At the head of a canvas whose runs should be grouped by a readable name.

Do not use it when:

- Not for naming the exported file: that is node.output.

## Prerequisites

- A canvas that holds at least one data-producing node downstream.

## Steps

1. Put 工作流命名 at the head of the canvas (no incoming wire).
2. Type the run name; a blank name is refused before the run and in history grouping.
3. Wire it into the node whose work the name describes.

## Examples

```json
{
  "type": "name",
  "params": {
    "workflow_name": "知乎评论 · 10 月",
    "layout_order": ""
  }
}
```

## Template JSON

```json
{
  "type": "name",
  "params": {
    "workflow_name": "example run",
    "layout_order": ""
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `workflow_name` | string |  | yes |  |
| `layout_order` | string |  |  |  |

## Failure modes

- Blank workflow_name: refused with engine.name_no_label.
- An incoming wire: refused with engine.name_not_head.
- No outgoing wire: refused with engine.name_no_downstream.

## Acceptance

- Validate reports no error for this node.
- The history panel groups the run under the typed name.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/name.md`
Skill page: `docs/capabilities/skills/nodes/name.md`
Contract tests: `tests/unit/capabilities/test_name_manifest.py`
