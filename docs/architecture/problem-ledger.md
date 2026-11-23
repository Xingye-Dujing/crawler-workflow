# 问题台账

- 状态标记：`已修` / `进行中` / `待办` / `待决策`
- 归类：`D` 直接热修（与架构迁移低耦合）、`R` 由重构解决、`Q` 需要拍板
- 方案：见 [ADR-001](ADR-001-kernel-replacement.md) / [ADR-002](ADR-002-capability-manifest.md) / [ADR-003](ADR-003-durable-state.md)

## 已修

| ID | 问题 | 归类 | 机制 | 证据 |
|---|---|---|---|---|
| H2 | 重开/切换会话后回答待答问题报“找不到消息：” | D | answer 只按 `question_id`；服务端从 question 行派生 `message_id`；前端恢复卡也写 `messageId` | `backend/api/ai.py`、`backend/ai/agent.py`、`tests/api/test_ai_workflow.py` |
| H2b | 多选问题只改 CSS、永远提交不了 | D | `_answerOption` 把选中项写入 `answers`；提交仍由卡片按钮触发 | `ai-workspace.js`、`tests/unit/frontend/test_frontend_ai_js.py` |
| H1 | 本地 Ollama 仍会出现思考 | D | 两条路径强制 `think:false`；忽略 `thinking` 字段；剥离 `<think>` 标签；UI 开关禁用 | `ai/providers/ollama.py`、`ai/agent.py`、`tests/unit/ai/test_ollama_transport.py` |
| H3a | 新消息会取消同会话待答问题 | D | 新消息在有待答问题时按名拒绝，不取消；问题仍可回答。邮箱/插话在 P4 | `ai/agent.py`、`tests/api/test_ai_workflow.py` |
| H4/H5 | 侧栏缩到最小拉不大、流式滚动跳回开头 | D | 按实测宽度切换 `.narrow`；列宽随 dock 夹紧；12px grip + pointer capture；重绘前保存并恢复 `scrollTop` | `ai-workspace.js`、`ai.css`、`tests/unit/frontend/test_frontend_ai_js.py` |
| H8 | Python 节点卡片空白、标题显示 Node | D | `getNodeSummary('python')` 显示脚本/参数；标题 map 补 `python`/`fuse` | `canvas.js`、`tests/unit/frontend/test_frontend_fuse_panel_js.py` |
| H9 | AI 输出/工具结果/回合/表格读取限制过小 | D | 输出 32768 且可配；工具结果/重放 0=不限；回合默认 0；表格单页 2000；问题 10；引用/记忆放大 | `agent.py`、`settings_schema.py`、`context.py`、`tools.py`、`tests/unit/ai/` |
| H10 | LLM 行任务没有可用的并发设置 | D | 设置面板新增 `workers`（1-8）；API 供应商并行；Ollama 强制串行 | `llm-settings.js`、`index.html`、`llm_client.py`、`tests/integration/test_llm_client_mock.py` |
| H11 | 无文件 API 的模型不能收附件 | D | 服务端抽取 pdf/docx/pptx/xlsx/csv/txt/html 并缓存；`files`/`vision`/`inline_images` 三能力拆分；图片可内联；旧 `.doc/.ppt` 按名拒绝 | `ai/file_text.py`、`ai/agent.py`、`ai/providers/`、`api/ai.py`、`tests/unit/ai/test_file_text.py`、`tests/api/test_ai_workflow.py` |
| H12 | 表格读取没有临时授权 | D | `request_dataset_access` 走同一个暂停/恢复问题通道；grant 按会话+数据集+行数，进程内可撤销；`dataset_page`/`dataset_sample`/筛选查询累计行数；`dataset_peek` 免费 5 行；侧栏列出授权并可撤销 | `ai/dataset_access.py`、`ai/agent.py`、`ai/tools.py`、`api/ai.py`、`ai-workspace.js`、`tests/unit/ai/test_dataset_access.py`、`tests/api/test_ai_workflow.py` |
| H13 | AI 不能管理工作流/产物 | D | `workflow_list/read/update/rename/delete/export/run/stop` + `export_list/delete`；全部走 `WorkflowManager`/`engine.run`/`build_bundle`/`services.exports`；删除（工作流与导出）绕过 `ai_auto_approve` 强制审批并写审计日志；停止与 HTTP 按钮共用 `engine.run.stop_run` | `ai/tools.py`、`engine/run.py`、`api/workflow.py`、`services/exports/writer.py`、`tests/unit/ai/test_workflow_admin.py` |
| H14 | 工具覆盖没有审计 | D | `ai.coverage.audit()` 从节点/平台模式/算子/图表/工具注册表生成矩阵；`UNIVERSAL_TOOLS` + `FILE_TOOLS` 是唯一入口集合；`ai_coverage` 工具可读；门禁拒绝空格子 | `ai/coverage.py`、`ai/agent.py`、`ai/tools.py`、`tests/unit/gates/test_ai_coverage.py` |
| H16 | 占比堆叠图运行才报错 | D | `ChartSpec.fields` 声明 `stack_fields`（以及每种图型的全部必填字段），`WorkflowEngine.validate_detailed` 读该声明并在 validate 阶段命名缺字段；默认值先填充，填了就不报；P3 起设置面板也按同一份声明画框 | `services/charts/registry.py`、`nodes/executors/visualize.py`、`engine/workflow.py`、`tests/unit/charts/test_chart_registry.py` |
| H17 | 关技能面板后答案消失 | D | `#ai-chat` 拆成两个同级面：`#ai-transcript` 与 `#ai-panel`；设置/工作室只渲染 panel 并隐藏转录（不覆盖），关闭时原 DOM 直接拿回；回来经 `selectConversation` 重读 pending，卡片挂回提问那一轮 | `index.html`、`ai.css`、`ai-workspace.js`、`ai/studio.js`、`tests/integration/test_ui_layout.py`、`tests/unit/frontend/test_frontend_ai_js.py` |
| H18 | 切会话又开一个消息区 | D | `_renderMessages` 按 `turn:<turn_id>` / `message:<id>` / `row:<id>` 协调复用节点，不再整段重建；流式气泡带同一 key，重绘与 A→B→A 都复用它；回到仍在流式的会话时把存储的轮次元素接管为 live，下一条 delta 写入同一气泡 | `ai-workspace.js`、`tests/frontend/harness_ai_workspace.mjs`、`tests/frontend/harness_dom.mjs`、`tests/unit/frontend/test_frontend_ai_js.py`、`tests/integration/test_ui_layout.py` |

