# hongguo（cn）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/platforms/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/platforms/hongguo.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

红果短剧：四个匿名热播榜，以及只能在桌面客户端里跑的评论采集。

## 何时使用

短剧赛道研究；榜单是匿名的，评论需要 Windows 桌面客户端。

不要用于：

- 评论采集在 Linux/macOS/云端没有可驱动的东西，面板会按名不提供。

## 采集模式

### `hot`（settings.collectHot）
- 产出：posts；屏幕行为：`fetch`；匿名。
- 可选：`target_count`、`board`、`backend`、`catbus_account`、`recrawl`

### `comments`（settings.collectComments）
- 产出：comments；屏幕行为：`external_app`；匿名。
- 本机要求：`windows_desktop`（不满足时面板按名不提供）。
- 必填：`urls`
- 可选：`input_column`、`comment_limit`、`comment_start`、`comment_end`、`episode_count`、`include_replies`、`harvest_timeout`、`per_article_file`、`recrawl`

## 契约测试

- `tests/unit/capabilities/test_platform_manifests.py`
