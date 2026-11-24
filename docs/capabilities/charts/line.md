# line（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/line.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

折线图：按有序类别（通常是时间）连成趋势线。

## 何时使用

看随时间或阶段的走势：每日发帖量、情感指数曲线。

不要用于：

- 类别之间没有顺序时用柱状图；两条量纲不同的曲线用双轴折线。
- 只有一个时间点或类别时用柱状图。

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
