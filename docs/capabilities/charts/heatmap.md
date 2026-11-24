# heatmap（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/heatmap.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

热力图：两个类别轴交叉成单元格，颜色深浅表示聚合值。

## 何时使用

两个维度交叉的强度：阶段 × 主题、平台 × 情感。

不要用于：

- 只有一个维度时用柱状图或折线图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category2 | 是 |  |  |
| `y_field` | category2 | 是 |  |  |
| `value_field` | value |  |  | agg |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
