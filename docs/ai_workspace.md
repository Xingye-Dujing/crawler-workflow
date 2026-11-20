# AI 工作区 / AI workspace

AI 工作区是右侧常驻的智能体面板：读项目事实、调用只读工具、流式回答，并把写入做成用户可应用的产物。
同一套工作区在桌面版、本地网页版和云端网页版上功能一致；差异只在宿主能触达的资源（见 §6）。

## 1. 结构与请求流

```text
index.html → ai-workspace.js
  ├─ ai/stream.js    SSE 解码（POST + fetch）
  ├─ ai/render.js    转义 Markdown、引用、问题卡、产物卡、工具卡
  ├─ ai/settings.js  浏览器本地 Key / 模型 / 偏好
  ├─ ai/context.js   当前画布草稿、手动 dataset/run id
  ├─ ai/watch.js     运行监控的投递轮询
  └─ ai/studio.js    技能、Python 脚本库、插件、权限
              │
POST /api/ai/chat → AgentService
  ├─ ContextBuilder   项目事实 / 实时数据 / 文档 / 预算
  ├─ SkillRegistry    内置 + 用户技能
  ├─ ToolRegistry     只读工具 + ask_user/update_plan/present_artifact
  └─ ProviderCatalog  DeepSeek / OpenCode Go / OpenRouter / Ollama
              │
事件：meta, thinking, text, citation, server_tool, tool_start, tool_result,
      plan, question, artifact, usage, title, error, done, paused
```

一轮对话可能包含多次供应商调用和工具调用；每次 assistant 行独立持久化，按 `turn_id` 分组。
`ask_user_question` 暂停该轮，答案作为工具结果恢复。崩溃留下 `interrupted`，不会留下 vanished 回答。

## 2. 供应商与密钥

| id | 协议 | 能力 |
|---|---|---|
| `deepseek` | 原生 Chat Completions（`api.deepseek.com/chat/completions`） | thinking、web search、读链接、安全、标题、文件、工具、提问 |
| `opencode_go` | OpenAI Chat Completions | thinking、工具、提问、视觉；无服务端联网/文件 |
| `openrouter` | OpenAI Chat Completions | 视模型而定；无服务端工具 |
| `ollama` | 本机 `/api/chat` | 工具、思考（每个模型以 `/api/show` 的 `capabilities` 为准）；无文件/联网；云端按名字拒绝 |

DeepSeek 走它自己的原生协议，不走 Anthropic 兼容层：`thinking` 显式给 `enabled/disabled`（缺省即开启），强度用
`reasoning_effort`，思考文本在 `delta.reasoning_content`，用量随最后一个 chunk（`stream_options.include_usage`）。
带 `tools` 的轮次必须回传此前每一步的 `reasoning_content`，否则 API 返回 400；联网工具 `deepseek_web_search` /
`deepseek_read_url` 是服务端工具，步骤通过 `choice.server_tool_event` 下发，完整的 `server_tool_calls`（含还原网页的
`signature`）在最后一个 chunk 里一次给全。流式按 UTF-8 **增量**解码（`stream_lines`）：按 chunk 用 `iter_lines` 解会用
ISO-8859-1，中文变火星文、跨 chunk 的多字节字符把 JSON 截断（这就是曾经那句“供应商返回了无法解析的数据”）。

**省 token 的三条规矩**：大表格（≥128 KB 或超过 200 行）上传时直接进数据集，前端得到一个 `@` 数据集引用——AI 用
`dataset_peek` 只读前几行，绝不把整张表塞进提示词；单个附件超过 4 MB 按名字拒绝，并提示改走数据集或拆分；`@` 引用
的导出文件/工作流只在服务端展开有界文本（每项 1200 字符、整轮 6000 字符）。同一份文件在不同会话里上传时按 sha256
复用已上传的 `file_id`，不重复上传、不重复解析计费。**提问卡的回答框同样支持 `@`**：引用随 `answers` 一起送到
`/api/ai/answer`，服务端用同一个 `references.resolve` 展开后放进该次工具结果，模型看到的是有界文本而不是路径。

