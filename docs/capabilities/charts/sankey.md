# sankey（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/sankey.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

桑基图：来源到目标的带权流向，带宽表示流量。

## 何时使用

主题流向、平台到情感的去向、阶段之间的转移。

不要用于：

- 没有“从哪到哪”的两列时用柱状图或热力图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | source | 是 |  |  |
| `y_field` | target | 是 |  |  |
| `value_field` | value |  |  | agg |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
