# 能力内核（capabilities_kernel）

> 状态：P1 骨架已落地；`tokenize` 是 pilot。目标契约见 [ADR-002](ADR-002-capability-manifest.md)。

`backend/capabilities_kernel/` 是“一个能力只声明一次”的落点。它替换的不是业务实现，而是**同一事实被复制到十几个表面**的做法：节点类型、默认参数、端口契约、验证、UI、AI 知识、测试和文档，都从同一份清单派生，或者由同一套门禁拒绝。

## 目录

```text
backend/capabilities_kernel/
  manifest.py              # 九段 dataclass + 结构校验 + manifest digest
  registry.py              # 发现/去重/排序/懒加载/版本检查
  nodes/
    <id>/manifest.py       # 一个能力一个目录（迁移目标）
    <id>.py                # 单文件形式（兼容期，同一 id 两边都有会被拒绝）
```

清单只声明契约，行为仍在 executor 里。清单**不得**导入 pandas/Selenium/Flask 或上层包：`nodes.catalog` 在解析 DAG 时会读它，启动路径必须保持轻。

## 九段

| 段 | dataclass | 回答的问题 |
|---|---|---|
| 身份 | `Identity` | id/kind/version/标题键/分组/目录位置/何时使用 |
| 参数 | `ParamSpec` | JSON Schema 子集（type/default/enum/min/max/required）+ 表单 widget/label/placeholder/hint 键 |
| 端口 | `Ports` | 行形状、输入数、`emit_columns`/`read_columns` 的 `module:function` |
| 执行 | `Execution` | 懒加载的 `module:function`、控制台静默策略 |
| 验证 | `Rule` | 运行前的声明式拒绝（`required_param`/`enum_param`/`upstream_required`/`no_input`/`requires_output`）、`validators` 指向的节点专属检查，以及可选的 `preflight`（对上游样本的数据检查） |
| UI | `Ui` | 默认 schema 表单（可带 `hint_key`），或 `custom_renderer` 逃生口 |
| AI | `Ai` | 七段技能：工具名、摘要、何时不用、前置、步骤、示例、模板 JSON、失败模式、验收 |
| 测试 | `Tests` | 证明该能力的契约测试路径 |
| 文档 | `Docs` | 说明页路径、生成的技能页路径、文档哈希 |

> 文档哈希（ADR-002）由**生成物**承载，不写回清单：`docs/capabilities/index.md` 每行带该清单的 digest，
> `generate.check()` 在清单变更而未重渲染时直接失败。把页面内容的哈希写进清单会让“改文档”变成“改清单再重渲染”，
> 两类事实互相绑架；`Docs.version_hash` 保持为空（技能页由 `docs.skill` 声明路径，页面内容是清单第七段的渲染）。
>
> 技能正文不在文件里手写：`capabilities_kernel.knowledge` 的 L2 渲染在每次读取时从 `manifest.params` 重建参数表，
> 所以页面和 `skill_load` 都不可能比清单旧。

`Manifest.problems()` 是完整性门禁的结构半部；`tests/unit/gates/test_capability_completeness.py` 再补文件系统事实（执行器可导入、端口钩子可解析、自定义设置表单的 renderer 确实在浏览器注册、文档/契约测试存在、双语词齐全、生成物最新）。`python tools/doctor.py --all` 从同一组事实逐项打印勾选。

## 数据 preflight：样本、身份与缓存

`Manifest.preflight='module:function'` 是 ADR 里的 `preflight(node, sample)`：只声明标准库与内核的清单指向能力自己的函数。样本由调用方提供，`WorkflowEngine` 永远不打开数据库：

