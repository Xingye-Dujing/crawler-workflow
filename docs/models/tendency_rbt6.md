# tendency_rbt6（立场六类·轻量版）

- 基座 `hfl/rbt6`（6 层），`train_tendency_bert_v2.py --base hfl/rbt6 --epochs 1`，fp16，约 83MB。
- DEV（Qwen 蒸馏标签，seed 42）macro-F1 **0.4945**，稀有类 Controversy F1 = 0；原推荐模型 macro-F1 0.668（另一次 0.681）。
- 低约 17 个百分点，按“1 分内取最快”规则**不切换默认**；保留为速度对照与显存紧张时的快速档。
- 许可 Apache-2.0。备份在 `ml_train/backups/models/<时间戳>/`。
