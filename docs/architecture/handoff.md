# 交接与压缩检查点

- 日期：2026-11-24
- 分支：`main`
- 最后提交：`97959ae3`（P4/P5 收口）；框架仓库 `630729a`（0.1.22）
- 工作区：干净（`git status --short` 无输出）

## 已完成（每个一类改动一个 commit）

| 提交 | 内容 |
|---|---|
| 本次 | P6 第一片：16 个节点能力技能七段内容、L1/L2 目录、`skill_catalog`/`skill_load`、生成页面与门禁 |
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
| `6ce014e` | 第二轮死代码清理：移除 15 个 executor 的 `NODE_TYPE`、无调用函数/方法/常量/helper（AST 扫描逐项确认） |
| `cd6cdc2` | P2 第七批：source 迁移；`_source_errors`/watermark 检查搬入 executor，`session_errors` 删除 |
| `109cb3d` | P2 前端第一片：`/api/node-types` 与生成的 `node-types-fallback.js` 同源；canvas 删除类型/标签/默认值字面表 |
| `d72b0a62` | P2 前端第二片：`/api/workflow/validate` 成为唯一运行门；删除 `runs.js` 校验 if 链与 `sourceNodeErrors` |
| `2f6e21cf` | P2 前端第三片：process/biblio 选项表改读清单枚举；`node-types.js` 幂等加载 |
| `64dede4e` | P2 前端第四片：清单 `ui` 选择表单；`openSettings` 删除逐类型分支；通用 schema 渲染器 + 注册表；设备层禁用节点用例等待服务端诊断 |
| `1be81060` | P3 第一片：`ChartSpec.fields` 成为面板/校验/血缘/AI 目录的单一来源；验证条目带 `param`/`severity`/`fix`；设置面板一键修复与字段描红 |
| `429b5cfd` | P3 第二片：`Manifest.preflight` + 同指纹上游样本（≤200 行、30 秒缓存）；图表缺列/非数值列在 validate 阶段命名；诊断/validate/运行门接线 |
| `43caa638` | P3 第三片：`node_schema` 记录生产者真实列集合 + `schema_hash`；`contracts.columns_for` 记录优先、声明兜底；引擎按 `read_columns` 报 `engine.missing_column`（warning）；前端删除差集，诊断不再返回 `reads` |
| `ec8faf20` | P3 第四片：`Manifest.postcheck`（`postcheck(node, rows, inputs)`）；运行循环在节点 DONE 后打一行控制台，不改状态；analysis 非空输入产出 0 行报 `engine.empty_output` |
| `8b6cc478` | P4 依赖：`vendor/agent_workspace-0.1.0-py3-none-any.whl` 钉版；`requirements.txt` 以仓库根相对路径引用；`deploy/Dockerfile` 复制 `vendor/` 并从 `/app` 安装；requirements 门禁校验 wheel 名/METADATA/唯一声明 |
| `31b3c9ba` | 框架升到 0.1.1：`HostAdapter.turn_finished(summary)` 轮次完成通知（桌面弹窗/提示音的宿主接缝）；wheel 替换并更新 sha256；P4.0 增加 F17 |
| `47496d0` | 框架 0.1.2（ADR-003 第一片）：`fsm.py` TurnFSM；`turns`/`turn_events`/`pending_calls`；answer 按 `call_id` 幂等并复用原 turn；重启保留待答问题、收尾半途 turn |
| `e99a6d8` | 框架 0.1.3（ADR-003 第二片）：后台 `TurnRunner` + `subscribe(after)`；关流不停轮；`EVENT_PROTOCOL=1`；`turn_commands` 持久 stop；`bind_account`；`/turns/<id>` 与 `/turns/<id>/events` 重连路由 |
| `30d1d5d` | 框架 0.1.4（ADR-003 第三片）：`turn_inbox` 邮箱——待答期间的新消息排队、`notice(turn.queued)`、带 `mailbox_id` 再发才执行 |
| `4c506e0` | 框架 0.1.5（ADR-003 第四片）：`steer` 安全边界插入指引；最后边界之后的指引进邮箱；`/steer` 路由 |
| `57dd1c9` | 框架 0.1.6（F6）：`policy.PolicyEngine` + `ToolSpec.always_ask`；删除/覆盖/资源授权永远人批且不接受 session 授权 |
| `82a4a081` | wheel 0.1.6；rewrite-plan 勾选 F6；handoff/README 记录第五片，下一步 F12 |
| `f0283b8` | 框架 0.1.7（F12）：`agent_steps` 工具步骤 + 幂等重放；崩溃遗留 `running` 标 `interrupted` 且不再执行；`/turns/<id>/steps` |
| `f21b5e8` | 框架 0.1.8（F13）：`HostAdapter.tools()` 构造时注册；重名按 `tool.builtinConflict` 拒绝 |
| `61d8952` | 框架 0.1.9（F8）：多问题卡 `questions[]`（1–5），一张卡一次答复，答案按 `call_id` 对齐 |
| `cd7eda6` | 框架 0.1.10（F9）：`agent_mode=plan` 遮罩写入工具（schema + 允许列表 + 执行处），meta 带 mode |
| `1df4f91` | 框架 0.1.11（F3）：`retry` 从 user 行所属 turn 恢复 provider/model/skill，复用已存上下文块，不新增 user 行 |
| `2511b09` | 框架 0.1.12（F10）：附件接缝（宿主抽取文本/内联图片，框架按能力路由）；修复用户消息在每次 provider 请求中被重复追加 |
| `e2a60b3` | 框架 0.1.13（F11）：`ArtifactRegistry` + HostAdapter 校验/预览声明；提案与 apply 各校验一次，未声明 kind 标 `unvalidated` |
| `5f99f6a` | 框架 0.1.14（F14）：`agent_traces` OTel GenAI span + trace 树；best-effort、无正文 |
| `13d9937` | 框架 0.1.15（F15）：`structured_output` 能力 + `output_schema`；OpenAI 兼容映射 `response_format`，未声明按名拒绝 |
| `8ed62f4` | 框架 0.1.16（F16）：`chat_once` 按供应商限流（`max_parallel`/设置/本地串行） |
| `cc589d3` | 框架 0.1.17（F18）：`CommandRegistry` + `/status` `/skills` `/mode` `/compact`；host 可注册 `/init`，重名拒绝 |
| `aef340c` | 修复 trace 顺序：按 rowid 插入顺序，避免同一微秒的 span 排序漂移 |
| `22f9ef51` | wheel 0.1.17；rewrite-plan 勾选 F18，P4.0 全部完成；handoff/README 记录第十五片与 P4 接入 |
| `c8a1278f` | P4 接入第一片：`backend/ai_host` 的 `CaiXiHuiHost`（facts/tools/skills 委托旧注册表）；门禁加入 ai_host；运行库带 vendored wheel |
| `809fe5c9` | P4 接入第二片：`CaiXiHuiHost.artifact_validators()` 委托 `ai.validators`（memory/workflow/workflow_draft） |
| `6c894ccb` | wheel 0.1.16；rewrite-plan 勾选 F16；handoff/README 记录第十四片，P4.0 只剩 F18 |
| `fa7d965d` | wheel 0.1.15；rewrite-plan 勾选 F15；handoff/README 记录第十三片，下一步 F16 |
| `c6d392d7` | wheel 0.1.14；rewrite-plan 勾选 F14；handoff/README 记录第十二片，下一步 F15 |
| `3708da31` | wheel 0.1.13；rewrite-plan 勾选 F11；handoff/README 记录第十一片，下一步 F14 |
| `aa8bb1af` | wheel 0.1.12；rewrite-plan 勾选 F10；handoff/README 记录第十片，下一步 F11 |
| `6fdb5712` | wheel 0.1.11；rewrite-plan 勾选 F3；handoff/README 记录第九片，下一步 F10 |
| `c23175bf` | wheel 0.1.9；rewrite-plan 勾选 F8；handoff/README 记录第七片，下一步 F9 |
| `06aa5735` | wheel 0.1.8（含 F12/F13）；rewrite-plan 勾选 F12/F13；handoff/README 记录第六片 |
| `6f49c40e` | wheel 0.1.4；rewrite-plan 勾选邮箱、留出 steer；handoff/README 记录第三片 |
| `5b2281ff` | wheel 0.1.2；AGENTS/architecture README 增加“每次先读架构文档”；补 ADR-002 的 custom_renderer 门禁与文档哈希说明；rewrite-plan 勾选 TurnFSM/重启恢复，补 R10 与双路径开关 |
| `860e6e85` | 删除 `nodes/catalog.py` 空置的旧字面表 `_DECLARED` 与 `_with_kernel_nodes`；16 个节点全部由清单投影 |

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

