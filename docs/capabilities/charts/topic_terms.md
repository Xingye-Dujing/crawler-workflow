# topic_terms（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/topic_terms.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

显著词图：每个主题里最有区分度的词，及其总体频率与主题内频率。

## 何时使用

显著词图：说明每个主题真正独特的词，而不是全语料高频词。

不要用于：

- 要看主题在平面上的位置用主题距离图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category | 是 | `term` |  |
| `y_field` | value | 是 | `overall_freq` |  |
| `y2_field` | value | 是 | `within_freq` | agg2 |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
