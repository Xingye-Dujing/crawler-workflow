# sample_rows（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/sample_rows.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

随机抽取 n 行或比例的样本（可固定随机种子）。

## 何时使用

大表先抽样看效果，或做对照实验时取固定样本。

不要用于：

- 要按条件挑行用 filter_rows。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `n` | integer |  |  |  |
| `frac` | number |  |  |  |
| `seed` | integer |  |  |  |

## 读取的列

- 不读取具名列。

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