**本机 Ollama 不是“只有聊天”**：模型列表来自 `/api/tags`（面板打开时静默刷新一次，存过的选择只要守护进程还有就保留），
`tools`/`thinking` 以 `/api/show` 的逐模型 `capabilities` 为答案；请求里 `messages` 保留 `role: tool`、assistant 回传
`tool_calls`，并按模型真实 `context_length` 下发 `num_ctx`（Ollama 缺省 4096，会把长长的系统提示悄悄截掉）。

`backend/ai/providers/registry.py` 是唯一目录，行分析器 `analyzers/llm_client.py` 也读它。
Key 只存浏览器 `localStorage`，随请求体发送（拉模型列表走 `X-Provider-Key` 请求头，绝不进 URL——反代的访问日志会记整行请求），服务端仅在本次调用持有；`ai.db` 与日志绝不写入 Key。
供应商不支持的能力按名字拒绝，不静默降级。

## 3. 技能、上下文与工具

内置技能（`backend/ai/skills.py`）：`project`、`crawl`、`catbus`、`diagnose`、`monitor`、`analysis`、
`workflow`、`charts`、`report`、`research`、`python`、`conductor`、`skill_author`、`developer`。
技能声明提示词、上下文来源、只读工具和所需能力；用户技能是数据，可 Fork/编辑/删除，不能包含代码或写操作。

`catbus` 是本地技能（`local_only`，云端按名拒绝）：面对采集需求先问“建画布节点（第二后端选 catbus）”还是
“AI 直接调 catbus 指令运行”，再用只读工具 `catbus_status` 分别探测采析绘适配器与全局 `catbus` CLI，
缺哪样点名哪样、绝不自行安装。它的权威文档随仓库放在 `docs/catbus/`（来自 catbus 的 `.claude/skills/catbus/`），
由 `docs_search` 按任务检索；直接指令路径通过 `run_cmd` 执行 `catbus`（已加入命令白名单），需用户批准。

`ContextBuilder` 从既有注册表生成项目事实，按账号读取实时数据，限额并脱敏；省略项写入
`context_meta` 并在检查器显示。

- **上下文对每一轮、每一个传输层都成立**：`ai.context.build_context` 生成一次，由
  `ai.providers.base.replay_context` 注入**那一轮自己的 user 行**，DeepSeek / OpenCode Go /
  OpenRouter / 本地 Ollama 一律收到。这条曾经只有 DeepSeek 的传输层读取，于是本地模型一轮都
  没收到项目事实，而侧栏仍显示“项目事实 N 字”。
- **重放是逐轮的，字节永不改写**：某一轮的上下文跟着那一轮的行留在会话里，后续每一轮原样重放。
  供应商的前缀缓存匹配的是字节——一段“只在第一轮存在”的上下文会让它之后的每个消息都失效，
  等于每个新轮次把整段历史按 cache-miss 价重算一次（实测 63,025 字符里只有 3,725 命中）。
  因此这段块的大小在**写入时**就定下来（`ai_context_replay_chars`，默认 16,000 字），超出的部分
  用工具现取，并在 `context_meta.replay_truncated` 里如实报告（检查器显示“已截到 N 字”）。
- **省略要看得见**：`context_meta.omitted`（整体预算丢掉的来源）以前只在 JSON 里，现在侧栏也列出来。
- **脱敏也要看得见**：`redact()` 用 `redact_with_count()` 计数，`build_context` 与被引用文本各自把
  去掉的密钥数按来源写进 `context_meta.redacted`（只记数量，绝不留原值），检查器汇总成一句
  “已移除 N 处密钥”；被预算丢掉、根本没发出的来源不计入。这样“悄悄擦掉”就变成一次可核对的事实。
- 工具参数不完整（典型是回答被 `max_tokens` 截断）时**拒绝执行并按名字说明**，不拿空参数去跑；
  `done.stop_reason == 'max_tokens'` 在转录里显示一行“被截断”，刷新后仍在（存进 assistant 行的
  `meta.stop_reason`）。
- 传输层在**首字节之前**对 429/5xx/连接失败重试（最多 3 次、可被停止打断）；401/402/404 这类
  确定性拒绝立即报错，不重试。
