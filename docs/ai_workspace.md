# AI 工作区 / AI workspace

The AI workspace is a right-side agent window, not another settings submenu. It reads the project
through one generated context builder, streams from one provider catalog, and performs only
read-only work; every write is an artifact the user applies.

## Runtime shape

```text
browser (index.html)
  #ai-workspace  ── AIWorkspace (js/ai-workspace.js)
      ├─ ai/stream.js      SSE decoder (POST + fetch)
      ├─ ai/render.js      escaped Markdown, citations, questions, artifacts
      ├─ ai/settings.js    browser-local provider keys and model choice
      ├─ ai/context.js     live canvas draft + manual dataset/run ids
      └─ ai/studio.js      skills, plugins, permissions
              │
              ▼
POST /api/ai/chat ──► AgentService._loop
                         ├─ ContextBuilder (project facts, live data, docs, budget)
                         ├─ SkillRegistry  (built-in + user skills)
                         ├─ ToolRegistry   (read-only tools + ask_user/update_plan/present)
                         └─ ProviderCatalog (DeepSeek / OpenCode Go / OpenRouter / Ollama)
              │
              ▼
        canonical events: meta, thinking, text, citation, server_tool, tool_start,
        tool_result, plan, question, artifact, usage, title, error, done, paused
```

`agent_runs` and `agent_steps` are durable; an assistant row is created as `streaming` before the
first token, so a dead process leaves `interrupted`, not a vanished answer. Each provider round is
its own assistant row, because the Messages API requires `assistant tool_use` → `tool result` →
next assistant; the page groups the rows by `turn_id`.

## Providers

| id | protocol | capabilities |
|---|---|---|
| `deepseek` | Messages API (`/anthropic/v1/messages`) | thinking, web search, read links, safety, titles, latest_reminder, tools, ask_user, vision, continue |
| `opencode_go` | OpenAI Chat Completions | thinking, tools, ask_user, vision; no server web/files/title/safety |
| `openrouter` | OpenAI Chat Completions | thinking, tools, ask_user (model-dependent); no server tools |
| `ollama` | local `/api/chat` | chat only; cloud mode refuses it by name |

`backend/ai/providers/registry.py` is the ONE list. `analyzers/llm_client.py` imports the same catalog
for row-by-row analysis, so a run cannot claim one transport while a second table answers with
another. `runtime.transport._local_transport_refusal` asks the catalog instead of hardcoding
`openrouter`.

The workspace uses Messages API for DeepSeek because it carries structured blocks (thinking, text
with citations, server tool results, client tool calls). Chat Completions is used by the row
analyzers, where a single prompt has no use for blocks. The top-bar AI submenu can now select
DeepSeek or OpenCode Go for those row analyzers too; its model/key fields are the same per-provider
browser-local credentials, not a second provider table.

### Keys

Keys live in browser `localStorage` (`crawler_ai_workspace.keys`). The page posts the active key in
the request body; the server holds it for that call only. It is never written to `ai.db`, never put
in a URL and never logged. The answer endpoint asks for it again because a reloaded assistant row
has no key.

## Skills and context

Built-in skills are code (`backend/ai/skills.py`); user skills are rows in `ai.db` and can be
created, forked, edited, tested, exported and deleted in the studio. A skill declares:

- a prompt;
- context sources (`project`, `canvas`, `dataset`, `run`, `docs`, `code`);
- read-only tools (control tools are always available and cannot be selected);
- required provider capabilities.

`ContextBuilder.build_context` reads the project facts from the existing registries, the live
canvas draft, the dataset profile, the run status/console and (in `full`) docs. Everything is
redacted and measured; a cut is reported in `context_meta` and shown in the inspector. The API key
is never part of context.

`ask_user_question` is a control tool: the server pauses the stream, stores a pending question,
and returns `question` + `paused`. The UI renders options; the answer is posted back and the same
turn resumes with a tool result. The model is instructed to ask when the goal, data scope, cost or
permission is ambiguous.

