# CLUENER NER（简体中文实体候选）

- 清单：`tools/model_manifests/cluener-ner.json`;权重仓库：`uer/roberta-base-finetuned-cluener2020-chinese`。
- 任务：process 节点 `ner` 的 `bert` 模式，把模型名填为该 id 或仓库 id。
- 训练语料：CLUENER2020，10 类细粒度中文实体（人物、组织机构、地点、职位、公司、政府、景点、书籍、游戏、电影）。
- 与 `ckip-ner` 的差别：ckip 的训练标注偏繁体/台湾用法;CLUENER 是简体细粒度标注，更贴微博正文常见实体。
- 下载：`python ml_train/scripts/fetch_assets.py --kind models --only cluener-ner`。
- 状态：**候选，未实测**;`default_for` 保持为空，需先在你的评论语料上测实体 F1 再考虑切换。
