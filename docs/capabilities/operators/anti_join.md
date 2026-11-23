# anti_join（join）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/anti_join.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按连接键排除已出现在第二张表里的行（内容去重），可只保留交集。

## 何时使用

新一轮采集前先剔掉上一轮已抓过的链接/内容。

不要用于：

- 要合并两张表的列用 join_tables；同一张表内去重用 drop_duplicates。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `left_on` | string |  |  |  |
| `right_on` | string |  |  |  |
| `mode` | string | `trim` |  | exact, trim, url, text, similar |
| `keep` | string | `exclude` |  | exclude, keep |
| `ignore_case` | boolean | `False` |  |  |
| `max_distance` | integer | `8` |  |  |
| `swap_tables` | boolean | `False` |  |  |

## 读取的列

- 两张表的连接键：`left_on`、`right_on`

## 输出形状

输出列依赖数据，需从运行结果读取。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
