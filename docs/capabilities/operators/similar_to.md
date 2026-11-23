# similar_to（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/similar_to.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

用本地句向量找出与给定文字最相似的前 K 行，输出新的相似度表。

## 何时使用

围绕一个说法找相关评论/帖子，而不是按关键词精确过滤。

不要用于：

- 要删除重复内容用 semantic_dedupe；按列值精确筛选用 filter_rows。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `query` | string |  |  |  |
| `top_k` | integer | `10` |  |  |
| `model` | string | `BAAI/bge-small-zh-v1.5` |  |  |

## 读取的列

- 必须存在的一列：`column`
- 不可为空：`query`

## 输出形状

新表，列固定：`rank`、`row_index`、`text`、`similarity`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
