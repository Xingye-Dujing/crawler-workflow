# timezone（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/timezone.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

时区图：每个节点按年份序列铺开，颜色表示该年的出现量。

## 何时使用

看单个关键词在每一年是否出现、出现多少。

不要用于：

- 要按簇汇总用聚类时间线。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| — | — | — | — | — |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表
- 文献列：`节点`、`年份序列`、`频次`

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
