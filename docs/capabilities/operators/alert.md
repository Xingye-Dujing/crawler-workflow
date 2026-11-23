# alert（time）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/alert.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按连续涨跌、摆动幅度、升温与量能规则，在曲线上标出二次爆发预警点。

## 何时使用

要在情感/热度曲线上自动指出“需要人工复核的时刻”。

不要用于：

- 预警是规则给出的候选，不是因果结论；要看趋势用 forecast。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string | `period` |  |  |
| `index_col` | string | `sentiment_index` |  |  |
| `intensity_col` | string |  |  |  |
| `volume_col` | string |  |  |  |
| `streak` | integer | `2` |  |  |
| `swing` | number | `0.2` |  |  |
| `heating` | number | `0.15` |  |  |
| `volume_floor` | number | `0.6` |  |  |

## 读取的列

- 必须存在的一列：`column`、`index_col`

## 输出形状

新表，列固定：`period`、`signal`、`value`、`threshold`、`reason`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
