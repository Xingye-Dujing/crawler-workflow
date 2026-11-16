---
name: python-extension
description: Work on 采析绘's Python extension — the saved script library, the row execution contract (CIXI_INPUT/CIXI_OUTPUT), the AI Python tools, the canvas Python node, interpreter detection/download, and token-bounded data reads. Use when adding or debugging a Python script, a Python node run, the Python panel, or the AI's script tooling.
---

# Python extension (AI + canvas)

Read first: `AGENTS.md` → "AI workspace", "Analysis steps and the data contract";
`docs/ai_workspace.md` → "Python extension"; `docs/best_practices.md` → "Token 与成本最佳实践".

## File map

```text
backend/services/python_scripts.py   # library: schema, built-ins, save/fork/delete, find by id/name
backend/services/python_runtime.py   # interpreter detection, workspace files, run_code (JSONL contract)
backend/nodes/executors/python_node.py  # type "python": script_id + args -> rows
backend/nodes/catalog.py / defaults.py  # declaration + seeds (pinned by tests)
backend/nodes/executors/__init__.py    # registration
backend/api/ai.py                      # /api/ai/python/* (status, install, scripts, run, files)
backend/ai/tools.py                    # python_scripts/python_script/save/run/files/read/write
backend/static/js/ai/studio.js         # Python tab: list, edit, run sample
backend/static/js/panels/node-python.js # node settings: pick a script, args, timeout
```

## Contract

- `CIXI_INPUT`: JSON Lines, one upstream row per line.
- `CIXI_OUTPUT`: JSON Lines; the last line wins nothing — every object row is kept.
- `CIXI_ARGS`: JSON object with the node/tool parameters.
- stdout/stderr are captured (20k cap) and printed as one attributed console line.
- Exit code ≠ 0 is a **named** failure with the stderr tail; non-object JSON output names the line.
- `run_code` caps output rows, timeout and workspace file size; it is **not a sandbox**.

## Invariants that bite

- **A script is a library row, never inline code in a node.** The node stores `script_id`/`args`;
  otherwise the workflow carries an unreviewable, unversioned copy.
- **One library for AI and canvas.** Both resolve through `services.python_scripts.find_script`, so
  "run my script" means the same file in both places.
- **Built-ins are forked, never overwritten.** `save_script` refuses a built-in id.
- **Local-only.** Cloud mode refuses by name before reading anything, and `ai_allow_python` gates
  both the tools and the node. Do not add a second switch.
- **Interpreter detection is one function.** `CIXI_PYTHON_BIN`/`AI_PYTHON_BIN` →
  `ai_python_path` → `.venv` → `sys.executable` → PATH; the download plan is shown before anything
  is fetched, and only a frozen Windows build may download.
- **Token economy is part of the contract.** `python_run` returns row count + a small sample +
  stderr, not the whole table; a node run returns every row because the workflow needs them.
- **Desktop snapshot is read-only.** `environment.code_root()` points at `source/` in a frozen
  bundle (collected by `desktop/frozen_modules.source_snapshot_datas`); never claim it is editable.
- **Node identity.** The Python node is a normal table node: `emit_columns` are whatever the output
  rows carry; a downstream chart must still refuse a missing column by name.

## Recipe: add a generic script

1. Read the real columns first (`dataset_peek`), not a guessed schema.
2. Write the script with the JSONL contract and `CIXI_ARGS` parameters.
3. `python_save_script` with a stable id, name, description, inputs/outputs and tags.
4. `python_run` a 5-row sample; report columns, rows and stderr.
5. If it is generally useful, add it to `BUILTIN` in `services/python_scripts.py` too (code + a
   test), and keep the user copy as a fork.

## Recipe: add a Python node capability

1. Extend `python_runtime.run_code` (new env var, output format) and document it in the module
   docstring — the node and the AI both inherit it.
2. Keep the node params in `nodes/defaults.py` and the panel in `panels/node-python.js`.
3. Add a case in `tests/unit/ai/test_python_node.py` and, for a real interpreter, the API case in
   `tests/api/test_ai_monitors.py`.

## Verification

```powershell
.venv\Scripts\python.exe -m pytest -q tests/unit/ai/test_python_node.py tests/api/test_ai_monitors.py
.venv\Scripts\python.exe -m pytest -q tests/unit/analysis/test_node_plugins.py tests/unit/frontend/test_frontend_node_types_js.py
.venv\Scripts\ruff.exe check backend/services/python_runtime.py backend/services/python_scripts.py backend/nodes/executors/python_node.py
```

A real script run belongs to the local/desktop tier; never run a user's script in a cloud test.

## Common failures

- A script prints rows to stdout but writes no `CIXI_OUTPUT` → the node settles DONE with 0 rows;
  make the sample run assert the output row count.
- A node stores code instead of `script_id` → the library and the canvas drift.
- `--` argv parsing inside the script: arguments are JSON in `CIXI_ARGS`, not flags.
- Treating numbers as strings because `_bounded_cell` was applied to non-strings.
- Forgetting `popen_kwargs()` → a console window flashes on Windows for every run.