- `services.validation.samples.samples_for(workflow)` 取每个声明了 preflight 的节点的**数据上游**（name 节点不算数据），以及该上游在“当前节点指纹”下最近一次已结算运行的 ≤200 行（`run_store.sample_rows`，SQL `LIMIT`）；任一上游没有同指纹的存储运行就是“没有样本”，不猜。多个上游按引擎 fan-in 的顺序拼接。
- 缓存键是 `(该账号的 runs.db, 节点 id, 节点指纹)`，TTL 30 秒、最多 32 项：诊断面板按击键防抖轮询，不能每次都读一遍 10 万行表。
- 调用点：`/api/workflow/diagnostics`、`/api/workflow/validate`（同一个 `validation_payload`）与运行门 `engine.run`。读样本失败只记日志并当作没有样本——样本是提示，不能让一次本来能跑的运行被拒。
- 钩子的返回形状与 validator 相同（`code`/`message_key`/`severity`/`param`/`context`/`fix`）；钩子抛错按名报 `engine.preflight_failed`，不 500。只有可证明的事实才报 error：数值角色列有非空值却没有一个数字；空样本、全空列、饼图负值、矩阵最终格数都不在样本上裁决。

## 数据契约：记录的形状 × 声明的读取

“这个节点的表有哪些列”有两个来源，强弱不同：

- **记录的形状**：节点结算时（`run_store.finish_node(..., schema=rows)`）把本次真实输出的列并集写进 `node_schema`（排序后的列名 + `schema_hash`），与 `(run_id, node_id)` 一起存，按 `node_fingerprint` 读取。爬虫的列静态看不见，这里就是唯一答案；一次运行后下游就能核对。没有行的表不写形状——空表不能证明“没有列”。
- **声明的契约**：`ports.emit_columns` 经 `nodes.schema.compute_columns` 折叠 fan-in，回答“第一次运行之前它应该有哪些列”。

`services.validation.contracts.columns_for(workflow)` 在**有效图**上取“记录优先、声明兜底”的 `{节点: 列|None}`；`None` 是“未知”，不是“没有列”。`WorkflowEngine.validate_detailed(columns=...)` 对每个声明了 `ports.read_columns` 的消费者，把所有**数据父节点**（name 不算数据）的列取并集，读列表里不在并集里的列按名报 `engine.missing_column`；任一父节点未知就整条检查沉默（`name` 父节点不占数据槽）。这正是引擎自己的 fan-in 语义，所以 verify/fuse/join 的两侧读法一致。读钩子抛错报 `engine.read_columns_failed`，不 500。

`engine.missing_column` 是 **warning**：它上画布徽章（`validate_detailed`/`perNode`），但不进入运行门（`validate()` 只保留 error），所以一次画布不会因为一条分支的缺列被整体拒绝——节点仍会在运行期按名失败。声明的一半是契约、不是真实见过的行，这也是不拒绝运行的原因。`/api/workflow/validate` 的 `messages` 同样只含 error，浏览器据此拦截运行。

调用方与样本相同：诊断路由、`/api/workflow/validate` 与运行门；`WorkflowEngine` 不打开数据库。读 store 失败只丢“记录的形状”，声明契约仍然生效（`run.schemaReadFailed`）。前端不再持有 `reads` 或做差集：它只渲染 `validation.perNode`，缺列徽章因此只有一个来源。

## 运行后数据质量断言

`Manifest.postcheck='module:function'` 是 `preflight` 的对侧：它在节点**结算为 DONE 之后**收到
`postcheck(node, rows, inputs)`——本次真正产出的行、以及它真正收到的上游表。适合静态契约看不到的事实（“这次输出真的非空”“写出的列不是整列空白”）。

- 运行循环在打印“节点完成”之后调用 `engine.run._postcheck_node`；每条 finding 都经 `t(message_key, nid, **context)` 打一行控制台（`add_log`），并随运行日志持久化。
- **只上控制台，不改状态**：行已经产出并存好，质量结论不能让一个完成的节点变成失败；下游该跳过仍跳过。钩子抛错/返回畸形报 `engine.postcheck_failed`，不打断运行。
- 目前唯一的使用者是 `analysis`：非空输入产出 0 行时报 `engine.empty_output`（warning）；含
  `filter_rows`/`join_tables`/`anti_join` 的流水线豁免——0 行就是用户要的答案；输入为空由运行循环按“跳过”处理。
