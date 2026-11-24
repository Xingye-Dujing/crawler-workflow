# weibo（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/weibo.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

微博：关键词搜索（可限定起止时间）、某个 UID 的微博、热搜榜、微博评论（含楼中楼）。

## 何时使用

舆情事件研究的主力语料：搜索 + 时间窗，或按账号追踪。

不要用于：

- 热搜是匿名接口，不需要登录；其他模式必须用能保持登录态的浏览器。

## 运行建议

- 建议用你自己的浏览器配置
- 必须串行（真排队）

## 采集模式

### `posts`（settings.collectPosts）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`keyword`
- 可选：`target_count`、`start_time`、`end_time`、`backend`、`catbus_account`、`account`、`recrawl`

### `author`（settings.collectAuthor）
- 产出：posts；屏幕行为：`fetch`；需要登录。
- 必填：`author`
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `hot`（settings.collectHot）
- 产出：posts；屏幕行为：`fetch`；匿名。
- 可选：`target_count`、`backend`、`catbus_account`、`recrawl`

### `comments`（settings.collectComments）
- 产出：comments；屏幕行为：`fetch`；需要登录。
- 必填：`urls`
- 可选：`input_column`、`comment_limit`、`include_replies`、`comment_start`、`comment_end`、`per_article_file`、`backend`、`catbus_account`、`account`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