### P2 最后一个节点：source

- `source` 的清单不声明参数：字段是平台 × 后端 × 模式的矩阵答案，清单用 `ui.defaults_from='capabilities'`
  让客户端问矩阵；`nodes/defaults.py` 的 `DYNAMIC_DEFAULTS` 字面表随之删除，改由 `NodePlugin.defaults_from` 传播。
- `engine/workflow.py::_source_errors`（约 100 行）、watermark 分支整段删除；同一套判断搬进
  `nodes/executors/source.py::validate_node`，返回 `code/message_key/context` 数据，`engine.workflow` 只保留
  唯一的清单校验循环。
- `sessions/preflight.session_errors()` 删除（迁移后无调用者），`tests/unit/pool/test_pool_contracts.py`
  改问 `session_problems()` 的数据。
- 契约测试：`tests/unit/capabilities/test_source_manifest.py`；文档：`docs/capabilities/nodes/source.md`。

## P3 第二片：样本 preflight（2026-11-23）

- `Manifest` 第九段之外新增可选 `preflight='module:function'`（ADR-002 的 `preflight(node, sample)`）；`problems()`
  拒绝不是 `module:function` 的引用，`doctor.py` 增一行 `preflight`，`generate.MATRIX_CHECKS` 与完整性门禁同步枚举。
- `services/validation/samples.py`：`samples_for(workflow)` 只给声明了 preflight 的节点取样本——
  - 上游是它的**数据父节点**（name 节点是元数据，不算数据），
  - 取“当前节点指纹”下最近一次已结算运行（`done`/`partial`/`restored`/`failed`）的 ≤200 行，
    由新 `run_store.sample_rows(node_id, fingerprint, limit)` 的 SQL `LIMIT` 读取（不物化整张表）；
  - 任一上游没有同指纹的存储运行 = 没有样本，不猜；多个上游按引擎 fan-in 顺序拼接；
  - 缓存键 `(该账号 runs.db, 节点 id, 指纹)`，TTL 30 秒、上限 32 项；命中返回浅拷贝行。
- `WorkflowEngine.validate_detailed(samples=None)` / `validate(samples=None)`：引擎不读数据库，调用方给样本；
  没有样本的节点不调用 preflight。`/api/workflow/diagnostics`、`/api/workflow/validate` 与运行门
  （`engine.run._preflight_samples`）都传入；读样本失败只记一条 `run.preflightSamplesFailed`，当作没有样本。
- `nodes.executors.visualize:preflight` → `chart_preflight()`：同一 `ChartSpec.fields` 的 role。只报能证明的事实：
  - 点名的列不在样本里 → `engine.chart_column_missing`（多半是改名）；
  - 数值/坐标/堆叠列有非空值却一个数字都没有 → `engine.chart_column_not_numeric`（与 builder 的 `chart.y_not_numeric` 同规则）；
  - 空样本、全空列、饼图负值、热力图最终格数都不下结论（builder 仍在运行期拒绝），写在函数 docstring 里。
  - 钩子抛错/返回畸形 → `engine.preflight_failed`（不 500，其它节点继续）。
- 测试：`tests/unit/charts/test_chart_preflight.py`（30 图型 × 合格样本；每个数值角色 × 文本列；改名/空样本/未知图型/
  默认列）；`tests/unit/runs/test_validation_samples.py`（数据父节点、多上游拼接、name 不取、指纹/账号缓存键）；
  `test_run_store.py::TestPreflightSampleRows`（最新已结算运行、指纹不匹配、running/skipped 不取、LIMIT）；
  `test_visualize_manifest.py` 与 `test_diagnostics.py` 钉端到端（引擎纯函数 + 路由接线 + 样本读取失败仍 200）；
  `engine.run._preflight_samples` 的通过/失败两例。
- 本片验证：全量快测 `11118 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟：
  种入一条同指纹的上游运行后，`POST /api/workflow/validate` 返回 `engine.chart_column_missing`（`param=x_field`），
  列存在时无条目。
- 第三片把缺列判定移到数据契约（`engine.missing_column`），`engine.chart_column_missing` 已删除；样本只保留
  “数值列没有数字”的值检查。

## P3 第四片：运行后数据质量断言（2026-11-23）

- `Manifest.postcheck='module:function'`（可选）：节点结算为 DONE 后调用 `postcheck(node, rows, inputs)`——
  本次真正产出的行 + 真正收到的上游表。`problems()` 拒绝非 `module:function` 引用；`doctor.py` 增一行
  `postcheck`，`generate.MATRIX_CHECKS` 与完整性门禁同步枚举。
- `services.validation.engine.postcheck_problems` 复用 validator 的归一化与坏钩子处理；钩子抛错报
  `engine.postcheck_failed`。运行循环在“节点完成”之后调用 `engine.run._postcheck_node`，每条 finding 走
  `add_log(t(message_key, nid, **context))`，随运行日志持久化。
- **只上控制台，不改状态**：行已经产出并存好，质量结论不能让完成节点变失败；下游该跳过仍跳过。
- 第一个使用者 `analysis`：非空输入产出 **0 行**报 `engine.empty_output`（warning）；含
  `filter_rows`/`join_tables`/`anti_join` 的流水线豁免（0 行是用户要的答案），输入为空由运行循环按“跳过”处理。
- 测试：`tests/unit/analysis/test_analysis_postcheck.py`（0 行/扁平与 steps 形状/豁免/非空/空输入）；
  `tests/unit/runs/test_run_postcheck.py`（每个 finding 一行、无钩子不打印、未知类型、dict 结果按无行）；
  `tests/unit/capabilities/test_validation_engine.py::TestThePostcheck`（归一化/坏钩子/畸形结果）；
  `test_analysis_manifest.py` 钉钩子身份；`tests/api/test_nodes_execution.py::TestTheAfterRunDataCheck`
  端到端：`drop_null` 把全空列清成 0 行，节点仍 done、控制台出现 `drop_null` 的警告行。
- 本片验证：全量快测 `11173 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；端到端 API 用例
  （`drop_null` 清空全空列）证明节点仍 done、控制台出现警告行。

## P3 第三片：数据契约（2026-11-23）

- 生产者结算时记录真实输出形状：`run_store.finish_node(..., schema=rows)` 把列并集写进新表 `node_schema`
  （排序后的 `columns_json` + `schema_hash`）；读取按 `node_fingerprint` 匹配，指纹变化时 `begin_node` 删除、
  `invalidate_nodes`/`delete_run` 一并释放；空表不写形状（空输出不是“没有列”的证据）。
- `services.validation.contracts.columns_for(workflow)`：在有效图上取“记录优先、声明兜底”的 `{节点: 列|None}`；
  store 读失败只丢记录的一半并记 `run.schemaReadFailed`，`compute_columns` 的插件错误仍由诊断路由按原有 `ok:false` 处理。
