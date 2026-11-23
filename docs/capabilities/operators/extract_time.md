# extract_time（time）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/extract_time.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

从时间列派生日期、小时、星期、月或年，写成新列。

## 何时使用

事件研究要按天聚合、看周内节律，或给分阶段准备时间基准列。

不要用于：

- 要按边界切成阶段用 bin_time；只改类型用 convert_type。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `new_col` | string | `日期` |  |  |
| `part` | string | `date` |  | date, hour, weekday, month, year |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

保留上游列，追加清单声明的列。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
