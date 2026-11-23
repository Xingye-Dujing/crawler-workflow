# topic_salience（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_salience.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

为每主题的词按“总体频率 + 主题内频率”的加权相关度排序，输出显著词表。

## 何时使用

要画显著词图，或说明每个主题真正有区分度的词（而不是全语料高频词）。

不要用于：

- 要主题距离图用 topic_map；要共现网络用 cooccur。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `n_topics` | integer | `5` |  |  |
| `max_features` | integer | `2000` |  |  |
| `topn` | integer | `30` |  |  |
| `relevance` | number | `1.0` |  |  |
| `method` | string | `auto` |  | lda, embedding, auto |
| `embedding_model` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

新表，列固定：`topic`、`rank`、`term`、`overall_freq`、`within_freq`、`relevance`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