- `WorkflowEngine.validate_detailed(samples=, columns=)`：每个声明了 `ports.read_columns` 的消费者，把所有数据父节点
  （name 不算数据）的列取并集，读列表里不在并集里的列按名报 `engine.missing_column`（warning：上徽章，不拒绝运行；
  节点仍在运行期按名失败）；任一父节点未知就沉默；读钩子抛错报 `engine.read_columns_failed`。诊断、
  `/api/workflow/validate` 与运行门接线，引擎仍不读数据库。`validate()` 只保留 error，`validate_detailed()` 含 warning。
- 图表缺列从样本 preflight 移到数据契约：同一缺列不再出现两条徽章；样本只保留数值角色检查。旧运行没有
  `node_schema` 时，爬虫→图表这一段要等下一次运行才裁决（声明已知的生产者不受影响）。
- 前端：`Diagnostics` 删除 `_reads`/`inputColumns`/`missingColumnProblems`，只渲染 `validation.perNode` 与
  `problems`；`/api/workflow/diagnostics` 不再返回 `reads`；`nodes.schema.referenced_columns` 删除（读取声明归清单）。
- 测试：`test_run_store.py::TestNodeSchema`（排序/摘要/指纹/最新/空形状/stale/invalidate/delete）；
  `test_validation_contracts.py`（记录优先、声明兜底、有效图、store 失败）；`test_validation_engine.py::TestTheColumnContract`
  （缺列/未知上游/name 父节点/无父节点/坏钩子）；`test_workflow_engine.py`（运行门 helper 与引擎接线）；
  `test_diagnostics.py`（不再有 reads、契约与样本各自接线）；前端 harness 场景改为“服务端条目才产生徽章”。
- 本片验证：全量快测 `11140 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟：
  种入一条同指纹运行（`schema=['X']`）后，`x_field=不存在的列` 返回 `engine.missing_column`（warning，`messages` 为空），
  `x_field=X` 无条目，`/api/workflow/diagnostics` 的 `columns.p=['X']` 且不再返回 `reads`。

## P3 第一片：图表契约与一键修复（2026-11-23）

- `services/charts/registry.py` 的 `ChartSpec` 新增 `fields`（`FieldSpec`：参数名、角色、是否必填、表单标签/占位/提示键、
  挂在其下的聚合控件）、`any_of`（箱线图 x 或 y 至少一个）、`controls`（字段之外的控件）、`hint_key`、
  `tokenize_compatible`；`no_x` 改为从 `fields` 派生，`required_params`（H16 的临时规则）删除。
- 30 种图型全部声明字段：柱/折线的 x+y、双轴的 y2、占比堆叠的 `stack_fields`、主题图的 pc1/pc2、散点/直方图的数值列、
  热力图的双分类、桑基/关系图的来源目标、词云的文本列、地图的地区列、模型一致率的三列、文献计量的固定 reads。
- 同一张表派生三个表面：
  - `chart_profiles()` → `/api/node-types` 的 `charts` + 冷启动 `node-types-fallback.js` + `capability-schema.json`；
    `node-types.js` 新增 `charts()`/`chart(key)`（深拷贝）。`panels/node-chart.js` 删除 `CHART_TYPES`/`BIBLIO_CHARTS`/
    `CHARTS_NO_Y`/`CHARTS_WITH_Y2`/`CHART_X_LABEL_KEY` 等 11 个手写数组与标签映射，按 profile 画框、控件与提示。
  - `chart_problems()` → `nodes.executors.visualize:validate_node` 只调用它；未知图型 `engine.chart_unknown`（声明默认
    值作为 fix）、缺字段 `engine.chart_field_missing`（带 `param`）、至少一个 `engine.chart_field_group_missing`；
    `engine.visualize_no_chart`/`engine.visualize_no_x` 删除（空白图型就是清单默认的 `bar`，执行器一直如此）。
  - `read_columns()` 从同一 `fields` 派生（模型一致率的三列现在也参与缺列检查）。
- 验证条目新增 `severity`/`param`/`fix`；`fix` 形如 `{'set': {参数: 值}}`，只允许顶级参数。首个真实修复：
  `engine.chart_unknown` → 声明默认图型、`engine.output_needs_pdf` → `format=pdf`；清单 `enum_param` 越界且有默认值时也
  自动带 fix。设置面板在节点问题列表里为带 fix 的条目画“一键修复”按钮（`applyValidationFix` 走 `updateParam` 再重问服务端），
  并把被点名的字段框描红。
- 测试：`TestRequiredFieldsReachValidation` 遍历 30 种图型（填满契约→无问题；逐个清空必填→按名报告；有默认值→不报；
  未知图型→带 fix）；面板场景新增 scatter/heatmap/stack/dual/未知图型/文献图/一键修复；冷启动目录带图表 profile 且深拷贝；
  `engine.visualize_no_*` 从后端目录与测试清单删除。
- 本片验证：全量快测 `11066 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint `10.00/10`；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟
  10 个 GET 全 200，`/api/node-types` 30 个图表 profile，`POST /api/workflow/validate` 对 heatmap 缺列与未知图型
  返回带 `param`/`severity`/`fix` 的条目。

## P2 前端第四片：表单由清单选择（2026-11-23）

- `Ui` 新增 `hint_key`；`ParamSpec` 新增 `label_key`/`placeholder_key`，并把 `description_key` 接到通用表单。
  `form='schema'` 的清单必须为每个参数声明 `label_key`（`problems()` 按名拒绝），`ui.hint_key` 是表头说明。
- 13 个有手写面板的节点在清单里声明 `ui.form='custom'` + `custom_renderer`：`source`/`comment`/`upload`/
  `resume`/`process`/`analysis`/`tokenize`/`biblio`/`verify`/`fuse`/`accumulate`/`visualize`/`output`。
  `name`/`compile` 留在 `schema`，由通用渲染器按清单画。
- `panels/settings.js::openSettings` 删除整条 `node.type === …` 分支链，只做一次
  `settingsRenderer(node.type)` 分派；各模块用 `registerSettingsRenderer('<id>', {html, mounted})` 注册自己的表单：
  settings.js（source/comment/accumulate/tokenize/output/resume/upload/process）、
  `panels/node-*.js`（analysis/biblio/fuse/visualize/verify/python）、`reusable.js`（reusable）。
- `mounted` 收拢了原先三个按类型执行的挂载动作：resume 填运行列表、upload 拉数据集、process 拉 Ollama 标签。
- 通用渲染器支持 `text`/`textarea`/`number`/`select`/`switch`/`column`/`dataset`/`json`；标签、占位、说明全部来自清单键，
  选项表仍是清单 enum。
- 失败按名：目录未加载 `settings.noCatalogue`、类型不在目录 `settings.unknownType`、清单点名了未注册渲染器
  `settings.noRenderer`；面板不画空表单。`reusable` 不是能力，按类型名注册，保持原来的模板边界表单。
- 测试：`TestSettingsPanel` 新增 `name`/`compile`/未知类型场景；`TestSettingsRenderers` 让每个 custom 清单 id 与注册项
  一一对应，并断言 `openSettings` 不再有类型链；完整性门禁检查 `hint_key`/`label_key`/`placeholder_key`/
  `description_key` 的双语词。
- 设备层回归：`test_a_disabled_node_goes_grey_and_its_downstream_says_so` 原先直接调 `Diagnostics.recompute()`；P2 第二片后
  编辑期判定来自 `/api/workflow/diagnostics`，用例改为 `await Diagnostics.refresh()` 后再测量（禁用/启用各等一次应答）。
- 本片验证：全量快测 `11034 passed, 7 skipped, 386 deselected`；设备层 `215 passed, 5 skipped`；ruff 全绿；
  product/tests pylint 10.00/10；`gen_capabilities.py --check`、`doctor.py --all` 全绿；隔离 data root 冒烟 10 个
  GET 全 200、`POST /api/workflow/validate` 200。

