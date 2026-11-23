# sort_rows（clean）

> 由 `tools/gen_capabilities.py` 从 `backend/capabilities_kernel/operators/` 的清单生成，请勿手改。
> 技能正文：`docs/capabilities/skills/operators/sort_rows.md`；机器可读：`backend/capabilities_kernel/generated/catalog.json`。

按一列升序或降序重排行（行集合不变）。

## 何时使用

图表 X 轴或分阶段分析要求按时间/热度排序时。

不要用于：

- 要按分组聚合用 groupby_agg；要取子集用 sample_rows 或 filter_rows。

## 参数

| 参数 | 类型 | 默认 | 必填 | 可选值 |
|---|---|---|---|---|
| `column` | string |  |  |  |
| `ascending` | boolean | `True` |  |  |

## 读取的列

- 必须存在的一列：`column`

## 输出形状

行被过滤或重排，列不变。

## 契约测试

- `tests/unit/capabilities/test_operator_manifests.py`
