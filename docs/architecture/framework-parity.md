# agent-workspace parity matrix

- 目标：`backend/ai`（采析绘原始实现）迁移到 `agent_workspace`（框架）后，功能只能持平或更强。
- 原则：先补框架通用能力，再做采析绘 host adapter，最后删旧模块；不把领域层塞回框架。
- 依赖：wheel 钉版 + dev editable（框架仓库当前没有 git remote，不能直接 submodule）。

## 框架已经有的（可直接用）

| 能力 | 证据 |
|---|---|
| HostAdapter / DefaultHostAdapter / HostEnvironment | `agent_workspace/host.py` |
| AgentWorkspace 门面（ask/retry/answer/stop/bootstrap/conversations/memories/artifacts/files/scripts/plugins/monitors/usage） | `agent_workspace/service.py` |
| Provider catalog + DeepSeek/Ollama/OpenAI-compatible/OpenRouter/OpenCode Go/offline complete | `agent_workspace/providers/` |
| 一轮多行、tool_use/tool_result 配对、streaming 落盘、interrupted 恢复 | `agent_workspace/agent.py` |
| 轮次持久化：TurnFSM、`turns`/`turn_events`/`turn_commands`/`turn_inbox`、后台 runner + 订阅续传 + 持久 stop | `agent_workspace/fsm.py` / `service.py` / `store.py` |
| 宿主提醒：`turn_finished(summary)`（桌面弹窗/提示音接缝） | `agent_workspace/host.py` / `service.py` |
| 上下文 sources、预算、脱敏、逐轮重放 | `agent_workspace/context.py` |
| 只读工具 + 控制工具 + 审批 + 产物 | `agent_workspace/tools.py` / `agent.py` |
| 声明式插件（skill/provider/tool pack） | `agent_workspace/plugins.py` |
| Flask 适配器（41 路由） | `agent_workspace/adapters/flask.py` |
| 132 个可移植测试（文档写 129） | `tests/` |

## 框架缺的（必须补或留在 host）

| 缺口 | 归属 | 处理 |
|---|---|---|
| `HostAdapter.tools()` 声明了但从未被调用 | 框架 | 上游修：`AgentWorkspace` 初始化时注册 `host.tools()`；host 也可显式 `ws.tools.register()` |
| pending question/approval 只在 `AgentWorkspace.pending` 内存 dict | 框架 | 加 `pending_calls` 表 + 启动 rehydrate；answer 按 `call_id` 幂等 |
| 新 turn 会把未答问题 settle 成 skipped | 框架 | 改成“保留 pending + 新消息进邮箱”；显式 cancel 才取消 |
| retry 不恢复原 turn 的 provider/model/skill/context | 框架 | 从 user 行 meta 恢复，与采析绘 `retry` 对齐 |
| `max_tokens` 默认 0、`fit_history` 预留 2048 | 框架 | 跟随模型窗口/用户设置；0 不再当 2048 |
| 事件名与采析绘不同（`text_delta`/`tool_start` vs `text`/`tool_call`） | 框架 + host | 定义 wire protocol v1，前端适配；不直接换名 |
| 多问题卡（questions 数组，最多 5） | 框架 | 通用 schema；采析绘的 18 个领域技能留在 host |
| plan/build 模式 | 框架 | 通用字段 + 工具遮罩 |
| artifact validators / previews | 框架接口 + host 实现 | 通用 validator 注册；preview 走 Host UI adapter |
| `agent_runs`/`agent_steps` | 框架或 host | 通用 run/step 记录；采析绘的 console 读取保持 |
| 代码插件 / HTTP 工具插件 / UI commands | host | 框架只做声明式；本地代码插件只在桌面/管理员 |
| 监控目录/自动分析/`monitor_events` | host 域层 | 框架只做投递；采析绘保留自己的 monitor catalog |
| 数据集行读取授权（会话/数据集/行数，可撤销） | host + 框架暂停通道 | 采析绘有 `request_dataset_access`、`ai/dataset_access` registry 和侧栏撤销；框架的 ask/approval 通道要能承载“人授权后创建资源”的控制工具，而不是只认 `request_approval` 一个名字 |
| 工作流/导出管理（list/read/update/rename/delete/export/run/stop） | host | 采析绘调用 `WorkflowManager` / `build_bundle` / `engine.run.begin_run/stop_run`；框架的审批策略要能表达“删除永远要人批”，而不是只看全局 auto-approve |
| 能力→AI 入口覆盖矩阵 | host + kernel | 采析绘 `ai.coverage` 从节点/平台/算子/图表/工具注册表生成并门禁；P1 后应由 capability manifest 生成同一张表，框架不维护第二份 |
| 图表必填字段 preflight | host（P3 迁 kernel） | `ChartSpec.fields` 已经是唯一声明（类型/必填/角色/标签），`WorkflowEngine.validate_detailed` 读它，设置面板也按它渲染；P3 继续把“列类型对不上”的样本 preflight 与 `fix` 接到同一引擎 |
| Files API / 附件文本抽取 / 图片内联 / workspace 浏览 / 文件夹选择 | host + 框架 attachment hook | 采析绘 host 侧做本地抽取（pdf/docx/pptx/xlsx/csv/txt/html）并把 `files`/`vision`/`inline_images` 拆成三个独立能力；框架的 attachment hook 必须能接收“已提取文本”，不能只认 file_id |
| 账号级 Python workspace（解释器安装/文件） | host | 采析绘 `services/python_runtime.py` |
| 68 条 HTTP 路由 | host | 采析绘 Flask blueprint；框架 adapter 只做通用 41 条 |
| 前端 210KB + 6 个 `ai/*.js` | 框架 UI 包 | 抽成零构建 custom elements；host 注册预览器 |
| 领域词汇（节点/平台/算子/图表） | host | `vocabulary.py` 由 kernel manifest 生成 |
| 18 个领域技能 + 47 个工具 | host | host adapter 的 `skills()`/`tools()`；不塞回框架 |
| workflow draft / apply / rerun | host | 采析绘工具 + `apply_artifact` |
| codebooks / traces | host | 采析绘服务与路由 |
| 对话区与设置/工作室共用一个列 | host（P5 迁移到框架 UI） | 采析绘现在是 `#ai-chat` 里的两个同级面：`#ai-transcript`（按 turn id 复用）与 `#ai-panel`；框架 UI 必须保留“面板不覆盖转录、转录按 turn_id 复用”的约定，不能回到整段重建 |

