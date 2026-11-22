# 交接与压缩检查点

- 日期：2026-11-22
- 分支：`main`
- 最后提交：`ef5b789 功能更新：状态机转换表与事件契约`
- 工作区：干净（`git status --short` 无输出）

## 已完成（每个一类改动一个 commit）

| 提交 | 内容 |
|---|---|
| `6e5fd4c` | 待答问题按 `question_id` 恢复；服务端派生 `message_id`；多选答案写入状态 |
| `28d9820` | 本地 Ollama 全局强制 `think:false`；过滤残留 thinking/think 标签；UI 开关禁用 |
| `1b69457` | 架构 ADR、问题台账、实施计划、5 个架构技能 |
| `f5b0c91` | 新消息不再取消待答问题；有待答问题时按名拒绝（邮箱在 P4） |
| `84b1a0c` | 侧栏按实测宽度布局；列宽随 dock 夹紧；12px grip + pointer capture；流式重绘恢复 scrollTop |
| `d8a7d55` | Python 节点显示脚本/参数；补全 `python`/`fuse` 标题 |
| `ab1285d` | 放宽 AI 输出/工具结果/回合/表格读取限制；0=不限；表格单页 2000 |
| `0c965b8` | LLM 行任务可配置并发；API 并行；Ollama 串行 |
| `279ed41` | agent-workspace parity 矩阵 |
| `5e038bd` | 附件文本抽取（pdf/docx/pptx/xlsx/csv/txt/html，缓存）；`files`/`vision`/`inline_images` 三能力拆分；图片内联；本地/无 key 供应商可上传；`pypdf` 依赖 |
| `438723e` | 数据集行读取授权：`request_dataset_access` 走暂停/恢复问题通道；会话+数据集+行数 grant；`dataset_page`/`sample`/筛选查询累计；`peek` 免费；侧栏列出/撤销 |
| `702705e` | 工作流/导出管理工具：list/read/update/rename/delete/export/run/stop + export_list/delete；删除强制审批+审计；停止与 HTTP 共用 `engine.run.stop_run` |
| `a00e89b` | `ai.coverage` 能力→AI 入口矩阵（节点/平台模式/算子/图表/工具）+ `ai_coverage` 工具 + 门禁（可反向失败） |
| `b3dbfb3` | `ChartSpec.required_params` 声明 `stack_fields`；`WorkflowEngine.validate_detailed` 在运行前按名报告，默认值先填充 |
| `33b738a` | 覆盖矩阵只统计内置工具，插件工具不算产品能力 |
| `0361be1` | 回归测试对齐：新消息在待答问题期间按名拒绝；stack_pct 在 validate 阶段拒绝 |
| `b54c5a0` | 测试复用已导入的 `store`，修 pylint 重复导入 |
| `44dcb01` | `setPointerCapture` 抛错不再中断侧栏拖拽；真实 Chrome 层验证 |
| `1c52910` | H11-H16 收口基线（10646/14:06、device 213/5:54、lint、冒烟） |
| `dad5d55` | H17/H18：`#ai-chat` 拆成 `#ai-transcript` + `#ai-panel`；转录按 `turn_id`/消息 id 复用；流式气泡跨重绘与 A→B→A 复用；`harness_dom.appendChild` 改为浏览器语义（移动而非复制） |
| `a8420a1` | P1 第一片：`capabilities_kernel` 九段清单 + registry 投影；`tokenize` pilot；声明式验证改由 `services/validation/engine.py` 求值 |
| `55329a7` | P1 第二片：`tools/gen_capabilities.py` 五类产物、`tools/doctor.py`、生成物 freshness gate |
| `ef5b789` | P1 第三片：`runtime/fsm.py` 四张状态机表 + recipe 工厂；`runtime/events.py` 字段契约 + AST 调用点 census |

## P1 第一片：能力内核 + tokenize pilot（2026-11-22）

- `backend/capabilities_kernel/`：九段 `Manifest`（identity/params/ports/execution/rules/ui/ai/tests/docs）、
  结构校验 `problems()`、SHA-256 `digest()`；`ROW_SHAPES` 等词汇在这里，`nodes/catalog.py` 不再保留第二份。
- `registry`：`<kind>/<id>.py` 或 `<id>/manifest.py` 两种家，目录名即 id；重复 id、未知 kind、api_version 不符、
  kind/id 不一致、不完整清单都在读取时**按名拒绝**；`node_entries()` / `node_defaults()` 是目录投影，
  `register_node_executors()` 把 handler 注册进 `nodes.registry`（所以 `registered_types() == NODE_TYPES` 仍成立）。
- 旧表面改读：`nodes/catalog.py` 按 `identity.order` 插回原槽位（tokenize 仍在 index 8）；`nodes/defaults.py`
  取 `ParamSpec.default`；`engine/workflow.py` 的 tokenize if 分支换成 `services/validation/engine.py`
  的声明式规则；血缘钩子由 `ports.emit_columns/read_columns` 解析到 executor 自己的函数。
