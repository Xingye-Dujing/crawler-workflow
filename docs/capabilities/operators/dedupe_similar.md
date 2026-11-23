# dedupe_similar（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/dedupe_similar.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按一列文本的 SimHash 距离删除近似重复行（改写、加表情、换标点）。

## 何时使用

评论/转发里同一句话被改写多次时，保留一条代表。

不要用于：

- 需要语义相似（同义改写）时用 semantic_dedupe；逐字重复用 drop_duplicates。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `max_distance` | integer | `8` |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
