# bin_time（time）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/bin_time.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按给定时间边界把行切成阶段，并写入阶段名与可选的阶段序号。

## 何时使用

要做分阶段 LDA、主题演化或情感演化，先把时间轴切成“发酵/爆发/衰退”。

不要用于：

- 不知道边界时先用 suggest_stages 提议；只取日期用 extract_time。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `edges` | array | `[]` |  |  |
| `labels` | array | `[]` |  |  |
| `new_col` | string | `阶段` |  |  |
| `order_new_col` | string |  |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

保留上游列，追加清单声明的列。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
