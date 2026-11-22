# PDF 编译（compile）

PDF 编译收集所有可视化父节点产出的 LaTeX，拼成一份文档并编译成 PDF。它读的是父节点的**产物**，不是行表；空来源会被按名拒绝，不会产出一页空白 PDF。

- 清单：`backend/capabilities_kernel/nodes/compile/manifest.py`
- 行为：`backend/nodes/executors/compile.py`
- 契约测试：`tests/unit/capabilities/test_compile_manifest.py`

## 端口与参数

- 输入：任意数量的可视化父节点（`inputs = -1`），每个都必须至少打开“输出 LaTeX”或“LaTeX 表格”之一。
- 参数：无。
- 输出：`pdf` 行形状（一份编译好的 PDF 权限）。

## 校验

- `engine.compile_no_upstream`：没有父节点。
- `engine.compile_bad_parent`：某个父节点不是可视化节点，消息带父节点标题。
- `engine.compile_source_both_off`：某个可视化父节点的 LaTeX/表格开关全关。

## 典型画布

```text
可视化（柱状图，输出 LaTeX）─┐
可视化（词云，输出 LaTeX）  ─┼→ PDF 编译 → 保存（format=pdf）
可视化（表格，LaTeX 表格）  ─┘
```

单独一张图可以直接用保存节点的 PDF 模式；编译节点的价值是把多张图合成一份文档。
