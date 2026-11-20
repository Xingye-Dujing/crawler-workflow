# 演示工作流（最佳实践示例）

这五个工作流体现采析绘推荐用法，均在独立演示数据根中实机跑通（Ollama qwen3.5:9b 与本地小模型）：

| 文件 | 演示的能力 | 最佳实践要点 |
|---|---|---|
| `演示1_质性编码开放编码.json` | LLM 节点 ↔ AI 工作区 | 每次 API/Ollama 调用生成可见临时对话；提示、回答、Token 估算、码本证据都留痕；不满意就在对话里继续改，确认后 `apply_codebook` → `rerun_node` |
| `演示2_情感极性BERT批量分类.json` | 微调小模型 | 默认走模型目录里实测最优的 rbt3 蒸馏模型；不逐行问 LLM；批量推理 + 断点缓存 |
| `演示3_语义去重与相似检索.json` | 向量小模型 | 语义近重复 ≠ SimHash 字面近重复；`similar_to` 固定四列输出，图表/下游可读 |
| `演示4_零样本用户标签分类.json` | NLI 小模型 | 临时标签集不用训练、不用 LLM；低于阈值的行留空而不是编造标签 |
| `演示5_NER实体抽取.json` | 序列标注小模型 | BERT NER 输出仍是 `row/text/label/start/end` 五列，可替换 regex/llm 模式而不改下游 |

工作流 JSON 里的 `dataset_id` 指向演示数据根中通过 `/api/data/paste` 创建的数据集；导入到你自己的项目后，把 upload 节点换成你自己的数据集即可。所有下载与缓存仍只落项目目录。

## 实机录屏

五个工作流都在独立演示数据根（`scratchpad/demo_trace_root`，端口 5001）里、桌面 1440×900 视口下真实执行过，录屏在 `videos/`：

- `videos/demo1.mp4`：质性编码开放编码（Ollama qwen3.5:9b，提示/回答/码本追踪可见）
- `videos/demo2.mp4`：情感极性微调 BERT 批量分类
- `videos/demo3.mp4`：语义近重复去重 + 相似文本检索
- `videos/demo4.mp4`：零样本用户自定义标签
- `videos/demo5.mp4`：NER 序列标注实体抽取

录屏为 1280×800 H.264/MP4；每次运行都串行，未并发。节点可见追踪对话的界面截图见 `.openchamber/screenshots/trace-9b-final-*.jpg`。
