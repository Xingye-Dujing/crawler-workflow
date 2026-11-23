# fill_null（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/fill_null.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

用固定值或上/下一行的值填补所选列的空单元格。

## 何时使用

缺失值是“未填写”而不是“不存在”时，保留行并补上占位值。

不要用于：

- 行本身没有意义（缺了关键字段就该丢弃）时用 drop_null。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |
| `value` | string |  |  |  |
| `method` | string |  |  | ffill, pad, bfill, backfill |

## 读取的列

- 可选列子集（留空=全部）：`columns`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
