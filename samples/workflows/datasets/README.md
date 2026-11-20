# 演示数据

`model` 组的数据通过 `/api/data/paste` 写入独立数据根 `scratchpad/demo_trace_root/data/datasets.db`：

| 数据集名 | 列 | 用途 |
|---|---|---|
| `demo_zero` | 正文 | 质性编码、零样本、量化内容分析 |
| `demo_sentiment` | 正文、日期 | 情感极性 BERT |
| `demo_semantic` | 正文 | 语义去重与相似检索 |
| `demo_ner` | 正文 | NER |

`showcase` 组直接复制项目正式数据根的 `data/datasets.db` 到 `scratchpad/demo_showcase_root/data/`，
所以已保存画布引用的 dataset_id 保持有效；这是复制，不改动正式数据。

新增演示数据时：先启动对应数据根的服务，再用 `POST /api/data/paste`（`{name, data:[{...}]}`）写入，
把返回的 `dataset_id` 填进 `templates/` 里对应画布的 upload 节点即可。
