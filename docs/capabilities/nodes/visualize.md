# 可视化（visualize）

可视化把上游行表变成一张图：ECharts option 或 matplotlib 图片，外加可选的 LaTeX 图表/表格。图表类型决定
它读哪些字段；`ChartSpec.required_params` 决定运行前必须填什么。

- 清单：`backend/capabilities_kernel/nodes/visualize/manifest.py`
- 行为：`backend/nodes/executors/visualize.py`
- 契约测试：`tests/unit/capabilities/test_visualize_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `chart_type` | `bar` | 图表类型（词云、柱状图、主题距离图、文献共现……）。 |
| `x_field` / `y_field` / `value_field` | 空 | 图表读取的列；不需要 x 的图由 `ChartSpec.no_x` 声明。 |
| `agg` | `sum` | 聚合方式。 |
| `engine` | `echarts` | `echarts` 或 `matplotlib`。 |
| `title` | 空 | 图标题。 |
| `tokenize` | `false` | 词云前是否分词。 |
| `emit_latex` / `emit_latex_table` | `true` | 是否产出 LaTeX 图/表，供 PDF 编译/保存消费。 |

## 校验

- `engine.visualize_no_chart`：没有图表类型。
- `engine.visualize_no_x`：该图需要 x 字段但没有填。
- `engine.chart_field_missing`：图表契约的必填字段缺失（例如占比堆叠图的 `stack_fields`），消息带图表名和字段名。

## 典型画布

```text
分词 → 可视化（词云）
分析（groupby 平台）→ 可视化（柱状图）→ PDF 编译
```
