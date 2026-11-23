# topic_label（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/topic_label.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

让本地模型读每主题的特征词与样本文本，写出一句主题概括。

## 何时使用

主题表只有“词1 词2”时，需要给人读得懂的主题名或摘要。

不要用于：

- 没有可用模型时不要调用：本步按名拒绝，绝不静默换成别的模型。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `words_col` | string | `feature_words` |  |  |
| `samples_col` | string | `sample_texts` |  |  |
| `summary_col` | string | `主题概括` |  |  |
| `on_fail` | string | `abort` |  | abort, blank, fallback |
| `max_topics` | integer | `30` |  |  |

## 读取的列

- 必须存在的一列：`words_col`
- 不可为空：`summary_col`

## 输出形状

保留上游列，追加清单声明的列。

## 模型

本步需要运行中的 LLM；没有可用模型时按名拒绝，不会静默换模型。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
