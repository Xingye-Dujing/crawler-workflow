# topic_map（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/topic_map.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

主题距离图：每个主题一个气泡，位置是主题间距离，大小是文档占比。

## 何时使用

主题距离图：看哪些主题彼此接近、哪个主题占比最大。

不要用于：

- 要看每个主题的词用显著词图；没有 pc1/pc2 列时先用分析节点生成。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | coordinate | 是 | `pc1` |  |
| `y_field` | coordinate | 是 | `pc2` |  |
| `label_field` | label |  | `topic` |  |
| `value_field` | value |  | `prevalence_pct` |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