- 与 `preflight` 一样，`problems()` 拒绝不是 `module:function` 的引用，`doctor.py` 打一行 `postcheck`，
  生成矩阵与完整性门禁同步枚举。

## 表单：清单选择渲染器，不选择分支

`Ui.form='schema'` 的节点由前端通用渲染器按 `params` 逐个画控件；这类清单的每个参数必须声明 `label_key`（`problems()` 按名拒绝），可选 `placeholder_key`/`description_key`，`Ui.hint_key` 是表头说明。`Ui.form='custom'` 必须声明 `custom_renderer`，实现该表单的模块用 `registerSettingsRenderer('<id>', {html, mounted})` 注册；`openSettings()` 只做一次 `settingsRenderer(node.type)` 分派，不含节点类型 if 链。清单点名了没人注册的渲染器、目录未加载、或目录不认识该类型，面板都按名拒绝（`settings.noRenderer`/`noCatalogue`/`unknownType`），不画空表单。`reusable` 不是能力（表单来自模板快照），以自身类型名注册。

## 图表：一个 ChartSpec 管三种表面

30 种图表类型都声明在 `services/charts/registry.py` 的 `SPECS` 里。每个 `ChartSpec` 除 builder/LaTeX/家族之外，还声明 `fields`：这个图从上游表读哪些参数、每个字段的角色（分类/数值/坐标/来源/目标/文本/地区/多列列表/标签）、是否必填、表单标签与提示键、以及挂在它下面的聚合控件；`controls` 是字段之外的独立控件（事件标注、关系图中心词、词云分词与样式），`defaults` 是空白框的运行期默认列。`any_of` 表达“至少填一个”（箱线图 x 或 y）。

同一张表派生三个表面，没有第二份：

- **设置面板**：`/api/node-types` 的 `charts` 与冷启动 `node-types-fallback.js` 由 `chart_profiles()` 生成；`panels/node-chart.js` 按 profile 画框，`NodeTypes.charts()` 之外没有图型/字段数组。
- **运行前校验**：`chart_problems(chart, params)` 先并入 `defaults` 再逐个检查必填字段；未知图型给出 `engine.chart_unknown` 与声明默认值的 `fix`，`nodes.executors.visualize:validate_node` 只调用它。
- **数据 preflight**：`nodes.executors.visualize:preflight(node, sample)` 读同一份 `fields` 的 role。样本来自 `services.validation.samples`：节点指纹与当前图一致的上游最近一次运行（≤200 行，`run_store.sample_rows` 的 SQL LIMIT），按 `(账号 runs.db, 节点, 指纹)` 缓存 30 秒。它只报样本能证明的值事实：数值角色列有非空值却一个数字都没有；缺列由数据契约回答（`engine.missing_column`），样本为空/全空列/饼图负值都不下结论（builder 仍在运行期拒绝）。调用方是 `/api/workflow/diagnostics`、`/api/workflow/validate` 与运行门；`WorkflowEngine` 自身不读数据库。
- **血缘**：`nodes.executors.visualize:read_columns` 从同一 `fields` 读出这个节点要读的列（含模型一致率的三列），所以面板显示的框、缺列徽章与 `node_schema` 的契约检查问的是同一份声明。

## 生成物（freshness gate）

`python tools/gen_capabilities.py` 从清单渲染六个固定产物，外加每个能力技能一页（`docs/capabilities/skills/<kind>s/<id>.md`，路径由清单第九段 `docs.skill` 声明）与技能索引；`--check` 只比较字节：

