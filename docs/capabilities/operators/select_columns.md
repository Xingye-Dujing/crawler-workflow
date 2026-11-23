# select_columns（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/select_columns.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

只保留列出的列（按此顺序），其余列丢弃。

## 何时使用

导出或画图前把表收窄到需要的几列。

不要用于：

- 要改列名用 rename_columns；要新增计算列用 column_calc。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |

## 读取的列

- 可选列子集（留空=全部）：`columns`

## 输出形状

只保留指定的列，顺序即参数顺序。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
