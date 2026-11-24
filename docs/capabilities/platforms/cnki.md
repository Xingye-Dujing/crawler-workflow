# cnki（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/cnki.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

中国知网：关键词检索，勾选结果并下载 RefWorks 导出，得到文献表。

## 何时使用

文献计量分析的起点：用主题词把一批文献记录取回来。

不要用于：

- 它不是通用网页采集；没有文献分析需求时用别的平台。

## 运行建议

- 建议用你自己的浏览器配置

## 采集模式

### `posts`（settings.collectLiterature）
- 产出：posts；屏幕行为：`dom_read`；需要登录。
- 必填：`keyword`
- 可选：`target_count`、`account`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
