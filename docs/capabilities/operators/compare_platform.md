# compare_platform（statistics）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/compare_platform.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按平台列（或任意分组列）统计行数，并可对一列数值求均值/求和。

## 何时使用

多平台合并后要比较各平台的量与强度。

不要用于：

- 只想看单一平台时用 filter_rows + groupby_agg。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `platform_col` | string | `platform` |  |  |
| `value_col` | string |  |  |  |
| `agg` | string | `mean` |  | mean, sum, median, min, max, count |

## 读取的列

- 必须存在的一列：`platform_col`

## 输出形状

新表，列名来自本步参数。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
