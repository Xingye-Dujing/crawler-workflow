# graph3d（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/graph3d.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

三维共现图：在三个坐标上展开节点，用深度缓解平面拥挤。

## 何时使用

共现关系密集、二维图互相遮挡时。

不要用于：

- 要印刷或静态截图时用二维知识图谱，三维在纸上无法阅读。

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
