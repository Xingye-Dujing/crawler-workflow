# topic_flow（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_flow.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按特征词相似度把相邻阶段的主题配对，输出来源/目标、相似度与分歧度的流向边。

## 何时使用

要画主题流向桑基图，说明“发酵期哪个议题变成了爆发期的什么议题”。

不要用于：

- 只看单个主题的生命周期用 topic_timeline。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `stage_col` | string | `stage` |  |  |
| `topic_col` | string | `topic` |  |  |
| `words_col` | string | `feature_words` |  |  |
| `weights_col` | string | `weights` |  |  |
| `order_col` | string |  |  |  |
| `min_similarity` | number | `0.5` |  |  |
| `label_col` | string |  |  |  |

## 读取的列

- 必须存在的一列：`stage_col`、`topic_col`、`weights_col`

## 输出形状

新表，列固定：`source`、`target`、`source_topic`、`target_topic`、`similarity`、`divergence`、`from_stage`、`to_stage`、`source_words`、`target_words`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
