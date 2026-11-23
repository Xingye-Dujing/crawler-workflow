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
- [ ] 每节点技能骨架 + 示例 + 工具生成
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

### P4.0 框架完善（先行）

- [ ] F1–F4 持久化与恢复：`pending_calls` 表 + rehydrate、回答按 `call_id` 幂等、未答问题不被新消息取消、
  邮箱、retry 还原原轮、事件 `seq`/`Last-Event-ID` 续传
- [x] **ADR-003 TurnFSM**：`agent_workspace/fsm.py` 通用状态机 + `turns`/`turn_events`/`pending_calls`；
  非法转换按名拒绝，转换表穷举测试（框架 0.1.2）
- [x] **ADR-003 runner**：`ask()` 建 turn 后由后台 `TurnRunner` 执行；事件带 `seq`+`v` 落盘；`subscribe(after)` /
  `/turns/<id>/events`（`after`/`Last-Event-ID`）可断线续传；关流不停轮（框架 0.1.3）
- [x] **ADR-003 answer/stop 命令**：`answer` 按 `call_id` 幂等并复用原 turn；`stop` 先写 `turn_commands` 再由 runner
  取走；重复答案按名拒绝（框架 0.1.3）
- [ ] **ADR-003 steer**：运行中插入指引只在安全边界注入（`turn_commands` 已有表结构，缺的是注入语义）
- [ ] **ADR-003 邮箱**：待答期间的普通新消息排队下一回合；当前先按 `turn.awaitingUser` 拒绝，不再静默取消
- [x] **ADR-003 重启恢复**：启动 rehydrate `pending_calls`；未完成 turn 收尾为 `interrupted`，`awaiting_user`
  保留；已过期/取消的问题按名回答而不是 404（框架 0.1.2）
- [ ] **ADR-003 RecipeFSM**：`recipe_runs` + 每步证据（工具结果/产物/验证 id）；勾选只由服务端证据决定（P6 使用）
- [ ] **R10 Asset 物化**：`core.asset.DataAsset` 接到运行输出（id/origin/sha256/parents + 已有 `schema_hash`），
  血缘与增量缓存读同一份身份（P3 的 `node_schema` 是形状半部）
- [ ] **双路径开关**：`ai_host` 与旧 `backend/ai` 并存期间在 `runtime/flags.py` 声明开关（owner/remove_by），
  parity 绿后删旧路径——ADR-001 的要求，不能以“直接替换”绕过
- [ ] F5–F7 后台 turn 与断线恢复、审批/权限策略引擎（destructive 永远要人批、先授权再建资源）、限制语义
  0=不限 + usage meter
- [ ] F8–F10 多问题卡（≤5）、plan/build 模式 + 工具遮罩、attachment 接缝（已抽取文本与内联图片）
- [ ] F11–F12 产物 validator/preview 注册、`agent_runs`/`agent_steps` + 崩溃恢复与幂等
- [ ] F13–F16 工具/技能注册收口、OTel GenAI trace、供应商能力声明、LLM 行任务并发与限流
- [x] F17 轮次完成通知接缝：`HostAdapter.turn_finished(summary)` 每次 `ask()` 一次，带状态与 ≤240 字预览；
  弹窗/提示音由宿主决定，钩子异常不打断轮次（框架 0.1.1）
- [ ] 架构收口：端口/适配器/`TurnFSM` 拆分；框架测试全绿；重建 wheel 并升版本
- [ ] 通用性门禁：框架仓库内不出现采析绘领域词；宿主只经 `HostAdapter` 注入
- **DoD**：F1–F17 全绿；本仓库 parity 矩阵每行有等价测试；host 只用框架公开 API，不复制 turn 循环/审批/事件序列化。

### P4 接入

- [x] 构建/钉版 agent-workspace wheel；CI 安装（`vendor/` + `requirements.txt`；本地 dev editable 见
  `vendor/README.md`）
- [ ] `backend/ai_host/` HostAdapter
- [ ] `backend/ai/` 改为薄门面；删重复引擎模块
- [ ] parity matrix：每个旧功能在新框架有等价/更强测试
- [ ] TurnFSM + 持久化 question + answer by question_id + mailbox
- [ ] SSE seq/resume；后台 turn；关闭/切换/刷新恢复
- [ ] 限制设置迁移；0=不限；usage meter
- [ ] `/compact` `/init` `/status` `/skills` `/mode`
- [ ] provider 能力：structured output/thinking control；Ollama `think:false`
- [ ] 附件抽取；并发；工作流/产物工具；源码阅读工具
- [ ] Run/Turn 事件溯源 + checkpoint + 幂等恢复
- [ ] 能力权限模型 + 工具策略引擎
- [ ] OTel GenAI trace 表 + trace 树
- **DoD**：旧 AI 功能全部在新框架跑通；旧 `backend/ai` 无业务逻辑；AI 会话关闭/切换不中断；question 不再“找不到消息”。

## P5 框架前端（2-3 周）

- [ ] `agent_workspace/web/` 零构建壳
- [ ] Host UI adapter：artifact/dataset/chart/run/source 预览注册
- [ ] 采析绘全屏页先接入；再替换右侧 dock
- [ ] 删除旧 `ai-workspace.js`/`ai/*.js`（或保留薄适配）
- [ ] 交互修复：滚动/思考展开/工具详情/原位回答/侧栏/复制/单实例
- [ ] 浏览器测量测试
- [ ] 零构建 custom elements + host adapter + design tokens
- [ ] 组件级 UI contribution registry
- **DoD**：新旧 UI 功能 parity 或更强；所有 UI 问题在新 UI 有回归测试；旧 UI 删除。

## P6 技能/工具/小模型（2-3 周）

- [ ] L1/L2 分类 + 目录生成
- [ ] 每节点/算子/图表/平台技能七段内容
- [ ] catalog/search/load/read + @
- [ ] 配方 FSM + 工具遮罩 + 证据勾选
- [ ] 严格/普通模式
- [ ] 能力优先策略 + Python 缺口审批 + 审计
- [ ] qwen3.5:4b/9b 评测集（20-30 个任务）
- [ ] 工具覆盖门禁
- [ ] 工具分层路由（每轮 ≤12 工具）
- [ ] 技能选择评测
- [ ] 工具描述质量规范
- **DoD**：小模型严格模式完成“选技能→建节点→填参→验证→运行”≥80%；普通模式不退化；技能/工具无孤儿。

## P7 其它域（3-4 周）

- [ ] 38 个分析算子清单化
- [ ] 30 个图表清单化
- [ ] 11 个平台清单化
- [ ] 面板/停靠/设置清单化
- [ ] 多表面生成：OpenAPI / MCP server / CLI / UI / AI 工具 / 文档
- [ ] 同一清单的七个表面一致性门禁
- [ ] 生成物与门禁
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
