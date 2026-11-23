# node.source

数据源 crawls one platform with one mode and emits that mode’s table (a search, a board, an author page, a note/article list, or one link list). The platform matrix decides the fields, the required values and whether the mode needs a saved login.

## When to use

When the corpus is a platform search, a board, an author page or a link list.

Do not use it when:

- A local file corpus belongs on node.upload; comments under known links belong on node.comment.

## Prerequisites

- A platform and a mode this build offers; the matrix answers both.
- A saved login for a mode whose session is required.
- Reachable network for the platform.

## Steps

1. Pick a platform, then an engine (Selenium or CatBus) and a mode; the form shows that cell’s fields.
2. Fill the mode’s required fields (a keyword, a board, a link list or an author link).
3. Pick the login account when the mode needs a session; anonymous modes are not asked.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "zhihu",
    "mode": "posts",
    "keyword": "人工智能",
    "target_count": 100,
    "account": "default"
  }
}
```

## Template JSON

```json
{
  "type": "source",
  "params": {
    "platform": "zhihu",
    "mode": "posts",
    "keyword": "AI",
    "target_count": 100
  }
}
```

## Parameters

This capability takes no declared parameters.

## Failure modes

- No platform: engine.source_no_platform.
- A platform/mode this matrix does not offer: engine.source_unknown_platform / _unknown_mode.
- A missing required field: engine.source_missing; a value off the offered list: engine.source_bad_option.
- A session-required mode whose account holds no login: the preflight keys.

## Acceptance

- The run stores rows with the columns the mode declares.
- A login wall or risk page is named in the console, never settled as an empty table.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/source.md`
Skill page: `docs/capabilities/skills/nodes/source.md`
Contract tests: `tests/unit/capabilities/test_source_manifest.py`
