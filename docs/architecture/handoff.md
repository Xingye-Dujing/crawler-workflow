# 交接与压缩检查点

- 日期：2026-11-22
- 分支：`main`
- 最后提交：`14938f8 功能更新：迁移 biblio 节点清单，参数与选项由清单派生`
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
| `afc7d34` | P1 第四片：`runtime/flags.py` 迁移开关与到期门禁；`core/asset.py` 的 `DataAsset` 骨架 |
| `7a5f660` | 生成的前端目录从 `static/js` 移到 `generated/capability-schema.json`（全量快测的前端门禁拒绝无人加载的模块） |
| `0086cca` | P2 第一批：manifest 增加 `validators` 与 `no_input`/`requires_output`；name/upload/compile/output 迁移，engine 删除对应 if 分支 |
| `77731f2` | P2 第二批：resume/process/python 迁移；process 的 operation/tokenize 检查移到 validator |
| `68b8f49` | P2 第三批：analysis/accumulate/verify 迁移；engine 不再导入行形状集合 |
| `d59d65b` | P2 第四批：visualize/fuse 迁移；fuse 参数错误改为 code/message_key 数据 |
| `45dd0be` | P2 第五批：comment 迁移；账号会话检查从 engine 移到 `sessions/preflight.py` |
| `14938f8` | P2 第六批：biblio 迁移；56 参数与 10 组选项表由清单派生，`schema.py` 不再保留第二份 |

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
  `ai_tools.json`、`capability-schema.json`、`docs/capabilities/index.md`；`--check` 与门禁共用
  `generate.check()`。`tools/doctor.py --all` 逐项打印 `[x]`，未知 `--capability` 也是失败行。
  前端表单目录先放在 `capabilities_kernel/generated/`：全量快测的 `test_frontend_page_scripts_js` 拒绝
  “没有页面加载的 static/js 模块”，P2 真正接页面时再移入 `static/js` 并注册到 `index.html`。
- `runtime/fsm.py`：`RUN`/`NODE`/`TURN`/`VIEW` 四张表 + `recipe_machine(steps)`；构造时拒绝不连贯表，
  `require()` 对非法移动按名拒绝；`tests/unit/foundation/test_fsm.py` 穷举全部状态对。
- `runtime/events.py`：四个运行事件的字段类型契约；`publish()` 校验后交给 `run_events` 总线；
  `tests/unit/gates/test_event_contract.py` 用 AST 检查现有调用点与 `ai/monitors.py` 的订阅词汇。
- `runtime/flags.py`：`Flag(name/owner/remove_by/description/default)`；`active()` 读 `CIXI_FLAG_*`（空值取默认，
  非布尔按名拒绝），`problems()` 把过期/无 owner/非法日期变成门禁失败；`tests/unit/gates/test_flags.py` 用合成开关
  证明门禁能红。当前 `FLAGS` 为空——P1 的两个 pilot 都是单路径切换。
- `core/asset.py`：`DataAsset`（id/kind/owner/origin/sha256/size/uri/parents/meta/schema）与 `from_dict`/`to_dict`；
  只导入标准库，供 P2 的运行库、节点、API、AI 共用。`services/components` 的 `Asset` 是可下载组件载荷，不是同一种。
- 文档：`docs/architecture/capabilities-kernel.md`、`docs/capabilities/nodes/tokenize.md`、ADR-001/ADR-003 的 P1 落点。
- 本片验证：相关模块 `2048 passed`（analysis/gates/runs/executors/capabilities + node-types/workflow API）；
  全量快测 `10789 passed, 7 skipped, 386 deselected, 1 failed`（14:16），失败项是“前端目录是无人加载的
  static/js 模块”，已改为 `generated/capability-schema.json` 并单跑通过；ruff 全绿；product pylint 10.00/10、
  tests pylint 10.00/10；`test_boot_import_budget` 9 passed。
- P1 清单已全部落地；下一步进入 P2（15 个节点迁移 + schema 表单 + 删除前端第二套规则）。

## P2 第一批：name / upload / tokenize / compile / output（2026-11-22）

- manifest 验证段扩展：`Rule` 新增 `no_input`/`requires_output`；`Manifest.validators` 指向能力目录自己的
  `module:function`。`services/validation/engine.py` 新增 `ValidationContext`（父节点、连线、标签、数据输入），
  并同时求值声明规则与 validators。
