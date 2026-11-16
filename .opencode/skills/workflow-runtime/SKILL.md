---
name: workflow-runtime
description: Work on the 采析绘 canvas runtime — node registry and column contracts, DAG validation, run start/queue/stop, resume/checkpoint records, reusable groups, schedules and the run console. Use when changing a node type/executor, execution order, resume behavior, run records, queueing, or diagnosing a failed/partial run.
---

# Workflow and run runtime

Read first: `AGENTS.md` → “Run, resume and record”, `docs/workflow.md`, `docs/ARCHITECTURE.md`,
`docs/agent_practices.md` → run invariants.

## File map

```text
backend/nodes/catalog.py                 # declared node types, palette labels, categories
backend/nodes/registry.py                # NODE_TYPE → run(node, call) plugin registry
backend/nodes/executors/<type>.py        # one executor: NODE_TYPE, run, emit/read columns
backend/nodes/schema.py                  # graph walk, type resolution
backend/engine/workflow.py               # resolve DAG, effective_workflow, node_label
backend/engine/plan.py                   # what a run is, transport, cost, invalidated nodes
backend/engine/run.py                    # begin_run, _run_worker, execute_node, queue drain
backend/engine/run_schedule.py           # scheduled fire → begin_run
backend/services/runs/store/             # RunStore: rows, cursors, logs, usage, settlement
backend/services/runs/queue.py           # in-memory queue + owner mirror
backend/services/workflows/              # manager/history/reusable/expand/bundle
```

## Invariants that bite

- **One start path**: manual Run, rerun, scheduled fire and queue drain all end at
  `engine.run.begin_run`. A test that stubs `begin_run` must govern every path.
- **One run at a time; a busy server queues.** `queue:false` is the only fail-fast; the Execute
  button relabels 排队运行. A `queued:true` answer means the entry is already parked.
- **The worker clears `execution_state['thread']` first and `stopping` in the same
  `execute_lock` section.** A stop route proves liveness under that lock.
- **A disabled node is not on the canvas**: `effective_workflow` drops it and cascades; fan-in
  survives on one live input. Validate/execute/fingerprint the effective graph.
- **A node's fingerprint owns its dedupe scope** (`'item:'+node_fingerprint`). Never put a label
  or a switch inside it; `_VOLATILE_PARAMS` keeps names/ids/switches out.
- **Rows are one transaction per row, seq is `MAX(seq)+1`, never `COUNT(*)`.** A cursor records
  position, not content.
- **A resumed run re-describes itself**: `start_run` refreshes workflow name/fingerprint/mode/
  headless/lang; it does not touch `started_at`.
- **Settlement is one definition**: skipped/failed/partial are not done, restored is; counts after
  settling over attempted nodes; a stopped node is not a failure.
- **A module-scope helper has no claim state.** Ten helpers were lifted out of `begin_run`; the gate
  checks AST/symtable. Do not re-embed one.
- **No `app` import** in `engine/`; state goes through `runtime.state`/`stores`.

## Recipe: add a node executor

1. Add the type/label/category to `nodes/catalog.py`; add defaults in `nodes/defaults.py`.
2. Create `nodes/executors/<type>.py` with `NODE_TYPE`, `run(node, call)`, `emit_columns`,
   `read_columns`; register through the executor package.
3. Build rows as `call.store.append_rows`/`replace_rows`; one atomic node uses one transaction.
4. Add the type to the frontend palette only from `/api/node-types` (never a second table).
5. Add a unit case for schema columns + a run case with a fake `NodeCall`.
6. Add the node label to both i18n catalogues.

## Recipe: diagnose a failed/partial run

1. Read `/api/runs/<id>` and `/api/runs/<id>/log`; the durable console is the evidence.
2. Separate a site refusal/login wall/risk from a code bug; quote the node and the line.
3. Check the node's cursor: a short table may be legal (site end marker/user cap) or a hole.
4. Check the queue/claim state: a stopped node is not a failed one.
5. Use 继续/重跑节点, never a hand-edited row; a durable mutation follows the claim.

## Verification

```bash
.venv/Scripts/python.exe -m pytest -q tests/unit/analysis/test_node_plugins.py tests/unit/engine tests/api/test_runs.py
```

If the change touches execution/resume/UI, also the device tier and `/smoke-verify`. A real run
that writes into the user's `data/` must be a user-started run, not a test.

## Common failures

- A new node emits a column the next node cannot read; validate at configuration time, name it.
- A filter/merge changed row order; a quoted row count is only true of that order.
- A resumed run's fingerprint includes a label; reuse/dedupe collapses unrelated tables.
- A stop path awaits a long backoff; the cancel event must be the thing retry sleeps on.
