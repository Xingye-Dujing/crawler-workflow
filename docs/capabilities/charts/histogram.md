# histogram（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/histogram.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

直方图：把一个数值列分箱，画出每个区间的数量分布。

## 何时使用

看一个数值的分布形状：点赞数的长尾、长度的集中区间。

不要用于：

- 要看两个数值的关系用散点图；要按类别比较用柱状图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | value | 是 |  |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