## 待办（热修列车，按优先级）

| ID | 问题 | 归类 | 机制 | 验收 |
|---|---|---|---|---|
| H3 | 新消息会取消同会话待答问题 | D/R | 新消息进邮箱；待答问题保留；显式取消才取消 | 发送新消息后仍能回答旧问题 |
| H4 | 侧栏缩到最小后无法拉大 | D | 持久 grip + pointer capture + 键盘；按实测宽度切换 `.narrow`；夹子与 dock 宽度联动 | 浏览器测试：缩到最小→拉大 |
| H5 | 流式输出滚动跳回开头 | D/R | append-only + 稳定锚点 + `stickToBottom`；`_renderMessages` 不再无条件滚底 | 上滚后流式追加不跳 |
| H6 | 回答/提问卡堆到最后 | D | 按 `tool_call_id` 原位回填；多选/自定义答案都走同一状态 | 回答出现在提问卡处 |
| H7 | 会话置顶/归档不即时刷新 | D | 事件驱动刷新，不靠重开面板 | 操作后列表立刻变 |
| H8 | Python 节点面板空白 | D | 脚本名/描述/参数 schema/解释器/上次运行信息卡 | 空态有引导，选中后有摘要 |
| H9 | AI 限制过小 | D | 0=不限；输出跟随模型；工具结果/回合/上下文可调 | 设置默认不限制，截断有报告 |
| H10 | LLM 行任务不能并发 | D | `workers` 设置 + 节点覆盖 + 退避；API 4 / Ollama 1 | 并发设置生效，结果顺序正确 |
| H11 | 无文件 API 的模型不能收附件 | D | pdf/docx/xlsx/csv/txt/html → text；`files` 与 `vision` 解耦 | 本地模型可读附件文本 |
| H12 | 表格只能读 50 行 | D | `request_dataset_access` + 会话/数据集/行数 grant + revoke | 授权后可读，全局设置不变 |
| H13 | AI 不能删工作流/产物 | D | 领域工具 list/read/create/update/delete/rename/export/run/stop；走服务不走裸文件系统；删除需审批+审计 | 工具可用，越权拒绝 |
| H14 | 工具缺一堆 | D | 能力→工具覆盖门禁；按清单补 | 每个能力至少一个入口 |
| H15 | 重试可能重发用户消息 | D | 复用同一 user 行；恢复原 turn 的 provider/model/skill/context | 只重跑同一 turn |
| H16 | 占比堆叠图运行才报错 | D/R | 临时验证规则 + P3 图表契约/preflight | validate 阶段命名 `stack_fields` |
| H17 | 关技能面板后答案消失 | D/R | 设置/工作室不再覆盖 `#ai-chat`；回来重新拉 pending；live DOM 保留 | 关闭/打开后答案与卡片都在 |
| H18 | 切会话又开一个消息区 | D/R | 单实例 + 按 `turn_id`/`id` 复用，不整段重建 | A→B→A 只有一个消息区 |
| H21 | 只有 `@` 消息被拒 | D | 框架允许空正文 + 结构化 references；产品前端也按 refs 放行；展开文本进 user 行 | `@skill`/`@dataset` 可直接发送（`tests/test_references.py::test_a_message_may_carry_only_references`） |
| H19 | 重试实时/刷新两种气泡 | D | 都按 `turn_id` 合并，不拼接两次回答 | 实时与刷新一致 |
| H20 | 工具结果无限存进 SQLite | D | `agent_steps.result` 也走截断/分页 | 大结果不写满库 |
| H22 | 非管理员改 scope 静默失败 | D | 前端显示“仅管理员可改”或改 per-conversation | 不再静默 |
| H23 | 限制不可见 | D | dock 显示当前回合/结果/上下文上限，可跳设置 | 用户知道当前值 |

