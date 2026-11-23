# cluster_label（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/cluster_label.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按聚类列分组，让本地模型为每个簇写摘要，输出每簇一行。

## 何时使用

已按主题/相似度聚好类，需要给每类一句可读的概括。

不要用于：

- 要保留明细行只在旁边加一列用 topic_label。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `group_col` | string | `cluster` |  |  |
| `text_col` | string | `正文` |  |  |
| `summary_col` | string | `摘要` |  |  |
| `on_fail` | string | `abort` |  | abort, blank, fallback |
| `max_groups` | integer | `60` |  |  |
| `sample_n` | integer | `8` |  |  |

## 读取的列

- 必须存在的一列：`group_col`、`text_col`
- 不可为空：`summary_col`

## 输出形状

新表，列名来自本步参数。

## 模型

本步需要运行中的 LLM；没有可用模型时按名拒绝，不会静默换模型。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
