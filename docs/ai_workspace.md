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
| `deepseek` | Messages API | thinking、web search、读链接、安全、标题、文件、工具、提问 |
| `opencode_go` | OpenAI Chat Completions | thinking、工具、提问、视觉；无服务端联网/文件 |
| `openrouter` | OpenAI Chat Completions | 视模型而定；无服务端工具 |
| `ollama` | 本机 `/api/chat` | 仅聊天；云端按名字拒绝 |

`backend/ai/providers/registry.py` 是唯一目录，行分析器 `analyzers/llm_client.py` 也读它。
Key 只存浏览器 `localStorage`，随请求体发送，服务端仅在本次调用持有；`ai.db` 与日志绝不写入 Key。
供应商不支持的能力按名字拒绝，不静默降级。

## 3. 技能、上下文与工具

内置技能（`backend/ai/skills.py`）：`project`、`crawl`、`diagnose`、`monitor`、`analysis`、
`workflow`、`charts`、`report`、`research`、`python`、`conductor`、`skill_author`、`developer`。
技能声明提示词、上下文来源、只读工具和所需能力；用户技能是数据，可 Fork/编辑/删除，不能包含代码或写操作。

`ContextBuilder` 从既有注册表生成项目事实，按账号读取实时数据，限额并脱敏；省略项写入
`context_meta` 并在检查器显示。默认只读最小证据：

- `dataset_peek`：列名/类型 + 5 行，单元格 120 字；
- `dataset_profile`：行数、缺失/唯一值、每列 2 个样本；
- `dataset_page`：≤50 行，带 `has_more`；
- `python_run`：行数 + 小样本 + stdout/stderr；
- 工具结果超过 12,000 字会被截断并注明。

写入永远是产物（工作流草稿、分析计划、图表规格、报告、技能草稿、插件清单、监控请求），由用户应用。

## 4. 运行监控

AI 用 `present_artifact(kind="monitor")` 提出条件，用户选“自动分析”或“只通知”。条件示例：

```json
{"run_id": "…", "events": ["node.finished", "run.finished"], "node_ids": ["n3"],
 "statuses": ["failed", "partial"], "min_rows": 0, "console_contains": "",
 "outcomes": ["failed"], "max_triggers": 20, "note": "分析节点失败时告诉我"}
```

- 引擎在 `runtime.run_events` 发布 `run.started` / `node.finished` / `run.finished`，仅在存在控制台监控时发布 `run.log`。
- `ai.monitors` 匹配条件，写一条持久投递；达到 `max_triggers` 自动结束。事件只含 id、状态、计数，不含爬取正文。
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

## 6. 桌面版、网页版与云端

| 能力 | 桌面版 | 本地网页版 | 云端网页版 |
|---|---|---|---|
| 会话、技能、声明式插件、文件上传、搜索/抓页、监控 | ✅ | ✅ | ✅ |
| DeepSeek / OpenCode Go / OpenRouter | ✅ | ✅ | ✅ |
| 本机 Ollama、用户本机文件 | ✅ | ✅ | ❌ 按名字拒绝 |
| Python 库 / 执行 / 节点（需 `ai_allow_python`） | ✅ | ✅ | ❌ 按名字拒绝 |
| 读仓库源码（`developer`） | 只读 `source/` 快照（若构建携带） | ✅（需 `ai_allow_code_context`） | ❌ 按名字拒绝 |
| 本地代码插件 | ✅ | ✅ | ❌ 按名字拒绝 |

判决只来自 `backend/ai/environment.py`：`Config.CLOUD_MODE` + `machine.is_frozen()`；前端不猜。
运行时 chip 显示宿主，技能不可用时禁用并展示服务端原因。桌面构建通过
`desktop/frozen_modules.source_snapshot_datas` 携带只读源码，AI 可引用、不可改运行中的程序。

## 7. 插件

`backend/extensions/` 是清单/权限注册表，`backend/ai/plugins.py` 是宿主。声明式（skill-pack /
provider-pack / tool-pack）是数据、可移植；`kind: "code"` 的本地插件只允许本地/管理员，云端按名字拒绝。
安装前校验 `api`、id、version、kind、permissions；禁用即从注册表移除。

## 8. OMM-ZEN

只用既有 token（`--paper`、`--text`/`--ink`、`--line`/`--line2`、`--accent`、`--ok`/`--warn`/`--err`、
`--radius`、`--font`）；选中是内嵌墨色下划线，勾选是发丝方框 + 墨色勾，没有纯黑/纯蓝填充。
动效只用 transform/opacity，`prefers-reduced-motion: reduce` 下全部关闭；dock 层级在浮动面板之上、对话框之下。

## 9. HTTP 端点

| 方法 | 路径 | 用途 |
|---|---|---|
| GET | `/api/ai/bootstrap` | 供应商、技能、会话、用量、设置、工具、运行时、监控 |
| GET | `/api/ai/providers` | 供应商目录与能力 |
| GET | `/api/ai/providers/<id>/models` | 模型列表 |
| POST | `/api/ai/providers/<id>/test` | 一次最小流式往返 |
| GET/POST | `/api/ai/conversations` | 列表 / 新建 |
| GET/PATCH/DELETE | `/api/ai/conversations/<id>` | 详情、重命名/置顶、删除 |
| POST | `/api/ai/chat` | SSE 一轮（`?stream=0` 为 JSON） |
| POST | `/api/ai/answer` | 恢复暂停的问题 |
| POST | `/api/ai/stop` | 取消事件 |
| POST | `/api/ai/context` | 上下文预览 |
| GET | `/api/ai/usage` | 本账号 token 汇总 |
| GET/POST | `/api/ai/skills` | 技能列表 / 保存 |
| POST | `/api/ai/skills/<id>/fork` | Fork 内置技能 |
| GET/POST | `/api/ai/plugins` | 插件列表 / 安装 |
| POST | `/api/ai/plugins/<id>/enable` | 启用/禁用 |
| POST | `/api/ai/files` | 上传文件（DeepSeek Files API） |
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
- `tests/api/test_ai_files.py`：上传分片顺序、本地副本、删除、搜索/抓页与凭据 URL 拒绝。
- `tests/api/test_ai_monitors.py`：监控匹配/投递/确认、`run.log` 关键字拒绝、脚本库往返与真实 Python 样本。
- `tests/unit/ai/test_python_node.py`：Python 节点契约、云端拒绝、受限数据读取。
- `tests/unit/frontend/test_frontend_ai_js.py` + `harness_ai.mjs`：真实解码器/渲染器、运行时 chip、禁用原因。

## 11. 未实现

语音输入输出、OCR、后台常驻智能体、代码插件沙箱。以上能力未声明，不在代码中假装存在。