## 框架先行（P4.0）：先补齐通用能力，再迁 host

**为什么顺序不能倒。** `agent_workspace` 是从本项目抽取的，抽取时只覆盖当时跑通的路径。采析绘现在的 AI 面
（18 技能 / 47 工具 / 审批 / 数据集授权 / 监控 / 多供应商 / 长会话）比框架宽。先写 `ai_host` 的话，缺的通用能力
只能在 host 里各实现一遍，框架就退回薄壳，下一次改动又出现两份事实。所以 P4 的顺序是
**框架补齐 → host adapter → 薄门面 → 前端**，host 只做领域翻译。

**通用性约束（每条改动都按它审）：**

- 判断标准是“另一个宿主是否也需要”，不是“采析绘现在能不能跑”。
- 节点、平台、算子、图表、数据集、工作流、导出这些事实只允许出现在 `backend/ai_host/`；框架代码里出现这些词
  就是缺陷。
- 框架不 import Flask，也不 import 宿主模块；`HostAdapter` 是唯一的反向注入点。
- 一项能力一个声明点：框架给接口，host 给实现和数据；框架里不得再存一份默认值、选项表或句子。
- 框架自己的测试是这项能力的验收标准；本仓库再加 host 侧 parity 用例，缺一不算完成。

**架构基准（2026-11-23 决定）：保留 `AgentWorkspace` 门面与分层，先做结构化重构，必要时重写单层；不做一次性全量重写。**

```text
domain/          纯类型与端口：Provider / AgentStore / ToolRegistry / EventSink / PolicyEngine / HostAdapter
application/     TurnFSM（持久化状态机）、上下文构建、工具编排与审批策略、产物应用
infrastructure/  SQLite store、供应商传输、Python 脚本运行时
adapters/        HTTP/SSE 绑定（Flask 等），只做序列化
```

- 现在 `store.py`（678 行）/`agent.py`（661 行）/`tools.py`（506 行）把持久化、循环与策略混在一起，pending、
  重试、事件序号散在门面里。把它们拆成“端口 + 适配器 + 显式状态机”是 P4.0 的架构工作。
- 允许“推倒重写”的边界：某一层承载不了所需通用能力时，重写该层并保留同名公开入口；公开 API 变化必须同时改
  host、重建 wheel 并升版本号。
