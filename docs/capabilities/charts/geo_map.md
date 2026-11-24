# geo_map（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/geo_map.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

文献地理分布图：把各节点的频次铺到内置底图的分区上。

## 何时使用

文献数据带有地区维度时。

不要用于：

- 普通语料的地区热度用地图图，它读的是你自己的地区列。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
