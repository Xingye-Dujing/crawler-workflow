# biblio_heatmap（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/biblio_heatmap.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

文献热力图：聚类 × 年份的单元格热度，看各板块何时活跃。

## 何时使用

比较多个聚类在不同年份的强度。

不要用于：

- 只看单个节点逐年出现用时区图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`聚类`、`聚类标签`、`年份序列`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
