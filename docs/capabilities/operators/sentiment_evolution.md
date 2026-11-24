# sentiment_evolution（time）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/sentiment_evolution.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按时间列聚合情感标签，输出每期正/中/负占比、总量与可选的情感指数。

## 何时使用

要画情感演化曲线：时间 × 正负比例 × 强度。

不要用于：

- 要做预测用 forecast；要触发预警用 alert。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `label_col` | string | `sentiment` |  |  |
| `positive` | string | `positive` |  |  |
| `neutral` | string | `neutral` |  |  |
| `negative` | string | `negative` |  |  |
| `new_col` | string | `sentiment_index` |  |  |
| `score_col` | string |  |  |  |
| `order_col` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

新表，列名来自本步参数。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
