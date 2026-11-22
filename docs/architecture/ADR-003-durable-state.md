# ADR-003：持久状态机与中断恢复

- 状态：已接受（2026-11-22）
- 相关：[ADR-001](ADR-001-kernel-replacement.md)

## 背景

今天的 AI turn 由 HTTP/SSE 生成器驱动：浏览器断开，生成器就结束，服务端把行标成 `interrupted`；没有 reattach endpoint。待答问题虽然写进了 `questions` 表，但新消息曾经会取消它（H3a 已改为按名拒绝新消息、保留问题可答）；恢复的卡片又因为前端 `messageId` 为空而 404 “找不到消息：”。运行侧已有断点续跑，但状态转换散落在 `engine/run.py` 的 if 里，没有一个可穷举的转换表。

用户要求：关闭面板、切换会话、刷新页面都不影响 AI 工作；待答问题在回答完之前一直存活；每个勾选/状态都有证据。

## 决策

把“有生命周期、会中断、会恢复”的四类对象建模为持久状态机；事件是事实，命令是直接调用。

### 四个状态机

1. **RunFSM**：`queued → starting → running → stopping/settling → completed|failed|interrupted|stopped`
2. **NodeFSM**：`pending → blocked|ready → running → done|partial|failed|skipped|stopped|restored`
3. **TurnFSM**：`new → context → streaming → tool → awaiting_user → streaming → settled|interrupted`
4. **RecipeFSM**：`created → step_1 … step_n → done`；每步要求证据（工具结果 id / 产物 id / 验证通过 id）

视图另有一个小的 **ViewFSM**（closed/docked/full/settings/studio/skills），保证切换面板不销毁对话 DOM。

**不用状态机的地方**：图表构建、分析算子、清洗、验证规则。它们是纯函数或规则流水线；把状态机用到处处是过度设计。

### Turn 与 HTTP/SSE 解耦

1. `POST /api/ai/chat` 只创建 turn 并入队，立刻返回 `turn_id`。
2. 常驻 turn runner 执行 FSM，把每个事件写入 `ai_events`（`seq`）。
3. `GET /api/ai/turns/<id>/events?after=<seq>` 是 SSE 订阅，可随时断开/重连；断开不影响 runner。
4. `answer`/`stop`/`steer` 都是对 runner 的命令，写入命令表并被 runner 消费。
5. 页面刷新/切换会话/关闭面板后，重新订阅从 `after=last_seq` 继续，画面与从未离开一致。

### 中断即 checkpoint

- `ask_user_question` / `request_approval` 是持久 `interrupt`，不是阻塞线程。
- `answer` 只按 `question_id` / `call_id`；`message_id` 由服务端从 question 行派生。
- 新消息进入邮箱：默认“排队下一回合”，另提供“插入指引”在安全边界注入；不再静默取消待答问题。
- 重启后 rehydrate pending interrupts；已过期/已取消的按名回答，不 404。

### P1 落点（2026-11-22）

- `backend/runtime/fsm.py`：`RUN`/`NODE`/`TURN`/`VIEW` 四张固定表 + `recipe_machine(steps)` 参数化表。
  `machine()` 在构造时拒绝“初始即终态/终态有出口/非终态无出口/空状态名”，`require()` 对任何非法移动
  按名拒绝（机器名 + 两端状态）。`tests/unit/foundation/test_fsm.py` 穷举每张表的所有合法与非法状态对。
- `backend/runtime/events.py`：四个运行事件的字段类型契约；`publish()` 先校验再交给
  `runtime/run_events.py` 的进程内总线。`tests/unit/gates/test_event_contract.py` 用 AST 检查现有
  `run_events.publish` 调用点：事件名、字段名、必填字段都必须与契约一致；`ai/monitors.py` 的订阅词汇
  必须等于声明集合。
- 迁移顺序：P4 的 Run/Turn 持久化改用这些表；在那之前，旧引擎的 if 仍跑，但新增状态转换必须先改表。

### Recipe 的勾选

- 每步有 `requires`、`tool`、`args_schema`、`produces`、`check`。
- 工具网关只暴露当前步骤 + 只读证据工具 + 控制工具；跳步按名拒绝。
- 勾选只由服务端证据决定；模型说“完成了”不算。
- 用户可 `recipe_skip`，但记录为“用户跳过”并在最终报告显示。

## 后果

- `backend/ai/agent.py` 的请求生成器要拆成“runner + 订阅”；旧 `/api/ai/chat` 保留兼容层直到 parity。
- 需要 `ai_events`/`pending_calls`/`recipe_runs` 三张表；`store` 要按账号解析路径。
- 事件名要与前端 wire protocol 版本化；框架迁移时不能直接换名。
- 运行侧把 `engine/run.py` 的转换收敛到一张表；每个转换有 guard/effect，测试穷举非法转换。

## 被否决的替代方案

- **把等待问题做成阻塞线程**：进程重启/部署就丢，且无法多标签页。
- **只在前端重连，不持久化**：刷新后仍会 404。
- **用事件总线做控制流**：会变成事件地狱；命令走直接调用，事件只传事实。
