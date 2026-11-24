# stack_pct（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/stack_pct.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

百分比堆叠柱：每个类别的几列占比堆成 100%，看构成变化。

## 何时使用

正/中/负情感占比随时间或阶段的变化。

不要用于：

- 没有被拆成几列占比时用普通柱状图；要看总量而不是构成时不适合。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `x_field` | category | 是 |  |  |
| `stack_fields` | list | 是 |  |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- ECharts 与 matplotlib 都能画
- 有 LaTeX 孪生图/表

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
