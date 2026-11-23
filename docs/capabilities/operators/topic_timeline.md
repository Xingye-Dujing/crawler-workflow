# topic_timeline（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_timeline.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

跨阶段追踪主题：首次出现、峰值、最后出现的阶段与规模，识别二次爆发。

## 何时使用

要讲“议题如何随事件推进”的故事，需要每主题的生命周期轨迹。

不要用于：

- 要看阶段之间的主题流动用 topic_flow。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `stage_col` | string | `stage` |  |  |
| `words_col` | string | `feature_words` |  |  |
| `size_col` | string | `doc_n` |  |  |
| `topic_col` | string | `topic` |  |  |
| `order_col` | string |  |  |  |
| `min_overlap` | number | `0.5` |  |  |

## 读取的列

- 必须存在的一列：`stage_col`、`words_col`、`size_col`

## 输出形状

新表，列固定：`topic`、`topic_words`、`first_stage`、`peak_stage`、`last_stage`、`stages_present`、`stage_path`、`size_total`、`peak_size`、`is_secondary`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
