# twitter（overseas）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/twitter.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

X / Twitter：关键词搜索、用户时间线、推文回复（需要登录）。

## 何时使用

海外舆情、名人/机构账号的发言与回复。

不要用于：

- 国内网络通常无法直接访问；评论需要登录会话。

## 采集模式

### `posts`（settings.collectPosts）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`keyword`
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `author`（settings.collectAuthor）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`author`
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `comments`（settings.collectComments）
- 产出：comments；屏幕行为：`dom_scroll`；需要登录。
- 必填：`urls`
- 可选：`input_column`、`comment_limit`、`comment_start`、`comment_end`、`per_article_file`、`backend`、`catbus_account`、`account`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