- **默认联网搜索**：工作区默认 DeepSeek 直连并默认开启联网搜索——DeepSeek 自 2026-11-18 起
  调用模型触发的服务端搜索/抓页工具调用本身免费，结果拼进上下文只按模型 Token 计费
  （`ai_web_search_default` 默认为开，浏览器没手动选过时采纳，点工具栏开关可关）；
  思考强度可选 `low/high/max`（`ai_reasoning_effort`，默认 high），非思考轮次的温度
  `ai_temperature` 默认 0.3（草案与 JSON 更稳；思考开启时供应商忽略它）。
- **token 软预算**：`ai_budget_conversation_tokens` / `ai_budget_daily_tokens`（默认 0=不限）只按
  真实 token 计，不把不同币种的标价相加。`costs.spend_state` 读本会话与本机当日（按服务器时区向机器
  询问，不写死时区）已花的 prompt+completion；新消息在写用户行、开 run、调供应商**之前**若已
  超支就具名拒绝（`ai.budgetExceeded`）；一轮之内触顶则复用 `ask_user_question` 的暂停通道问一次
  “继续 / 到此为止”，回答记在该轮用户行上，续跑不再重复问。金额仍由 `costs.conversation_cost`
  按供应商自己的价格呈现，价格未知就说未知。
- **窗口由我们自己守**：`Provider.context_window()` 是唯一答案（Ollama 回它真正下发的
  `min(num_ctx, 模型自报窗口)`），`agent._fit_history` 在**user 边界**裁掉最旧轮次，并把
  `context_meta.history`（window/budget/dropped/kept）交给检查器显示。否则本地 daemon 会**从开头**
  截断——系统提示最先丢，模型跑到一半就不记得自己的规则。Ollama 的 `num_predict` 现在等于同一次
  请求的输出预算，不再“生成到窗口填满为止”。
- **停止是一等状态，不是错误**：按停止的那一轮存 `status=done` + `meta.stop_reason='cancelled'`，
  已经写出的半截回答留在转录里、也留在下一轮的历史里（说“继续”时模型看得见自己写过什么）；刷新后
  显示的是一行中性提示，不是红色报错。
- **生成期间输入框仍可用**：`_setSending` 只禁用发送键、亮出停止键；重复发送由 `_sendText` 用一句
  toast 挡住，而不是把光标和草稿一起收走（用输入框禁用来防重复，代价是用户连下一条都打不了）。
- **只要这一轮还开着，“生成中”这一行就一直在**：它画在 `.ai-flow` **外面**（`.ai-status`，流程块按 HTML
  串记忆，带秒数的一行若在里面要么冻住、要么每秒重画整段），由 `_startClock()` 的 1 秒定时器原地改字。
  三种状态各有措辞：正常生成（`ai.working`）、正在等应用返回（有工具在跑，`ai.waiting`）、**15 秒没有任何
  字节**（`ai.stillWaiting`）；秒数写在旁边一个 `aria-hidden` 的 span 里，读屏只会念一次阶段词。旧实现只在
  “最后一块不是文本”时才画，于是**一段写完后的静默**看起来就是回答结束；而那个为长命令写的工具时钟写好了
  却**从未启动**，三分钟的命令全程一行静止的“运行中”。
- **结束必须被说出来，而且只能由结束事件说出来**：`done`/`question`/`paused`/`error`/停止各有一条路径，
  它们都把这一行收掉并留下自己的一句（截断、已停止、等你的回答）。**流没有结束事件就结束**（服务端崩了、
  代理断了、笔记本睡了）时，`_noteCutStream()` 补一行“连接在回答结束前就断了”，而不是让半截回答冒充完成。
- **重开一段没写完的回答也要说明白**：文件里最后一条 assistant 行 `status` 为 `interrupted`（服务端判定：
  读端消失，`_stream` 的 `finally` 当场落库，不再等下次启动的清扫）显示“这次回答没写完就中断了”；仍为
  `streaming` 则显示“还在生成中（可能另一个页面在接收）”——两个事实不是一件事，措辞也不该相同。
  **清算要按会话**：新会话的 `conversation_id` 不在请求里，`_stream` 从第一个 `meta` 事件学到它再落库——
  否则一次刷新会把**别的会话**正在生成的回答也标成 `interrupted`（这条是被测试逼出来的真 bug）。
