# 处理（process）

处理节点承载所有“对文本列做一件事”的操作：清洗、分词、词频、TF-IDF/TextRank、情感/情绪/倾向、
NER、聚类、相关性，以及质性编码。操作决定输出列和它需要的输入参数。

- 清单：`backend/capabilities_kernel/nodes/process/manifest.py`
- 行为：`backend/nodes/executors/process.py`
- 契约测试：`tests/unit/capabilities/test_process_manifest.py`

## 参数（种子形状）

| 参数 | 默认 | 说明 |
|---|---|---|
| `operation` | `clean` | 操作名。也可以写在节点对象上。 |
| `text_column` | `正文` | 要处理的文本列。 |
| `topic` | 空 | 主题标注使用的主题名。 |
| `live_export` | `false` | 逐行导出开关。 |
| `format` | `csv` | 导出格式。 |

操作专属参数（模型、阈值、词性、批量大小等）由面板按操作渲染，执行器在自己的边界校验；未知值按
`analysis.bad_option` 拒绝并列出允许值。

## 校验

- `engine.process_no_op`：没有操作。
- `engine.tokenize_no_column`：`operation=tokenize` 且没有文本列。

分词操作复用分词节点的执行器与列契约；两者都报同一个 `engine.tokenize_no_column`。

## 典型画布

```text
数据源 → 处理（clean, 正文）→ 处理（sentiment）→ 可视化
数据源 → 处理（tokenize, 正文）→ 词云
```
