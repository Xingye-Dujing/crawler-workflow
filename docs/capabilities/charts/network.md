# network（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/network.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

关系网络：来源/目标/权重三列画成节点与连线，可居中一个关键节点。

## 何时使用

回复网络、词语共现、作者互动。

不要用于：

- 只要看两两流向的带宽用桑基图；边太多时网络会变成毛线球。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | source | 是 |  |  |
| `y_field` | target | 是 |  |  |
| `value_field` | value |  |  | agg |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
