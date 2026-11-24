# platform.bilibili

哔哩哔哩：关键词搜索视频、UP 主的投稿、热门/排行榜、视频评论（含楼中楼）。

## When to use

以视频为载体的舆情或创作者研究；评论来自 reply API，结构稳定。

Do not use it when:

- 热门与排行是同一模式里的一个选择，不是两种采集。

## Prerequisites

- A network this platform answers from: 国内.
- A saved login for the modes that need one: posts, author, hot, comments.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `bilibili` and `collect` one of: `posts`, `author`, `hot`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "bilibili",
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
    "platform": "bilibili",
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
Documentation: `docs/capabilities/platforms/bilibili.md`
Skill page: `docs/capabilities/skills/platforms/bilibili.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
