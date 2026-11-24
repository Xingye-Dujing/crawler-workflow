# box（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/box.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

箱线图：按类别展示数值的中位数、四分位与离群值。

## 何时使用

比较不同类别的分布形状，而不只是均值：各平台点赞分布。

不要用于：

- 只需要均值或总量时用柱状图；样本极少时箱线图没有意义。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category | 当 y_field 已填 |  |  |
| `y_field` | value |  |  | agg |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
