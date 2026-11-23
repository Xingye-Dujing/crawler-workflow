# join_tables（join）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/join_tables.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

把第二条输入的表格按连接键拼到第一条上（left/right/inner/outer/cross）。

## 何时使用

把主题表、统计表或另一平台的结果按共同键合并成一张宽表。

不要用于：

- 只想剔除已在另一张表里的行用 anti_join；同表内改列用 rename_columns。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `how` | string | `left` |  | left, right, inner, outer, cross |
| `left_on` | string |  |  |  |
| `right_on` | string |  |  |  |

## 读取的列

- 两张表的连接键：`left_on`、`right_on`

## 输出形状

输出列依赖数据，需从运行结果读取。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
