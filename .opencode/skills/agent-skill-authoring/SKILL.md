---
name: agent-skill-authoring
description: Write a 采析绘 AI-workspace skill (one capability per skill) with metadata, when-to-use, step-by-step tool calls, examples, template JSON, failure modes and evals. Use when adding a node/operator/chart/platform skill, or when a small local model misselects or misuses existing skills.
---

# Agent skill authoring

Read `AGENTS.md` and `docs/architecture/ADR-002-capability-manifest.md`. This skill is the content
contract for `backend/ai_knowledge/` (and the repo's `.opencode/skills`); it is not the app's runtime
prompt.

## One capability, one skill

Do not write a 500-line "text processing" skill. Split by capability:

```text
text.tokenize
text.clean
text.sentiment
chart.stack_pct
platform.zhihu.comment
```

A skill that covers several capabilities is a router, not a skill. The catalog is generated from the
manifest; the body is authored.

## Seven sections (required)

1. **When to use** — the user's goal, the data shape, the trigger words. Include `when_not_to_use`
   and the nearest confusable skill.
2. **Prerequisites** — dataset/table, columns, session/account, model, permissions.
3. **Steps** — an ordered TODO; each step names ONE tool and its arguments. No "figure it out".
4. **Examples** — at least one real input -> tool call -> expected result.
5. **Template JSON** — a node/workflow/artifact template that validates.
6. **Failure modes** — the named refusals (missing column, login wall, empty group, unsupported chart)
   and the smallest next step.
7. **Acceptance** — how the user/AI knows it worked (validate green, run id, row count, file exists).

## Progressive disclosure

- Level 1: metadata (~100 tokens): id, title, L1/L2, one-sentence description, when_to_use.
- Level 2: the SKILL.md body (<500 lines / ~5k tokens); load only when selected.
- Level 3: `examples/`, `reference.md`, scripts; load by name only when the body points there.
- The system prompt gets the L1 catalog + `skill_search`/`skill_load` tools, not every body.
- `@skill` forces a load; the runtime still validates the skill's requirements.

## Tool descriptions

A tool description is part of the API. It must say:

- what it does, in one sentence
- when to use it / when not to
- the required arguments and their meaning
- the result shape and its bounds
- the named refusals

Bad: "Read data." Good: "Read up to N rows from a saved dataset. Use dataset_peek first; use
dataset_query for exact counts. Refuses an unknown column by name."

## Recipes and guards

A step is not "done" because the model says so. The runtime checks evidence:

```json
{"id":"validate","tool":"workflow_validate","requires":["connect"],
 "check":"no_errors","produces":"validation_id"}
```

- Tool masking: only the current step's tool + read-only evidence tools are offered.
- `requires` is enforced server-side; skipping is a named refusal with `next_step`.
- A user skip is recorded and shown in the final report.

## Small models

- One step at a time; one question at a time (2-5 options).
- Prefer a typed tool over free-form JSON; provide a template and a repair path.
- Keep the catalog small at level 1; retrieve level 2 by category/query.
- Eval the skill: selection accuracy, tool choice, argument validity, completion rate. 20-30 tasks
  with qwen3.5:4b/9b is enough to catch a regression.

## Anti-patterns

- A skill that repeats the manifest's params table by hand (it will go stale).
- A skill with no negative trigger; it will be selected for the wrong task.
- A step that says "use the appropriate tool"; name it.
- A template JSON that has never been validated.
- A skill that requires Python when a node/operator exists (capability-first policy).

## Acceptance

- The catalog lists it with the right L1/L2 and when_to_use.
- `skill_load` renders fresh params from the manifest, not a copied table.
- The recipe cannot skip a step; the final checklist shows evidence.
- The eval set passes on the target small model, and the normal-mode behavior does not regress.
