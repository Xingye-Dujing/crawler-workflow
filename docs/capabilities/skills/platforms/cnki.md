# platform.cnki

中国知网：关键词检索，勾选结果并下载 RefWorks 导出，得到文献表。

## When to use

文献计量分析的起点：用主题词把一批文献记录取回来。

Do not use it when:

- 它不是通用网页采集；没有文献分析需求时用别的平台。

## Prerequisites

- A network this platform answers from: 国内.
- A saved login for the modes that need one: posts.
- Every required box of the chosen mode filled (or fed from an upstream column).

## Steps

1. Put a `source` node with `platform` `cnki` and `collect` one of: `posts`.
2. Fill the mode’s required boxes; a comment walk takes the article/video links.
3. A mode this machine cannot run is refused by name before the run starts.

## Examples

```json
{
  "type": "source",
  "params": {
    "platform": "cnki",
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
    "platform": "cnki",
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
Documentation: `docs/capabilities/platforms/cnki.md`
Skill page: `docs/capabilities/skills/platforms/cnki.md`
Contract tests: `tests/unit/capabilities/test_platform_manifests.py`