## P2 前端第三片：选项表来自清单（2026-11-23）

- `process` 清单的 `operation` 声明 16 个 enum 值；`panels/settings.js` 的 `PROCESS_OPS` 数组删除，
  面板在渲染时读 `NodeTypes.params('process')`。
- `panels/node-biblio.js` 的 10 个手写选项数组（实体、选择、连线、计数、剪枝、寻径、标签、输出形态）删除，
  统一由 `biblioEnum(name)` 读 `NodeTypes.params('biblio')` 的 enum；工作区 `panels/biblio.js` 也读同一处。
- `node-types.js` 改为幂等全局（`var NodeTypes = window.NodeTypes || {...}`）：一个 harness 可能通过两条
  companion 路径读到同一模块，重复求值不再触发 `Identifier 'NodeTypes' has already been declared`。
- `splits.json` 让 workflow/settings 侧也能拿到目录；测试改为断言面板读清单，而不是逐字比较两份数组。
- 本片验证：全量快测 `11012 passed`；ruff、两档 pylint、生成物 freshness、doctor 全绿。

## P2 前端第二片：校验单一来源（2026-11-23）

- `/api/workflow/validate` 返回 `engine.workflow.validate_detailed()` 的 `messages`/`perNode`/`entries`；
  `/api/workflow/diagnostics` 的同一份 payload 也带上 `validation`，编辑期徽章与运行门读同一套规则。
- `panels/runs.js` 删除整段本地校验 if 链（约 290 行）与 `workflow.js::sourceNodeErrors`（约 120 行）；
  `workflow.validate()` / `validateDetailed()` 改为一次服务端调用，网络失败按名报“无法校验”，不伪装成干净画布。
- `panels/diagnostics.js::recompute()` 读服务端 `validation.perNode`；分析算子的参数徽章仍由浏览器措辞。
- `i18n/checks.js` 只保留仍在前端渲染的词（analysis 参数 + `validate.unavailable`），60 余个只服务于旧 if 链的键删除。
- 测试：删除 `TestValidateGate`/compile/PDF/model_agreement 的 JS 规则用例（Python `WorkflowEngine` 用例已覆盖），
  harness 不再断言本地规则；运行管理/画像/Cookie 门/面板场景改为提供 `/api/workflow/validate` 的应答。
- 新增 API 用例：诊断 payload 的 `validation`、独立 validate 端点、干净画布通过。

## P2 前端第一片：目录单一来源（2026-11-23）

- `/api/node-types` 与生成物 `backend/static/js/node-types-fallback.js` 现在读同一个投影
  `capabilities_kernel.registry.node_schema_entries()`：每个节点带 `params`/`rules`/`ports`/`ui`，
  前端不再有第二份类型表或默认值表。
- `canvas.js` 删除 `_VALID_NODE_TYPES`、`_META_ONLY_TYPES`、`addNode` 的标签表和
  `getDefaultParams` 的全部字面分支；只剩 `source`（矩阵）与 `reusable`（前端模板）两个真实例外。
- `node-types.js` 从生成的 `window.NODE_TYPE_CATALOGUE` 冷启动（懒读，顺序无关），失败时保留它并报出原因；
  `index.html` 在 `node-types.js` 之前加载该脚本。
- `splits.json` 声明 `canvas.js → node-types.js → node-types-fallback.js`，所有 canvas harness 自动获得
  与页面一致的目录。
- 测试改钉生成物：`test_node_plugins.py` 解析 fallback 并对比 `NODE_TYPES`/rows/seeds；
  `test_frontend_node_types_js.py` 驱动真实画布验证冷启动、失败保留与深拷贝。
- 当时未做：schema 表单渲染器；已在“P2 前端第四片”完成（`openSettings` 只做一次 `ui` 分派）。

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

2026-11-22 第二轮死代码清理（AST 全仓库扫描，逐项人工确认）：
- 迁移残骸：15 个已迁移 executor 的 `NODE_TYPE`（清单已声明类型；`source` 迁移后最后一个也删掉）、
  `nodes/catalog.py` 的 `plugin_for`/`types_in` 与 `nodes/__init__.py` 的再导出（无人按名字使用）、
  `nodes/defaults.py` 的空 `_DECLARED` 与合并函数（直接投影清单）。
- 无调用取名字/兼容读：`core/machine.py` 的 `driver_executable_name`/`node_executable_name`/`_installer_export`
  与 `DRIVER_FILE_NAMES`；`crawlers/engine/pacing.py` 的 `pace_scale`/`page_scale`/`gentle_crawl_on`
  与 `_PAUSE_DIMENSIONS`（`page_nap` 仍读 `crawl_page_scale`，所以设置项保留；`crawler_rules.md` 已改指 `nap`）。
- 无人引用的 helper：`services/biblio/formats/common.py` 的 `split_affiliations`/`refs_payload`/`has_columns`/
  `header_has`/`parse_ref`；`services/components/install.py::verify_component`；
  `services/models/manifest.py::is_legacy_manifest`；`ai/plugins.py::manifest_json`。
- 无引用方法：`EmotionAnalyzer._train_ml`、`Crawler.scroll_to_bottom`、`PlayerUI.wait_window`、
  `XiaohongshuCrawler._extract_count`、`FilesMixin.forget_run_files`。
- 无引用常量：`GRAPH_KEYS`、`SCORE_MODES`、`doctor.CHECKS`、bilibili `REPLY_API`、cnki `ROW_PAUSE`、
  xhs comments `OPENER_RE`、`RESTART_KEYS`/`CRAWL_KEYS`、`DIVERGING_CMAP`/`SEQUENTIAL_CMAP`、`STATE_CANCELLED`。
- 保留（扫到但确认在用）：`services/charts/options/relations.py` 的 `_model_agreement`/`_sankey`（`@builder`
  装饰器注册，名字不在调用点出现）；`services/biblio/formats/*` 与 `i18n_catalog/sched.py`（按注册表/列表加载）。
- 本片验证：2324 passed（capabilities/analysis/biblio/crawlers/charts/update/ai/node-types API），
  208 passed（node plugins + node-types API + capabilities），ruff 全绿。


## P6 第一片：能力技能目录（L1/L2）与七段内容（2026-11-24）

- **清单第七段成为技能的唯一家**：`Ai` 新增 `when_not_to_use`/`prerequisites`/`template`/`acceptance`；
  16 个节点清单全部补齐七段（何时用/何时不用含最近可混淆能力、前置、步骤、示例、模板、失败、验收）。
  `Manifest.problems()` 对 `node` 拒绝缺段、模板 `type` 不符、模板参数超出枚举。
- **派生而不是复制**：`capabilities_kernel/knowledge.py` 投影 **L1**（id/分组/一句话/何时用/何时不用/文档）
  并渲染 **L2** 正文（七段 + 参数表 + 可达工具）；参数表在渲染时从 `manifest.params` 重读（测试改默认值
  验证正文随之变化）。`ai/knowledge.py` 只加本地化标题与 `AIError` 具名拒绝。
- **两个常备工具**：`skill_catalog`（`kind`/`query`/`limit`）与 `skill_load`（正文 + 模板 + 工具名）进入
  `UNIVERSAL_TOOLS`，任何技能都能用；未知 kind 报 `ai.skillKindBad`，未知技能报 `ai.skillUnknown`。
- **项目事实只放 L1**：`project_facts()` 增加“能力技能”一节（每技能一行摘要），正文按需展开，不占系统提示。
- **生成物**：`gen_capabilities.py` 额外生成 `docs/capabilities/skills/index.md` 与每能力一页；页面与
  `skill_load` 共用 `knowledge.render`，`docs/capabilities/` 也加入 `docs_search` 的文档根。
