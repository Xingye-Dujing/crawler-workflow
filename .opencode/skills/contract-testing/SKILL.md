---
name: contract-testing
description: Choose and write the right proof in 采析绘: generated capability matrices, consumer contracts, property-based data tests, browser-measured UI assertions, and a test-value inventory. Use before claiming a change is done, or when the suite is slow, flaky or green without proving anything.
---

# Contract testing

Read `AGENTS.md` ("How tests are written here") and `docs/architecture/ADR-002-capability-manifest.md`.
This skill decides what to test and what to delete; it does not replace the tier rules.

## The rule

Every test must name the defect it prevents. If removing it would not let a real regression through,
it is not a test; it is decoration.

## The four kinds

| kind | proves | example |
|---|---|---|
| generated matrix | every registered capability has the same contract | each node: manifest -> executor -> UI -> validation -> skill |
| consumer contract | the boundary the consumer actually reads | kernel -> UI schema, kernel -> AI tool schema, kernel -> MCP |
| property test | a data transform holds for all inputs in a domain | dedupe never grows rows; bin_time never drops a row silently |
| browser measurement | pixels/positions/DOM lifecycle, not strings | closed panel is gone, stream does not jump, one transcript per conversation |

## Generated matrix

Do not hand-write one test per type. Iterate the registry:

```python
@pytest.mark.parametrize('manifest', registry.all(), ids=lambda m: m.id)
def test_capability_contract(manifest):
    assert manifest.sections_complete()
    assert executor_registered(manifest)
    assert examples_validate(manifest)
    assert skill_complete(manifest)
```

A new type with no test is green today; the generated matrix makes that impossible.

## Property tests

Use Hypothesis for pure data transforms (dedupe, merge, filtering, binning, column selection).
Keep the domain small and deterministic; never hit the network or a browser.

## Browser-measured UI

- Assert by container id, never `<body>`; report the viewport and a per-container floor.
- A closed panel must be GONE, not merely moved: compare pixels with the same box at `display:none`.
- State the measurement: "one `.ai-message`", "scrollTop unchanged after 5 deltas", "width grew by 40px".
- A node captured before an await is gone after it; re-look it up.

## Test value inventory

Before deleting anything, classify each file/case:

- prevents a named regression (keep)
- restates an implementation detail (delete or rewrite)
- duplicates a generated contract (delete)
- permanently skipped (delete or turn into a named refusal test)
- live/device only (keep behind its marker)

The fast tier target is <= 8 minutes, but coverage is the constraint, not the count.

## Anti-patterns

- `assert 'foo' in html` for a user-visible behavior that could be measured.
- One giant integration test that fails at the first step and hides the rest.
- A mock that returns a shape the real provider never sends.
- A test that patches the product gate (`sys.platform`, cloud) and calls it proof.
- Deleting a gate because it is slow; gates are the reason a rewrite is safe.

## Acceptance

- `python -m pytest -q` proves every user-facing fix in this change.
- The completeness gate fails when a capability is half-registered.
- A browser test fails when the scroll anchor, transcript count or close measurement regresses.
