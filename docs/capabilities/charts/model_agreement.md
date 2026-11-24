# model_agreement（console）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/charts/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/charts/model_agreement.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

模型一致性矩阵：每个模型对每条数据给出的标签是否一致。

## 何时使用

多个情感/倾向模型对同一份语料比较，找出分歧样本。

不要用于：

- 只用一个模型时没有“一致性”可看。

## 字段

| 字段 | 角色 | 必填 | 默认列 | 控件 |
|---|---|---|---|---|
| `model_field` | column | 是 | `模型` |  |
| `agreement_label_field` | column |  |  |  |
| `id_field` | column | 是 | `原行` |  |

## 输出形状

ECharts/matplotlib 图（可另出 LaTeX 图/表），不是一张数据表。

## 引擎

- 仅 ECharts
- 没有 LaTeX 孪生图（只出现在一致性矩阵）

## 契约测试

- `tests/unit/capabilities/test_chart_manifests.py`