| 产物 | 用途 |
|---|---|
| `backend/capabilities_kernel/generated/catalog.json` | 机器目录 + 能力 × 检查项测试矩阵（含每个清单的 digest） |
| `backend/capabilities_kernel/generated/openapi.json` | `/api/node-types` 的 OpenAPI 3.1 描述与每个节点的参数 schema |
| `backend/capabilities_kernel/generated/ai_tools.json` | AI 可读的摘要/步骤/示例/失败模式（P4/P6 生成技能与工具） |
| `backend/capabilities_kernel/generated/capability-schema.json` | 浏览器 schema 表单目录（数据形态，供 P2 渲染器/工具读取） |
| `backend/static/js/node-types-fallback.js` | 同一目录的冷启动脚本：`index.html` 在 `node-types.js` 之前加载，画布不再手写类型/默认值表 |
| `docs/capabilities/index.md` | 人类可读的能力索引 |
| `docs/capabilities/skills/index.md` + `skills/<kind>s/<id>.md` | 能力技能的 L1 索引与 L2 七段正文；与 `skill_load` 共用 `capabilities_kernel.knowledge.render` |

`tests/unit/gates/test_capability_completeness.py` 调用同一个 `generate.check()`：改了清单却忘记重新生成，CI 直接红，并打印 `run python tools/gen_capabilities.py`。渲染是确定性的（registry 顺序、dataclass 字段顺序、跨平台 LF），所以 Windows 与 Linux 比较的是同一串字节。

## 注册表

| 调用 | 行为 |
|---|---|
| `registry.manifests(kind)` | 发现整棵树，按 `identity.order` 再按 id 排序；每个模块只导入一次 |
| `registry.get(kind, id)` / `manifest_for_node(type)` | 只加载被问到的清单 |
| `registry.resolve('module:function')` | 解析执行器/端口钩子；缺模块或缺属性按名拒绝 |
| `registry.node_entries()` | `nodes.catalog` 的投影（type/label/category/rows/quiet/order） |
| `registry.node_defaults()` | `nodes.defaults` 的投影（参数默认值深拷贝） |
| `registry.register_node_executors()` | 把迁移节点的 handler 注册进 `nodes.registry` |

按名拒绝的情况：未知 kind、同一 id 同时有 `x.py` 与 `x/manifest.py`、`api_version` 不是当前版本、清单目录名与 `identity.id` 不一致、九段结构不完整、handler/validator 不是 `module:function` 或不可调用。

## 今天已经派生的表面

- `nodes/catalog.py`：全部类型从清单合并，按 `identity.order` 插回原槽位；字面表为空。
- `nodes/defaults.py`：种子参数来自 `ParamSpec.default`；声明 `ui.defaults_from='capabilities'` 的类型（`source`）不冻结参数，由前端问平台矩阵。
- `services/validation/engine.py`：`Rule` 与 `validators` 的唯一求值器；`engine/workflow.py` 不再为任何节点类型写 if 分支。
- `nodes/schema.py`（血缘）：清单声明的 `emit_columns`/`read_columns` 指向 executor 的同一个函数。
- `manifest.digest()`：声明内容的 SHA-256，供生成物 freshness 门禁使用。
- 六个固定生成物（`catalog.json`/`openapi.json`/`ai_tools.json`/`capability-schema.json`/`node-types-fallback.js`/`docs/capabilities/index.md`）与能力页面（技能 `docs/capabilities/skills/<kind>s/`、算子说明 `docs/capabilities/operators/`）由 `tools/gen_capabilities.py` 渲染；`tests/unit/gates/test_capability_completeness.py` 的 `generate.check()` 拒绝陈旧字节。
- `tools/doctor.py`：同一组事实的逐项勾选（含 validator 可解析），`--capability node:<id>` 只看一个能力。

## 算子清单（`operator` kind）

分析算子是 P7 第一类清单化的能力，声明在 `backend/capabilities_kernel/operators/<id>/manifest.py`，用
`capabilities_kernel.operator.OperatorManifest`：九段之外多三段。

