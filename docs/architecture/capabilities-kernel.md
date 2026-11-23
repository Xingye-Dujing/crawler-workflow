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
| AI | `Ai` | 工具名、摘要、步骤、可解析的模板 JSON、失败模式 |
| 测试 | `Tests` | 证明该能力的契约测试路径 |
| 文档 | `Docs` | 说明页路径、生成的技能路径、文档哈希 |

`Manifest.problems()` 是完整性门禁的结构半部；`tests/unit/gates/test_capability_completeness.py` 再补文件系统事实（执行器可导入、端口钩子可解析、文档/契约测试存在、双语词齐全、生成物最新）。`python tools/doctor.py --all` 从同一组事实逐项打印勾选。

## 数据 preflight：样本、身份与缓存

`Manifest.preflight='module:function'` 是 ADR 里的 `preflight(node, sample)`：只声明标准库与内核的清单指向能力自己的函数。样本由调用方提供，`WorkflowEngine` 永远不打开数据库：

- `services.validation.samples.samples_for(workflow)` 取每个声明了 preflight 的节点的**数据上游**（name 节点不算数据），以及该上游在“当前节点指纹”下最近一次已结算运行的 ≤200 行（`run_store.sample_rows`，SQL `LIMIT`）；任一上游没有同指纹的存储运行就是“没有样本”，不猜。多个上游按引擎 fan-in 的顺序拼接。
- 缓存键是 `(该账号的 runs.db, 节点 id, 节点指纹)`，TTL 30 秒、最多 32 项：诊断面板按击键防抖轮询，不能每次都读一遍 10 万行表。
- 调用点：`/api/workflow/diagnostics`、`/api/workflow/validate`（同一个 `validation_payload`）与运行门 `engine.run`。读样本失败只记日志并当作没有样本——样本是提示，不能让一次本来能跑的运行被拒。
- 钩子的返回形状与 validator 相同（`code`/`message_key`/`severity`/`param`/`context`/`fix`）；钩子抛错按名报 `engine.preflight_failed`，不 500。只有可证明的事实才报 error：列不在样本里、数值角色列有非空值却没有一个数字；空样本、全空列、饼图负值、矩阵最终格数都不在样本上裁决。

## 表单：清单选择渲染器，不选择分支

`Ui.form='schema'` 的节点由前端通用渲染器按 `params` 逐个画控件；这类清单的每个参数必须声明 `label_key`（`problems()` 按名拒绝），可选 `placeholder_key`/`description_key`，`Ui.hint_key` 是表头说明。`Ui.form='custom'` 必须声明 `custom_renderer`，实现该表单的模块用 `registerSettingsRenderer('<id>', {html, mounted})` 注册；`openSettings()` 只做一次 `settingsRenderer(node.type)` 分派，不含节点类型 if 链。清单点名了没人注册的渲染器、目录未加载、或目录不认识该类型，面板都按名拒绝（`settings.noRenderer`/`noCatalogue`/`unknownType`），不画空表单。`reusable` 不是能力（表单来自模板快照），以自身类型名注册。

## 图表：一个 ChartSpec 管三种表面

30 种图表类型都声明在 `services/charts/registry.py` 的 `SPECS` 里。每个 `ChartSpec` 除 builder/LaTeX/家族之外，还声明 `fields`：这个图从上游表读哪些参数、每个字段的角色（分类/数值/坐标/来源/目标/文本/地区/多列列表/标签）、是否必填、表单标签与提示键、以及挂在它下面的聚合控件；`controls` 是字段之外的独立控件（事件标注、关系图中心词、词云分词与样式），`defaults` 是空白框的运行期默认列。`any_of` 表达“至少填一个”（箱线图 x 或 y）。

同一张表派生三个表面，没有第二份：

- **设置面板**：`/api/node-types` 的 `charts` 与冷启动 `node-types-fallback.js` 由 `chart_profiles()` 生成；`panels/node-chart.js` 按 profile 画框，`NodeTypes.charts()` 之外没有图型/字段数组。
- **运行前校验**：`chart_problems(chart, params)` 先并入 `defaults` 再逐个检查必填字段；未知图型给出 `engine.chart_unknown` 与声明默认值的 `fix`，`nodes.executors.visualize:validate_node` 只调用它。
- **数据 preflight**：`nodes.executors.visualize:preflight(node, sample)` 读同一份 `fields` 的 role。样本来自 `services.validation.samples`：节点指纹与当前图一致的上游最近一次运行（≤200 行，`run_store.sample_rows` 的 SQL LIMIT），按 `(账号 runs.db, 节点, 指纹)` 缓存 30 秒。它只报能证明的事实：字段点名的列不在样本里（改名）、数值角色列有非空值却一个数字都没有；样本为空/全空列/饼图负值都不下结论（builder 仍在运行期拒绝）。调用方是 `/api/workflow/diagnostics`、`/api/workflow/validate` 与运行门；`WorkflowEngine` 自身不读数据库。
- **血缘**：`nodes.executors.visualize:read_columns` 从同一 `fields` 读出这个节点要读的列（含模型一致率的三列），所以面板显示的框与缺列徽章问的是同一份声明。

## 生成物（freshness gate）

`python tools/gen_capabilities.py` 从清单渲染六个产物；`--check` 只比较字节：

| 产物 | 用途 |
|---|---|
| `backend/capabilities_kernel/generated/catalog.json` | 机器目录 + 能力 × 检查项测试矩阵（含每个清单的 digest） |
| `backend/capabilities_kernel/generated/openapi.json` | `/api/node-types` 的 OpenAPI 3.1 描述与每个节点的参数 schema |
| `backend/capabilities_kernel/generated/ai_tools.json` | AI 可读的摘要/步骤/示例/失败模式（P4/P6 生成技能与工具） |
| `backend/capabilities_kernel/generated/capability-schema.json` | 浏览器 schema 表单目录（数据形态，供 P2 渲染器/工具读取） |
| `backend/static/js/node-types-fallback.js` | 同一目录的冷启动脚本：`index.html` 在 `node-types.js` 之前加载，画布不再手写类型/默认值表 |
| `docs/capabilities/index.md` | 人类可读的能力索引 |

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
- 六个生成物（`catalog.json`/`openapi.json`/`ai_tools.json`/`capability-schema.json`/`node-types-fallback.js`/`docs/capabilities/index.md`）由 `tools/gen_capabilities.py` 渲染；`tests/unit/gates/test_capability_completeness.py` 的 `generate.check()` 拒绝陈旧字节。
- `tools/doctor.py`：同一组事实的逐项勾选（含 validator 可解析），`--capability node:<id>` 只看一个能力。

## 已迁移 / 还没迁移

已迁移（P2 全部 16 个节点类型）：`name`、`source`、`upload`、`resume`、`comment`、`process`、`python`、
`analysis`、`tokenize`、`biblio`、`verify`、`fuse`、`accumulate`、`visualize`、`compile`、`output`。
`biblio` 的 56 个参数与选项表就声明在它的清单里，`services/biblio/schema.py` 的 `DEFAULTS`/选项元组由清单派生
（不再保留第二份）。`source` 的字段由平台矩阵决定，清单不声明参数，两类运行前检查（矩阵 + 增量水位）由
`nodes.executors.source.validate_node` 回答。
前端表单与 `canvas.js`/`runs.js` 的第二套规则在 P2 后续切片删除。

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
