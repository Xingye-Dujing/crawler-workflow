# 可视化（visualize）

可视化把上游行表变成一张图：ECharts option 或 matplotlib 图片，外加可选的 LaTeX 图表/表格。每种图表类型读哪些字段、
哪些必填、每个字段是什么角色（分类列 / 数值列 / 坐标 / 来源目标 / 文本 / 地区 / 多列列表），全部声明在
`backend/services/charts/registry.py` 的 `ChartSpec.fields` 里；设置面板按这份声明画输入框，运行前校验读同一份声明。

- 清单：`backend/capabilities_kernel/nodes/visualize/manifest.py`
- 图表契约：`backend/services/charts/registry.py`
- 行为：`backend/nodes/executors/visualize.py`
- 契约测试：`tests/unit/capabilities/test_visualize_manifest.py`、`tests/unit/charts/test_chart_registry.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `chart_type` | `bar` | 图表类型（词云、柱状图、主题距离图、文献共现……）。 |
| `x_field` / `y_field` / `y2_field` / `value_field` / `label_field` | 空 | 图表读取的列；由该图型的 `ChartSpec.fields` 决定显示哪些框、哪些必填。 |
| `stack_fields` | 空 | 占比堆叠图的多列列表（逗号分隔），每列是柱内一段。 |
| `model_field` / `agreement_label_field` / `id_field` | `模型` / 空 / `原行` | 模型一致率读取多模型对比表的三列。 |
| `agg` / `agg2` | `sum` | 聚合方式（左轴 / 右轴）。 |
| `engine` | `echarts` | `echarts` 或 `matplotlib`；部分图型只有 ECharts 实现。 |
| `title` | 空 | 图标题。 |
| `tokenize` | `false` | 词云前是否分词。 |
| `emit_latex` / `emit_latex_table` | `true` | 是否产出 LaTeX 图/表，供 PDF 编译/保存消费。 |

## 校验

- `engine.chart_field_missing`：该图型的必填字段为空（例如散点图的 y、占比堆叠图的 `stack_fields`），
  消息带图表名和字段的中文标签。
- `engine.chart_field_group_missing`：至少需要一个字段的图型（箱线图：x 或 y）两个都空。
- `engine.chart_unknown`：存档里的 `chart_type` 已不在本版本的图表清单里；声明默认值（`bar`）就是它的修复建议。
- `engine.chart_column_missing`：**数据 preflight**。该图点名的列不在上游最近一次同指纹运行的表里（多半是改名了）。
- `engine.chart_column_not_numeric`：**数据 preflight**。数值角色（数值/坐标/堆叠列表）的列有非空值，但样本里一个数字都没有。
- `engine.preflight_failed`：preflight 钩子自己抛错；按名报出，诊断接口继续回答其它节点。

preflight 只报能证明的事实：样本为空、列全空、饼图聚合后为负、热力图最终格数都不裁决，这些仍由 builder 在运行期按名拒绝。
样本来自该账号 `runs.db` 中与当前节点指纹一致的上游最近一次运行（≤200 行），30 秒缓存；没有样本就没有数据结论。

问题条目带 `param`（哪个参数）和可选 `fix`（`{"set": {参数: 值}}`）；设置面板据此显示“一键修复”。

## 典型画布

```text
分词 → 可视化（词云）
分析（groupby 平台）→ 可视化（柱状图）→ PDF 编译
```