| 段 | 字段 | 回答什么 |
|---|---|---|
| 读 | `reads` | 哪些参数必须点名一列（`one`）、哪些是可选列子集（`some`）、哪些不可为空（`nonblank`）、是否要改名映射（`mapping`）、哪些键分属两张表（`two_table_keys`） |
| 写 | `writes` | `replace`/`add`/`select`/`passthrough`/`dynamic`/`unknown` 与固定列名、追加列（含 `bin_time` 的第二个可选列、`bin_column` 的 `<列>_bin`） |
| 策略 | `needs_llm` / `empty_by_design` / `checks` | 是否交给运行中的 LLM、零行是否本来就是答案、形状类检查的 `module:function` |

`services.analysis` 的旧表全部改为投影，不再有第二份：`contracts.STEP_PARAMS`、`LLM_OPS`、`params` 的
`STEP_REPLACE`/`STEP_ADD_ONE`/`STEP_ADD_MAYBE`/`STEP_PASSTHROUGH`/`STEP_UNKNOWN`/`STEP_DYNAMIC_REPLACE`/`STEP_SELECT`/
`STEP_EMPTY_BY_DESIGN`、`matching.STEP_TWO_TABLE`/`MATCH_MODES`/`KEEP_MODES`、`kernels` 的 `FILTER_OPS`/`CONVERT_TYPES`/
`DROP_HOW`/`FILL_METHODS`/`DEDUPE_MODES`/`TIME_PARTS`、`step_checks.TWO_TABLE_KEYS` 与徽章字段名、`ops.OPS`。
七段技能由 `operator_manifest()` 生成（模板从“必填框”机械推导，必填列给占位符），因此新算子只写两句人类语言 +
契约，就能被 `skill_catalog`/`skill_load` 检索和阅读。`tests/unit/capabilities/test_operator_manifests.py` 钉住
“投影 == 清单”和“模板不会被按名拒绝”。

## 已迁移 / 还没迁移

已迁移（P2 全部 16 个节点类型）：`name`、`source`、`upload`、`resume`、`comment`、`process`、`python`、
`analysis`、`tokenize`、`biblio`、`verify`、`fuse`、`accumulate`、`visualize`、`compile`、`output`。
`biblio` 的 56 个参数与选项表就声明在它的清单里，`services/biblio/schema.py` 的 `DEFAULTS`/选项元组由清单派生
（不再保留第二份）。`source` 的字段由平台矩阵决定，清单不声明参数，两类运行前检查（矩阵 + 增量水位）由
`nodes.executors.source.validate_node` 回答。
前端表单与 `canvas.js`/`runs.js` 的第二套规则在 P2 后续切片删除。

P7 第一类：37 个分析算子已全部迁到 `capabilities_kernel/operators/<id>/`（见上一节）；P7 第二类：30 个图表类型
在 `capabilities_kernel/charts/<id>/`，`services.charts.registry.SPECS` 是其投影（字段词汇在
`charts/_fields.py`，绘图函数是清单的 handler）；P7 第三类：10 个平台在
`capabilities_kernel/platforms/<id>/`，`capabilities.platforms.CAPABILITIES` 与
`capabilities.registry` 是其投影（社交矩阵的字段/模式工厂在 `platforms/_fields.py`，
爬虫类 `crawlers.platforms.<id>.crawler:<Class>` 是清单 handler）。

## 图表清单（`chart` kind）

`ChartManifest`（`capabilities_kernel/chart.py`）沿用旧的 `ChartSpec` 字段（`family`/`echarts_only`/
`latex_buildable`/`reads`/`defaults`/`fields`/`any_of`/`controls`/`hint_key`/`tokenize_compatible`，以及
`key`/`label_key`/`no_x` 三个属性），再补九段：identity 的槽位是面板顺序（`order` 10…300），`execution.handler`
是真正画图的函数（控制台图 `services.charts.options.*:build_<id>`、文献图 `services.biblio.charts.*`），
第七段由字段契约机械推导（模板填每个必填框与 `any_of` 组成员），第九段生成 `docs/capabilities/charts/<id>.md`
与 `docs/capabilities/skills/charts/<id>.md`。`chart_manifest()` 对 `biblio` 家族默认 `echarts_only=True`
（文献图都是网络/布局图，没有 matplotlib 孪生），与原 `_biblio()` 同一条规则。`tests/unit/capabilities/
test_chart_manifests.py` 钉住“投影 == 清单、handler 就是 BUILDERS 里那一个、模板满足自己的字段契约”。

