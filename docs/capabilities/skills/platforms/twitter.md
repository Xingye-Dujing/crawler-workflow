# platform.twitter

X / Twitter：关键词搜索、用户时间线、推文回复（需要登录）。

## When to use

海外舆情、名人/机构账号的发言与回复。

Do not use it when:

- 国内网络通常无法直接访问；评论需要登录会话。

## Prerequisites

- A network this platform answers from: 海外（需要对应的网络出口）.
- A saved login for the modes that need one: posts, author, comments.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `twitter` and `collect` one of: `posts`, `author`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "twitter",
    "collect": "posts",
    "keyword": "关键词"
  }
}
```

## Template JSON

```json
{
  "type": "source",
  "params": {
    "platform": "twitter",
    "collect": "posts",
    "keyword": "关键词"
  }
}
```

## Parameters

This capability takes no declared parameters.

## Failure modes

- A required box left blank: the refusal names the field (engine.source names it once).
- A link that belongs to another platform: the comment walk refuses it by name.
- A login wall or risk page: the crawl names it and the run is not silently empty.

## Acceptance

- The node produced rows, or the refusal named the reason (login wall / risk / captcha).

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/platforms/twitter.md`
Skill page: `docs/capabilities/skills/platforms/twitter.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