- pilot：`backend/capabilities_kernel/nodes/tokenize/manifest.py`；`tests/unit/capabilities/test_tokenize_manifest.py`
  逐项钉住“旧家不再有答案”（catalogue/defaults/validate/hooks）。
- 门禁：`tests/unit/gates/test_capability_completeness.py`（结构/执行器/端口/文档/契约测试/双语词/清单轻导入/生成物 fresh）；
  `test_doc_paths` 与 `test_requirements_pinned` 的包清单已加 `capabilities_kernel`。
- 生成物：`tools/gen_capabilities.py` 渲染 `catalog.json`（目录 + 测试矩阵）、`openapi.json`、
  `ai_tools.json`、`backend/static/js/capability-schema.generated.js`、`docs/capabilities/index.md`；
  `--check` 与门禁共用 `generate.check()`。`tools/doctor.py --all` 逐项打印 `[x]`，未知 `--capability` 也是失败行。
- `runtime/fsm.py`：`RUN`/`NODE`/`TURN`/`VIEW` 四张表 + `recipe_machine(steps)`；构造时拒绝不连贯表，
  `require()` 对非法移动按名拒绝；`tests/unit/foundation/test_fsm.py` 穷举全部状态对。
- `runtime/events.py`：四个运行事件的字段类型契约；`publish()` 校验后交给 `run_events` 总线；
  `tests/unit/gates/test_event_contract.py` 用 AST 检查现有调用点与 `ai/monitors.py` 的订阅词汇。
- 文档：`docs/architecture/capabilities-kernel.md`、`docs/capabilities/nodes/tokenize.md`、ADR-003 的 P1 落点。
- 本片验证：相关模块 `2048 passed`（analysis/gates/runs/executors/capabilities + node-types/workflow API）；
  ruff 全绿；product pylint 10.00/10、tests pylint（本片文件）10.00/10；`test_boot_import_budget` 9 passed。
- 未做（P1 后续切片）：`runtime/flags.py`、Asset 数据模型骨架。
  前端表单与 `canvas.js`/`runs.js` 的 if 链按计划在 P2。

## 测试基线（H11-H16 收口，2026-11-22）

- 全量快测：`10646 passed, 7 skipped, 384 deselected, 1 warning in 846.06s (14:06)`。
- 设备层：`-m "integration or live_ollama"` → `213 passed, 5 skipped, 10820 deselected`，5 分 54 秒；
  H4/H5 的 pointer capture 回归就是这一层发现的，已修。
- lint：`ruff check` / `format --check` 全绿；`ci_lint_tiers.py product` 10.00/10；
  `ci_lint_tiers.py tests` 10.00/10。
- 冒烟：隔离 data root 在 5057 启动，9 个基础 GET + 5 个 AI GET 全部 200；进程已停、端口已释放。
- **未跑**：`live_quick`/`live_site`（花用户账号；需要用户指定网络并同意）。
- H17/H18 之后又全量跑过一次：`10651 passed, 7 skipped, 386 deselected, 1 warning in 836.93s (13:56)`；
  两个新增的 device 用例（面板面 / 切会话单消息区）单跑通过。之后按用户要求改为按改动范围测试。

## 测试策略（用户 2026-11-22 明确要求）

- **小改动只跑改动到的地方**：相关模块的 pytest 用例 + 前端 harness + 受影响的 device 用例；不再每次都全量。
- **攒一批或做大改动后才跑全量**：`python -m pytest -q`、全量 device、两档 pylint、冒烟。
- **不要为仪式感测试**：能用一条针对性用例证明的行为，不重复铺三层。
- 本次 H17/H18 已做过一次全量（10651 passed / 7 skipped / 386 deselected / 13:56）；之后的 P1 切片先按需测试。

## 下一步（按顺序）

1. **P1 续**：`tools/gen_capabilities.py` 五类产物 + `tools/doctor.py` + 生成物 freshness gate；然后
   `runtime/fsm.py` / `runtime/events.py` / `runtime/flags.py` / Asset 骨架。
2. 后续按 `docs/architecture/rewrite-plan.md` 推进 P2-P9；每个切片结束更新本文件。

## H11 的关键落点（避免重复调查）

