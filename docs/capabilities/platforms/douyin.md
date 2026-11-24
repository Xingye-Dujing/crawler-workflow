# douyin（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/douyin.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

抖音：某个创作者的主页视频、热榜、视频评论（含楼中楼）。

## 何时使用

短视频平台的热点与评论研究。

不要用于：

- 无头的投递浏览器经常被验证码中间页挡住；用你自己的浏览器配置更可靠。

## 运行建议

- 建议用你自己的浏览器配置

## 采集模式

### `author`（settings.collectAuthor）
- 产出：posts；屏幕行为：`modal_per_row`；需要登录。
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
