# 分词（tokenize）

分词把一个文本列切成词，输出词表。它自己不读文件：数据总是来自上游连线（上传、采集、清洗或分析节点）。

- 清单：`backend/capabilities_kernel/nodes/tokenize/manifest.py`
- 行为：`backend/nodes/executors/tokenize.py`
- 契约测试：`tests/unit/capabilities/test_tokenize_manifest.py`

## 参数

| 参数 | 默认 | 说明 |
|---|---|---|
| `text_column` | 空 | 必填。上游表里要切分的文本列（例如 `正文`）。空值在运行前按名拒绝。 |
| `output_mode` | `word_freq` | 输出形状：`word_freq`（词 + 频次）、`words_only`（每行一个词）、`csv_line`（一行空格连接的词）。未知值由执行器按名拒绝。 |
| `top_n` | 空 | 仅 `word_freq` 生效。空表示执行器默认上限；非空必须是正整数。 |

## 输出列

| `output_mode` | 列 |
|---|---|
| `word_freq` | `word`, `frequency` |
| `words_only` | `word` |
| `csv_line` | `words` |

这三张表是执行器的端口契约；清单通过 `ports.emit_columns` / `read_columns` 指向同一组函数，血缘视图不会保存第二份列名。

## 失败模式

- **没有文本列**：`engine.tokenize_no_column`，在运行前由清单规则拒绝，消息带节点标题。
- **列不在上游表中**：执行器拒绝并列出实际列名，而不是返回一张空表。
- **没有上游数据**：执行器拒绝，提示连接数据源或上传节点；空表不会以“完成”结算。
- **未知 `output_mode`**：执行器按名拒绝，列出允许的三个值。

## 典型画布

```text
数据源 / 上传 → 分词（word_freq, 正文, top_n=120）→ 词云 / 柱状图
```

同一画布里的“处理”节点也有 `tokenize` 操作，它复用这里的执行器与列契约；两者在验证阶段都报 `engine.tokenize_no_column`。
