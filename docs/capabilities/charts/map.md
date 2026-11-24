# map（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/map.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

地图图：按地区名称把数值铺到地图上，颜色深浅表示大小。

## 何时使用

语料带地区维度（IP 归属、用户城市）时。

不要用于：

- 地区名与内置底图不一致时会落空；没有地区列时用柱状图。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | geo | 是 |  |  |
| `value_field` | value |  |  |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
