---
name: smoke-verify
description: Verify a change in this repo end to end — fast pytest tier (and the device tier when crawling/UI/LLM changed), ruff lint + format, both pylint tiers, boot the Flask server headlessly on an isolated data root, smoke-test key GET endpoints, then shut it down cleanly. Use after any backend, crawler, frontend-JS or analysis change.
---

Verify a change in this repo. Run the steps in order and stop at the first failure — a half-run
tier is not evidence. Work from the **checkout root** (the venv and `pytest.ini` live there; only
the app itself wants cwd `backend/`).

Measured on this checkout (2026-11-11, Windows, Python 3.11):

| tier | command | result | wall time |
|---|---|---|---|
| fast | `python -m pytest -q` | 8,939 passed / 5 skipped / 356 deselected | ~9 min |
| device (Chrome half) | `python -m pytest -q -m integration` | 182 passed / 5 skipped | ~3.5 min |
| lint | ruff + 2× pylint | 10.00/10 | ~2 min |

Do **not** quote these numbers as a guarantee: the point is the shape and the order of magnitude.
A run that finishes in one minute, or reports ~5k cases, is not this suite.

## 0. Preflight

- `.venv/` is mandatory: Windows `.venv/Scripts/python.exe`, POSIX `.venv/bin/python`. Never the
  system Python.
- `git status --porcelain` before you start. `data/` and `logs/` must not gain a file during any
  step; the fast suite has an import-time isolation guard and fails if they do.
- Port **5057** must be free. Never kill the process on **5000** — that is the user's server.
- Clear account/deployment variables for this boot (`CRAWLER_ADMIN_PASSWORD`, `SECRET_KEY`,
  `CRAWLER_CLOUD`, `HOST`): a stray one turns the gate on and every smoke GET answers 302/401
  instead of 200.

## 1. Fast tier (always)

```bash
.venv/Scripts/python.exe -m pytest -q -rs
```

`-rs` is not decoration: a tier whose cases all skip still prints "passed". The fast tier excludes
the device/live markers through `pytest.ini`; `-m` filters are for the tiers below.

- Every failure is the change's bug until proven otherwise: fix the code, not the test (unless the
  test pinned an old bug, in which case update it in the same change).
- Any warning in the summary is a test that noticed something and passed anyway — fix it, never
  add `filterwarnings`.
- If you edit anything afterwards, the closure rule restarts the loop: re-run the full tier.

## 2. Device tier (when crawling, LLM transports, checkpoint/resume or UI changed)

```bash
export CRAWLER_REQUIRE_BROWSER=1 CRAWLER_REQUIRE_NODE=1
export CIXI_DRIVER_PATH="/path/to/chromedriver"      # matching this machine's Chrome
.venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama" -rs
```

- Use this machine's Chrome and its matching chromedriver. **Without `CIXI_DRIVER_PATH` Selenium
  Manager tries to download one** — measured, that run hung past 40 minutes on a restricted
  network. Check the driver version against `chrome --version` first.
- `CRAWLER_REQUIRE_BROWSER=1`/`CRAWLER_REQUIRE_NODE=1` turn "browser/node unavailable" from a skip
  into a failure; a green tier that skipped every case is the exact false green this repo bans.
- Ollama cases skip cleanly when no daemon is listening; add `CRAWLER_REQUIRE_OLLAMA=1` only when
  the change must prove the daemon path.
- CatBus adapter cases skip by name when the separate checkout is absent; that skip is honest.
- **Never run `live_quick` / `live_site` here.** They spend the user's accounts and need an
  explicit network direction (`live_cn` vs `live_os`); ask first.
- If the workspace is restricted, `ruff format`'s temp-file rename can fail with `os error 5` —
  format by hand and let CI be the gate.

## 3. Lint (always; three standards, all clean)

```bash
.venv/Scripts/ruff.exe check backend/ tests/
.venv/Scripts/ruff.exe format --check backend/ tests/
.venv/Scripts/python.exe tools/ci_lint_tiers.py product
.venv/Scripts/python.exe tools/ci_lint_tiers.py tests
```

- Both pylint tiers matter; `tools/ci_lint_tiers.py` enumerates the files CI lints and fails on an
  empty list. (The third tier, `.pylintrc.probes`, is local-only: `backend/test_*.py` are
  gitignored probe scripts.)
