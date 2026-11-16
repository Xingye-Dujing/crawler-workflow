---
name: data-pipeline
description: Work on 采析绘's dataset layer — upload/paste/import, dataset store and lineage, merge and SimHash dedupe, preview/inspect/diff/rename/delete, and CSV/Excel export. Use when rows appear duplicated or missing, a merged table has the wrong order or count, an import loses columns, or an export is incomplete.
---

# Dataset pipeline (import → merge → dedupe → export)

Read first: `AGENTS.md` → "Analysis steps and the data contract"; `docs/analysis.md`;
`docs/agent_practices.md` → "Dataset merge", "A quoted row count...".

## File map

```text
backend/api/data.py                 # upload / paste / inspect / diff / merge / preview / clear / rename
backend/api/exports.py              # /api/export/save + /api/exports/*
backend/services/datasets/store.py  # datasets.db: frames, parquet/csv, lineage, metadata
backend/services/datasets/merge.py  # column union, order, conflict rules
backend/services/datasets/dedupe.py # SimHash (keeps the first-arriving row)
backend/services/exports/writer.py  # CSV/Excel writing, shard batches, 固定 files
backend/services/exports/browser.py # listing/download of export files
backend/services/biblio/            # CNKI/RefWorks importers and their own metrics
backend/nodes/executors/upload.py   # the upload node (dataset into a canvas)
backend/nodes/executors/output.py   # the output/export node
```

## Invariants that bite

- **A quoted row count is only true of the merge order that produced it.** SimHash keeps the first
  row it sees, so a different upstream order yields a different table. Measure through the canvas's
  own `connections` walk, never by globbing `data/`.
- **Column union order is a contract.** A merge decides column order; a downstream chart reading a
  renamed column must fail by name, not render empty.
- **Dedupe keys are explicit.** State the text column and the threshold you used. A near-duplicate
  is not a duplicate; keep the evidence (which row survived).
- **Lineage is data, not a comment.** `data/lineages` must name the parent datasets a merge/analysis
  produced; deleting a parent must not leave a dangling id silently.
- **An import must not silently drop rows or columns.** A skipped sheet/encoding/row count is
  reported; an empty result never settles as success.
- **Blank is not zero, and `0` is a value.** Numeric coercion must not turn a missing cell into 0.
- **Export writes what the run stored**, in the platform's column order; a shard batch keeps its
  `.partNNN` siblings and a 固定 file is never deleted by 清理.
- **Uploads are bounded by `max_upload_mb`** (Flask `MAX_CONTENT_LENGTH`); a too-large body answers
  the JSON 413 envelope, never HTML.
- **One data root, one writer.** A dataset write during a live run follows the run's account scope;
  never write system-level while an account is bound.

## Recipe: add an import format

1. Detect the format by content/suffix and state the chosen parser.
2. Parse into a DataFrame with explicit dtypes; report encoding, sheet, skipped rows.
3. Normalize column names only through the existing helper; keep a mapping to the original.
4. Store the dataset and its lineage; return the id and a profile (rows, columns, missing).
5. Add a fixture file under `tests/` (small, deterministic) plus an API case and a merge case.
6. Show the format in the panel's accept list and both-language hint.

## Recipe: fix a duplicate/short table

1. Reproduce through the canvas: read the upstream order and the exact merge/dedupe parameters.
2. Identify whether the missing rows are (a) dedupe survivors, (b) a column mismatch dropping
   rows, (c) a cursor/checkpoint hole, or (d) a site-side short list.
3. Fix the cause; do not "top up" rows by hand.
4. Re-run and quote the count with the order that produced it.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q tests/unit/datasets tests/api/test_data.py
.venv\Scripts\python.exe -m pytest -q tests/unit/exports tests/api/test_exports.py
```

A real file export/Excel check belongs to the device tier; never claim a workbook from a mocked
writer.

## Common failures

- `COUNT(*)` used for the next offset/seq (should be `MAX(seq)+1`).
- Dedupe applied before the sort the user expected, changing which row survives.
- Renaming a column at merge time without updating the chart contract.
- A 413 answered as HTML, so the panel reports "unknown error".
- Deleting a dataset that a stored workflow still references by id.
