# platform.wechat

微信公众号：粘贴文章链接，逐篇打开并保存正文。

## When to use

已有公众号文章链接清单，需要正文语料时。

Do not use it when:

- 它不搜索、不翻页、不需要登录；要发现文章请先用别的方式拿到链接。

## Prerequisites

- A network this platform answers from: 国内.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `wechat` and `collect` one of: `posts`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "wechat",
    "collect": "posts",
    "urls": "https://example.com/item/1"
  }
}
```

## Template JSON

```json
{
  "type": "source",
  "params": {
    "platform": "wechat",
    "collect": "posts",
    "urls": "https://example.com/item/1"
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
Documentation: `docs/capabilities/platforms/wechat.md`
Skill page: `docs/capabilities/skills/platforms/wechat.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