- Never silence a finding with `# noqa` / `# pylint: disable` / a config exemption. Fix the cause.
- If only docs/anchors changed, `ruff check` on touched `.py` plus
  `tests/unit/gates/test_doc_paths.py` is enough; CI still runs the full set on push.

## 4. Boot the server headlessly

Do **not** run `python app.py` — its `__main__` opens a browser and enables the reloader (two
processes, messy to kill). Boot the app object instead, with its own data root.

The one-liner is shell-specific and, in PowerShell, `Start-Process -ArgumentList '-c', ...` mangles
the quotes. Write a four-line `scratchpad/smoke_boot.py` (gitignored) and run that:

```python
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..', 'backend')))
from app import app

app.run(host='127.0.0.1', port=5057, use_reloader=False)
```

POSIX:

```bash
mkdir -p scratchpad/smoke_state
PORT=5057 CRAWLER_DATA_ROOT="$(cd scratchpad/smoke_state && pwd)" \
  .venv/bin/python scratchpad/smoke_boot.py &
echo $! > scratchpad/smoke.pid
```

PowerShell:

```powershell
New-Item -ItemType Directory -Force -Path scratchpad\smoke_state | Out-Null
$env:PORT = '5057'
$env:CRAWLER_DATA_ROOT = (Resolve-Path scratchpad\smoke_state).Path
$p = Start-Process -FilePath (Resolve-Path .venv\Scripts\python.exe).Path `
  -ArgumentList @((Resolve-Path scratchpad\smoke_boot.py).Path) -PassThru `
  -RedirectStandardOutput scratchpad\smoke_out.log -RedirectStandardError scratchpad\smoke_err.log
$p.Id | Set-Content scratchpad\smoke.pid
```

- `CRAWLER_DATA_ROOT` must be an **absolute** path. It gives this boot its own `data/` and `logs/`
  — without it the second `RunStore` settles the user's live run as interrupted at startup.
- Wait for the `Running on http://127.0.0.1:5057` line (or a traceback) before requesting anything.
  The import is the first real test: a bad import, syntax error or missing dependency dies here.
- Chrome and Ollama need not be running; do not call crawl or LLM endpoints from this smoke.

## 5. Smoke-test GET endpoints

POSIX:

```bash
for ep in / /api/config /api/settings /api/workflow/list /api/data/datasets \
          /api/runs/list /api/stats/summary /api/capabilities /api/cookies/flow; do
  printf '%s %s\n' "$(curl -s -o /dev/null -w '%{http_code}' "http://127.0.0.1:5057$ep")" "$ep"
done
```

PowerShell (`curl.exe` ships with Windows 10+; `Invoke-WebRequest` throws on non-2xx):

```powershell
foreach ($ep in @('/','/api/config','/api/settings','/api/workflow/list','/api/data/datasets',
                  '/api/runs/list','/api/stats/summary','/api/capabilities','/api/cookies/flow')) {
  $code = (curl.exe -s -o NUL -w '%{http_code}' "http://127.0.0.1:5057$ep")
  "$code $ep"
}
```

Expect `200` for every line (including `/`, the HTML page). Anything else: read
`scratchpad/smoke_err.log` and the failing handler, fix, and restart the loop at step 1.

## 6. Shut down (only what you started)

POSIX: `kill "$(cat scratchpad/smoke.pid)"`. PowerShell:
`Stop-Process -Id (Get-Content scratchpad\smoke.pid) -Force`.

Then prove the port is free (`ss -ltn | grep 5057` / `Get-NetTCPConnection -LocalPort 5057`) and
remove `scratchpad/smoke_boot.py`, `smoke_out.log`, `smoke_err.log`, `smoke.pid` and
`scratchpad/smoke_state`. Never kill by port alone and never touch 5000.

## 7. Report

State, plainly:

- fast tier: passed/failed, count, skips and their reasons;
- device tier (if run): what ran, and which skips are environmental (CatBus checkout, Ollama);
- lint: ruff check, format, both pylint scores;
- boot: import ok, per-endpoint status codes;
- what this does **not** prove: a real cloud-server boot, real Chrome against live sites, Ollama
  answers, the packaged desktop GUI, or any logged-in crawl path. Those are the user's call (and
  `live_*` spends their accounts), never something this smoke may claim.
