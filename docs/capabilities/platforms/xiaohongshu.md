# xiaohongshu（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/xiaohongshu.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

小红书：关键词搜索笔记（可带前 N 条评论预览），或对笔记链接采集评论。

## 何时使用

消费决策/种草类语料，或某篇笔记下的评论互动。

不要用于：

- 搜索结果页会滚动，无头模式更容易被重定向到登录页。

## 运行建议

- 建议用你自己的浏览器配置

## 采集模式

### `posts`（settings.collectPosts）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`keyword`
- 可选：`target_count`、`comment_preview`、`backend`、`catbus_account`、`account`、`recrawl`

### `comments`（settings.collectComments）
- 产出：comments；屏幕行为：`dom_scroll`；需要登录。
- 必填：`urls`
- 可选：`input_column`、`comment_limit`、`include_replies`、`comment_start`、`comment_end`、`per_article_file`、`backend`、`catbus_account`、`account`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
