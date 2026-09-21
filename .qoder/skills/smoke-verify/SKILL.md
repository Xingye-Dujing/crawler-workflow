---
name: smoke-verify
description: Verify backend changes in this repo — pytest fast suite, ruff lint, boot the Flask server headlessly, smoke-test key GET endpoints, then shut it down cleanly. Use after changing backend code.
---

Verify recent changes to the crawler_workflow backend. Run steps in order; stop and report on the first failure.

## 1. Automated tests

```bash
.venv/Scripts/python.exe -m pytest -q
```

All tests must pass (~860 cases, under a minute). If the change touched crawling, LLM transports,
or checkpoint/resume, also run the device tier:
`.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"` (real Chrome + real Ollama).

## 2. Lint

```bash
.venv/Scripts/ruff.exe check backend/ tests/
```

If findings exist, fix them (never add blanket ignores) and re-run. Optionally run
`.venv/Scripts/pylint.exe <module>` on each changed module as a deeper check — report findings but only fix
real problems, not style nits that conflict with ruff.

## 3. Boot the server headlessly

Do NOT run `python app.py` directly — its `__main__` opens a browser and enables the
reloader (two processes, messy to kill). Instead, in the background with cwd `backend/`:

```bash
cd backend && PORT=5057 ../.venv/Scripts/python.exe -c "from app import app; app.run(host='127.0.0.1', port=5057, use_reloader=False)"
```

- Port 5057 avoids clashing with a user-run instance on 5000. Never kill a process on 5000.
- The import itself is the first real test: any syntax error, bad import, or missing
  dependency crashes the boot. Check the background output for the "Running on" line
  (or traceback) before proceeding.
- Ollama/Chrome need not be running for these checks; do not exercise crawl or LLM
  endpoints — only GETs listed below.

## 4. Smoke-test endpoints

```bash
for ep in / /api/config /api/settings /api/workflow/list /api/data/datasets /api/runs/list /api/stats/summary; do
  code=$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:5057$ep")
  echo "$code $ep"
done
```

Expect `200` for all (and `200` for `/`, the HTML page). Anything else: read the server log
output and the failing handler, fix, re-run from step 1.

## 5. Shut down

Kill only the background server you started (match on port 5057, e.g.
`taskkill //F //PID <pid>` after `netstat -ano | grep :5057`, or stop the background task).
Confirm the port is free.

## 6. Report

Summarize: test-suite result, lint result, boot result, per-endpoint status codes, anything not covered
(e.g. changes to logged-in crawler paths need manual browser testing by the user).