- 禁止的捷径：在 host 里复制 turn 循环、审批或事件序列化。

**P4.0 清单（按依赖顺序，每项都要有框架测试）：**

| # | 通用能力 | 现在 | 验收 |
|---|---|---|---|
| F1 | pending call 持久化 | 只在内存 dict，重启即丢 | `pending_calls` 表 + 启动 rehydrate + `answer(call_id)` 幂等；刷新、切会话后可答 |
| F2 | 提问不被新消息取消 | 新 turn 把未答问题 settle 成 skipped | 未答问题保留，新消息进邮箱逐轮投递；只有显式 cancel 才取消 |
| F3 | retry 还原原轮 | 只重发最后一条用户消息 | 从 user 行 meta 恢复 provider/model/skill/context/attachments，重跑同一轮的后续 |
| F4 | 事件协议 v1 | 事件名与旧前端不同、无序号 | `seq` 单调、`Last-Event-ID` 续传、`tool_start/tool_result` 成对；迁移期旧前端仍能解析 |
| F5 | 后台 turn + 断线恢复 | 跑在请求线程里 | 轮次与 HTTP 请求解耦；重连从 seq 续传；关页不中断 |
| F6 | 审批/权限策略引擎 | 只有全局 auto-approve | 工具声明 permission/destructive；“删除永远要人批”“同参数 once/session”可表达；`request_dataset_access` 这类“先授权再建资源”的控制工具走同一暂停通道 |
| F7 | 限制语义 0=不限 | 0 被当 2048 | 跟随模型窗口与用户设置；usage meter 报真实占用 |
| F8 | 多问题卡 | 单问题 | `questions[]`（≤5）通用 schema，答案按 `call_id` 回填 |
| F9 | plan/build 模式 | 无 | 通用字段 + 工具遮罩，host 只提供模式文案 |
| F10 | attachment 接缝 | 只认 file_id | 接收“已抽取文本 + 内联图片”两路；`files`/`vision`/`inline_images` 是三个独立能力 |
| F11 | 产物 validator/preview 注册 | 无 | 通用注册表；preview 由 Host UI adapter 实现；无 validator 的产物按名拒绝或降级为纯文本 |
| F12 | run/step 记录 + 恢复 | 无 | `agent_runs`/`agent_steps`；崩溃按状态机恢复；同一 `tool_use` 不重复执行 |
| F13 | 工具/技能注册收口 | `host.tools()` 声明了却从未被调用 | 初始化即注册；id 冲突按名拒绝；技能按白名单过滤工具 |
| F14 | trace/观测 | 无 | OTel GenAI 语义的 trace 表 + trace 树；事件只含 id/状态/计数 |
| F15 | 结构化输出 / thinking 控制 | 部分 | 能力声明 + 不支持按名拒绝；Ollama `think:false` 保持 |
| F16 | 并发 | 串行 | LLM 行任务可并发、按供应商限流；一轮内工具调用仍有序 |
| F17 | 轮次完成通知接缝 | 无 | `HostAdapter.turn_finished(summary)`：每次 `ask()` 结束后一次，`completed`/`paused`/`cancelled`/`error`/`aborted` + ≤240 字预览；宿主决定桌面弹窗/提示音，异常不打断轮次 |
| F18 | 命令与上下文压缩 | 无 | 通用命令注册表；框架提供 `/status` `/skills` `/mode` `/compact`，`/init` 等认识宿主项目的命令由 host 注册 |

F1–F5 是“不修就要带病迁移”的前置项；F6–F16、F18 在写 host adapter 前完成；F17 已与 host 并行落地。

**归类标准（决定一项 P4 要求放 P4.0 还是接入）**：换一个宿主是否也需要？是 → 框架（回合、事件、策略、限制、
命令、attachment 接缝、产物校验、run/step、trace、供应商能力、并发）；否 → host（节点/数据集/工作流/图表/平台/
账号/本地文件/UI，以及旧前端事件名映射）。

### ADR-003 的硬性要求（P4.0 必须兑现）

[ADR-003](ADR-003-durable-state.md) 把“关闭面板 / 切换会话 / 刷新 / 重启都不影响 AI 工作”定成持久状态机。
框架侧的实现口径如下，一项都不能漏：

