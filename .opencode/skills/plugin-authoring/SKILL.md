---
name: plugin-authoring
description: Write or review a 采析绘 AI plugin manifest — a declarative skill pack, provider pack or HTTP tool pack, or a local code plugin — with the correct id, version, api, kind, permissions and contributions. Use when adding an extension or auditing an install.
---

# Plugin authoring

`backend/extensions/manifest.py` validates every install; `backend/ai/plugins.py` registers the
contributions. A manifest is data unless `kind` is `code`.

## Manifest

```json
{
  "id": "acme.research-pack",
  "name": "Acme research pack",
  "version": "1.0.0",
  "api": 1,
  "kind": "skill-pack",
  "description": "Two project research skills.",
  "permissions": ["read:docs", "read:dataset"],
  "skills": [
    {
      "id": "acme.research.data",
      "name_key": "plugin.acme.research.data.name",
      "description_key": "plugin.acme.research.data.desc",
      "prompt": "Answer only from the supplied context; cite the source.",
      "context": ["project", "docs", "dataset"],
      "tools": ["project_facts", "docs_search", "dataset_profile"],
      "suggested": ["Summarize the project docs."],
      "ask_policy": "auto"
    }
  ]
}
```

Rules:

- `id` matches `^[a-z][a-z0-9._-]{2,63}$`; `version` is `x.y.z`; `api` is `1`.
- `kind` is `skill-pack`, `provider-pack`, `tool-pack` or `code`.
- `permissions` are from `read:project`, `read:canvas`, `read:dataset`, `read:run`, `read:docs`,
  `read:code`, `net:http`, `provider:custom`, `code:execute`.
- A skill may only reference a registered read-only tool; control tools are always available and
  cannot be selected. A skill may not contain code or write actions.
- A provider pack must request `provider:custom` and declare `base_url`, at least one model and
  capabilities. Capabilities are promises; an unsupported one is refused by name.
- A tool pack must request `net:http` and name `allowed_hosts`. The host check blocks any other
  host and a non-http(s) scheme; responses are truncated.
- A code plugin needs `kind: "code"`, `permissions: ["code:execute"]`, and `entry: "plugin.py"`
  inside the account's `ai_plugins/` directory. `plugin.py` exposes `register(registry)` and may
  call `add_tool`, `add_provider`, `add_skill`. It is local/admin only; cloud mode refuses it.

## Install and lifecycle

1. The UI posts the manifest to `/api/ai/plugins/install`.
2. The server validates it, checks for a duplicate id, applies contributions, and records the
   permissions the user approved.
3. `POST /api/ai/plugins/<id>/enable` toggles it. Disabling unregisters its owner; a disabled plugin
   is not listed in the skill picker and its declarative skills are removed.
4. `DELETE /api/ai/plugins/<id>` removes it. Conversations keep their transcript; a future turn that
   names a removed skill refuses by name.

## Audit checklist

- Manifest id/version/api/kind/permissions are declared and valid.
- Every tool is registered; no control or code tool in a user skill.
- Provider/tool packs request the permission their kind requires.
- No entry path escapes `ai_plugins_dir`; no zip-slip; no arbitrary HTML/CSS (the host renders UI).
- A local code plugin is not installed on a cloud host; the refusal is by name.
- Add a test under `tests/api/` for the install path and a unit test for any new validation branch.
