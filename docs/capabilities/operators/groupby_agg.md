# groupby_agg（statistics）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/groupby_agg.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按一列分组，对另一列求和/均值/计数等，输出每组一行。

## 何时使用

把明细表变成“每个平台/每天/每个主题一行”的统计表再画图。

不要用于：

- 要保留明细只用 filter_rows；要比较两个平台的整体分布用 compare_platform。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `group_col` | string |  |  |  |
| `agg_col` | string |  |  |  |
| `agg_func` | string | `sum` |  | sum, mean, median, min, max, count, nunique, std, var |
| `order_col` | string |  |  |  |
| `agg_metrics` | array | `[]` |  |  |

## 读取的列

- 必须存在的一列：`group_col`、`agg_col`

## 输出形状

输出列依赖数据，需从运行结果读取。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
