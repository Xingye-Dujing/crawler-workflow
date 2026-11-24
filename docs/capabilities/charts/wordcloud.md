# wordcloud（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/wordcloud.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

词云：词语按权重放大排布，一眼看出高频词。

## 何时使用

分词结果的直观展示，尤其是报告首页的“关键词印象”。

不要用于：

- 要精确比较词频用柱状图或表格；词太多时词云会看不清。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | text | 是 |  |  |
| `value_field` | value |  |  |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
