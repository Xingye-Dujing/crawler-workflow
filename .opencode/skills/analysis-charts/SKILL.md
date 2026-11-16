---
name: analysis-charts
description: Work on 采析绘 analysis and visualization — analysis operators and column contracts, pandas pipelines, LLM-backed ops, chart registry/contracts, topic/LDA views, reports and bibliometrics. Use when adding an analysis step, changing a chart, fixing an empty or wrong figure, or wiring a new data column into the pipeline.
---

# Analysis, charts and reports

Read first: `AGENTS.md` → “Analysis steps and the data contract”, `docs/analysis.md`,
`docs/agent_practices.md` → analysis/measurement notes.

## File map

```text
backend/services/analysis/ops/<op>.py      # one operator per module; OPS registry
backend/services/analysis/params.py        # flat panel strings -> typed kwargs, STEP_* contracts
backend/services/analysis/pipeline.py      # run_pipeline, LLM_OPS, cancel
backend/services/analysis/process.py       # sequential steps, categorical phase handling
backend/services/analysis/stats.py         # summary/tests/evolution kernels
backend/services/charts/registry.py        # ONE ChartSpec table
backend/services/charts/contracts.py       # chart → required columns / reads
backend/services/charts/visualizer.py      # matplotlib/ECharts rendering
backend/services/charts/options/           # option builders per family
backend/services/reports/                  # HTML/paper/PDF
backend/services/biblio/                   # importers, metrics, charts, formats
```

## Invariants that bite

- **A step's output columns are a chart's input contract.** `topic_map` reads
  `pc1/pc2/topic/prevalence_pct`; `topic_salience` reads `term/overall_freq/within_freq`. A rename
  is a named refusal, never an empty figure.
- **A phase column's order is not data, and a records round trip erases the categorical.** A step
  that groups by phase must emit a position column (`stage_order`/阶段序号) or take time; else
  REFUSE. `分阶段 LDA`, `TopicⅠ-1…`, lifecycle/flow, evolution, group-by all depend on this.
- **A score is a function of the column it was read from.** Quote `正文` vs `cleaned_text` in the
  node title/answer; a curve without the source column cannot be audited.
- **A coherence sweep is not a decision; only the canvas's own sweep may be quoted.** The argmax
  follows row order and can be flat noise. Run `coherence_max_documents=0` on the canvas's own
  phase filters; where flat, state the tie-break (highest coherence at ≥3 topics), no unseen floor.
- **An unused LDA topic is the model's answer, not a user mistake.** `topic_by_stage` fills the
  zero-doc row from the topic's word distribution, files `doc_n=0`, and logs a named warning.
- **LLM ops are runtime, not a silent fallback.** `run_pipeline(df, steps, llm=, cancel=)` passes
  the client only to `LLM_OPS`; no model is refused before paying; a Stop leaves `未处理` →
  PARTIAL.
- **A quoted row count belongs to the merge order that produced it** (SimHash keeps first arrival).
  Walk the canvas's connections; never glob the dataset directory.
- **One chart registry.** `SPECS` is the only answer; panel labels are derived and pinned against
  it. A chart with no builder/LaTeX twin/front-end word fails its contract test.
- **Report numbers** come from the run/dataset/analysis actually read; method, sample, finding,
  limitation are separate.

## Recipe: add an analysis op

1. Add `ops/<op>.py` with the function and its `STEP_PARAMS`/contract entry where shared.
2. Declare what it reads and emits; if it replaces the table, add the emitted columns to
   `STEP_REPLACE`/the contract test.
3. If it is LLM-backed, add it to `LLM_OPS`, consume `ctx['llm']`, and handle cancel/未处理.
4. Add the panel label in both languages and a frontend `ANALYSIS_OPS` entry only if the renderer
   needs one (server payload is the authority).
5. Add unit cases for the column contract + a tiny frame; add a chart contract case if it feeds one.
6. Update `docs/analysis.md` if the visible behavior changed.

## Recipe: add or fix a chart

1. Add one `ChartSpec` to `services/charts/registry.py`; add its builder/option path and LaTeX twin
   or mark it ECharts-only/unbuildable with a reason.
2. Declare `reads`; validate required columns before rendering and refuse by name.
3. Add the label to both browser/server catalogues; pin the palette/theme through `chartPalette()`.
4. Add a contract test and a render/snapshot test where stable; a figure with zero rows is not a
   pass.

## Verification

```bash
.venv/Scripts/python.exe -m pytest -q tests/unit/analysis tests/unit/charts tests/api/test_analysis.py
.venv/Scripts/python.exe -m pytest -q tests/unit/biblio
```

If a real chart/PDF changed, also the device tier and a manual report check. Never claim a figure
from a dataframe you did not read.

## Common failures

- Renamed a column in one step, left the chart default; empty figure, green test.
- Used `COUNT(*)`/row order for a phase; the result changes after a merge.
- Let a BERT op fall back silently; the output says a mode that did not run.
- Quoted a “best topic count” from a different dataset/order than the canvas.
