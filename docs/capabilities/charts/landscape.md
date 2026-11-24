# landscape（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/landscape.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

聚类景观图：把每个聚类画成一块区域，块内是它的成员节点。

## 何时使用

用一页说明文献由哪几个研究板块构成。

不要用于：

- 要看板块随年代的变化用聚类时间线或热力图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`聚类`、`聚类标签`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
