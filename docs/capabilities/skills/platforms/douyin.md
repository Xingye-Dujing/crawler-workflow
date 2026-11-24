# platform.douyin

抖音：某个创作者的主页视频、热榜、视频评论（含楼中楼）。

## When to use

短视频平台的热点与评论研究。

Do not use it when:

- 无头的投递浏览器经常被验证码中间页挡住；用你自己的浏览器配置更可靠。

## Prerequisites

- A network this platform answers from: 国内.
- A saved login for the modes that need one: author, hot, comments.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `douyin` and `collect` one of: `author`, `hot`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "douyin",
    "collect": "author",
    "author": "@handle"
  }
}
```

## Template JSON

```json
{
  "type": "source",
  "params": {
    "platform": "douyin",
    "collect": "author",
    "author": "@handle"
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
Documentation: `docs/capabilities/platforms/douyin.md`
Skill page: `docs/capabilities/skills/platforms/douyin.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