- 迁移：`name`（头部/命名/下游三条规则）、`upload`（dataset_id 必填 + 数据集列钩子）、`compile`/`output`
  （父节点形状检查移到 executor 的 `validate_node`）、`tokenize` 保持。`engine/workflow.py` 删掉这五个节点的
  验证 if 分支；`nodes/catalog.py` / `nodes/defaults.py` 的字面表只剩 11 个未迁移节点（顺序与槽位不变）。
- 失败语义：validator 抛错、返回非 list、缺 code/message_key、非法 severity/context 都变成
  `engine.validator_failed` 并有 zh/en 文案；`/api/workflow/diagnostics` 不 500，其他徽章仍显示。
- 门禁：completeness gate/doctor 增加 validators 可解析；生成物矩阵增加 `validators` 检查项。
- 测试：`tests/unit/capabilities/test_{name,upload,compile,output}_manifest.py`、
  `test_validation_engine.py`；`tests/unit/analysis/test_node_plugins.py` 不再把 `PDF_SOURCE_NODE_TYPES`
  钉在 engine 上（它已随保存/编译的校验移入能力目录）。
- 本片验证：相关用例 `245 passed`（capabilities + node plugins/schema + workflow/node-types API）、
  `1262 passed`（workflow API + runs/charts/biblio/frontend node-types + capabilities）；ruff 全绿；
  product pylint 10.00/10、tests pylint 10.00/10；生成物 `--check` 通过、doctor 全绿。
- 未做（P2 后续）：`source`/`resume`/`comment`/`process`/`python`/`analysis`/`biblio`/`verify`/`fuse`/
  `accumulate`/`visualize` 的清单；schema 表单渲染器；删除 `canvas.js`/`runs.js` 的第二套规则；executor 搬进能力目录。

## P2 第二批：resume / process / python（2026-11-22）

- `process` 用 `validators=('nodes.executors.process:validate_node',)` 保留 `process_no_op` 与
  `tokenize_no_column`；节点对象上的 `operation` 与 params 里的都接受。`engine/workflow.py` 删除这两条 if。
- `python` 只声明脚本 id/args/timeout/max_rows 与“本地可运行”的契约；云模式/空脚本/坏 args 仍由 executor 按名拒绝。
- `resume` 刻意没有必填规则：空 run/node 是“自动选择最新可恢复运行/最满节点”的合法路径。
- 三个节点的 catalogue 槽位（3/5/6）与默认参数不变；`nodes/catalog.py` 剩 8 个未迁移类型。
- 本片验证：`156 passed`（capabilities + node plugins/schema + executors）、`585 passed`
  （workflow/node-types API + runs + capabilities）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check 通过。

## P2 第三批：analysis / accumulate / verify（2026-11-22）

- `analysis`：`steps` 或 operation 之一存在即可；`analysis_no_op` 移到 `validate_node`，emit/read 钩子继续由执行器回答。
- `accumulate`：名字/identity/键列/恰好一个表父节点全部移进 validator；`emit_columns` 仍返回上游合并列。
- `verify`：两个数据父节点（命名节点不计）与两个键列移进 validator；`read_columns` 继续回答血缘。
- `engine/workflow.py` 删除这三段 if；`TABLE_NODE_TYPES` 从此不再被 engine 导入（行形状检查已随
  accumulate/compile/output 的 validator 走），契约测试改为只钉 `NODE_TYPES`。
- 本片验证：`181 passed`（capabilities + node plugins/schema + executors）、`1770 passed`
  （analysis + workflow/node-types API + runs）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check 通过。

## P2 第四批：visualize / fuse（2026-11-22）

- `visualize`：chart_type/x_field/ChartSpec.required_params 移进 `nodes.executors.visualize:validate_node`；
  engine 删除整段图表校验与 `NO_X_TYPES` 导入。`read_columns` 继续回答图表字段与文献固定列。
- `fuse`：输入要求变成声明规则 `upstream_required`；参数错误由 `services.biblio.fuse.collect_problems` 返回
  `{code,message_key}`，validator 求值；`collect_errors` 仍是给直接调用者的已本地化句子。
- `nodes/catalog.py` / `nodes/defaults.py` 只剩 `source`/`comment`/`biblio` 三个未迁移类型。
- 本片验证：`196 passed`（capabilities + node plugins/schema + executors）、`1293 passed`
  （charts/biblio + workflow API + runs + capabilities）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check 通过。

## P2 第五批：comment（2026-11-22）

