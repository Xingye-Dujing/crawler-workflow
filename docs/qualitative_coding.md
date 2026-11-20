# 质性编码与可见的 LLM 调用（画布 ↔ AI 工作区）

## 量化的内容分析（演绎式编码）

同一套码本体系也服务量化研究：`content_analysis` 节点先有码本（类别、定义、纳入/排除标准），再由 LLM
逐行归类。`mode=code` 单人编码，`mode=dual` 两次独立编码并计算 **Cohen kappa 与一致率**，分歧行保留
两套编码供人工裁定；`mode=report` 输出频次表。AI 工作区的“内容分析”技能引导你定义码本、确认、
看信度、按 kappa 修订码本重跑。节点调用仍走同一条可见追踪对话，重跑闭环完全一致。示例码本见
`samples/workflows/codebooks/content_analysis_sample.json`。

## 通用能力：一次埋点，按等级自动可见

`services/analysis/llm.py::build_llm_run_ctx` 是**唯一**构造节点运行上下文的地方。它在那里调用
`services/llm_trace.start_node_trace(...)` 为符合等级的节点建一个 AI 工作区临时对话（标题
`run | node | op #n`，skill=`node_trace`）。

**追踪等级**（设置 → AI 工作区 → 模型调用追踪等级，`ai_trace_tier`）分三档，所选档位**含更高档**：

- `traditional`（默认）：本地 BERT/sklearn/SnowNLP、NLI（零样本）、句向量（语义去重/相似推荐）等传统模型；
- `llm`：本地 Ollama，以及质性编码、量化内容分析这类驱动模型的节点；
- `api`：云端 DeepSeek/OpenRouter/OpenCode Go；`off` 关闭全部节点追踪。

`services/analysis/trace_tier.py` 是唯一的等级注册表：`node_tier` 定节点档位（LLM 节点按运行时的
provider 落在 llm 或 api），`should_trace` 做门槛比较，浏览器端 `opCallsLlmProcess` 与费用门槛
`op_needs_llm` 也读同一套声明，不会有两处意见。设置改变后无需重启，下一次运行即生效。

对话内容按节点类型而定：

- LLM 节点：`TraceClient` 包住 provider 客户端，**每次 chat 的提示与回答都流式写成对话消息**
  （逐 token 追加、结束结算 Token 估算），录屏里能看到文字逐渐生成；
- 传统模型节点：没有 chat 循环，写入**有界的输入/输出样本**（模型看到的前几行文本 → 产生的列与分数）
  加一条完成消息。会话的 provider/model 填的是**真正跑的模型**（如 `local BERT / ml_train/models/…rbt3`、
  `local model / BAAI/bge-small-zh-v1.5`），所以 AI 工作区底部的模型信息显示的就是本次运行的模型，
  不会误显示为上次聊天的 LLM。

以后新增节点只要使用共享 run context 并在等级注册表里声明档位，就自动获得上述可见性，不需要再写追踪代码。
Key 只留在原客户端里，不写进 ai.db；消息 meta 中的 Token 数是字符估算，明确标 `estimated: true`，不是账单数字。

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
