# cluster_timeline（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/cluster_timeline.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

聚类时间线：每条聚类一行，横轴是首年到末年。

## 何时使用

看各主题簇的活跃年代与延续长度。

不要用于：

- 需要单节点的突现年份用突现图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`聚类`、`聚类标签`、`首年`、`末年`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
