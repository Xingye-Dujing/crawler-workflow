# mnli-xnli（零样本分类）

- 家族 `zero_shot`；process 节点 `operation=zero_shot`，候选标签填在你自己的参数里，模型名默认 `MoritzLaurer/mDeBERTa-v3-base-mnli-xnli`。
- 输出 `zero_shot_label` / `zero_shot_score`；低于阈值的行留空，不制造标签。
- 许可 MIT。适合临时标签集；固定六类/情绪这类封闭标签请改用微调分类器。