- **实测就是那一档测试**：`tests/integration/test_ai_workspace_live.py`（真实 Chrome + 本地 Ollama + 真服务器，
  独立 `CRAWLER_DATA_ROOT`）每 250 ms 读一次页面，断言“第一个可见样本到最后一个可见样本之间**没有任何一帧**没有这一行”、
  秒数在轮次跨过 2.5 秒时**确实变过**、阶段词只取目录里的三种、回答结束后这一行收起；第二个用例按停止并断言只剩
  “已停止生成”且没有红色错误。本机实测：一次完整回答 21 次采样、秒数 0→4 秒、回答 116 字，全档 2 例约 56 秒。

**默认只读最小证据**：

- `dataset_peek`：列名/类型 + 5 行，单元格 120 字；- `dataset_profile`：行数、缺失/唯一值、每列 2 个样本；
- `dataset_page`：≤50 行，带 `has_more`；
- `python_run`：行数 + 小样本 + stdout/stderr；
- `dataset_query`：精确的只读聚合（`count`/`sum`/`mean`/`median`/`min`/`max`/`std`/`nunique`/`value_counts`/`groupby`/`filter`），操作名白名单在 schema 与执行时各查一次，列名不存在、算子不支持、参数不完整都按名拒绝，结果行数与单元格都封顶——精确数字不靠 `dataset_peek` 的前几行估算；
- 工具结果超过 12,000 字会被截断并注明。

写入永远是产物（工作流草稿、分析计划、图表规格、报告、技能草稿、插件清单、监控请求），由用户应用。可预览的产物卡（memory / workflow / workflow_draft / monitor / chart_spec）额外带一个“预览变更”按钮：`POST /api/ai/artifacts/preview` 先跑与原产物相同的校验（不通过时带校验原句按名拒绝），再由 `ai/previews/` 注册表按 kind 给出结构化说明——节点是新增还是覆盖、将写入的记忆文本、监控规则、图表与列名。工作流草稿会对照当前画布标出每个节点的去向；确认框里可勾选节点，只把选中的节点并入现有画布（未选中的保持原样，指向它们的连线丢弃），然后走与主键完全相同的 apply 路径。预览本身只读，不写任何东西。图表规格的产物卡还有“渲染这张图”按钮：`POST /api/ai/chart/preview` 按图表注册表与账号数据集校验类型、数据集与每个列名（缺列具名拒绝），返回归一化的渲染请求，浏览器再走**同一个** `/api/visualize/render` 与现有图表查看器；这里不持有第二份图表契约，也不把渲染逻辑复制成另一条路。

**长期记忆是另一条边界：读得到，也必须管得住。** `ai.db` 的 `memories` 表由工作室的“记忆”页维护
（新增/删除/计数）。助手不能直接写：它用 `present_artifact(kind="memory", payload={text})` 提议，
卡片里的“记住这条”才落库。同一句话再次保存返回已有行（`duplicate`），超过 2000 字或 200 条都按名
拒绝（`ai.memoryTooLong`/`ai.memoryFull`），不截断、不淘汰最旧一条。每条记忆跟着之后每一轮上下文发送，
`build_context` 只带最新 20 条，并把 `context_meta.memories = {total, shown, omitted}` 交给检查器。

## 4. 运行监控

AI 用 `present_artifact(kind="monitor")` 提出条件，用户选“自动分析”或“只通知”；侧栏也有“新建监控”手动填同一份规则。构建器先读 `GET /api/ai/monitors/catalog`：它从 `ai.monitors` 的 `EVENTS`/`STATUSES`/`OUTCOMES` 三张表给出可选名字，浏览器因此不持第二份事件表；填好后与产物卡共用 `POST /api/ai/monitors`，校验和投递路径不会分叉。条件示例：

```json
{"run_id": "…", "events": ["node.finished", "run.finished"], "node_ids": ["n3"],
 "statuses": ["failed", "partial"], "min_rows": 0, "console_contains": "",
 "outcomes": ["failed"], "max_triggers": 20, "note": "分析节点失败时告诉我"}
```

- 引擎在 `runtime.run_events` 发布 `run.started` / `node.finished` / `run.finished`；订阅者存在时 `run.log` 每行都发布，由 `ai.monitors` 在工作线程里筛选。
- `ai.monitors` 匹配条件后写一条持久投递；达到 `max_triggers` 自动结束。事件只含 id、状态、计数，不含爬取正文（控制台行也不进投递，模型用 `run_console` 自己读）。
- 投递写入在专用线程队列里完成，运行线程不做磁盘 I/O；`run.log` 的筛选命中后也只排队。
- 浏览器 `ai/watch.js` 轮询投递并在工作区打开/收到事件时反应；自动分析用浏览器里的 Key 发起一轮对话，
  用户行标记 `monitor_event`。服务端从不自行花钱，Key 不进监控表。

