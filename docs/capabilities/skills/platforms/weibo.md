# platform.weibo

微博：关键词搜索（可限定起止时间）、某个 UID 的微博、热搜榜、微博评论（含楼中楼）。

## When to use

舆情事件研究的主力语料：搜索 + 时间窗，或按账号追踪。

Do not use it when:

- 热搜是匿名接口，不需要登录；其他模式必须用能保持登录态的浏览器。

## Prerequisites

- A network this platform answers from: 国内.
- A saved login for the modes that need one: posts, author, comments.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `weibo` and `collect` one of: `posts`, `author`, `hot`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "weibo",
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
    "platform": "weibo",
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
- This platform is serial-only: two sessions at once is a login wall (the gate forces 真排队).

## Acceptance

- The node produced rows, or the refusal named the reason (login wall / risk / captcha).

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/platforms/weibo.md`
Skill page: `docs/capabilities/skills/platforms/weibo.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