## 平台清单（`platform` kind）

`PlatformManifest`（`capabilities_kernel/platform.py`）把旧的 `Capability`/`Mode`/`Field` 三个值类型搬进
kernel，再补九段：identity 的 `category` 就是 `cn`/`overseas`，`execution.handler` 是这个平台的爬虫类
（`crawlers.platforms.<id>.crawler:<Class>`，doctor 因此能逐个核对“这个平台的爬虫还在”），
`profile_recommended`/`serial_only`/`parallel_recommended` 保留为实测建议。模式与字段仍由
`platforms/_fields.py` 的共享原子/工厂组合（搜索帖、作者时间线、站内榜、评论），`platform_manifest()`
从每个模式的必填框推导技能的前置/步骤/失败/验收与 `source` 节点模板。`Field.value_from` 的
`core.refs` 导入被延迟到方法内：`core.refs` 会拉 pandas，而清单在解析画布时就要加载。

## 表面矩阵与一致性门禁

一个清单要被哪些表面服务，写成数据而不是口头约定：`tests/unit/gates/test_capability_surfaces.py`
的 `SURFACES` 按 kind 列出表面（`runtime:*` 服务端注册表、`api:chart-profiles`、`generated:*` 生成物、
`ai:skill-catalog`/`ai:vocabulary`、`mcp:capabilities`、`cli:capabilities`、
`docs:page`/`docs:skill`），并对每个 (kind, surface) 双向断言：清单里的每个 id 都在表面上（不漏），
表面上的每个 id 都在清单里（不多）。它第一次跑就抓到三件事：OpenAPI 里 node 与 operator 共用
`NodeParams.` 前缀（现在拆成 `OperatorParams.`）、前端目录的 key 写成 `types` 而实际是 `nodes`、
AI 词汇表里的 CatBus-only 平台（京东/淘宝/快手/TikTok/闲鱼）不属于本树（门禁显式排除而不是假装它们
不存在）。

浏览器之外的两种用法也读同一份清单：`services.mcp`（JSON-RPC，工具
`capabilities_list`/`capabilities_show`/`workflow_validate`，`tools/mcp_server.py` 走 stdio）与
`services.capability_cli`（`python tools/capability_cli.py list|show|validate`）。两者都只是
`ai.knowledge` 与 `engine.workflow` 的薄封装，所以终端或编辑器里看到的能力不会比产品多一个。

## 已迁移的例子

`backend/capabilities_kernel/nodes/tokenize/manifest.py` 是最初的 pilot：catalogue 槽位 8、默认参数、
`engine.tokenize_no_column`、血缘钩子四处旧落点都已改读清单，`tests/unit/capabilities/test_tokenize_manifest.py`
逐项钉住“旧家不再有答案”。

P2 第一批按同一模板迁移了 `name`、`upload`、`compile`、`output`：
- `name` 用声明的 `no_input`/`requires_output` 规则表达“必须在头部、必须有下游”；
- `compile`/`output` 用 `validators` 指向 executor 自己的 `validate_node`，把父节点形状检查留在能力目录，
  共享引擎只负责求值和按名报告；
- `upload` 的 `emit_columns` 仍从数据集存储读真实列，清单只声明这个钩子属于它。

新增一个节点的目标剧本：

```text
backend/capabilities_kernel/nodes/<id>/
  manifest.py
  executor.py
  knowledge/SKILL.md
  examples/*.json
```

然后 `python -m tools.doctor --capability node:<id>` 全绿即可；前端表单、验证、AI 工具、技能索引、测试矩阵、文档索引在 P2-P6 自动派生。
