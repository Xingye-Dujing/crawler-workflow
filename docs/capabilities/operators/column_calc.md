# column_calc（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/column_calc.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

用一列或多列的算式派生新列（如 点赞 / 评论）。

## 何时使用

图表需要比率、差值或加权分，而表里只有原始计数时。

不要用于：

- 要按时间/数值分箱用 bin_column；要按行条件筛选用 filter_rows。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `new_col` | string |  |  |  |
| `expr` | string |  |  |  |

## 读取的列

- 不可为空：`new_col`、`expr`

## 输出形状

保留上游列，追加清单声明的列。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
