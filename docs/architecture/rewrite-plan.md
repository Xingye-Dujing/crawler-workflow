# 实施计划（Workbuddy 勾选）

> 勾选规则：一个框只有在“代码 + 测试 + 文档/技能 + 门禁 + 收口”全部通过后才能打勾；否则保持 `[ ]`。
> 每个阶段结束跑一次 closure gate。工期按“熟悉仓库的开发者 + AI 辅助”估算：P0-P9 约 14-20 周纯开发。

## 硬性工程约束：不留残骸

**重构/迁移完成后，旧实现必须删除，不保留“兼容层”。** 只留当前真正在用的代码与文件：

- 一个事实只允许一处声明。第二次出现的默认值、选项表、验证分支、格式化句子都是待删项，不是待同步项。
- 迁移完成即删：旧函数、旧分支、旧的转发别名、只为旧路径存在的测试、没人 import 的模块文件。
- **不写 “暂时保留 / 以后可能用 / 兼容旧调用” 的代码。** 仓库里没有外部消费者，兼容性不是理由。
- 每个切片的收口检查包含一次“本片是否新增了重复”：grep 新名字的所有旧落点、删除无用 import/常量/文件、跑 `ruff`（F401/F811）并人工确认新文件都有引用者。
- 发现历史遗留的死代码（定义后无人调用/无人 import 的模块）就顺手删除，并在提交信息里写明；不要让它继续留到下一片。

## 已确认的决策

2026-11-22 已确认，全部采用推荐项：

| # | 决策 | 选择 |
|---|---|---|
| 1 | 重写策略 | 内核替换 + 逐域迁移 |
| 2 | agent-workspace 依赖 | wheel 钉版 + dev editable |
| 3 | “消除限制”语义 | 0=不限，模型/供应商上限为准 |
| 4 | 表格读取授权 | 按会话/数据集/行数临时授权 |
| 5 | 运行中发消息 | 排队下一回合 + 插入指引 |
| 6 | 测试瘦身 | 只删重复/实现细节，矩阵生成化 |
| 7 | 技能粒度 | 每节点 + 每算子/图表/平台模式 |
| 8 | 架构技能/知名 Agent | 自研 5 个架构技能 + 只读研究，不 vendor |
| 9 | 严格模式默认 | 本地小模型自动严格，强模型普通 |
| 10 | 并发范围 | 仅 LLM 行任务 |

## P0 基线 + 热修列车（进行中）

- [x] 基线：记录 fast 测试数与耗时（见 `docs/architecture/baseline.md`）
- [x] 能力清单：16 节点/38 算子/30 图表/11 平台/47 工具/18 技能
- [x] 问题台账：[problem-ledger.md](problem-ledger.md)
- [x] ADR-001/002/003
- [x] H1 Ollama 不思考
- [x] H2 待答问题按 question_id 恢复 + 多选答案
- [x] H3a 新消息不取消待答问题（按名拒绝；邮箱在 P4）
- [ ] H3b 同会话邮箱：排队下一回合 + 插入指引（P4）
- [x] H4 侧栏最小宽度（实测宽度 + 列宽夹紧 + pointer capture）
- [x] H5 流式滚动（重绘前后恢复 scrollTop）
- [ ] H6 原位回答
- [ ] H7 置顶/归档即时刷新
- [x] H8 Python 节点信息卡（脚本/参数/空态）
- [x] H9 限制默认值（0=不限、输出 32k、表格单页 2k）
- [x] H10 并发 workers（面板 1-8；API 并行；Ollama 串行）
- [x] H11 附件文本抽取（pdf/docx/pptx/xlsx/csv/txt/html；files/vision/inline_images 拆分）
- [x] H12 数据读取授权（会话/数据集/行数 grant；peek 免费；可撤销）
- [x] H13 工作流/产物工具（list/read/update/rename/delete/export/run/stop；删除强制审批+审计）
- [x] H14 工具覆盖审计（能力矩阵 + `ai_coverage` 工具 + 门禁）
- [ ] H15 重试 parity
- [x] H16 stack_pct 验证（`ChartSpec.fields` → validate 阶段命名）
- [x] H17/H18 视图单实例（转录/面板两个面；按 turn_id 复用节点）
- [ ] H19 重试气泡
- [ ] H20 工具结果上限
- [ ] H21 @-only 消息
- [ ] H22 scope 静默失败
- [ ] H23 限制可见
- **DoD**：每个 H 有回归测试；fast + ruff + pylint 绿；无 `data/`/`logs/` 写入。

