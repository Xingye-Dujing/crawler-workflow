# AGENTS.md

This file provides guidance to the AI agent when working with code in this repository.

## Project

采析绘 (crawler_workflow): Flask backend + vanilla-JS frontend that crawls Chinese social media
(Zhihu/Weibo/Xiaohongshu/WeChat) via Selenium, cleans/analyzes text with Ollama LLMs and
scikit-learn, and renders a drag-and-drop workflow canvas. Single project, no build step.

## Commands

**The project venv `.venv/` (Python 3.11) is mandatory — never use system Python.** Every run,
install, lint and test goes through it: in Git Bash run `source .venv/Scripts/activate`, or call
`.venv/Scripts/python.exe` / `ruff.exe` / `pylint.exe` / `pip.exe` directly.
- Install new third-party libraries: `.venv/Scripts/pip.exe install <pkg>`, and add it to
  `requirements.txt` **in the same change** — no exceptions.
- Install/restore deps: `pip install -r requirements.txt`
- Run the app: `cd backend && python app.py` → http://localhost:5000 (port via `PORT` env).
  **Must run from `backend/`** — it is the `sys.path` root, so imports are top-level
  (`from config import Config`, `from analyzers import ...`). Never add a `backend.` prefix to imports.
- Lint: `ruff check backend/` then `pylint <module>` (both configured; ruff is the fast gate, pylint the deeper check).
- Format: `ruff format backend/`
- Standalone crawler scripts: `python backend/test_zhihu.py <keyword> --count N --no-headless`
  (test_*.py are manual run scripts, NOT pytest; there is no test suite).

## Style (differs from defaults)

- Comments and docstrings are in **English** even though README/commits are Chinese. Explain "why".
- Section dividers use `# ─── Name ───`.
- Ruff: line-length 120, **single quotes**, indent 4. Lint findings must be **genuinely fixed**:
  never `# noqa`, never `# ruff: noqa`, never a `per-file-ignores`/rule-exemption in `ruff.toml`.
- Modern typing (`str | None`, `list[str]`), target py311.

## Commits

Chinese messages with a type prefix, matching history: `功能更新：`, `问题修复：`, `修改：`.

## Environment & gotchas

- Requires **Ollama** running at `localhost:11434` (model `qwen3.5:9b`, override via `OLLAMA_MODEL`/`OLLAMA_HOST`)
  and **Chrome + chromedriver** for crawling. `DRIVER_PATH` is hardcoded in `backend/config.py`
  but overridable at runtime via `data/settings.json` (POST `/api/settings`).
- Runtime state lives in gitignored `data/` (SQLite: `runs.db`, `datasets.db`, `history.db`) and `logs/`.
  Do not delete `data/` contents casually — saved workflows reference uploaded datasets there.
- Interrupt/resume checkpointing (`backend/services/run_store.py`) is core: per-node outputs and LLM
  answers persist so interrupted runs resume rather than re-crawl/re-pay. Change executor/run-store
  code carefully so resumed runs stay compatible with existing `runs.db` state.
- UI text supports zh/en via `backend/i18n.py` message catalog — add new user-facing strings there.

## Change workflow (MANDATORY — run the full loop on every change)

No automated test suite exists, so correctness comes from this loop. Every step must actually
pass — a change is not done until the whole chain is green end to end.

1. **Edit** — the PostToolUse hook auto-runs `ruff format` + `ruff check --fix` on each touched `.py` file.
2. **Lint every file being committed**: `.venv/Scripts/ruff.exe check <files>` and `format --check <files>`
   must both pass. Fix real warnings/errors in code — suppression (noqa/ignores) is forbidden (see Style).
3. **New packages**: installed into `.venv/` AND listed in `requirements.txt` in the same change,
   then verify `pip install -r requirements.txt` in a clean env would work (import matches a listed package).
4. **Verify with `/smoke-verify` end to end**: lint → boot server (port 5057, headless) → all GET
   endpoints return 200 → clean shutdown. Do not skip the boot step; import errors are the commonest
   regression. If the change touches paths the GET smoke list can't reach (crawler, LLM analysis,
   workflow execution, checkpoint/resume), exercise them for real — Ollama and Chrome are available
   on this machine; use `backend/test_*.py` scripts or run the app in a browser.
5. **Commit** last, with a Chinese type prefix (`功能更新：` / `问题修复：` / `修改：`).
