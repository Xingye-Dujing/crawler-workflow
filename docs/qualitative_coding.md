# 质性编码与可见的 LLM 调用（画布 ↔ AI 工作区）

## 量化的内容分析（演绎式编码）

同一套码本体系也服务量化研究：`content_analysis` 节点先有码本（类别、定义、纳入/排除标准），再由 LLM
逐行归类。`mode=code` 单人编码，`mode=dual` 两次独立编码并计算 **Cohen kappa 与一致率**，分歧行保留
两套编码供人工裁定；`mode=report` 输出频次表。AI 工作区的「内容分析」技能引导你定义码本、确认、
看信度、按 kappa 修订码本重跑。节点调用仍走同一条可见追踪对话，重跑闭环完全一致。示例码本见
`samples/workflows/codebooks/content_analysis_sample.json`。

## 通用能力：一次埋点，所有 API 节点可见

`services/analysis/llm.py::build_llm_run_ctx` 是**唯一**构造 LLM 运行上下文的地方。它在那里调用
`services/llm_trace.start_node_trace(run_id, node_id, op, client)`：

- 若当前有运行 id，就为这个节点建一个 AI 工作区临时对话（标题 `run | node | op #n`，skill=`node_trace`）；
- 用 `TraceClient` 包住节点原本的 provider 客户端，**每次 chat 的提示与回答都写成对话消息**；
- 控制台打印对话 id；`GET /api/ai/traces/<run_id>` 列出该运行的全部追踪对话。

因此清洗、情感/立场/情绪 llm 模式、`topic_label`、`cluster_label`、`cluster_review`、NER 的 llm
模式、攻击性识别、质性编码——**所有会调 API 的节点自动可见**，以后新增节点只要使用共享
run context，不需要再写一行追踪代码。Key 只留在原客户端里，不写进 ai.db；消息 meta 中的
Token 数是字符估算，明确标 `estimated: true`，不是账单数字。

## 三级编码

`qualitative_code` 节点，`phase` 参数：

1. **开放编码**：逐行让模型给短概念 + 原文证据，输出 `open_codes` / `evidence`（`|` 分隔多码）。复用
   `run_llm_dataframe` 的断点、缓存、停止语义；并把频次码本保存为第 1 版。
2. **主轴编码**：读已确认码本，模型把码归为 `类目 | 副类目 | 代码 | 关系`，保存为下一版，输出类目表。
3. **选择性编码**：模型给出 `CORE:` 与 `MEMO:`，保存为下一版，输出核心类目与备忘录。

码本按账号存在 `data/users/<id>/ai_files/codebooks/`，每次保存递增版本，不覆盖旧版；API：
`GET/POST /api/ai/codebooks`、`GET/DELETE /api/ai/codebooks/<id>`。

## 在 AI 工作区里闭环

`qualitative_coding` 技能引导三个Phase：先看追踪对话里的真实提示/回答，用 `dataset_peek` 抽样，
`ask_user_question` 让你确认或合并码；你确认后用 `apply_codebook` 保存新版本（需审批），再
`rerun_node` 从该节点连同下游重跑。这样“改完再跑”走的是既有的重跑机制，画布不会被替换。

**Provider**：本地 Ollama 与 DeepSeek 等 API 都走运行时统一的 LLM 设置（与画布其他 LLM 节点一致）；
云端模式对本地模型仍按名拒绝。
