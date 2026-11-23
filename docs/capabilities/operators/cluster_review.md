# cluster_review（biblio）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/cluster_review.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按文献聚类分组，汇总成员、频次与年份跨度，并让模型写簇综述。

## 何时使用

知识图谱聚类已生成，需要逐簇的文献计量解读。

不要用于：

- 要给普通文本聚类写摘要用 cluster_label。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `group_col` | string | `聚类` |  |  |
| `label_col` | string | `聚类标签` |  |  |
| `name_col` | string | `节点` |  |  |
| `freq_col` | string | `频次` |  |  |
| `first_col` | string | `首年` |  |  |
| `last_col` | string | `末年` |  |  |
| `summary_col` | string | `簇综述` |  |  |
| `members` | integer | `12` |  |  |
| `on_fail` | string | `abort` |  | abort, blank, fallback |
| `max_groups` | integer | `60` |  |  |

## 读取的列

- 必须存在的一列：`group_col`、`name_col`
- 不可为空：`summary_col`

## 输出形状

输出列依赖数据，需从运行结果读取。

## 模型

本步需要运行中的 LLM；没有可用模型时按名拒绝，不会静默换模型。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