## 5. Python 扩展

一个脚本库同时服务 AI 与画布：

- **库**：`services/python_scripts.py`，账号树 `python_scripts.db`；脚本含 id、名称、描述、代码、
  输入/输出、标签、版本。内置 `passthrough`/`clean_text`/`dedupe`/`groupby` 只可 Fork。
- **执行**：`services/python_runtime.py`。`CIXI_INPUT`（JSON Lines）→ `CIXI_OUTPUT`（JSON Lines），
  参数 `CIXI_ARGS`；捕获 stdout/stderr，带超时与行数上限。不是沙箱，以账号权限运行。
- **画布节点**：`type: "python"`，保存 `script_id`/`args`/`timeout`/`max_rows`，不内联代码；
  缺脚本按名字拒绝，控制台一行归因输出。
- **面板**：AI studio 的 Python 页管理/编辑/跑样本；节点面板选脚本并显示解释器状态。
- **解释器**：`CIXI_PYTHON_BIN`/`AI_PYTHON_BIN` → `ai_python_path` → `.venv` → `sys.executable` → PATH。
  桌面版没有解释器时先给出下载计划，用户同意后仅 Windows 下载官方嵌入式包；其他系统按名字拒绝。
- **门槛**：仅本地/桌面；`ai_allow_python` 关闭时工具与节点都拒绝；云端按名字拒绝。

## 5.5 本机 Harness：工作文件夹、命令、工作流直载

AI 工作区是采析绘自己的 agent/harness，不只是问答：

- **合法词汇进提示词**：`backend/ai/vocabulary.py` 从 `nodes/catalog.py`+`nodes/defaults.py`、
  `services.analysis.contracts.STEP_PARAMS`、`services.charts.registry.SPECS`、`capabilities.registry`
  生成一份稳定文本（节点类型与参数种子、平台模式必填字段、算子契约、图表必需列、工作流文件形状），
  进系统提示词前缀（可被 DeepSeek 前缀缓存命中）。`workflow_schema`/`workflow_validate` 工具给出同一份答案。
- **草案先验证再落地**：`ai/workflow_draft.py` 的结构检查 + `WorkflowEngine.validate()` 的运行时检查
  合成一个答案；`present_artifact`/`apply_workflow` 不合法就按名字拒绝并列出节点。
- **直接载入/运行**：`apply_workflow` 校验 → 写进本账号 `data/workflows/`（重名加序号，不覆盖）→ 发
  `workflow_apply` 事件给页面；页面用真实 `workflow.loadFromJSON()` 载入，`run=true` 时接着走正常 Run 通道。
  失败时页面把原因作为“自动反馈”消息送回 AI，让它改完再试。
- **工作文件夹**：`ai/workspace.py`，每账号存在 `ai.db` 的 `prefs` 表；所有路径解析后必须留在根内，
  `..`/绝对路径/越界符号链接按名字拒绝。页面顶栏 chip 打开目录选择器（服务端 `/api/ai/workspace/browse`）；
  选择器顶部列出本机**所有磁盘/挂载点**（`core.machine.filesystem_roots`，Windows 盘符、macOS `/Volumes`、
  Linux `/media` `/mnt`），所以文件夹不限于系统盘。`POST /api/ai/workspace/pick` 用**系统自带**的文件夹
  对话框（Windows PowerShell `FolderBrowserDialog`、macOS `osascript`、Linux `zenity`/`kdialog`）选完即设为
  工作文件夹；关掉窗口算取消，机器上没有任何一个对话框时按名拒绝（`ai.pickUnavailable`），云端不提供。
- **本地文件 → 数据集 / Python / 命令**：`workspace_import` 走上传面板同一套解析器；`run_cmd` 不是 shell，
  只接受白名单可执行文件、无管道/重定向、超时与输出上限，工作目录为所选文件夹（未选时用仓库根/安装根）。
