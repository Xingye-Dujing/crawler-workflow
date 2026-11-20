# 本地模型目录、下载与选型

## 一句话

一个模型 = 一个清单（`tools/model_manifests/<id>.json` 或 `data/models/<id>/model.json`）+ 一个家族适配器（`backend/analyzers/backends/`）。节点、面板和 AI 工作区都从同一个目录读取，浏览器里没有第二张模型表。

## 清单里有什么

`id / name / family / task / path / labels / outputs / score_kind / precision / quality[] / use_for / avoid_for / license / docs / default_for`。运行时再补两项：`runnable` 与 `why_not`（本机跑不了时按名字说明原因，不静默换模型）。

- `GET /api/models` 仍只返回旧的 `{name,path,desc,operation}` 手编注册表，保持旧画布与测试行为。
- `GET /api/models/catalog` 返回完整目录 + 本机能力（`torch/onnxruntime/cuda/空闲显存`）。
- `default_for` 决定该任务的推荐模型；未知 id 一律按名字拒绝。

## 下载与缓存（绝不写 C 盘）

`backend/core/cache.py` 在 `core.config` 导入时发布所有缓存路径；`ml_train/scripts/_env.py` 给离线脚本发布同样的路径。实际目录：

```
ml_train/.hf-cache/          HF_HOME / hub / xet（已下载权重复用这里）
ml_train/.cache/             torch / sentence-transformers / matplotlib / joblib
ml_train/.tmp/               训练临时文件
ml_train/datasets/<任务>/    分类数据集
ml_train/models/             部署用权重（旧路径，保持不变）
ml_train/backups/models/     微调模型的独立备份
ml_train/.locks/gpu.lock     单任务锁
```

国内网络默认走 `https://hf-mirror.com`；可用 `CIXI_HF_ENDPOINT` 覆盖。下载一次一个资产：`python ml_train/scripts/fetch_assets.py --kind models --only rbt3`。资产表在 `ml_train/scripts/assets.json`（可编辑 repo id），回执在 `ml_train/logs/fetch_*.json`。

## 微调模型备份（防误删）

`python ml_train/scripts/backup_assets.py` 为 `ml_train/models/` 下每个权重目录做**独立副本**（不是硬链接），写入 `ml_train/backups/models/<时间戳>/`，并生成带 SHA-256 的 `manifest.json`。`--verify` 只读取并比对当前权重与最新备份。现有 4 个模型已备份并校验通过。

## 数据集目录

按任务分类，不堆在根目录：

```
datasets/classification/sentiment|emotion/
datasets/stance/raw|distilled|labeled/
datasets/ner/<语料>/
datasets/retrieval/<句对>/
datasets/evaluation/<任务>/
datasets/raw/<原始语料>/
```

`backup_assets.py` 用硬链接把原有平铺文件放进对应目录（不移动、不删除原文件，也不额外占空间）；`INDEX.json` 记录映射。

## 单任务约束

`ml_train/scripts/job_lock.py` 的 `gpu_slot()` 是一把全局文件锁：训练、基准、批量推理一次只跑一个。`gpu_preflight.py` 要求训练前至少 4.5GB 空闲显存、推理前 1.5GB，不足则按名字拒绝并打印当前数字。应用内 `services/models/lease.py` 保证同一时刻只驻留一个重型模型。

## 选型规则

`ml_train/scripts/bench.py` 在固定留出集上逐模型测 accuracy、rows/s、峰值显存，结果写入 `ml_train/logs/model_bench/` 与 `docs/model_bench.md`。入选规则：**在最优指标 1 个百分点以内的模型中取最快者**；同分取显存更小者。指标必须带数据集、划分、种子；没有实测数字的模型不得进入 `default_for`。

## 已接的小模型场景

- 文本分类：`sentiment` / `emotion` / `tendency`（每个模型都可从目录选择，多模型对比复用 `bert_models`）。
- 语义：`semantic_dedupe`（近重复去重）、`similar_to`（相似文本检索），以及主题步骤的 embedding 路径。
- AI 工作区：`models_catalog` 查目录、`model_infer` 在 ≤200 行上试跑；`models` 与 `model_tuning` 技能负责调度与配方。