- **门禁/测试**：完整性门禁要求七段并证明模板可被引擎接受（不得产生参数/矩阵拒绝）；生成物 freshness 覆盖
  新页面；新增 `tests/unit/capabilities/test_skill_catalog.py`、`tests/unit/ai/test_knowledge_tools.py`；
  `test_generate.py` 的固定产物集合改为“六个固定产物 + `docs/capabilities/skills/` 下的能力页”。
- **验证**：按 2026-11-24 用户要求，小改动只跑相关域、不再每次全量——AI/能力/门禁/i18n **937 passed**，
  同一批更早的 api+frontend+i18n **4638 passed**；`gen_capabilities.py --check` 通过；ruff 全绿；
  product/tests 两档 pylint **10.00/10**。本片按新策略没有跑全量 fast（留给下一批收口）。
- **测试策略（同时写入 AGENTS/practices/testing-lanes）**：小改动只跑它碰到的域 + 命名它的门禁；全量 fast 只在
  大改动、跨域改动或一批（约 4 刀）收口时跑一次；已经证明过的文件不为文档换行重跑。
- **未做（明确声明）**：算子/图表/平台技能要等 P7 把这三类清单化；`@技能` 强制加载、配方 FSM、工具分层路由
  与严格模式仍是 P6 待办。

## P4/P5 收口：旧 AI 引擎与蓝图已删除（2026-11-23）

- **删除**：`backend/api/ai.py`；`backend/ai/agent.py`、`store.py`、`costs.py`、`approvals.py`、
  `approval_preview.py`、`references.py`、`plugins.py`；`runtime/flags.py::ai_workspace`（已无在途开关）；
  `api/ai.py` 的 `_workspace_conversation` 过渡桥。对应的 `tests/api/test_ai_*.py` 旧引擎用例随模块删除，
  有价值的覆盖改写为直接单测/新表面用例。
- **`backend/ai` 只留领域事实**：providers、context（项目事实+文档搜索）、skills（BUILTIN）、tools（领域工具）、
  validators/previews、vocabulary/workflow_draft、workspace（文件夹选择器+表格导入）、monitors（事件词汇）、
  file_text、dataset_access、files（搜索/抓取）、errors/types/scopes/environment。
- **宿主编排补齐（0.1.22）**：`CaiXiHuiHost` 现在提供 `environment()`（cloud/desktop/local）、`bind_account`
  （账号树 + 线程语言）、`search/fetch`（浏览器密钥随请求到工具上下文）、`import_table`、`script_library`、
  `python_runtime`（画布与 AI 共用一个脚本库/解释器）、`universal_tools`、`event_bus`（把
  `runtime.run_events` 映射为框架监视事件）、工具权限门（cloud/python/机器管理员）。
- **修复的真实缺陷**：
  - 新表面 `account()` 曾把 `Account` 对象的 repr 当账号 id（登录账号的路径全错），已改为 `user_id`。
  - 监视器 POST 旧前端发 `spec`，新路由只读 `conditions`（手动建监视器从不生效）；现在在 host 边缘把
    `spec` 规范化成框架 conditions，并把 armed/active、交付行映射回前端形状。
  - 数据集读取授权（`request_dataset_access`）改为“永远询问”的审批工具：用户批准后落 grant，行数仍按
    `dataset_access` 预算扣减；不再存在模型自行授权。
  - 工作文件夹只有一个根：`/workspace` GET/POST 与工具都用框架 workspace；browse/pick 只做机器选择器，
    非管理员按名拒绝。
  - `/stop` 与删除会话会同时结束该会话 scope 的子进程（进程面板 parity）。
  - POST 体规则统一：非对象 JSON 一律 400（`api/ai/ws/*` 全部纳入 body 矩阵）。
- **前端**：保持不变，只把请求切到 `/api/ai/ws`（`AI_BASE` + 47 处调用及 studio/watch/llm-settings/
  node-python/workflow）。实机浏览器用例（本地模型真实回答 + 实时行 + 停止）通过。
- **验证**：全量 fast **10964 passed**（7 skipped）；`ruff check`/`format --check` 全绿；product/tests 两档 pylint
  **10.00/10**；隔离数据根启动服务器（端口 5057）后 `/api/config`、`/api/ai/ws/health`、`/api/ai/ws/bootstrap`、
  `/api/node-types`、`/api/workflow/list` 均 200；本地 Ollama 经 `/api/ai/ws/chat` 一轮真实回答 37s（text/usage/done）。
  浏览器版 AI 实机用例本轮未能重跑：Selenium 启动在当前机器上挂起（无失败断言），此前同一前端切换已 2 passed。
- **仍未做（明确声明，不静默）**：
  1. 旧 `data/users/<id>/ai.db` 的历史会话/记忆/技能**不迁移**；新表面从空工作区开始。需要历史时用旧版
     本导出，本版本没有导入器。
  2. 框架的 `apply_artifact` 宿主钩子未实现写入；前端产物卡片走各自的类型端点（workflow/记忆/监控/图表），
     `/artifacts/<id>/apply` 直接调用时按名拒绝。


## P4 接入第五片：node trace 迁到框架 store（2026-11-23）

- `services/llm_trace.py` 不再写旧 `ai.db`：会话、intro、追问、流式行、样本、结果全部进 `AgentWorkspace`
  store；会话标题仍是 `run | node | op #n`，`traces_for_run` 按 run 前缀检索，`meta.skill=node_trace`。
- 工作区目录按账号解析：`ai_host.manager` 用 `paths.active()`（本地所有者）或 `paths.for_user(id)`，
  不再把 `default` 当账号 id。
- `/api/ai/ws` 增加 `GET /traces/<run_id>`、`POST /traces/<id>/apply`；会话详情返回 `skill` 供 trace 面板识别。
- 旧 `api/ai.py` 的 trace 列表已读新 store（同一 `services.llm_trace`），但打开会话仍走旧 store——前端切换时一并解决。
- 测试：框架 store 的 trace 用例（prompt/answer 行、run 检索、结果 provenance、传统模型样本）替换旧 sweep 用例；
  AI/analysis/API **1584 passed**。
- 下一步：前端切 `/api/ai/ws` → 删旧 `api/ai.py`/`backend/ai`/开关 → 旧 ai.db 历史。

## P4 接入第四片：host 端点补齐（2026-11-23）

- `/api/ai/ws` 补齐旧前端在用的 host 端点：workspace（GET/POST/browse/pick）、artifacts/preview、chart/preview、
  workflow/validate、rerun、monitors/catalog、python/install、plugins/install、codebooks、multipart 上传（文本/图片
  存入框架文件行 `meta`，chat 的 attachments 接受文件 id）。
- 框架 0.1.20：`add_file(..., meta=)`；0.1.19：`test_provider` 返回 model/latency/reply。
- 测试：上传→按 id 附件进模型、预览/图表/校验/重跑拒绝、codebooks/插件冒烟；蓝图用例 13 passed。
- **仍剩**：node trace（`services/llm_trace` 仍写旧 store，需迁到框架 store/turns）；前端切到 `/api/ai/ws`；
  删旧引擎与开关；旧 ai.db 历史。

## P4 接入第三片：新表面补齐通用路由（2026-11-23）

- `/api/ai/ws` 现有约 40 条路由：chat/turns/events/steps/trace、answer/stop/steer/retry/command、pending/inbox、
  bootstrap/providers、会话 CRUD+导出、记忆、产物+apply、技能/插件、监控+投递、文件、Python、设置、用量、上下文、
  引用、健康检查。账号来自 `account_context`，附件在 host 侧用 `ai.file_text` 抽取，`/init` 由 host 注册。
- 测试：聊天→turn→重放、关流后续跑、命令/停止/steer、附件进模型、会话/记忆/产物/设置/用量、通用路由冒烟；
  282 个 AI 相关用例通过。
