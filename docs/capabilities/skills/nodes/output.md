# node.output

保存 merges every incoming table into one file, or saves a PDF from visualize/compile parents. Column sets must match; the executor refuses a merge rather than exporting only the first table.

## When to use

At the end of a chain when the rows or the PDF need a file on disk.

Do not use it when:

- Intermediate results stay on the canvas; a reusable growing table belongs on node.accumulate.

## Prerequisites

- Table parents with matching columns, or visualize/compile parents for a PDF.
- A filename; the exporter appends the extension.

## Steps

1. Wire one or more table producers into 保存 for a tabular export.
2. For a PDF, choose format=pdf (or a .pdf filename) and wire visualize/compile parents only.
3. Set the filename; the exporter appends the format extension when it is missing.

## Examples

```json
{
  "type": "output",
  "params": {
    "operation": "save",
    "format": "csv",
    "filename": "comments.csv"
  }
}
```

## Template JSON

```json
{
  "type": "output",
  "params": {
    "operation": "save",
    "format": "csv",
    "filename": "export.csv"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `operation` | string | `save` |  |  |
| `format` | string | `csv` |  |  |
| `filename` | string | `export.csv` |  |  |

## Failure modes

- No parent: engine.output_no_upstream.
- A PDF save mixed with table parents: engine.output_pdf_mixed.
- A PDF save with no visualize/compile parent: engine.output_pdf_only_pdfable.
- Both a visualize and a compile PDF source: engine.output_pdf_two_sources.
- A table save fed only by a PDF source: engine.output_needs_pdf.

## Acceptance

- The exported file exists and its row count matches the merged input.
- Mixed table and PDF parents are refused by name.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/output.md`
Skill page: `docs/capabilities/skills/nodes/output.md`
Contract tests: `tests/unit/capabilities/test_output_manifest.py`