- **反馈闭环**：`app_errors` 读后端 `logs/app.log` 尾部 + 最近失败/部分完成运行的节点错误与控制台；
  运行监控可把结果作为新一轮消息送回。
- **工具预算不是硬墙**：默认 30 轮（`ai_max_tool_rounds`，0=不限）；到达时 AI 通过同一个
  `ask_user_question` 通道询问“继续/到此为止”，回答即续跑一轮，按钮/选项照常进入历史。
- **Plan / Build 与安全开关**：`agent_mode=plan` 时变更类工具不下发（`apply_workflow`、`rerun_node`、
  `workspace_write`、`workspace_import`、`run_cmd`、Python 写入/运行）；`ai_auto_approve` 关闭时
  `run_cmd`/`workspace_write`/`workspace_import`/`rerun_node` 按名拒绝并让 AI 先走 `request_approval`
  （见下一节）。单次工具结果上限 `ai_max_tool_result_chars` 默认 12000，可调。
- **失败节点重跑**：监控的自动分析回答用 `app_errors` 拿到失败节点，卡片列出节点 id + 错误，按钮
  “重跑此节点及其下游”调 `POST /api/ai/rerun`；`ai/agent.py` 的 `rerun_node` 工具走同一个决定
  （`engine/workflow_rerun.rerun_node`，路由 `/api/workflow/rerun-node` 也只剩薄壳）。它只读本账号
  `data/workflows/` 里的**已保存文件**，指纹与运行记录不一致、文件缺失、节点未知、运行未结束都按名拒绝；
  永不把工作流载回画布——页面只标一张“已开始重跑”的卡片并发 `rerun_started` 事件。
- **逐次审批**：`ai/approvals.py` 在进程内按 `(会话, 工具, 参数的 SHA-256)` 记住授权，不落盘、不存密钥。
  `request_approval` 复用 `ask_user_question` 的可恢复暂停（合成 assistant `tool_use`，供应商配对规则仍成立），
  选项为 允许一次 / 本次会话允许 / 拒绝；`once` 用掉即失效，`session` 对同一份确切参数可重复使用，
  拒绝/取消/换一份参数都不授权。`request_approval` 的 `detail` 必须是将要执行的**确切参数对象**。
- **审批卡显示确切改动**：模型的 `summary` 只是它对自己的描述，不能当作批准依据。`ai/approval_preview.py`
  按工具给出可核对的预览：`workspace_write` 用 `difflib` 对照现有文件与提议内容（解析后的绝对路径、
  前后字节数、逐行 `+/-` diff，最多 400 行并声明截断；大文件只报大小并说明会整体替换），`run_cmd`
  给出命令/工作目录/超时，`workspace_import` 给出文件与大小，`rerun_node` 给出运行/节点/工作流。
  预览只读、绝不写入；路径逃逸或云端按名拒绝时，卡片显示工具本会给出的那句话，而不是中断对话。
  预览随 `questions_json` 存入会话，刷新后的已回答卡仍显示当时批准的路径。
- **跨面板入口**：数据集列表、运行列表、节点设置里的“问 AI”调 `AIWorkspace.askAbout()`：打开工作区、
  新建会话、把该对象作为手动上下文（服务端自己重读），并把问题**预填不发送**。面板不持有 AI 的会话
  模型，也不会猜上下文该送什么。
- **@ 运行记录**：`references.KINDS` 增加 `run`，展开为状态、节点错误与控制台尾部（20 行、整块受引用预算限制）。
- **每一步都在历史里**：一轮的块流按模型真实顺序保存——技能（自动路由或用户选择）→ 思考 → 工具（名称、
  参数摘要、结果）→ 计划 → 回答；刷新后同一份块流重绘，不靠“回答完再分块”。

## 6. 桌面版、网页版与云端

| 能力 | 桌面版 | 本地网页版 | 云端网页版 |
|---|---|---|---|
| 会话、技能、声明式插件、文件上传、搜索/抓页、监控 | ✅ | ✅ | ✅ |
| DeepSeek / OpenCode Go / OpenRouter | ✅ | ✅ | ✅ |
| 本机 Ollama、用户本机文件 | ✅ | ✅ | ❌ 按名字拒绝 |
| 工作文件夹（读/写/导入数据集）、白名单命令 | ✅ | ✅ | ❌ 按名字拒绝 |
| Python 库 / 执行 / 节点（需 `ai_allow_python`） | ✅ | ✅ | ❌ 按名字拒绝 |
| 读仓库源码（`developer`） | 只读 `source/` 快照（若构建携带） | ✅（需 `ai_allow_code_context`） | ❌ 按名字拒绝 |
| 本地代码插件 | ✅ | ✅ | ❌ 按名字拒绝 |

