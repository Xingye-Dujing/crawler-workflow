# drop_null（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/drop_null.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

删除所选列中含空值的行（任一为空或全部为空）。

## 何时使用

在分析前去掉缺字段的行，或只保留每一列都填写完整的行。

不要用于：

- 只想填补空值而不是删除行时用 fill_null；要按列去重用 drop_duplicates。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |
| `how` | string | `any` |  | any, all |

## 读取的列

- 可选列子集（留空=全部）：`columns`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
