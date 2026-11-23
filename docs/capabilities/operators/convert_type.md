# convert_type（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/convert_type.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

把一列转换为文本/整数/小数/布尔/日期时间类型。

## 何时使用

CSV 里数字被读成文本、时间戳需要变成 datetime 以按时间排序时。

不要用于：

- 只想去空格用 strip_whitespace；要派生日期列用 extract_time。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `dtype` | string | `str` |  | str, int, float, bool, datetime |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
