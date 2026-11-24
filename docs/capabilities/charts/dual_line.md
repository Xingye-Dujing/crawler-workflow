# dual_line（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/dual_line.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

双轴折线图：左右两条 Y 轴各画一条曲线，量纲不同也能同图比较。

## 何时使用

同时看“热度（条数）”与“情感指数（-1~1）”这类量纲不同的两条曲线。

不要用于：

- 两条曲线量纲相同时用普通折线，双轴容易被误读成同一刻度。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category | 是 |  |  |
| `y_field` | value |  |  | agg |
| `y2_field` | value | 是 |  | agg2 |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
