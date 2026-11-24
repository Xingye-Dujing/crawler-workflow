# platform.xiaohongshu

小红书：关键词搜索笔记（可带前 N 条评论预览），或对笔记链接采集评论。

## When to use

消费决策/种草类语料，或某篇笔记下的评论互动。

Do not use it when:

- 搜索结果页会滚动，无头模式更容易被重定向到登录页。

## Prerequisites

- A network this platform answers from: 国内.
- A saved login for the modes that need one: posts, comments.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `xiaohongshu` and `collect` one of: `posts`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "xiaohongshu",
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
    "platform": "xiaohongshu",
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
Documentation: `docs/capabilities/platforms/xiaohongshu.md`
Skill page: `docs/capabilities/skills/platforms/xiaohongshu.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
