---
name: cai-xihui-context
description: Navigate the 采析绘 (crawler_workflow) checkout and the new AI workspace: where the provider catalog, context builder, agent loop, store, skills, plugin host and OMM-ZEN frontend live; which invariants apply before changing them. Use when working on the AI workspace, a provider, a skill, a plugin, or any backend/frontend change that touches it.
---

# 采析绘 project context

Read `AGENTS.md` first: it is the rule book, not this file. This skill is the map for the AI
subsystem. The why behind a rule is in `docs/agent_practices.md`; the shape of the whole app is in
`docs/ARCHITECTURE.md`.

## The app in one paragraph

Flask + zero-build vanilla JS. A canvas of nodes collects social-media data through Selenium (and a
second CatBus backend), stores datasets/runs per account in `data/`, cleans and analyses text with
local Ollama or remote APIs, and draws charts/reports. One Flask process, started from `backend/`
(`python app.py`), with `backend/` as the import root.

## Where the AI workspace lives

| area | file |
|---|---|
| provider catalog / capabilities | `backend/ai/providers/registry.py`, one module per provider |
| provider transports | `backend/ai/providers/{deepseek,opencode_go,openrouter,ollama,openai_compat}.py` |
| canonical shapes | `backend/ai/types.py`, `backend/ai/errors.py` |
| agent loop / questions / artifacts | `backend/ai/agent.py` |
| context budget and redaction | `backend/ai/context.py` |
| project facts and docs search | `backend/ai/context.py` (generated, not a second table) |
| read-only tools | `backend/ai/tools.py` |
| built-in + user skills | `backend/ai/skills.py`, `backend/ai/store.py` |
| plugin host | `backend/extensions/`, `backend/ai/plugins.py` |
| HTTP / SSE | `backend/api/ai.py` |
| frontend shell | `backend/static/js/ai-workspace.js` + `backend/static/js/ai/*.js` |
| OMM-ZEN styles | `backend/static/css/ai.css` |
| design note | `docs/ai_workspace.md` |

The browser owns the API key (`localStorage`), not the server. The server owns the transcript
(`data/users/<id>/ai.db`; the local owner uses `data/ai.db`), resolved through
`runtime.paths.active()` at call time.

## Invariants that will bite

- **One provider catalog.** `analyzers/llm_client.py`, the AI settings panel and the workspace all ask
  `backend/ai/providers/registry.py`. Never hardcode an endpoint or a model list in JS.
- **Capabilities are server data.** A provider that lacks `web_search`, `files`, `thinking`, etc.
  must be refused by name, never silently sent a field it ignores. The UI hides a control only from
  the capability manifest.
- **Keys never reach disk or logs.** They are request-scoped. `ai.db` must not contain `api_key`.
- **The transcript is per account.** Do not cache a path in a module constant; ask `paths.active()`.
- **A turn is several assistant rows.** Tool calls need an immediate tool result; the page groups by
  `turn_id`. Do not merge rounds into one assistant message.
- **`ask_user_question` pauses the turn.** The answer is a tool result, not a new user message. A new
  user message abandons the pending question with a cancellation result.
- **Read-only tools only.** A write is an artifact/proposal; the user clicks Apply/Run through the
  existing route. No tool may mutate canvas, runs or datasets.
- **Context is budgeted and redacted.** A cut is reported in `context_meta`/the inspector; never
  silently trim and claim the project was read whole.
- **OMM-ZEN.** Paper/ink tokens, hairline borders, one radius, inset underline selection. No filled
  black or blue surface. Motion is transform/opacity and respects `prefers-reduced-motion`.
- **Plugins are data first.** Declarative skill/provider/tool packs are safe; local code plugins are
  local/admin only and cloud mode refuses them by name.

## Commands

```bash
# from the checkout root, always the venv
.venv/Scripts/python.exe -m pytest -q
.venv/Scripts/ruff.exe check backend/ tests/
.venv/Scripts/ruff.exe format --check backend/ tests/
.venv/Scripts/python.exe tools/ci_lint_tiers.py product
.venv/Scripts/python.exe tools/ci_lint_tiers.py tests
```

Device/UI tier when the workspace, a panel or CSS changed:

```bash
CRAWLER_REQUIRE_BROWSER=1 CRAWLER_REQUIRE_NODE=1 .venv/Scripts/python.exe -m pytest -q -m "integration or live_ollama"
```

Never run `live_*` unattended. Never kill the process on port 5000; use `CRAWLER_DATA_ROOT` for a
second server.

## Adding something

1. **Provider:** add `backend/ai/providers/<id>.py` with a `ProviderSpec` and a `Provider`, register it
   in `registry.py`, add tests for capabilities/refusals, and add its label/note keys to both
   catalogues.
2. **Tool:** add a `ToolSpec` in `backend/ai/tools.py` with a JSON schema, a read-only handler, a
   permission and a bounded result; add a test.
3. **Skill:** add a `SkillSpec` in `backend/ai/skills.py` (prompt, context sources, tools, requires,
   suggested) and both-language name/description keys.
4. **Plugin kind:** add a manifest branch in `backend/ai/plugins.py`, validate permissions, and never
   let a plugin override a built-in id.
5. **UI:** call `AIWorkspace.ask({skill, prompt, context})`; do not add a second chat UI.