判决只来自 `backend/ai/environment.py`：`Config.CLOUD_MODE` + `machine.is_frozen()`；前端不猜。
运行时 chip 显示宿主，技能不可用时禁用并展示服务端原因。桌面构建通过
`desktop/frozen_modules.source_snapshot_datas` 携带只读源码，AI 可引用、不可改运行中的程序。

## 7. 插件

`backend/extensions/` 是清单/权限注册表，`backend/ai/plugins.py` 是宿主。声明式（skill-pack /
provider-pack / tool-pack）是数据、可移植；`kind: "code"` 的本地插件只允许本地/管理员，云端按名字拒绝。
安装前校验 `api`、id、version、kind、permissions；禁用即从注册表移除，并同时从 `PROVIDERS`/`tools.TOOLS`/`skills.BUILTIN` 撤掉。

**安装是机器级的，使用是账号级的。** provider/tool/code 包装进进程共用的表，因此开启账号系统时只有管理员
能安装；但每条贡献在 `backend/ai/scopes.py` 里记下安装它的账号作用域，工具清单、`tools.execute`、
`get_provider` 与技能目录都按当前账号过滤——别的账号既看不到、也调不动。

## 8. OMM-ZEN

只用既有 token（`--paper`、`--text`/`--ink`、`--line`/`--line2`、`--accent`、`--ok`/`--warn`/`--err`、
`--radius`、`--font`）；选中是内嵌墨色下划线，勾选是发丝方框 + 墨色勾，没有纯黑/纯蓝填充。
动效以 transform/opacity 为主（少数状态用背景/边框色过渡），`prefers-reduced-motion: reduce` 下全部关闭；dock 层级在浮动面板之上、对话框之下。

## 9. HTTP 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/ai/bootstrap` | 供应商、技能、会话、用量、设置、工具、运行时、监控 |
| GET | `/api/ai/providers` | 供应商目录与能力 |
| GET | `/api/ai/providers/<id>/models` | 模型列表 |
| POST | `/api/ai/providers/<id>/test` | 一次最小流式往返 |
| GET/POST | `/api/ai/conversations` | 列表（`?q=` 标题搜索、`?archived=1`、`limit/offset`）/ 新建 |
| GET/PATCH/DELETE | `/api/ai/conversations/<id>` | 详情、重命名/置顶/归档、删除 |
| GET | `/api/ai/conversations/<id>/export` | 下载 `format=md|json`（Markdown 投影 / JSON 无损） |
| GET/POST | `/api/ai/memories` | 长期记忆列表（附上限）/ 新增（去重、超长与满额按名拒绝） |
| DELETE | `/api/ai/memories/<id>` | 删除一条记忆 |
| POST | `/api/ai/chat` | SSE 一轮（`?stream=0` 为 JSON） |
| POST | `/api/ai/answer` | 恢复暂停的问题 |
| POST | `/api/ai/stop` | 取消事件 |
| POST | `/api/ai/context` | 上下文预览 |
| GET/POST | `/api/ai/workspace` | 工作文件夹状态 / 设置 |
| GET | `/api/ai/workspace/browse` | 目录选择器（只列目录，附本机磁盘/挂载点 `roots`） |
| POST | `/api/ai/workspace/pick` | 调起系统文件夹对话框，返回所选路径或 `cancelled` |
| POST | `/api/ai/workflow/validate` | 工作流草案的结构 + 引擎校验 |
| POST | `/api/ai/chart/preview` | 校验 chart_spec（图表类型/数据集/列名）并返回归一化渲染请求 |
| POST | `/api/ai/rerun` | 从已保存文件重跑一个失败节点及其下游（失败节点卡片的按钮） |
| GET | `/api/ai/usage` | 本账号 token 汇总 |
| GET/POST | `/api/ai/skills` | 技能列表 / 保存 |
| POST | `/api/ai/skills/<id>/fork` | Fork 内置技能 |
| GET/POST | `/api/ai/plugins` | 插件列表 / 安装 |
| POST | `/api/ai/plugins/<id>/enable` | 启用/禁用 |
| POST | `/api/ai/files` | 上传文件（DeepSeek Files API）；大表格改登记为数据集并回 `dataset` |
| GET | `/api/ai/references` | `@` 引用候选：数据集 / 导出产物 / 工作流文件 / 之前上传的文件 |
| GET | `/api/ai/conversations/<id>/files` | 会话附件 |
| DELETE | `/api/ai/files/<id>` | 删除远端文件、本地副本与行 |
| POST | `/api/ai/search` / `/api/ai/fetch` | 独立搜索 / 抓页 |
| GET/POST | `/api/ai/monitors` | 监控列表 / 开启 |
| DELETE | `/api/ai/monitors/<id>` | 停止监控 |
| GET | `/api/ai/monitors/events` | 待投递事件 |
| POST | `/api/ai/monitors/events/<id>/ack` | 确认投递 |
| GET | `/api/ai/python/status` | 解释器、开关、工作区、下载计划 |
| POST | `/api/ai/python/install` | 同意后下载解释器 |
| GET/POST | `/api/ai/python/scripts` | 脚本列表 / 保存 |
| GET/DELETE | `/api/ai/python/scripts/<id>` | 读取 / 删除 |
| POST | `/api/ai/python/scripts/<id>/fork` | Fork |
| POST | `/api/ai/python/run` | 用给定行跑脚本（返回样本） |
| GET/POST | `/api/ai/python/files` | 工作区文件 |

