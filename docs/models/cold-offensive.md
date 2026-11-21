# COLD 攻击性识别（候选）

- 清单：`tools/model_manifests/cold-offensive.json`;权重仓库：`thu-coai/roberta-base-cold`（COLD 论文基线）。
- 输出：二分类，`label 1 = offensive`;不是严重程度分级，也不判定立场。
- 用法：作为 `aggression` 节点的传统模型候选（当前节点只有词表与逐行 LLM 两档）。先按 `docs/analysis.md` 的分析算子契约接入 `mode=bert` 再谈默认。
- 下载：`python ml_train/scripts/fetch_assets.py --kind models --only cold-offensive`。
- 状态：**候选，未接入节点执行器**。清单入目录只是让模型可寻址，不能把它当成已经可用的节点模式;接入需新增算子/模式与测试。
