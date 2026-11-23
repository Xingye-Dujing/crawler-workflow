# cooccur（topic）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/cooccur.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

统计同一文本窗口内共同出现的词对，输出 source/target/value 边表。

## 何时使用

要画词语共现网络，看概念如何绑定在一起。

不要用于：

- 要主题的特征词用 topic_model 或 topic_salience。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `topn` | integer | `30` |  |  |
| `min_count` | integer | `2` |  |  |
| `window` | integer | `0` |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

新表，列固定：`source`、`target`、`value`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