## 10. 测试

- `tests/unit/ai/test_ai_core.py`：目录、序列化、脱敏、技能、运行时矩阵。
- `tests/api/test_ai_workflow.py`：脚本化供应商、SSE、提问/恢复、能力拒绝、技能与插件。
- `tests/unit/ai/test_ai_approvals.py` + `tests/api/test_ai_approval_turn.py`：授权键（确切参数、
  一次/会话、跨会话与换参数不命中）、拒绝/取消不授权、云端仍按名拒绝、`request_approval` 的暂停与恢复。
- `tests/api/test_ai_rerun.py`：重跑决定（画布改过、运行缺失、节点未知、运行进行中、成功路径）与
  `/api/ai/rerun` 的具名拒绝；agent 的 `rerun_node` 只发 `rerun_started`，不载入画布。
- `tests/api/test_ai_files.py`：上传分片顺序、本地副本、删除、搜索/抓页与凭据 URL 拒绝。
- `tests/api/test_ai_monitors.py`：监控匹配/投递/确认、`run.log` 关键字拒绝、脚本库往返与真实 Python 样本。
- `tests/api/test_ai_memories.py`：记忆去重/超长/满额按名拒绝、上下文只带最新 N 条并报告省略、账号隔离、
  记忆产物卡的提议与“空提案退回模型”。
- `tests/api/test_ai_conversations.py`：标题搜索的 LIKE 转义、置顶/取消置顶不改变活跃时间、归档可见性、
  Markdown/JSON 导出与文件名头。
- `tests/unit/ai/test_approval_preview.py`：写文件 diff / 新建 / 相同内容 / 路径逃逸 / 超大文件 / 行数截断，
  命令与导入的事实，未知工具的原始参数兜底。
- `tests/unit/ai/test_python_node.py`：Python 节点契约、云端拒绝、受限数据读取。
- `tests/unit/ai/test_dataset_query.py`：精确聚合的算子白名单、有界结果、缺列/未知算子按名拒绝。
- `tests/unit/ai/test_budget.py` + `tests/api/test_ai_budget.py`：token 软预算——超支预拒且不发起调用、轮中触顶只问一次、当日边界问机器时区。
- `tests/api/test_ai_chart_artifact.py`：chart_spec 的类型/数据集/列名校验与具名拒绝；前端产物卡的渲染按钮在 `tests/unit/frontend/test_frontend_ai_js.py`。
- `tests/unit/frontend/test_frontend_ai_js.py` + `harness_ai.mjs`：真实解码器/渲染器、运行时 chip、禁用原因。

## 11. 未实现

语音输入输出、OCR、后台常驻智能体、代码插件沙箱。以上能力未声明，不在代码中假装存在。
