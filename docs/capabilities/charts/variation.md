# variation（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/variation.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

变化图：每个节点的起止年与结构变化，用颜色标记上升/下降。

## 何时使用

看关键词在研究周期内是升温还是退场。

不要用于：

- 要看突现强度与区间用突现词图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`起始年`、`结束年`、`结构变化`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
