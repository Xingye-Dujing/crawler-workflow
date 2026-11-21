# bge-base-zh（句向量候选）

- 清单：`tools/model_manifests/bge-base-zh.json`;权重仓库：`BAAI/bge-base-zh-v1.5`。
- 任务：语义去重、相似检索、主题步骤的 embedding 路径（节点里 `embedding_model` 填 `BAAI/bge-base-zh-v1.5`）。
- 下载：`python ml_train/scripts/fetch_assets.py --kind models --only bge-base-zh`。
- 状态：**已实测，未入选**（2026-11-21）。T2Reranking 上 recall@10 0.985 / 42.5 行每秒 / 1,660MB；
  比默认 small 仅高 2 行/200 query，吞吐低 3.4 倍。按 `docs/models.md` 的 1 个百分点规则不换默认。
- 原始报告：`ml_train/logs/model_bench/retrieval_embedding_20261121_105421.json`。
