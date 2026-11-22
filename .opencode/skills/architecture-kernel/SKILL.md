---
name: architecture-kernel
description: Design or review a capability manifest, registry, derived artifact or completeness gate in 采析绘. Use when adding a node/operator/chart/platform/panel, when a new feature needs edits in many files, or when deciding whether something should be generated instead of hand-written.
---

# Architecture kernel

Read `AGENTS.md` and `docs/architecture/ADR-002-capability-manifest.md` first. This skill is the
working recipe for the kernel; the ADR owns the decision.

## When to use

- A new node, analysis operator, chart type, platform mode, panel or AI tool is being added.
- The same fact is edited in two or more files (type list, defaults, validation, UI, docs, tests).
- A generated artifact can go stale (frontend fallback, skill index, OpenAPI, test matrix).
- A review asks "will this be forgotten next time?".

## The rule

One capability = one manifest. Everything else is derived or generated:

```text
manifest (identity, params, ports, run, validate, ui, ai, tests, docs)
   -> registry
   -> HTTP schema / AI tool schema / MCP / CLI / UI form / skill index / test matrix / docs
```

If a new capability needs a hand edit outside its own directory, the manifest is missing a generic
field. Add the field to the shared layer; do not add an `if` for that capability in shared code.

## Manifest checklist

1. Identity: id, kind, version, title key, category (L1/L2), description, when_to_use.
2. Params: JSON Schema subset + UI metadata (widget, options, columnRef, default).
3. Ports: input count, row shape, emitted/read columns.
4. Run: executor module or handler id, lazy loaded.
5. Validate: declarative rules + optional `preflight(node, sample)`; problems carry code/severity/fix.
6. UI: schema form by default; a custom renderer id only when the generic form cannot express it.
7. AI: tool names, usage, steps, examples, template JSON, failure modes.
8. Tests: at least one fixture/golden case.
9. Docs: skill path + manifest hash.

## Completeness gate

The gate enumerates the registry, never a hand-written list:

```python
for manifest in registry.all():
    assert manifest.sections_complete()
    assert executor_registered(manifest)
    assert rules_exist(manifest)
    assert ui_renderer_exists(manifest)
    assert both_languages(manifest)
    assert skill_sections(manifest)
    assert examples_parse(manifest)
    assert generated_artifacts_fresh(manifest)
    assert docs_hash_matches(manifest)
```

`python -m tools.doctor --all` must print the same checks. A capability is not "done" until doctor
is green.

## Anti-patterns

- A new `if type == '<new>'` in `canvas.js`, `runs.js`, `engine/workflow.py` or `reports/paper.py`.
- A second list of types in JS, docs or tests. Generate it or pin it to the registry.
- A skill body that copies the params table by hand. Render it from the manifest.
- A generated file with no `--check` freshness test.
- "We will remember to update it" as a strategy.

## Acceptance

- Add a pilot capability by adding one directory; `git diff --stat` shows no shared file changed.
- Delete the capability; doctor reports the missing skill/tool/test/doc, not a silent green.
- `gen_capabilities.py --check` fails when a generated file is edited by hand.

## References

- `docs/architecture/ADR-002-capability-manifest.md`
- `docs/architecture/problem-ledger.md` (the 14-edit / 20-silent list)
- MCP, VS Code contribution points, Home Assistant integration manifest (manifest-first ecosystems)
