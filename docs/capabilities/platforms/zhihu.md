# zhihu（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/zhihu.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

知乎：关键词搜索（可展开全文）、创作者回答、站内热榜、问题/回答评论（含楼中楼）。

## 何时使用

要分析知乎的问答语料、某个作者的回答，或一个问题下的评论互动。

不要用于：

- 热榜只有 30 条且需要登录；匿名浏览会被 401 拒绝。

## 运行建议

- 推荐并行

## 采集模式

### `posts`（settings.collectPosts）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`keyword`
- 可选：`target_count`、`full_body`、`backend`、`catbus_account`、`account`、`recrawl`

### `author`（settings.collectAuthor）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`author`
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `hot`（settings.collectHot）
- 产出：posts；屏幕行为：`fetch`；需要登录。
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `comments`（settings.collectComments）
- 产出：comments；屏幕行为：`dom_scroll`；需要登录。
- 必填：`urls`
- 可选：`input_column`、`comment_limit`、`include_replies`、`comment_start`、`comment_end`、`per_article_file`、`backend`、`catbus_account`、`account`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
