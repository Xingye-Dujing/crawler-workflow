# bge-large-zh（句向量质量候选）

- 清单：`tools/model_manifests/bge-large-zh.json`;权重仓库：`BAAI/bge-large-zh-v1.5`（326M）。
- 任务：语义去重、相似检索与主题 embedding 的高质量候选。
- 下载：`python ml_train/scripts/fetch_assets.py --kind models --only bge-large-zh`。
- 状态：**已实测，未入选**（2026-11-21）。recall@10 0.990 / 17.2 行每秒 / 峰值 2,806MB；
  对默认 small 只多 3 行/200 query，吞吐低 8.5 倍。原始报告同 `bge-base-zh` 的那份。
- 注意：不同尺寸向量空间不能直接比较分数;整列切换模型后旧缓存/旧结果不可复用。
