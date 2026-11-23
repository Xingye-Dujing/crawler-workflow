# topic_by_stage（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_by_stage.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按阶段列分别做主题建模，输出阶段、主题、特征词、权重、文档数与困惑度。

## 何时使用

要比较“发酵期”和“爆发期”的议题差异，就需要每阶段一套主题。

不要用于：

- 不关心阶段差异时用 topic_model；阶段本身要先由 bin_time 生成。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `stage_col` | string | `阶段` |  |  |
| `order_col` | string |  |  |  |
| `topics` | array | `[]` |  |  |
| `topn` | integer | `10` |  |  |
| `max_features` | integer | `2000` |  |  |
| `word_source` | string | `tfidf` |  | tfidf, lda |
| `sample_n` | integer | `5` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`、`stage_col`
- 不可为空：`topics`

## 输出形状

新表，列固定：`stage`、`stage_order`、`topic`、`feature_words`、`weights`、`doc_n`、`perplexity`、`sample_texts`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