## 由重构解决（不在旧代码上打补丁）

| ID | 问题 | 机制 |
|---|---|---|
| R1 | 新增节点要改 14 处、漏 20 处 | Manifest + Registry + Generator + Doctor |
| R2 | 前后端两套验证 | 服务端唯一验证引擎；前端只渲染 |
| R3 | 18 个大领域技能，节点用法缺失 | 一能力一技能 + 三级渐进披露 |
| R4 | 47 个工具平铺，未来几百个 | L1/L2/L3 分层 + 工具遮罩 + 每轮预算 |
| R5 | 没有结构化输出强制 | provider 能力 + json_schema/grammar + 修复循环 |
| R6 | AI 工作区复制框架 | 依赖 agent-workspace + host adapter + parity |
| R7 | AI 前端 210KB 单体 | 框架 UI + custom elements + host adapter |
| R8 | 测试矩阵手写、过重 | 生成式契约 + 性质测试 + 删除重复 |
| R9 | 运行/回合状态散落 | Run/Turn/Recipe/View FSM + 事件日志 |
| R10 | 节点输出没有资产身份 | Asset + lineage + schema_hash |

## 待决策

见 [rewrite-plan.md](rewrite-plan.md#已确认的决策)。10 项已于 2026-11-22 按推荐确认；如复议，在此记录。
