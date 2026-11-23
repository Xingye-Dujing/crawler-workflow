# forecast（time）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/forecast.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

用移动平均、Holt 或 Holt-Winters 对一条曲线外推若干期，并给出区间。

## 何时使用

情感演化曲线需要往后看几期（预测区间是模型给的，不是事实）。

不要用于：

- 期数不足 min_periods 时按名拒绝，不要用拟合线冒充观测。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string | `period` |  |  |
| `value_col` | string | `sentiment_index` |  |  |
| `method` | string | `moving_average` |  | moving_average, holt, seasonal_naive, holt_winters |
| `horizon` | integer | `3` |  |  |
| `window` | integer | `3` |  |  |
| `alpha` | number | `0.5` |  |  |
| `beta` | number | `0.3` |  |  |
| `min_periods` | integer | `4` |  |  |
| `season` | integer | `7` |  |  |
| `gamma` | number | `0.35` |  |  |

## 读取的列

- 必须存在的一列：`column`、`value_col`

## 输出形状

新表，列固定：`period`、`actual`、`predicted`、`lower`、`upper`、`horizon`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
