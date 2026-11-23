# strip_whitespace（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/strip_whitespace.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

去掉所选列文本首尾的空白（含全角空格），行数不变。

## 何时使用

采集文本带换行/缩进，导致去重、分词或图表标签不一致时。

不要用于：

- 要改数据类型用 convert_type。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `columns` | array | `[]` |  |  |

## 读取的列

- 可选列子集（留空=全部）：`columns`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