- **仍未完成（P4 DoD 不勾）**：领域路由（traces/harness/workflow draft/codebooks）仍在旧 `api/ai.py`；旧引擎未删；
  旧 `ai.db` 历史未迁移；parity 矩阵未逐行补齐。

## P4 接入第二片：/api/ai/ws 新表面（2026-11-23）

- `backend/ai_host/manager.py`：每账号一个 `AgentWorkspace`，目录 `users/<id>/ai_workspace`（**不复用旧 ai.db**）；
  `close()` 先结束 runner 再关库。
- `backend/api/ai_workspace.py`：`/api/ai/ws` 的 `/chat`（SSE/非流式）、`/turns/<id>`、`/turns/<id>/events`
  （`after`/`Last-Event-ID`）、`/turns/<id>/steps|trace`、`/pending`、`/inbox`、`/answer` `/stop` `/steer` `/command`。
- `app.py` 在 `runtime/flags.py` 的 `ai_workspace` 开关（默认开，owner=P4 AI 接入，remove_by=2027-03-01）下注册；
  旧 `/api/ai` 原样保留。
- 测试：裸 Flask + 临时账号根跑通 chat → turn → 重放 → command / stop / steer / pending；旧 app 启动用例不受影响。
- 仍待：附件抽取、设置映射、`/init`、parity 矩阵、旧引擎删除。

## P4 接入第一片：ai_host 宿主适配器（2026-11-23）

- `backend/ai_host/`：`CaiXiHuiHost(DefaultHostAdapter)` 把领域事实/工具/技能以**委托**方式交给框架：
  `facts()` ← `ai.context.project_facts()`；`tools()` 逐条转换 `ai.tools.TOOLS`（handler 原样保留，`mutating`/
  `always_ask` 复用 `APPROVAL_TOOLS`/`ALWAYS_APPROVAL_TOOLS`）；`skills()` 转换 `ai.skills.BUILTIN`。
- 框架自带的同名工具（`project_facts` 等）不重复声明——框架的版本读同一份宿主事实；`FRAMEWORK_TOOLS` 明确列出。
- 门禁同步：`test_doc_paths._PROJECT_DIRS` 与本地包清单加入 `ai_host`；`desktop/requirements-runtime.txt` 声明
  vendored wheel，requirements 门禁从 wheel METADATA 取发行版名。
- 测试：全量工具/技能与旧注册表一一对应、审批标志来源、`AgentWorkspace(CaiXiHuiHost)` 能启动。
- **仍待**：路由迁移到 `AgentWorkspace`（`/chat` 返回 turn_id、`/turns/<id>/events`）、本地附件抽取、设置映射、
  `/init`、parity 矩阵、`runtime/flags.py` 双路径开关、薄门面与删旧引擎。

## P4.0 第十五片：命令与压缩（2026-11-23，框架 0.1.17 —— P4.0 收口）

- `CommandRegistry`：框架 `/status`（会话/最近 turn/pending/inbox/usage/mode）、`/skills`、`/mode`
  （写会话偏好，下一轮默认遵守）、`/compact`（清旧 user 行的 `context_text`，不改写转录）；宿主用
  `HostAdapter.commands()` 注册 `/init` 等，重名按 `command.duplicate` 拒绝。
- Flask 增加 `POST /command`（name/args/conversation_id）。
- 同一轮的两个 provider span 可能共享 `started_at` 的微秒，trace 树曾因此漂移；改为 rowid 插入顺序（`aef340c`），
  测试连跑 10 次稳定。
- **P4.0 至此全部完成（F1–F18）**。框架 0.1.17，220 条测试全绿。
- 下一步：P4 接入（`backend/ai_host`）——HostAdapter 领域实现、领域技能/工具、本地附件抽取、设置映射、`/init`、
  parity、双路径开关、薄门面。

## P4.0 第十四片：行任务并发（2026-11-23，框架 0.1.16）

- `chat_once` 走每供应商信号量：`ProviderSpec.max_parallel` → 设置 `providers.max_parallel`（默认 4）；`local_only`
  固定 1（一个守护进程、一次模型加载）。轮次内的工具调用仍在轮次线程上按序执行。
- 测试：设置上限、供应商上限覆盖设置、本地串行；213 条全绿。
- **P4.0 只剩 F18**：命令注册表 + `/status` `/skills` `/mode` `/compact`（`/init` 留 host）。

## P4.0 第十三片：结构化输出能力（2026-11-23，框架 0.1.15）

- `ChatRequest.output_schema`：只有声明 `structured_output` 的供应商会收到；OpenAI 兼容传输映射为
  `response_format={'type':'json_schema', …}`，未声明的按 `capability.refused` 拒绝（不拿散文冒充结构化结果）。
- `thinking` 继续同一规则；Ollama 不声明 `structured_output`，其 `think:false` 行为保持不变。
- 测试：声明者收到 schema、未声明者按名拒绝、OpenAI 传输映射、thinking 拒绝、Ollama 不声明；210 条全绿。
- 下一片：F16 并发 → F18 命令/压缩。

## P4.0 第十二片：OTel GenAI trace（2026-11-23，框架 0.1.14）

- `agent_traces`：每次 provider 调用与每次工具调用一行；属性用 `gen_ai.system`/`gen_ai.request.model`/
  `gen_ai.usage.*`/`gen_ai.tool.name`/`gen_ai.operation.name`，只含 id、状态、token 与耗时，**不含正文**。
- 工具 span 的 `parent` 是发起它的 provider span；`trace_tree()` 返回嵌套结构。`Tracing` 全部 best-effort：
  写失败只丢观测，不影响已经付费的轮次。
- 读接口：`traces(turn_id)`、`trace_tree(turn_id)`、`GET /turns/<id>/trace`。测试覆盖树形、无正文、崩溃 span 的
  `error`、trace 写入失败仍完成轮次；205 条全绿。
- 下一片：F15 供应商能力 → F16 并发 → F18 命令/压缩。

## P4.0 第十一片：产物校验与预览（2026-11-23，框架 0.1.13）

- `ArtifactRegistry`：`HostAdapter.artifact_validators()`（kind → `payload -> list[str]`）与
  `artifact_previews()`（kind → `payload -> dict`）在构造时注册。
- `present_artifact` 先校验：有问题 → 错误 tool_result `artifact.invalid`，**不落库**；通过后存库，事件带
  `preview` 与 `unvalidated`（未声明的 kind 如实标为未校验，交给宿主按纯文本渲染）。
- `apply_artifact` **再次**校验（payload 现在是什么就是什么），失败按名拒绝，宿主永远拿不到坏 payload；
  预览构建失败不影响卡片呈现。
- 测试：有效/无效/未声明 kind、apply 前复检、有效产物只交给宿主一次；201 条全绿。
- 下一片：F14 trace → F15 供应商能力 → F16 并发 → F18 命令/压缩。

## P4.0 第十片：附件接缝（2026-11-23，框架 0.1.12）

- `attachments.prepare()`：宿主通过 `context_payload['attachments']` 交来 `{name, text, image, file_id}`；文本有界并
  随 user 行持久化（块 + `meta.attachments`）；图片只在供应商同时声明 `vision` 与 `inline_images` 时以 OpenAI
  兼容的 image part 送入，否则按 `attachment.visionRequired` / `attachment.inlineRequired` 拒绝（超限另报
  `attachment.imageTooLarge`）。框架**不读文件、不解析文档**——抽取是 host 的事。
- `provider_messages` 会把 user 行的图片块还原成 content parts；`replay_context` 不再把多模态 content 字符串化。
- **顺带修掉一个真 bug**：user 消息在每次 provider 请求里被重复追加（存好的 user 行之后又拼了一遍）。现在只有
  `retry` 需要补一次（历史以旧回答结尾），新 turn 与 resume 都不补；附件测试断言一个 turn 只有一条 user 消息。