## P1 内核骨架（1-2 周）

- [x] `capabilities_kernel/` manifest dataclasses + JSON Schema 子集
- [x] registry 自动发现/去重/懒加载
- [x] `tools/gen_capabilities.py` 生成 5 类产物
- [x] `tools/doctor.py` 逐项勾选
- [x] `runtime/fsm.py` + 转换表测试
- [x] `runtime/events.py` + 契约测试
- [x] `services/validation/engine.py` 骨架 + static 规则
- [x] pilot：`tokenize` 节点全链路迁移（服务端；前端表单/if 链在 P2）
- [x] 生成物 freshness gate
- [x] `runtime/flags.py` 迁移开关 + 到期门禁
- [x] manifest `api_version`/`manifest_hash` + 兼容检查
- [x] Asset 数据模型骨架
- **DoD**：tokenize 只改一个清单目录即可工作；doctor 全绿；旧路径仍绿；无行为变化。

## P2 节点内核全量（2-3 周）

- [x] 16 个节点逐个迁移（`tokenize` pilot + 其余 15 个，含 `source` 的矩阵校验）
- [x] schema 表单渲染器 + custom renderer 注册表（`panels/settings.js` 只做一次 `ui` 分派）
- [x] 删除 `canvas.js` 的节点默认参数/类型表；表单分派由清单 `ui` 选择
- [x] 删除前端验证 if 链；接 `/api/workflow/validate`
- [x] `/api/node-types` 返回完整清单；`node-types.js` 只做冷启动 fallback
- [x] 每节点技能骨架 + 示例 + 工具生成（清单第七段；`knowledge.py` 投影 L1/L2，生成 `docs/capabilities/skills/`）
- [ ] 每节点声明 `emit`/`read` 契约与 `schema_hash`
- [ ] 每节点输出物化为 Asset
- [ ] 完整性门禁全绿
- **DoD**：新增一个节点只加一个清单目录；其它文件 0 改动；全部节点 doctor 绿；fast+device 绿。

## P3 验证完整化（1-2 周，与 P2 交叠）

- [x] 30 个图表契约 required/type/preflight/fix（`ChartSpec.fields` 的必填与角色、`chart_preflight`、`fix`）
- [x] stack_pct/stack_fields、pie/value、heatmap/xy、sankey/source-target、biblio reads
- [x] 样本 preflight：每节点可选 hook；上游取样 ≤200 行；缓存
- [x] 验证结果含 fix；UI 一键修复；AI 工具同一引擎
- [x] 删除临时热修规则（H16）
- [x] 数据契约：生产者 `schema_hash` × 消费者 `read_columns` 对齐
- [x] 运行后数据质量断言（可选 hook）
- [x] 验证矩阵：每个图表 × 缺参/错类型/空数据/正常（空数据=无样本，不下结论）
- **DoD**：所有“运行才知道”的已知错误在 validate 阶段被命名；无前端第二套规则。

## P4 AI 框架完善与接入（3-4 周；先补框架，再迁 host）