## Plugins

`backend/extensions/` is the manifest/permission registry; `backend/ai/plugins.py` is the AI host.
Built-ins register through the same typed registry as user plugins.

- **Declarative** (`skill-pack`, `provider-pack`, `tool-pack`): data only. A skill pack may add
  skills; a provider pack adds an OpenAI-compatible endpoint and declares capabilities; a tool pack
  adds a constrained HTTP tool with `allowed_hosts`.
- **Code** (`kind: "code"`): a local `plugin.py` with `register(registry)`. Local/desktop and
  administrator only; cloud mode refuses it by name. It runs in-process with the server's
  privileges; there is no sandbox in this cut.

A manifest is validated before install (`api`, id, version, kind, permissions). The install route is
the user's confirmation; a disabled plugin is removed from the registry, and its declarative skills
are removed with it.

## OMM-ZEN

The workspace uses the app's tokens only: `--paper`, `--text`/`--ink`, `--line`/`--line2`,
`--hover`/`--active-bg`, `--accent`, `--ok`/`--warn`/`--err`, `--radius`, `--font`. Selection is the
same inset ink underline as the custom select; a checked box is a hairline square with an ink tick.
There is no filled black or blue surface.

Motion is short and only transform/opacity: dock slide, message rise, thinking pulse, streaming
caret, agent-trace hairline, question option stagger, artifact hover lift. `prefers-reduced-motion:
reduce` removes all of it, including chart animation. The dock is fixed above floating panels
(`z-index: 7000`), below dialogs.

## Endpoints

| method | path | purpose |
|---|---|---|
| GET | `/api/ai/bootstrap` | providers, skills, conversations, usage, settings, tools |
| GET | `/api/ai/providers` | provider catalog and capability manifest |
| GET | `/api/ai/providers/<id>/models` | live model list (falls back to the declared catalog) |
| POST | `/api/ai/providers/<id>/test` | one tiny streaming round-trip |
| GET/POST | `/api/ai/skills` | list / save user skills |
| GET | `/api/ai/skills/<id>` | full skill (prompt included) |
| POST | `/api/ai/skills/<id>/fork` | fork a built-in skill |
| DELETE | `/api/ai/skills/<id>` | delete a user skill |
| GET/POST | `/api/ai/plugins` | list / install declarative plugin |
| POST | `/api/ai/plugins/<id>/enable` | enable or disable |
| DELETE | `/api/ai/plugins/<id>` | remove |
| GET/POST | `/api/ai/conversations` | list / create |
| GET/PATCH/DELETE | `/api/ai/conversations/<id>` | detail, rename/pin, delete |
| POST | `/api/ai/chat` | SSE turn (or `?stream=0` JSON fallback) |
| POST | `/api/ai/answer` | resume a paused question (SSE or JSON) |
| POST | `/api/ai/stop` | set the turn's cancel event |
| POST | `/api/ai/context` | context preview |
| GET | `/api/ai/usage` | token totals for this account |

## Tests

- `tests/unit/ai/test_ai_core.py` — catalog, serializer, redaction, skills, store sequence.
- `tests/api/test_ai_workflow.py` — scripted provider, SSE events, ask/resume, capability refusal,
  skill studio, plugin install.
- `tests/unit/frontend/test_frontend_ai_js.py` + `tests/frontend/harness_ai.mjs` — real decoder and
  renderer, XSS escaping, question/artifact data actions.
- Existing LLM row tests prove the catalog change did not alter OpenRouter/Ollama behavior.

## Not in this cut

Voice input/output, OCR, the standalone Search/Fetch APIs and the DeepSeek Files API upload path are
still declared capability names but have no transport yet; the workspace hides them from providers
that do not offer them. The attach button reads plain text into the prompt; it is not a Files API
upload. A background agent runner and a code-plugin sandbox are the next architectural steps, not
claims.