- 测试：文本附件、内联图片 + 重放、纯文本模型拒绝图片、有 vision 无 inline_images 拒绝、单一 user 消息；196 条全绿。
- 下一片：F11 产物 validator/preview → F14 → F15 → F16 → F18。

## P4.0 第九片：retry 还原原轮（2026-11-23，框架 0.1.11）

- `retry()` 用 user 行所属 turn 的 provider/model/skill 构造请求，而不是今天的默认值。
- 重试分支不再重建上下文：provider 历史由 `replay_context()` 把该 user 行自己的 `meta.context_text` 放回，
  重读实时 sources 会描述“现在”而不是被复现的那次运行；`meta.context.context_restored` 记录这一点。
- 不新增 user 行；测试断言三件套（provider/model/skill）与单一 user 行。框架 192 条全绿。
- 下一片：F10 attachment 接缝 → F11 → F14 → F15 → F16 → F18。

## P4.0 第八片：plan/build 模式（2026-11-23，框架 0.1.10）

- `context_payload['agent_mode']` = `plan` / `build` / 空；未知词按 `mode.unknown` 拒绝，meta 事件带 `mode`。
- plan 模式把 `mutating`/`always_ask` 工具从 **schema 与 allowed 列表**一起移除；`_dispatch` 的“未提供即拒绝”
  再挡一次，回放的历史也绕不过去。
- 测试：plan 隐藏/拒绝写入、build 默认、未知模式；框架 191 条全绿。
- 下一片：F3（retry 还原原轮），随后 F10 → F11 → F14 → F15 → F16 → F18。

## P4.0 第七片：多问题卡（2026-11-23，框架 0.1.9）

- `ask_user_question` 接受 `questions[]`（1–5）；单问题仍走旧的 `question`/`options` 形状。
- 多问题事件只带 `questions`（不伪装成单问题）；答案以与问题对齐的列表按同一 `call_id` 回填；长度不符报
  `question.answersExpected`。
- 畸形/超过 5 个返回 `badArgs`，并把错误结果写进转录——此前不写，会留下孤立 `tool_use`，现在由同一修复覆盖。
- 测试：schema、单卡两问、成组回答、长度不符、六个问题；框架 187 条全绿。
- 下一片：F9 plan/build → F10 → F11 → F14 → F15 → F16 → F18 → F3。

## P4.0 第六片：步骤幂等与注册收口（2026-11-23，框架 0.1.7/0.1.8）

- **F12**：`agent_steps` 每次工具调用一行（`running` → `done`/`error` + 结果），覆盖普通工具与审批后的执行；
  同一 `(turn_id, call_id)` 再次出现时重放记录，**不再执行**；启动把遗留 `running` 标为 `interrupted`
  （`{'error': 'step.interrupted'}`），下一次同样不重跑。`steps(turn_id)` 与 `/turns/<id>/steps` 可读。
  说明：框架的“run”就是 `turns` 行（一个生命周期对象，不新增第二张 run 表）；工作流 Run 仍是 host 域。
- **F13**：`HostAdapter.tools()` 在 `AgentWorkspace` 构造时注册一次；与内置/控制工具或另一个宿主工具重名按
  `tool.builtinConflict` 拒绝；技能白名单仍过滤工具。
- 测试：步骤记录/重放/崩溃恢复、宿主工具注册/重名拒绝；框架 182 条全绿。
- 下一片：F8 多问题卡 → F9 → F10 → F11 → F14 → F15 → F16 → F18 → F3。

## P4.0 第五片：审批策略（2026-11-23，框架 0.1.6）

- `agent_workspace/policy.py` 的 `PolicyEngine.decide(spec, auto=)` 是唯一判断点：读工具不询问；`mutating`
  在 auto-approve 关闭时询问；`always_ask`（删除/覆盖/资源授权）**永远**询问，`session_allowed=False`。
- `ToolSpec.always_ask` 由 host 在注册工具时声明；审批卡只提供“允许一次/拒绝”，`Approvals.consume(once_only=True)`
  拒绝 session 授权，`settle` 对未提供的 scope 不授予任何东西。
- 测试覆盖三类决策、伪造 session 答案、同一参数的一次授权、以及“下一轮再问一次”。
- 下一步：F12（`agent_runs`/`agent_steps` + 幂等恢复）→ F13（注册收口）→ F8…。

## P4.0 第四片：steer（2026-11-23，框架 0.1.5）

- `steer(conversation_id, text)` 写 `turn_commands`；runner 在**两轮之间**把指引作为一条 `user` 行加入本轮
  （`meta.steer`）并发 `steer` 事件——这是唯一不会把 tool_call 和它的 result 拆开的位置。
- 最后一个安全边界之后才到的指引进 `turn_inbox` 成为下一轮，不会被静默丢弃；没有活动 runner 时 `steer()` 返回
  `False`。
- Flask 增加 `POST /steer`；测试覆盖注入、事件、用户行与“无活动轮次”。框架 168 条全绿。
- ADR-003 的 turn 部分至此全部落地（TurnFSM、事件、runner、answer/stop/steer、邮箱、重启恢复）。

## P4 归属复核（2026-11-23）

rewrite-plan 的 P4 清单原先混着“框架通用能力”和“采析绘接入”。按“换一个宿主是否也需要”重新归类：

- **移到 P4.0（框架）**：SSE 续传/后台 turn、限制语义 0=不限 + usage meter、`/status` `/skills` `/mode` `/compact`
  （新增 F18；`/init` 仍留 host）、provider 结构化输出/thinking 能力声明、并发与限流、run/turn 记录与幂等恢复、
  权限策略引擎、OTel trace、多问题卡、plan/build、attachment 接缝、产物 validator/preview、retry 还原原轮。
- **留在 P4 接入（host）**：ai_host、领域技能/工具、工作流/产物/源码工具、本地附件抽取、设置项到框架语义的映射、
  `/init` 注册、旧前端事件名映射、parity 矩阵、双路径开关、薄门面。
- **共享但一侧一半**：`answer` 用框架 `call_id`，旧前端 `question_id`/`message_id` 的派生属 host 的 HTTP 层；
  附件由 host 抽取文本，框架只收结果。

## P4.0 第三片：邮箱（2026-11-23，框架 0.1.4）

- 待答期间发来的普通消息不再取消问题、也不再静默 settle：`ask()` 入 `turn_inbox`，返回
  `notice(key=turn.queued, mailbox_id)` + `done(stop_reason=queued)`，问题原样保留。
- `inbox(conversation_id)` 列出排队消息；客户端在问题答完后带 `context_payload={'mailbox_id': …}`（和自己的 Key）
  再发一次，服务端 `take_inbox` 取走一次后执行——排队不替用户花钱，Key 永不入队。
- 未知/已取走的 mailbox id 按 `turn.unknownMailbox` 拒绝；`delete_conversation` 一并清理。
- 仍开放：`steer`（安全边界插入指引）与 F6–F16。

## P4.0 第二片：轮次脱离请求线程（2026-11-23，框架 0.1.3）

- `ask()` 建 turn 后起后台 `TurnRunner`，自身只 `subscribe(after)`：关流、刷新、切会话都只结束订阅，答案仍落盘。
- 事件带 `seq` 与 `v=EVENT_PROTOCOL`；`subscribe(turn_id, after)` 与 Flask 路由 `/turns/<id>`、
  `/turns/<id>/events`（`after` / `Last-Event-ID` / `?stream=0`）提供重连与重放。
- `stop` 先写 `turn_commands`，runner 在轮次边界取走并置取消位；没有活动 runner 返回 `False`。`answer` 复用原
  `turn_id`，重复答案按 `question.unknown` 拒绝。
