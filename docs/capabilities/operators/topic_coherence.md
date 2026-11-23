# topic_coherence（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_coherence.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

在给定主题数区间上扫一遍 LDA，输出每个主题数的连贯度，帮助选择主题数。

## 何时使用

不确定 n_topics 取几时，用连贯度曲线给依据。

不要用于：

- 已有确定主题数就直接 topic_model，不必再扫。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `min_topics` | integer | `2` |  |  |
| `max_topics` | integer | `8` |  |  |
| `topn` | integer | `10` |  |  |
| `max_features` | integer | `2000` |  |  |
| `max_documents` | integer | `2000` |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

输出列依赖数据，需从运行结果读取。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
