# topic_map（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_map.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

把主题投射到二维平面（pc1/pc2），并给出每主题的占比与特征词。

## 何时使用

要画主题距离图（气泡位置=主题距离，大小=占比）。

不要用于：

- 只想看特征词的重要性用 topic_salience。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `n_topics` | integer | `5` |  |  |
| `max_features` | integer | `2000` |  |  |
| `topn` | integer | `6` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

新表，列固定：`topic`、`pc1`、`pc2`、`prevalence_pct`、`doc_n`、`feature_words`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
