# burst（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/burst.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

突现词图：每个节点标出突现的起止年份与强度。

## 何时使用

找出某一时期突然升温的关键词。

不要用于：

- 看整体聚类年代跨度的聚簇时间线更合适。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`突现起始`、`突现结束`、`突现强度`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
