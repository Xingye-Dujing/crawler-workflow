---
name: ai-workspace-dev
description: Extend the 采析绘 AI workspace end to end — add a provider transport, a read-only tool, a built-in or user skill, an agent artifact, an SSE event, or a frontend companion — and keep the one catalog, capability manifest, per-account store, i18n and OMM-ZEN contracts green. Use when implementing or reviewing the AI subsystem.
---

# AI workspace development

The workspace is a provider-neutral agent. The same canonical events feed DeepSeek, OpenCode Go,
OpenRouter and Ollama; the page never branches on a provider.

## Contract map

```text
ChatRequest (dict)
  system, messages[], tools[], thinking, web_search, safety, title,
  context_text, max_tokens, timeout, cancel_event, session_id, user_id, host
        │  Provider.stream(request)
        ▼
canonical events
  meta / thinking_delta / text_delta / citation / server_tool / tool_call /
  usage / title / refusal / done
        │  AgentService._round
        ▼
tool calls + control tools
  ask_user_question → question + paused → /api/ai/answer
  update_plan       → plan event
  present_artifact  → artifact event
  local read tools  → tool_start / tool_result
```

## Add a provider

1. Create `backend/ai/providers/<id>.py`:
   - a `ProviderSpec(id, label_key, notes_key, protocol, base_url, models, requires_key,
     local_only, capabilities, models_url)`;
   - a `Provider` subclass implementing `stream(request)` and, if different, `list_models`.
2. Register it in `backend/ai/providers/registry.py` (`PROVIDERS` and `ORDER`).
3. Capabilities are a promise. If the transport cannot carry a field, do not declare it; the agent
   refuses a requested unsupported capability by name (`ai.capabilityRefused`).
4. Add both-language `ai.provider.<id>` and `ai.providerNote.<id>` keys.
5. Add a unit test for the capability matrix and a serializer/stream test.
6. `analyzers/llm_client.py` already reads the catalog; a provider that should work row-by-row must
   support the one-prompt `chat_once` shape.

## Add a read-only tool

```python
ToolSpec(
    'dataset_profile',
    'Read a dataset schema; never returns the whole table.',
    {'type': 'object', 'properties': {'dataset_id': {'type': 'string'}}},
    permission='read:dataset',
    handler=tool_dataset_profile,
)
```

- The handler takes `(args, ctx)` and returns JSON-safe data.
- Bound every result (rows, bytes, hits) and set `truncated` where it matters.
- A missing id/column is `AIError('ai.toolRefused', tool=..., reason=...)`, not an empty table.
- A write is never a tool. Produce a `present_artifact` proposal and let the user apply it.
- Add the tool to a skill's `tools` allowlist and a test.

## Add a skill

```python
'project': SkillSpec(
    id='project',
    name_key='ai.skill.project.name',
    description_key='ai.skill.project.desc',
    prompt='...',
    context=('project', 'docs'),
    tools=('project_facts', 'capabilities', 'docs_search'),
    suggested=('...',),
)
```

- `context` sources must be in `CONTEXT_SOURCES`; `tools` must exist; control tools are never named.
- `requires` is a capability set; the UI shows the skill unavailable if the provider lacks one.
- Add both-language name/description keys. The studio shows built-ins read-only and lets the user
  fork them into a user skill.
- A user skill is data in `ai.db`; it may not contain code or write actions.

## Add a plugin kind

- Manifest: `id`, `name`, `version`, `api` (1), `kind`, `permissions`, contributions.
- Validate before install; refuse an unknown permission, a version mismatch, a duplicate id or an
  entry that escapes the plugin directory.
- Declarative kinds are data; code plugins are local/admin only and cloud refuses them by name.
- A plugin may not override a built-in contribution id.
- Disabling/removing unregisters its owner and removes its declarative skills.

## Add a frontend piece

- Everything is a flat script; no bundler. A new file must be listed in `index.html` and in
  `tests/frontend/splits.json` as a companion, or a harness boots half the workspace.
- Use `AIRender.escape` before any model text enters HTML. The safe Markdown renderer escapes first,
  allows only http/https links, and never executes raw HTML.
- Use host components/classes and OMM-ZEN tokens; no filled black/blue, no arbitrary plugin CSS.
- The composer toggles are driven by the server capability manifest, not a local guess.
- `ask_user_question` is answered with `AIWorkspace._answerOption`/`_answerCustom`/`_maybeAnswer`; do not turn a
  pending question into a new user message.
- Add a harness/unit test for any result-affecting JS change.

## Tests and gates

```bash
.venv/Scripts/python.exe -m pytest -q tests/unit/ai tests/api/test_ai_workflow.py
.venv/Scripts/python.exe -m pytest -q tests/unit/frontend/test_frontend_ai_js.py
.venv/Scripts/ruff.exe check backend/ tests/
.venv/Scripts/ruff.exe format --check backend/ tests/
```

Then the full fast tier, device UI tier when the workspace/CSS changed, both pylint tiers and
`/smoke-verify`. A green run that skipped node/browser/Ollama is not evidence; set
`CRAWLER_REQUIRE_NODE=1` / `CRAWLER_REQUIRE_BROWSER=1` when those are the subject.

## Failure rules

- A provider error is an `AIError` with a kind; the API turns it into JSON before the stream or an
  `error` SSE event after it. Do not print the same failure again in a logger.
- A capability/unknown skill/unknown tool is refused by name; no silent fallback, no second provider.
- A turn interrupted by Stop keeps the partial transcript and settles `stopped`/`partial`, not done.
- A key is never persisted or printed. The answer request carries it again.
