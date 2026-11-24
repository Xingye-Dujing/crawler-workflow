# bilibili（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/bilibili.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

哔哩哔哩：关键词搜索视频、UP 主的投稿、热门/排行榜、视频评论（含楼中楼）。

## 何时使用

以视频为载体的舆情或创作者研究；评论来自 reply API，结构稳定。

不要用于：

- 热门与排行是同一模式里的一个选择，不是两种采集。

## 运行建议

- 推荐并行

## 采集模式

### `posts`（settings.collectVideos）
- 产出：posts；屏幕行为：`dom_read`；需要登录。
- 必填：`keyword`
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `author`（settings.collectAuthor）
- 产出：posts；屏幕行为：`dom_scroll`；需要登录。
- 必填：`author`
- 可选：`target_count`、`backend`、`catbus_account`、`account`、`recrawl`

### `hot`（settings.collectHot）
- 产出：posts；屏幕行为：`fetch`；需要登录。
- 可选：`target_count`、`board`、`backend`、`catbus_account`、`account`、`recrawl`

### `comments`（settings.collectComments）
- 产出：comments；屏幕行为：`fetch`；需要登录。
- 必填：`urls`
- 可选：`input_column`、`comment_limit`、`include_replies`、`comment_start`、`comment_end`、`per_article_file`、`backend`、`catbus_account`、`account`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
