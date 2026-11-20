# tendency_stance_v2_cyberbully（网暴立场·推荐）

- **任务**：process 节点 `operation=tendency`，`mode=bert`（默认）。
- **标签**：Advocacy/Call-to-action、Controversy/Reflection、Criticism/Questioning、Objective Statement、Praise/Affirmation、Satire/Mockery。
- **输出列**：`tendency`、`tendency_confidence`。
- **权重**：`ml_train/models/tendency_stance_v2_cyberbully`，基座 `hfl/chinese-roberta-wwm-ext`，fp32，约 391MB。
- **实测**：dev（seed 42）macro-F1 0.668； controversy 8,208 行 + batch1 的 F1 0.537。
- **吞吐**：同机约 235 行/秒。
- **适用**：六类传播立场、网暴事件评论、立场演化分析。
- **不适用**：简单正负情感、小样本探索性判断、老师标注之外的立场定义。
- **许可**：Apache-2.0。
- **训练**：`ml_train/scripts/train_tendency_bert_v2.py`（软标签蒸馏 + 自训练）。
- **注意**：稀有类 Controversy 与反讽 Satire 最弱；上限受老师判断约束，见 `docs/tendency_model_comparison.md`。
