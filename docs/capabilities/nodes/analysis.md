# 数据分析（analysis）

数据分析在一个表上按顺序执行算子流水线：筛选/选列/改名/连接/分组、统计、文本分析（关键词/主题/LDA）
以及图表用的聚合。每一步声明它读哪些列、产出哪些列。

- 清单：`backend/capabilities_kernel/nodes/analysis/manifest.py`
- 行为：`backend/nodes/executors/analysis.py`
- 契约测试：`tests/unit/capabilities/test_analysis_manifest.py`

## 参数（种子形状）

| 参数 | 默认 | 说明 |
|---|---|---|
| `operation` | `drop_null` | 单步快捷操作；也可以写在节点对象上。 |
| `columns` | 空 | 多列参数（逗号分隔）。 |
| `column` | 空 | 单列参数。 |
| `value` | 空 | 比较值。 |
| `op` | `eq` | 比较方式。 |
| `dtype` | `str` | 类型转换目标。 |
| `rename_from` / `rename_to` | 空 | 改名步骤的两个列名。 |

完整流水线写在 `steps`（JSON 数组）；每个算子的参数契约在 `services/analysis/ops/`，未知算子/参数按名拒绝。

## 校验与血缘

- `engine.analysis_no_op`：既没有 `steps` 也没有 `operation`。
- `emit_columns`/`read_columns`：由执行器按 `steps` 回答；未枚举的算子回答“未知”，不猜形状。
- 缺失的输入列会在 `validate_step` 阶段按名拒绝。
- **运行后数据检查**（`postcheck`）：流水线从非空输入产出 **0 行**时，控制台按名报
  `engine.empty_output`（warning，不改变节点状态）。含 `filter_rows`/`join_tables`/`anti_join` 的流水线豁免——
  这些步骤产出 0 行就是用户要的答案。输入本身为空时由运行循环按“跳过”处理，不在这里重复。

## 典型画布

```text
数据源 → 数据分析（drop_null 正文 → groupby 平台）→ 可视化
```
