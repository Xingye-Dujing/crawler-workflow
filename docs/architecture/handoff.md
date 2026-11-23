# 交接与压缩检查点

- 日期：2026-11-23
- 分支：`main`
- 最后提交：`8b6cc478 功能更新：钉版 agent-workspace 框架 wheel（vendor + 门禁 + 镜像安装路径）`
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
5. **P4.0 第一项已完成（F17）**：框架 `turn_finished` 通知接缝（框架 `7323f2e`，0.1.1）。
6. **下一步：P4.0 框架完善 F1–F4**：`pending_calls` 持久化与 rehydrate、`answer(call_id)` 幂等、未答问题不被新消息
   取消 + 邮箱、retry 还原原轮、事件 `seq`/续传。框架测试全绿后重建 wheel，再更新本仓库的 parity 与测试。
   `core.asset.DataAsset` 物化可以并行，但不阻塞框架。


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