> 2026-11-23 追加约束：框架可能还不完善，**先按通用标准把框架补到能承载采析绘的全部 AI 功能**，再做 host
> adapter。框架必须保持宿主无关、可扩展；不为采析绘在框架里加领域分支。允许重构框架，必要时重写单层。清单与
> 验收见 [framework-parity.md](framework-parity.md#框架先行p40先补齐通用能力再迁-host)。

**归类标准（决定一项工作属于 P4.0 还是 P4 接入）**：换一个宿主是否也需要？

- **是 → P4.0 框架完善**：回合生命周期、事件协议、审批/权限策略、限制语义、命令与压缩、attachment 接缝、
  产物校验接缝、run/step 记录、trace、供应商能力、并发、通知接缝。
- **否 → P4 接入**：只依赖采析绘的节点/数据集/工作流/图表/平台/账号/本地文件/UI 的部分。宿主侧只做“翻译与注册”，
  不复制框架的引擎逻辑。

### P4.0 框架完善（先行）

**已完成（框架 0.1.4）**

- [x] wheel 钉版、CI 安装、dev editable（`vendor/README.md`）
- [x] **TurnFSM**：`agent_workspace/fsm.py`，非法转换按名拒绝（0.1.2）
- [x] **持久事件**：`turns`/`turn_events`（`seq` 单调、`v=EVENT_PROTOCOL`），`subscribe(after)` 与
  `/turns/<id>/events`（`after`/`Last-Event-ID`）续传（0.1.2/0.1.3）
- [x] **turn 与 HTTP/SSE 解耦**：后台 runner，关流/刷新/切会话不停轮（0.1.3）
- [x] **持久中断**：`pending_calls` + 重启 rehydrate；`answer` 按 `call_id` 幂等并复用原 turn（0.1.2）
- [x] **stop 命令**：`turn_commands` 持久，runner 在安全边界取走（0.1.3）
- [x] **邮箱**：待答期间的新消息排队，带 `mailbox_id` 再发才执行，Key 不入队（0.1.4）
- [x] **重启恢复**：半途 turn 收尾 `interrupted`，`awaiting_user` 保留（0.1.2）
- [x] **完成通知**：`HostAdapter.turn_finished(summary)`，弹窗/提示音由宿主决定（0.1.1）
- [x] **线程账号绑定**：`HostAdapter.bind_account()`，runner 启动即绑定（0.1.3）

**待框架实现（按依赖顺序）**

- [x] **steer**：运行中插入指引只在安全边界注入——`steer()` 写 `turn_commands`，runner 在两轮之间把指引作为
  `user` 行加入本轮并发 `steer` 事件；最后边界之后到达的指引进邮箱作为下一轮（框架 0.1.5）
- [x] **F6 权限/审批策略引擎**：`ToolSpec.always_ask` + `policy.PolicyEngine`；`mutating` 在 auto 关闭时确认，
  `always_ask`（删除/覆盖/资源授权）永远确认且不接受 session 授权（框架 0.1.6）
- [x] **F7 限制语义 0=不限 + usage meter**：`context.max_chars`/`replay_chars`/两类 token 预算取 0 不设框架上限；
  `max_tokens=0` 不下发；usage 由框架按真实 token 记录（框架 0.1.18）
- [x] **F12 工具步骤记录 + 幂等**：`agent_steps`（调用前 `running`、结束 `done`/`error` + 结果）；同一
  `(turn_id, call_id)` 重放不重跑；崩溃遗留的 `running` 启动时标 `interrupted` 且不再执行（框架 0.1.7）
- [x] **F13 注册收口**：`HostAdapter.tools()` 在构造时注册；与内置/控制/宿主工具重名按 `tool.builtinConflict`
  拒绝；技能白名单仍过滤工具（框架 0.1.8）
- [x] **F8 多问题卡**：`ask_user_question` 接受 `questions[]`（1–5），一张卡一次答复；答案按同一 `call_id`
  回填并与问题对齐；畸形/超限返回 `badArgs` 且写入结果；单问题旧形状兼容（框架 0.1.9）
- [x] **F9 plan/build 模式**：`context_payload.agent_mode`；plan 把写入/`always_ask` 工具从 schema 与允许列表一起
  移除（执行处再次拒绝），meta 带 `mode`；未知模式按 `mode.unknown` 拒绝（框架 0.1.10）
- [x] **F10 attachment 接缝**：`context_payload['attachments']` 收“已抽取文本 + 内联图片”；文本随 user 行持久化，
  图片仅在 `vision`+`inline_images` 时以内联部件发送，否则按名拒绝；host 负责抽取（框架 0.1.12）
- [x] **F11 产物 validator/preview 注册**：`HostAdapter.artifact_validators()/artifact_previews()`；提案与 apply 各
  校验一次，失败按 `artifact.invalid` 拒绝；未声明 kind 标记 `unvalidated`；预览失败不影响呈现（框架 0.1.13）
- [x] **F14 OTel GenAI trace**：`agent_traces`（provider/工具 span，`gen_ai.*` 属性、状态、耗时）；工具挂在发起它的
  provider span 下；`traces`/`trace_tree`/`/turns/<id>/trace`；写入 best-effort，无正文（框架 0.1.14）
- [x] **F15 供应商能力**：`structured_output` 能力 + `ChatRequest.output_schema`；OpenAI 兼容传输映射
  `response_format`，未声明按 `capability.refused` 拒绝；`thinking` 同规则；Ollama 的 `think:false` 保持（框架 0.1.15）
- [x] **F16 LLM 行任务并发**：`chat_once` 按供应商信号量限流（`max_parallel` → 设置 `providers.max_parallel`），
  `local_only` 固定串行；轮次工具调用仍有序（框架 0.1.16）
- [x] **F18 命令与压缩**：`CommandRegistry` + `/status` `/skills` `/mode` `/compact`；`/mode` 写会话偏好、下一轮
  生效；`/compact` 清旧 user 行的 `context_text`（不改写转录）；宿主经 `HostAdapter.commands()` 注册 `/init`
  等（重名按 `command.duplicate` 拒绝）（框架 0.1.17）
- [x] **F3 retry 还原原轮**：从 user 行所属 turn 恢复 provider/model/skill，复用该行已存的上下文块（不重读实时
  sources）；不新增 user 行（框架 0.1.11）
- [ ] **RecipeFSM**：`recipe_runs` + 每步证据（P6 使用）——框架
- [ ] **架构收口**：端口/适配器/`TurnFSM` 拆分（`store.py`/`agent.py`/`tools.py` 减重）
- [ ] **通用性门禁**：框架仓库内不出现采析绘领域词；宿主只经 `HostAdapter` 注入

- **DoD**：上述全绿；本仓库 parity 矩阵每行有等价测试；host 只用框架公开 API，不复制 turn 循环/审批/事件序列化。

### P4 接入（只做采析绘的领域翻译与注册）

- [x] `backend/ai_host/` HostAdapter：facts/tools/skills/artifact validators/settings/commands/附件/
  环境/搜索抓取/导入/脚本库/Python 运行器/事件总线/语言与账号绑定
- [x] `backend/api/ai_workspace.py`：`/api/ai/ws` 是唯一的 AI 表面（旧 `api/ai.py` 已删除）
- [x] 领域技能与工具迁移（18 技能 / 47 工具）、工作流/产物工具、源码阅读工具
- [x] **本地附件抽取**（pdf/docx/pptx/xlsx/csv/txt/html）与图片内联数据；框架只收结果
- [x] **限制设置迁移**：采析绘设置经 `config.LEGACY_KEYS` 映射到框架的 0=不限语义
- [x] **`/init` 等宿主命令注册**；框架的 `/status` `/skills` `/mode` `/compact` 由框架提供
- [x] parity matrix：每个旧功能在新框架有等价/更强测试（见 framework-parity.md 的残留项）
- [x] 双路径开关已随旧引擎删除（`runtime/flags.py` 目前没有在途开关）
- [x] `backend/ai/` 只剩领域模块：provider/context/skills/tools/validators/previews/vocabulary/
  workflow_draft/workspace/monitors/file_text/dataset_access/files/errors/types/scopes/environment
- **DoD**：旧 AI 功能全部在新框架跑通；旧 `backend/ai` 无回合引擎/存储/审批/插件宿主；
  AI 会话关闭/切换不中断；question 不再“找不到消息”。

> 归属备忘：`answer` 用框架的 `call_id`；旧前端的 `question_id`/`message_id` 派生是**host 的 HTTP 层**职责。
> 事件名与前端 wire protocol 的映射也放 host（框架只保证 `EVENT_PROTOCOL` 版本与 `seq`）。

## P5 前端（已按“切换现有页面”完成，不做框架自带前端）

- [x] `ai-workspace.js` 全部请求切到 `/api/ai/ws`；`ai/studio.js`、`ai/watch.js`、`llm-settings.js`、
  `panels/node-python.js`、`workflow.js` 同步切换（前端不再调用 `/api/ai/*`）
- [x] host 边缘做 wire 映射（`text_delta→text`、`thinking_delta→thinking`、`tool_*`、`citation`）
- [x] 实机浏览器用例：本地模型真实回答 + 实时行 + 停止
- [x] 监视器：宿主事件总线把 `runtime.run_events` 映射给框架，交付行回填会话/运行事实
- [ ] 框架自带 `agent_workspace/web/` 壳与 custom elements（**已决定不做**：保留采析绘自己的
  零构建前端，只换后端表面；见 `docs/architecture/rewrite-plan.md#已确认的决策`）
- **DoD**：前端功能 parity；旧 API 删除后页面无失效入口（本轮已达成，监视器/工作文件夹/附件/Python
  面板均走同一表面）。

> 2026-11-23 方向调整：**保留现有前端，仅切换 API 表面**。原计划的“替换右侧 dock / 删旧 UI”
> 不再执行；对应事项视为关闭。

## P6 技能/工具/小模型（2-3 周）

- [x] L1/L2 分类 + 目录生成（16 个节点技能：清单第七段七段内容；`skill_catalog`/`skill_load`；生成页面有 freshness 门禁）
- [x] 每节点/算子/图表/平台技能七段内容（16 节点、37 算子、30 图表、10 平台，全部由各自清单生成）
- [x] catalog/search/load/read + @（`skill_catalog`/`skill_load` + `@` 引用：技能/数据集/运行/工作流/导出/文件/产物/会话）
- [x] 配方 FSM + 工具遮罩 + 证据勾选（框架 0.1.24：`recipe_runs`/`recipe_evidence`、当前步遮罩、`recipe_start`/`recipe_skip`；产品两条通用配方与 `/recipes` API）
- [x] 严格/普通模式（本地 `local_only` 供应商自动严格：12 个工具预算；强模型完整列表）
- [ ] 能力优先策略 + Python 缺口审批 + 审计
- [ ] qwen3.5:4b/9b 评测集（20-30 个任务）
- [ ] 工具覆盖门禁
- [x] 工具分层路由（每轮 ≤12 工具：控制 + 核心 + 当前配方步骤必留，其余按用户原话排序）
- [ ] 技能选择评测
- [ ] 工具描述质量规范
- **DoD**：小模型严格模式完成“选技能→建节点→填参→验证→运行”≥80%；普通模式不退化；技能/工具无孤儿。

## P7 其它域（3-4 周）

- [x] 分析算子清单化（37 个：`capabilities_kernel/operators/<id>/manifest.py` 声明契约/读写列/输出形状/是否用模型/双表/空表策略，七段技能由清单生成；`STEP_PARAMS`/写表/`OPS`/`LLM_OPS`/`STEP_TWO_TABLE` 全部由其投影）
- [x] 图表清单化（30 个：`capabilities_kernel/charts/<id>/manifest.py` 声明字段/角色/控件/引擎/文献必读列与七段技能；`services.charts.registry.SPECS` 全部由其投影，绘图函数公开为 `build_*` 并成为清单 handler）
- [x] 平台清单化（10 个：`capabilities_kernel/platforms/<id>/manifest.py` 声明模式/字段/采集行为/登录与机器要求/运行建议与七段技能；`capabilities.platforms.CAPABILITIES` 与 `capabilities.registry` 全部由其投影，爬虫类成为清单 handler）
- [ ] 面板/停靠/设置清单化
- [x] 生成物与门禁（catalog/openapi/ai_tools/前端目录/能力页与技能页 + freshness；OpenAPI 为每类能力生成 `NodeParams.`/`OperatorParams.`/`ChartFields.`/`PlatformModes.` schema）
- [ ] 多表面生成：MCP server / CLI / UI 表单（API、AI 工具、文档、生成物已覆盖）
- [x] 同一清单的七个表面一致性门禁（`tests/unit/gates/test_capability_surfaces.py`：每种能力 × 每个应服务的表面，双向断言“没有漏、没有多”）
- **DoD**：每个域新增一项只改一个清单；doctor 全绿；多表面生成无漂移。

## P8 测试瘦身与收口（1-2 周）

- [ ] 测试价值清单（每条测试防什么）
- [ ] 删重复/实现细节/永久 skip
- [ ] 节点/算子/图表矩阵生成式
- [ ] 快测目标 ≤8 分钟；device 目标 ≤20 分钟
- [ ] 全量 closure gate
- [ ] README/AGENTS/docs/crawler_notes/skills 同步
- [ ] 消费者契约测试
- [ ] 性质测试 + nightly mutation
- **DoD**：覆盖率不降；fast+ruff+pylint+device+smoke 全绿；无文件待改。

## P9 发布（1 周）

- [ ] `version.json`/`APP_VERSION`
- [ ] Windows/macOS 打包含 agent-workspace wheel
- [ ] CI 三系统 + browser + docker
- [ ] 迁移说明/回滚方案
- **DoD**：三系统安装包可启动；AI 工作区/节点/技能/验证冒烟通过。