| ADR 要求 | 框架落点 | 验收 |
|---|---|---|
| **TurnFSM**：`new → context → streaming → tool → awaiting_user → streaming → settled\|interrupted` | `agent_workspace/fsm.py`：通用 `machine()`/`require()`，非法移动按机器名 + 两端状态拒绝 | 穷举每张表所有合法与非法转换 |
| **turn 与 HTTP/SSE 解耦**：POST 建 turn 即返回 `turn_id`；常驻 runner 执行；SSE 只是订阅 | `ai_turns` 行 + `TurnRunner`；`ask()` = 建 turn + 订阅 | 断开订阅后 runner 继续跑完并写事件 |
| **事件是事实，命令是直接调用**：`answer`/`stop`/`steer` 写 `turn_commands`，runner 在安全边界消费 | `ai_events(seq)` + `turn_commands` | 重连 `after=seq` 不缺不重；命令不经过事件总线 |
| **中断即 checkpoint**：`ask_user_question`/`request_approval` 是持久 interrupt | `pending_calls` 表 + 启动 rehydrate；`answer` 只按 `call_id`，服务端派生 `message_id` | 重启、刷新、切会话后仍可答；重复答案按名拒绝 |
| **新消息进邮箱**：默认“排队下一回合”；“插入指引”只在安全边界注入；不再静默取消待答问题 | `turn_inbox` + runner 安全边界 | 待答期间发消息不丢、不取消问题，答完后按序执行 |
| **事件协议版本化**：迁移期不能直接换名 | `EVENT_PROTOCOL = 1`；事件带 `v`/`seq`；旧前端可解析 | wire 契约测试 |
| **RecipeFSM**：每步要求证据（工具结果 / 产物 / 验证通过 id），跳步按名拒绝 | `recipe_runs` + 证据表（P6 使用） | 勾选只由服务端证据决定 |

P4.0 的第一片就是表中前四行：`fsm.py` + `turns`/`turn_events`/`pending_calls`，随后是 runner、命令与邮箱。

**进度（2026-11-23，框架 0.1.18）**：**P4.0 全部完成**（F1–F18）。P4 接入进行中：`ai_host` 的 facts/tools/skills/
artifact validators 已委托，`/api/ai/ws` 蓝图已建（待注册与 parity）。

## 依赖与钉版

- 框架没有 index 发布：`vendor/agent_workspace-<version>-py3-none-any.whl` 是钉版产物，`requirements.txt`
  用仓库根相对路径引用它。相对路径按**工作目录**解析，所以 `pip install -r requirements.txt` 必须从仓库根运行；
  CI 如此，`deploy/Dockerfile` 也把 `requirements.txt` 和 `vendor/` 一起复制到 `/app` 后从那里安装。
- 开发用框架检出：`pip install -e <framework checkout>` 在该 venv 里盖过 wheel；提交前以 wheel 为准。
- 升版流程：框架改动 → 框架测试全绿 → 重建 wheel → **替换**同一文件（不新增第二个）→ 更新
  `vendor/README.md` 的 sha256 → 本仓库重跑 AI 相关测试 → 提交。
- 门禁 `tests/unit/gates/test_requirements_pinned.py` 保证文件名、METADATA 与声明三者一致，拒绝目录里未声明的
  wheel，也拒绝同一发行版再被 `name==version` 钉一次。

## 迁移顺序

0. **P4.0 框架完善**（见上）：F1–F16 与架构拆分在框架仓库完成，框架测试全绿、重建 wheel；host 不复制引擎。
1. 框架通用修复（已并入 P4.0 的 F1–F4；这里保留原来的表述作为验收口径）。
2. `backend/ai_host/`：facts/sources/tools/skills/resolvers/artifacts/UI adapter。
3. `backend/api/ai.py` 改为 `AgentWorkspace` 的薄 HTTP/SSE 适配；旧 `backend/ai` 在切换期只做转发。
4. parity matrix 全绿；删旧引擎模块；保留采析绘域工具/技能/路由。
5. 前端切到框架 UI；旧 `ai-workspace.js` 删除或只留适配。

## 验收

- 旧功能 × 新框架测试：没有空单元格。
- 新框架的 pending question 在重启、刷新、切会话后仍可回答。
- 事件 wire protocol 有版本号；旧前端在迁移期仍能解析。
- `grep -R "from ai import" backend` 只出现在 host/兼容层，不再出现在框架代码。
