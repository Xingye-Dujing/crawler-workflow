# node.comment

评论采集 walks the comments of the article links on one form, batch by batch, and emits the same comment table a 数据源 in comments mode produces (评论内容/评论时间/点赞数/文章URL …). The cursor records only the leading links it PROVED complete, so 继续 replays from the first hole.

## When to use

When the post table is known and the comments under each post are the corpus.

Do not use it when:

- A platform mode that already emits comments belongs on node.source.
- A post table that only needs a chart is not a comment crawl.

## Prerequisites

- One article link per line, or a title where the platform matrix declares names.
- A saved login for each platform the links name; the wall is per account.
- A comment budget when the crawl should stop early.

## Steps

1. Paste article links (one per line); a 红果 title is accepted where the matrix declares names.
2. Pick the login account — the comment wall is a per-account rate limit, which is why accounts exist.
3. Set comment_limit (0 = every comment), part_size and whether parts are kept.

## Examples

```json
{
  "type": "comment",
  "params": {
    "urls": "https://www.zhihu.com/question/1/answer/2",
    "comment_limit": 0,
    "part_size": 50,
    "per_article_file": true,
    "keep_parts": false,
    "recrawl": false,
    "format": "csv"
  }
}
```

## Template JSON

```json
{
  "type": "comment",
  "params": {
    "urls": "https://www.zhihu.com/question/1/answer/2",
    "comment_limit": 0,
    "part_size": 50,
    "format": "csv"
  }
}
```

## Parameters

| name | type | default | required | allowed |
|---|---|---|---|---|
| `urls` | string |  | yes |  |
| `comment_limit` | integer | `0` |  |  |
| `part_size` | integer | `50` |  |  |
| `per_article_file` | boolean | `True` |  |  |
| `keep_parts` | boolean | `False` |  |  |
| `recrawl` | boolean | `False` |  |  |
| `format` | string | `csv` |  | csv, json |

## Failure modes

- No links: engine.comment_no_urls.
- The account holds no login for a platform a link names: engine.source_no_cookie_account.
- A @pool account with no saved login / all cooling: engine.source_pool_empty / _cooling.
- A walled or short link settles PARTIAL and keeps its cursor hole, so 继续 re-walks it.

## Acceptance

- The node stores the comment table with content/time/likes/article URL.
- Every blocked link stays a cursor hole and is reported as PARTIAL.

## Reach it

Tools: `workflow_schema`, `apply_workflow`, `workflow_validate`
Documentation: `docs/capabilities/nodes/comment.md`
Skill page: `docs/capabilities/skills/nodes/comment.md`
Contract tests: `tests/unit/capabilities/test_comment_manifest.py`