- `backend/ai/file_text.py`：`extract(name, data)`、`extract_attachment(row)`（缓存 `<local>.text.json`）、`image_payload(row)`（>8 MB 用 Pillow 缩到 4096px）。
- `backend/ai/agent.py::_attachment_plan`：有 `files` + `file_id` → 原生；否则本地抽取；图片只问 `vision`，无 `file_id` 时要求 `inline_images`，否则 `ai.imageNeedsUpload`。
- 新增设置 `ai_attachment_text_chars`（0=不限）；浏览器 `settings.js` 与后端 `settings_schema.py` 同步；`pypdf==6.1.1` 已进 `requirements.txt` 与 `desktop/requirements-runtime.txt`。
- 本地/无 key 供应商上传：`files.save_attachment` + 服务端上传后立即抽取；`.doc/.ppt` 按名拒绝，提示转 `.docx/.pptx`/PDF。

## H12-H16 的关键落点（避免重复调查）

- **H12 授权**：`backend/ai/dataset_access.py`（进程内 grant，键 `(会话, 数据集)`，`max_rows=0` 表示不限）；
  `request_dataset_access` 是 control 工具，走 `_dataset_access_event` → `_attach_question`；
  `answer()` 里先 `approvals.settle` 再 `dataset_access.settle`；`tools._dataset_rows` 是唯一的行消费口。
  API：`GET /api/ai/conversations/<id>` 带 `dataset_grants`；`DELETE …/dataset-grants/<dataset_id>`。
- **H13 管理**：`workflow_list/read/update/rename/delete/export/run/stop` + `export_list/delete` 在 `ai/tools.py`；
  `APPROVAL_TOOLS` 覆盖写操作，`ALWAYS_APPROVAL_TOOLS={'workflow_delete','export_delete'}` 绕过 auto-approve 强制审批；
  `engine.run.stop_run` 是 HTTP 与工具共用的停止实现（旧的 route 主体已移走）。
- **H14 覆盖**：`backend/ai/coverage.py`；入口集合是 `agent.UNIVERSAL_TOOLS` + `agent.FILE_TOOLS` + 技能 `tools`；
  插件工具 `ToolSpec.builtin=False`，不计入；门禁 `tests/unit/gates/test_ai_coverage.py` 可反向失败。
- **H16 图表**：`ChartSpec.required_params` 是唯一声明；`WorkflowEngine.validate_detailed` 的 visualize 分支读它，
  先 `with_chart_defaults`；stack_pct 缺失时整张画布在运行前被 rejected，控制台按名给出 `stack_fields`。

## H17/H18 的关键落点（避免重复调查）

- `index.html` 的 `#ai-chat` 下有两个同级面：`#ai-transcript`（对话）与 `#ai-panel`（设置/工作室），CSS 里两者 `grid-area: 1/1`。
- `ai-workspace.js`：`_showPanel()` 只隐藏转录、`_showChat(refresh)` 拿回并可选重读会话；设置/工作室的所有 `innerHTML` 与
  面板内查询都走 `_dom.panel`（grep 找不到 `_dom.chat` 的面板写入即正确）。
- `_renderMessages` 协调 key：`message:<id>` / `turn:<turn_id>` / `row:<id>`；流式气泡在 `meta` 时打同一 key；
  `_streamTurnId` + `_streamConversation` 让“回到仍在流式的会话”接管存储的轮次元素。
- `_appendQuestion(question, turn)` 把卡片挂回提问那一轮，`blocks` 用该轮存储内容播种，回答后续写不会丢前文。
- `tests/frontend/harness_dom.mjs::appendChild` 现在是浏览器语义（已在树内的节点移动、不复制）；改协调逻辑前先看它。

## 压缩后必须保留的规则

1. **10 个已确认决策**（见 `docs/architecture/rewrite-plan.md#已确认的决策`）不得重新讨论，除非用户明确复议。
2. **一类改动一个 commit**；每个勾选项只在“代码 + 测试 + 文档/技能 + 门禁 + 收口”全过后打勾。
3. **自动压缩时机**：当预计剩余上下文不足以完成一个“代码 + 测试 + commit”的完整切片时，先收口当前切片、提交、更新本文件，再请求用户压缩；**不要在半成品上压缩**。压缩后从“下一步”继续。
4. **不要靠提示词保证行为**：能用服务端校验/工具遮罩/状态机/门禁的，必须用机制。
5. **不要在全量重写上打转**：内核替换 + 逐域迁移；旧路径只在数据丢失/安全级别热修。
6. **歧义必须问**，不要猜；用户语言是中文。
7. **关键路径**：`docs/architecture/`、`backend/ai/`、`backend/static/js/ai-workspace.js`、`backend/static/js/canvas.js`、`backend/runtime/settings_schema.py`、`tests/api/test_ai_workflow.py`、`tests/unit/frontend/test_frontend_ai_js.py`。
8. **测试按改动范围跑（用户 2026-11-22 要求）**：小改动只跑相关用例；攒一批/大改动再全量 fast + device + 两档 pylint + 冒烟。

## 给压缩后的第一句话

> 从 `docs/architecture/handoff.md` 的“下一步”继续；当前工作区干净，最后提交 `dad5d55`。先做 P1 内核骨架。
