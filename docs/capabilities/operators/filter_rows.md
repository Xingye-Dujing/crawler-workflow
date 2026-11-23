# filter_rows（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/filter_rows.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按一列与给定值的比较（等于/包含/大于/为空…）保留或删除行。

## 何时使用

把分析限定在一个子集：某平台、某时间段、包含某个词。

不要用于：

- 要按另一张表的键去重/剔除用 anti_join；只挑列用 select_columns。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `op` | string |  | 是 | eq, ne, gt, gte, lt, lte, contains, not_contains, in, not_in, is_null, not_null |
| `value` | string |  |  |  |
| `keep` | string | `keep` |  | keep, exclude |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
