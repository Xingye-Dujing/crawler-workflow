# node.compile

PDF 编译 collects the LaTeX emitted by visualize parents and compiles one document. It reads parent artifacts, not rows, and refuses an empty source instead of producing a blank PDF.

## When to use

When several charts/tables should become one PDF; a single chart can be saved directly.

Do not use it when:

- One chart is saved directly; a table export belongs on node.output.
- This node only assembles LaTeX parents, it does not read rows.

## Prerequisites

- At least one visualize parent.
- That parent has LaTeX figure and/or table switched on.

## Steps

1. Turn on 输出 LaTeX and/or LaTeX 表格 on every visualize parent.
2. Wire those visualize nodes into PDF 编译.
3. Wire the compile node into 保存 when the PDF needs a user-chosen filename.

## Examples

```json
{
  "type": "compile",
  "params": {}
}
```

## Template JSON

```json
{
  "type": "compile",
  "params": {}
}
```

## Parameters

This capability takes no declared parameters.

## Failure modes

- No parent: engine.compile_no_upstream.
- A parent is not a visualize node: engine.compile_bad_parent names it.
- A visualize parent has both LaTeX boxes off: engine.compile_source_both_off names it.

## Acceptance

- A PDF file exists for the run.
- A parent that is not a visualize node or has both LaTeX boxes off is named.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/compile.md`
Skill page: `docs/capabilities/skills/nodes/compile.md`
Contract tests: `tests/unit/capabilities/test_compile_manifest.py`
