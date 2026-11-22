---
name: strangler-migration
description: Move a 采析绘 subsystem from the legacy path to the new kernel without a big-bang rewrite. Use when a seam has two implementations, when a feature flag or parity matrix is needed, or when deciding whether to hotfix or wait for the rewrite.
---

# Strangler migration

Read `AGENTS.md` and `docs/architecture/ADR-001-kernel-replacement.md` first. The ADR owns the
"kernel replacement, not big-bang" decision; this skill is the execution discipline.

## The rule

Keep the product runnable at every commit. A migration is a sequence of reversible slices, each with
a parity proof. The old path is deleted only when the new path is green and nobody imports it.

## Hotfix vs wait

Use this test before touching legacy code:

| condition | action |
|---|---|
| data loss, security, wrong credentials, a crash the user cannot avoid | hotfix now, with a regression test |
| a visual/UX defect in a component that will be replaced | fix once in the new UI, unless it blocks daily use |
| a missing capability that the new kernel will generate | implement in the kernel, not twice |
| a bug that only exists because of the old duplication | let the migration delete it; add a parity test |

## A migration slice

1. **Name the seam** and the single new contract (manifest, tool, event, endpoint).
2. **Adapter first**: the new path reads the old registries, so both see the same truth.
3. **Parity matrix**: for every old behavior, one new test. "Looks the same" is not a proof.
4. **Flag**: `runtime/flags.py` with owner and removal date; default off in production, on in tests.
5. **Shadow read** where possible: compute the new answer, compare, still serve the old one.
6. **Cut over** one consumer at a time; keep the old path until no import remains.
7. **Delete** the old path, its tests that only asserted its implementation, and the flag.
8. **Doctor**: the completeness gate now owns the contract; no second list.

## Parity matrix shape

```text
behavior              old proof                     new proof
route /api/x          api test                      same test against host adapter
event shape           frontend harness              wire protocol test + harness
node defaults         frontend fallback test        manifest -> generated fallback test
question answer       message_id + question_id      question_id only, reload case
```

## Rollback

- A flag is a circuit breaker, not a permanent feature. It must have a removal date.
- A data migration has a forward fix and a compensating move; never a "delete and hope".
- A cutover that cannot be rolled back needs a backup/export step first.

## Anti-patterns

- "Rewrite the module in one PR" with no parity tests.
- A flag with no owner or removal date (the gate should fail it).
- Two sources of truth kept "for now" with no deletion checklist.
- Deleting the old tests before the old code is gone; you lose the specification.

## Acceptance

- Each slice is one commit (or a small series) and the full fast tier is green.
- The parity matrix has no empty cell.
- The flag is gone at the end; `grep` for the old import returns zero.
