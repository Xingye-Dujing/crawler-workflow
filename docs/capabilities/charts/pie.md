# pie（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/pie.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

饼图：一个整体被分成几份，扇面角度表示占比。

## 何时使用

少量类别（约 6 个以内）的份额构成，如情感分布。

不要用于：

- 类别多或需要精确比较大小时用柱状图；份额为负无法画面积。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category | 是 |  |  |
| `y_field` | value |  |  | agg |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
