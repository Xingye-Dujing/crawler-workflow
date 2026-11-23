# bin_column（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/bin_column.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

把数值列分成若干区间或给定边界，并写成一列分箱标签。

## 何时使用

把连续的热度/时长变成可做分组统计的类别。

不要用于：

- 按时间分阶段用 bin_time；要写算式列用 column_calc。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `bins` | array | `[]` |  |  |
| `labels` | array | `[]` |  |  |
| `new_col` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

保留上游列，追加清单声明的列。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
