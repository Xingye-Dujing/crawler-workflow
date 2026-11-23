# topic_model（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_model.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

对一列文本做主题建模（LDA 或句向量聚类），输出主题号、排名、特征词与权重。

## 何时使用

要看语料由哪些议题构成，并得到每主题的特征词表。

不要用于：

- 要按阶段分别建模用 topic_by_stage；只要词频共现用 cooccur。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `n_topics` | integer | `5` |  |  |
| `topn` | integer | `10` |  |  |
| `max_features` | integer | `2000` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

新表，列固定：`topic`、`rank`、`keyword`、`weight`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
