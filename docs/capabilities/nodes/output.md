# 保存（output）

保存是画布的合并点：所有上游行表合并成一份文件；PDF 模式则把可视化/编译父节点的产物保存成 PDF。两种形状互斥，都在运行前校验。

- 清单：`backend/capabilities_kernel/nodes/output/manifest.py`
- 行为：`backend/nodes/executors/output.py`
- 契约测试：`tests/unit/capabilities/test_output_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `operation` | `save` | 保存操作；也可以写在节点对象上。 |
| `format` | `csv` | 导出格式。`pdf`（或 `.pdf` 文件名）走 PDF 形状。 |
| `filename` | `export.csv` | 用户文件名；缺少扩展名时由导出器补。 |

## 两种合法形状

1. **表格**：一个或多个行表父节点。列集合不同会拒绝合并，而不是只导出第一张表。
2. **PDF**：只接可视化/编译父节点，且不能同时混有表格父节点、也不能同时接可视化和编译两种来源。

## 校验

- `engine.output_no_op`：没有保存操作。
- `engine.output_no_upstream`：没有父节点。
- `engine.output_pdf_mixed`：PDF 保存混入表格父节点。
- `engine.output_pdf_only_pdfable`：PDF 保存没有任何可视化/编译父节点。
- `engine.output_pdf_two_sources`：PDF 保存同时接可视化和编译。
- `engine.output_needs_pdf` / `engine.output_no_table`：表格保存接到的父节点不能提供行。

## 典型画布

```text
数据源 → 清洗 → 保存（comments.csv）
可视化 → 保存（format=pdf, report.pdf）
```