- 账号会话检查从 `engine/workflow.py::_account_session_errors` 移到 `sessions/preflight.py`：
  `session_problems()` 返回 `{code, message_key, context}`，`session_errors()` 是给 source 节点（尚未迁移）
  用的已本地化句子版本。source 的 `_source_errors` 改调后者，engine 里不再有这段逻辑。
- `comment` 清单：`urls` 必填规则 + `validate_node`（对链接涉及的每个平台问一次账号会话，@pool 问池，
  CatBus 不问 Cookie）。表单声明为 `ui.form='custom'` / `custom_renderer='comment'`，因为它的账号/楼中楼/
  时间过滤表单本来就是自定义面板。
- `engine/workflow.py` 删除 comment 的 if 分支；`nodes/catalog.py` / `nodes/defaults.py` 只剩
  `source`/`biblio` 两个未迁移类型。
- 本片验证：`229 passed`（capabilities + pool + node plugins/schema）、`850 passed`
  （node-types/workflow API + runs/workflows/sessions + 前端 node-types + completeness）、
  `1334 passed, 4 skipped`（crawlers + executors + node matrix）；ruff 全绿；生成物 --check 通过。

## P2 第六批：biblio（2026-11-22）

- `biblio` 的 56 个参数、10 组选项表与默认值搬进 `capabilities_kernel/nodes/biblio/manifest.py`；
  `services/biblio/schema.py` 的 `DEFAULTS`/`ENTITY_TYPES`/`OUTPUT_SHAPES`/… 全部由清单派生，不再有第二份。
- 参数校验改成 `collect_problems()`（`{code, message_key, context}`）+ `collect_errors()`（同一份数据的句子版，
  供 `normalize_params` 直接调用者）；数值范围集中在 `RANGE_CHECKS`，选项集中在 `OPTION_CHECKS`。
  `biblio` 的“无上游/多上游”检查移到 executor 的 `validate_node`，`engine/workflow.py` 删除整段 biblio 分支与
  `biblio_param_errors` 导入。
- 清理随迁移失效的代码：`nodes.catalog`/`nodes.defaults` 只剩 `source`；`services.biblio.fuse.collect_errors`
  与 `name.execute_name_node` 删除（前者由 `collect_problems` 取代，后者是只被 `run` 调用一行的转发）。
- 本片验证：`704 passed`（capabilities + biblio + node plugins + frontend contract + biblio/node-types API）、
  `622 passed`（frontend js + 门禁 + runs）；ruff 全绿；product/tests pylint 10.00/10；生成物 --check、doctor 全绿。

### P2 剩余 1 个节点的已知风险

- **`source`**：`_source_errors` 约 100 行，依赖平台矩阵、必填字段、会话和链接归属；最后迁移，先保持现状。

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

## 硬性约束：不留残骸

重构/迁移完成后旧实现必须删除，不留“兼容层”：一个事实只允许一处声明（默认值、选项表、验证分支、句子都是），
迁移完成即删旧函数/旧分支/转发别名/只为旧路径存在的测试/没人 import 的模块。每片收口包含一次“本片是否新增了重复”
的检查；发现历史死代码顺手删除。详见 `docs/architecture/rewrite-plan.md` 开头与 `docs/agent_practices.md`。

2026-11-22 已删（随 P2 迁移失效）：`name.execute_name_node`、`fuse.collect_errors`、
`registry.register_many`、`nodes/executors/__init__.py` 里 15 个迁移类型的第二条注册表（现在由清单注册，
该文件只剩尚未迁移的 `source`）；AI 重写留下的无调用函数 `_current_thinking`、`_abandon_pending`、
`ensure_dirs`、`attachments_payload`、`abandon_questions`、`list_steps`、`thinking_block`/
`tool_use_block`/`tool_result_block`、`ProviderReply`、`context_section`。
仍待按“各自切片”清理（有文档或装饰器/动态引用，需先确认）：`core/machine.py` 的三个无调用取名字、
`crawlers/engine/pacing.py` 的三个 `*_scale` 兼容读、`services/biblio/formats/common.py` 的五个无人引用的
helper、`services/charts/options/relations.py`（`@builder` 注册，实际在用，勿删）。

## 下一步（按顺序）

1. **P2 续**：迁移最后一个节点 `source`（平台矩阵、字段、会话、链接归属）；再做 schema 表单渲染器 +
   删除 `canvas.js`/`runs.js` 的第二套规则。
2. 后续按 `docs/architecture/rewrite-plan.md` 推进 P3-P9；每个切片结束更新本文件。

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
