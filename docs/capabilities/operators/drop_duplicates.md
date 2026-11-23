# drop_duplicates（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/drop_duplicates.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按所选列删除重复行；exact 逐字比较，normalized 先做全半角/空白归一。

## 何时使用

同一行被采集了两次（翻页重叠、导出合并）时去重。

不要用于：

- 两段文字意思相同但写法不同时用 dedupe_similar 或 semantic_dedupe。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |
| `keep` | string | `first` |  |  |
| `mode` | string | `exact` |  | exact, normalized |

## 读取的列

- 可选列子集（留空=全部）：`columns`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
