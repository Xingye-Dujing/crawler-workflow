# platform.hongguo

红果短剧：四个匿名热播榜，以及只能在桌面客户端里跑的评论采集。

## When to use

短剧赛道研究；榜单是匿名的，评论需要 Windows 桌面客户端。

Do not use it when:

- 评论采集在 Linux/macOS/云端没有可驱动的东西，面板会按名不提供。

## Prerequisites

- A network this platform answers from: 国内.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `hongguo` and `collect` one of: `hot`, `comments`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "hongguo",
    "collect": "hot"
  }
}
```

## Template JSON

```json
{
  "type": "source",
  "params": {
    "platform": "hongguo",
    "collect": "hot"
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
Documentation: `docs/capabilities/platforms/hongguo.md`
Skill page: `docs/capabilities/skills/platforms/hongguo.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
