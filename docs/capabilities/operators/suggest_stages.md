# suggest_stages（time）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/suggest_stages.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按时间列的每日/每窗行数曲线，提议若干个阶段边界（起点、终点、峰值）。

## 何时使用

不知道该把事件切成几段时，先让数据给出候选边界，再人工确认。

不要用于：

- 已有明确边界时直接 bin_time，不要用建议值覆盖已知事实。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `min_days` | integer | `3` |  |  |
| `max_windows` | integer | `6` |  |  |
| `peak_ratio` | number | `2.0` |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

新表，列固定：`序号`、`起点`、`终点`、`天数`、`行数`、`峰值日`、`峰值计数`、`依据`。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
