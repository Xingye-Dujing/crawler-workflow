# semantic_dedupe（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/semantic_dedupe.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

用本地句向量比较一列文本，删掉语义重复的行（同义改写也算）。

## 何时使用

同一观点被换词重写多次，需要按意思去重时。

不要用于：

- 只是字面相近用 dedupe_similar；要按关键词找相似行用 similar_to。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `model` | string | `BAAI/bge-small-zh-v1.5` |  |  |
| `threshold` | number | `0.92` |  |  |
| `batch_size` | integer | `64` |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
