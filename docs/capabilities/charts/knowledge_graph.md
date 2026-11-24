# knowledge_graph（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/knowledge_graph.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

文献知识图谱：节点按共现坐标布局，连线宽度表示共现强度。

## 何时使用

文献分析之后的主题/关键词共现图谱。

不要用于：

- 普通评论语料的词共现用关系网络；没有 biblio 节点写出的列时无法绘制。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`x`、`y`、`连接`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
