# circular（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/circular.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

环形共现图：节点沿圆周排布，连线表示共现关系。

## 何时使用

共现关系多、力导向布局容易挤成一团时。

不要用于：

- 要看聚类分组用知识图谱或聚类景观图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`连接`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
