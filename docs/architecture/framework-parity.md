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
| Files API / workspace 浏览 / 文件夹选择 | host | 采析绘工具；框架提供 attachment hook |
| 账号级 Python workspace（解释器安装/文件） | host | 采析绘 `services/python_runtime.py` |
| 68 条 HTTP 路由 | host | 采析绘 Flask blueprint；框架 adapter 只做通用 41 条 |
| 前端 210KB + 6 个 `ai/*.js` | 框架 UI 包 | 抽成零构建 custom elements；host 注册预览器 |
| 领域词汇（节点/平台/算子/图表） | host | `vocabulary.py` 由 kernel manifest 生成 |
| 18 个领域技能 + 47 个工具 | host | host adapter 的 `skills()`/`tools()`；不塞回框架 |
| workflow draft / apply / rerun | host | 采析绘工具 + `apply_artifact` |
| codebooks / traces | host | 采析绘服务与路由 |

## 迁移顺序

1. 框架通用修复（pending 持久化、retry、event 协议、validator 接口、host.tools、max_tokens）。
2. `backend/ai_host/`：facts/sources/tools/skills/resolvers/artifacts/UI adapter。
3. `backend/api/ai.py` 改为 `AgentWorkspace` 的薄 HTTP/SSE 适配；旧 `backend/ai` 保留兼容层。
4. parity matrix 全绿；删旧引擎模块；保留采析绘域工具/技能/路由。
5. 前端切到框架 UI；旧 `ai-workspace.js` 删除或只留适配。

## 验收

- 旧功能 × 新框架测试：没有空单元格。
- 新框架的 pending question 在重启、刷新、切会话后仍可回答。
- 事件 wire protocol 有版本号；旧前端在迁移期仍能解析。
- `grep -R "from ai import" backend` 只出现在 host/兼容层，不再出现在框架代码。