- `HostAdapter.bind_account(account)`：runner 线程启动先绑定账号数据根（线程继承不到宿主上下文）。
- `close()` 先停活动轮次并 join 再关 store——否则后台写会撞上临时目录清理（本片实测到一次 access violation）。
- 待答期间的新消息改为按名 `turn.awaitingUser` 拒绝，不再静默 settle 成 skipped；排队邮箱是下一片。
- 测试：163 条全绿（新增 runner/订阅/stop/bind_account/重连路由/关流不停轮）。

## P4.0 第一片：TurnFSM + 持久事件 + 中断恢复（2026-11-23）

按 ADR-003 先落数据模型，不先写 runner（避免“先做界面再改表”）：

- 框架 `agent_workspace/fsm.py`：`TURN` 表 `new→context→streaming→tool→awaiting_user→streaming→settled|interrupted`；
  `require()` 对非法移动按“机器名 + 两端状态”拒绝；测试逐对穷举合法/非法。
- `store.py` 新增 `turns`（状态/停止原因/解析后的 provider/model/skill）、`turn_events`（`seq = MAX(seq)+1`）、
  `pending_calls`（call_id/conversation/account/turn/kind/tool/args/provider/model/skill）。删会话时一并清理。
- `service.ask()`：每轮建行、逐事件落盘并推进状态；`answer()` 复用 pending 行的 `turn_id`，`_resume` 在同一把锁里
  `claim` 一次 → 重复答案按 `question.unknown` 拒绝；重启时 `settle_interrupted_turns()` 只收尾真正半途的 turn，
  `awaiting_user` 保留。新增公开读：`turn()`/`turn_events(after)`/`pending()`。
- 待答期间的普通新消息仍按旧行为 settle 为 skipped（邮箱是下一片）；`answer` 对已结算的 call 现在按名拒绝，不再
  静默开新轮。
- 同时补 ADR-002 的一个门禁缺口：`test_capability_completeness.py` 现在拒绝“清单指向浏览器未注册的
  `custom_renderer`”；`capabilities-kernel.md` 说明文档哈希由生成物 digest 承载（写回清单会让文档与清单互相绑架）。
- 仍开放：runner（脱离请求线程）、`turn_commands`（stop/steer）、邮箱、事件 `v`/`Last-Event-ID`、R10 Asset、
  `ai_host` 双路径开关。

### 对照 ADR-001/002/003 的复核（2026-11-23）

- **ADR-001**：P1–P3 都是逐域迁移，旧节点表已删除（`nodes/catalog.py` 现在只是清单投影）；P4 的“双路径开关”此前
  只写在 parity 文档的流程里，现已变成 rewrite-plan 的未勾选项，接入时必须在 `runtime/flags.py` 声明。
- **ADR-002**：九段、注册表、六类生成物与 freshness 门禁都在；**缺的两个门禁已处理**——自定义表单 renderer 现在
  会被门禁核对（浏览器里没有人 `registerSettingsRenderer` 的 id 直接红）；“文档哈希”按“生成物携带清单 digest”
  解释并写进 `capabilities-kernel.md`（写回清单是反向依赖）。技能七段属于 P6，保持未勾选。另删掉了
  `nodes/catalog.py` 里空置的旧字面表与合并函数——16 个节点全在清单里，旧表是残骸。
- **ADR-003**：TurnFSM、事件 seq、pending 持久化、重启恢复已落地；runner、命令表、邮箱、事件版本号仍未勾选，
  顺序写在 rewrite-plan。
- **R10**：`DataAsset` 仍只有骨架；`node_schema` 是形状半部，物化列入 P4 未勾选项，不能算 P3 已完成。

## P4.0 决策：框架先完善，再接入（2026-11-23）

用户追加约束：**AI 框架可能还不完善；先按通用标准把框架补到能承载采析绘的全部 AI 功能，再做接入。框架必须保持
宿主无关、可扩展、架构合理，不为采析绘加领域分支；允许重构，必要时重写单层。**

- 顺序：P4.0 框架完善（F1–F16，见 `framework-parity.md`）→ `backend/ai_host/` → `/api/ai` 薄门面 → 前端。
- 架构基准：保留 `AgentWorkspace` 门面与分层；把 `store.py`/`agent.py`/`tools.py` 的持久化、策略与循环拆成
  “端口 + 适配器 + `TurnFSM`”；某一层无法承载所需通用能力时重写该层、保留公开入口并升版本。
- 通用性门禁：框架仓库里不得出现节点/数据集/工作流/图表/平台等领域词；宿主只经 `HostAdapter` 注入。
- 依赖节奏：框架改动 → 框架测试全绿 → 重建 wheel（替换同一文件、更新 sha256）→ 本仓库 AI 测试 → 提交流程不变。
- 已完成：`8b6cc478` 把 wheel 钉版、`vendor/README.md`、requirements 门禁与 Docker 安装路径落好。
- 已完成 F17：框架仓库 `7323f2e` 新增 `HostAdapter.turn_finished(summary)`——每次 `ask()` 结束后一次，
  `completed`/`paused`/`cancelled`/`error`/`aborted` + ≤240 字预览；宿主据此做桌面右下角通知与提示音，框架不知道
  窗口焦点，钩子异常也不打断轮次。框架升到 0.1.1（139 个测试全绿），`vendor/` 已替换新 wheel。
  **采析绘接入时**：`ai_host` 覆写该方法，只在窗口不在前台或用户开了提醒时弹窗/响铃；不要在钩子里做网络或长任务。

## 下一步（按顺序）

1. **P3 第二片已完成**：`Manifest.preflight` + `samples_for`（≤200 行、指纹匹配、30 秒缓存）+ visualize 数据检查；
   验证条目带 `param`/`severity`/`fix`，设置面板有一键修复。见“P3 第二片”。
2. **P3 第三片已完成**：`node_schema` 记录生产者真实列集合 + `schema_hash`；`contracts.columns_for` 记录优先、
   声明兜底；引擎按 `read_columns` 报 `engine.missing_column`，前端删除差集。见“P3 第三片”。
3. **P3 第四片已完成**：`Manifest.postcheck` + 运行循环的控制台告警；analysis 0 行检查。P3 清单全部勾选。
   见“P3 第四片”。
4. **P4 依赖已完成**：wheel 钉版 + 门禁 + 镜像安装路径（`8b6cc478`）。
5. **P4.0 第一片已完成**：框架 `turn_finished` 通知（`7323f2e`，0.1.1）；ADR-003 的 TurnFSM + `turns`/`turn_events`/
   `pending_calls` + 幂等 answer + 重启恢复（框架 `47496d0`，0.1.2）。
6. **P4.0 第二片已完成**：后台 runner + 订阅续传 + 持久 stop + `bind_account` + 重连路由（框架 `e99a6d8`，0.1.3）。
7. **P4.0 第三片已完成**：邮箱（待答期间的新消息排队，带 `mailbox_id` 再发才执行）（框架 `30d1d5d`，0.1.4）。
8. **P4.0 已完成（框架 0.1.17，F1–F18 全勾）**。下一步进入 **P4 接入**：`backend/ai_host`（HostAdapter 的 facts/
   sources/tools/skills/resolvers/artifacts/UI）→ 领域技能/工具迁移 → 本地附件抽取 → 设置映射 → `/init` →
   parity → `runtime/flags.py` 双路径开关 → 删旧引擎/薄门面。R10 Asset 物化可以并行。


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
- **H16 图表**：`ChartSpec.fields` 是唯一声明（P3 起含字段角色/必填/表单标签）；`WorkflowEngine.validate_detailed`
  经 `chart_problems` 读它，先 `with_chart_defaults`；stack_pct 缺失时整张画布在运行前被 rejected，控制台按名给出 `stack_fields`。

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
