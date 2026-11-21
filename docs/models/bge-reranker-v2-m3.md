# bge-reranker-v2-m3（重排候选）

- 清单：`tools/model_manifests/bge-reranker-v2-m3.json`;权重仓库：`BAAI/bge-reranker-v2-m3`。
- 任务：对召回的 ≤50 个候选做交叉编码精排（AI 工作区 `model_rerank`）。
- 下载：`python ml_train/scripts/fetch_assets.py --kind models --only bge-reranker-v2-m3`。
- 状态：**已实测，未入选**（2026-11-21）。pairwise accuracy 0.69 对 base 的 0.68（400 对里差 4 对，噪声内），
  但 batch 8 只有 0.5 对每秒、峰值 5,424MB；同进程连载两个重排模型还会在 8GB 卡上 OOM。
  `default_for=['reranker']` 保持 `bge-reranker-base`。
- 边界：重排分数不与召回阶段的向量分数直接比较;不对逐行分类使用。
