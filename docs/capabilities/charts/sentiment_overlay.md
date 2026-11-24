# sentiment_overlay（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/sentiment_overlay.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

情感叠加图：节点按情感分布着色，看研究板块的情绪倾向。

## 何时使用

文献分析时填了情感映射，想在图谱上区分正负。

不要用于：

- 没有情感分布列时无法着色；普通情感演化用折线图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`情感分布`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
