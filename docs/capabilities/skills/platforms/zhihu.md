# platform.zhihu

知乎：关键词搜索（可展开全文）、创作者回答、站内热榜、问题/回答评论（含楼中楼）。

## When to use

要分析知乎的问答语料、某个作者的回答，或一个问题下的评论互动。

Do not use it when:

- 热榜只有 30 条且需要登录；匿名浏览会被 401 拒绝。

## Prerequisites

- A network this platform answers from: 国内.
- A saved login for the modes that need one: posts, author, hot, comments.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `zhihu` and `collect` one of: `posts`, `author`, `hot`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "zhihu",
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
    "platform": "zhihu",
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
Documentation: `docs/capabilities/platforms/zhihu.md`
Skill page: `docs/capabilities/skills/platforms/zhihu.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
