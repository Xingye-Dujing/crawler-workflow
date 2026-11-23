# rename_columns（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/rename_columns.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

把一列改名为另一个名字（旧列 -> 新列）。

## 何时使用

上游列名与下游图表/算子约定的列名不一致时对齐一次。

不要用于：

- 要移动/挑选列的集合用 select_columns。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `mapping` | object | `{}` |  |  |

## 读取的列

- 需要 `mapping`（旧列 → 新列）。

## 输出形状

输出列依赖数据，需从运行结果读取。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
