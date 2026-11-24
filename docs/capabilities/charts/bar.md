# bar（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/bar.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

柱状图：每个类别一根柱子，柱长表示聚合后的数值。

## 何时使用

类别之间比大小：各平台发帖量、高频词、各主题文档数。

不要用于：

- 类别多到看不清（十几类以上）时改用表格或折线；看份额用饼图/百分比堆叠。
- 时间连续且点多时用折线图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category | 是 |  |  |
| `y_field` | value |  |  | agg |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
