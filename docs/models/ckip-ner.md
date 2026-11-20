# ckip-ner（中文命名实体识别）

- 家族 `token_classification`；process 节点 `operation=ner`，`mode=bert`，模型名填 `ckiplab/bert-base-chinese-ner`。
- 输出沿用 NER 节点的五列契约 `row/text/label/start/end`；只保留能在原文中按字符位置复原的实体。
- 权重从 hf-mirror 下载到 `ml_train/.hf-cache`，不写 C 盘。
- 许可 MIT。无自定义标签；新实体类型需要重新训练。
