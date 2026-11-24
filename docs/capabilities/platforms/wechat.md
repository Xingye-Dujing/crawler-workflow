# wechat（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/wechat.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

微信公众号：粘贴文章链接，逐篇打开并保存正文。

## 何时使用

已有公众号文章链接清单，需要正文语料时。

不要用于：

- 它不搜索、不翻页、不需要登录；要发现文章请先用别的方式拿到链接。

## 采集模式

### `posts`（settings.articleUrls）
- 产出：posts；屏幕行为：`page_per_row`；匿名。
- 必填：`urls`
- 可选：`input_column`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
