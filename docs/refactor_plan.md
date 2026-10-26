# 可扩展性重构方案 / Extensibility refactor plan

> 目标：把「新增一个节点类型 / 平台 / 采集引擎」从**改四处、漏一处就半截功能**，变成**登记一次、契约测试兜底**。
> 本文件是分阶段方案与验收口径；**Phase 0 与 Phase 1a 已落地**（8 个内置执行器 + 统一注册表），
> 后续阶段按顺序做，每一阶段都必须全量测试通过、单独提交。

## 1. 现状盘点（为什么要改）

一个节点类型现在同时存在于这些地方：

| 位置 | 内容 | 现状 |
|---|---|---|
| `backend/nodes/catalog.py` | 类型、行形态（table/pdf/none）、是否安静、面板词 key、分组 | **唯一声明**（Phase 0） |
| `backend/nodes/registry.py` | 类型 → `run(node, call)`，重复注册按名拒绝 | **统一注册表**（Phase 1a） |
| `backend/app.py` `_run_*` | 仍留在 app 的 6 个执行体（source/comment/process/analysis/visualize/output） | Phase 1b 迁到 `nodes/executors/` |
| `backend/nodes/executors/*.py` | 8 个内置执行器（name/upload/resume/tokenize/accumulate/compile/biblio/fuse） | **Phase 1a 已迁** |
| `backend/engine/workflow.py` | `NODE_TYPES` / `TABLE_NODE_TYPES` / `PDF_SOURCE_NODE_TYPES` | 从目录派生（Phase 0） |
| `backend/services/node_schema.py` | 输出了哪些列 / 读了哪些列 | Phase 3 拆进每个插件 |
| `backend/static/js/canvas.js` | `_VALID_NODE_TYPES`、`getDefaultParams`、labels、摘要 | Phase 2 改为服务端下发 |
| `backend/static/js/app.js` | `nodeType.*` / `node.*` 词条 | 保留（词条仍在前端，服务端只发 key） |

同样的「多份清单」问题也出现在平台/引擎层，本轮已经处理完（`crawl_capabilities` 只从 Selenium 矩阵 +
CatBus 清单派生；见 `docs/crawler_rules.md`「第二采集后端」）。节点层现在处于同样的起点：
`tests/unit/test_node_plugins.py` 已把**目录 ↔ 执行器 ↔ 前端粘贴白名单 ↔ 双语气泡词**四处互相钉住，
所以下一阶段拆执行体时，漏一处会红，而不是变成一次「面板接受了、运行才拒绝」。

文件结构上，`backend/` 已经是多包结构（`api/ engine/ services/ crawlers/ analyzers/ utils/ nodes/`），
根目录只剩组合根与少量跨包模块（`app.py config.py i18n.py state.py settings_store.py cookie_preflight.py
browser_profiles.py crawl_capabilities.py crawl_gate.py scheduler.py profiles.py`）。Phase 4 把这些
跨包模块收进 `core/` 与 `capabilities/`；那是最后一步，因为它会动所有 import，收益不如前三个阶段。

### 一次性文件与缓存（本轮清理）

- 已删：`build/`（构建日志、lint 清单、一次性验收脚本）、`scratchpad/`（探针、截图、隔离数据根）、
  `.pytest_cache/`、`.ruff_cache/`、源码树内全部 `__pycache__/`。
- 保留：`data/`（运行结果/登录/数据集，用户数据）、`logs/`（运行日志）、`dist/`（交付物）、
  `.venv/`、`ml_train/models/`（模型权重）、`.qoder/`（编辑器配置）。
- 规则：以后一次性脚本放忽略目录（`build/` / `scratchpad/`），不进 git、不进 CI；被跟踪的探针只在
  明确需要长期回归时升级成 `tests/` 下的用例，否则用完即删。

## 2. 目标架构

### 2.1 后端：一个节点 = 一个插件模块

```
backend/nodes/
  __init__.py          # 只做显式导出，不做 barrel 魔法
  catalog.py           # 类型、行形态、分组、quiet、label key（Phase 0）
  context.py           # NodeCall：每个执行器收到的唯一调用形状（Phase 1a）
  registry.py          # EXECUTORS = {type: run}，唯一查找入口；重复注册按名拒绝（Phase 1a）
  schema.py            # Phase 3：聚合并发列/读取列（由各插件的 emits/reads 组成）
  executors/
    __init__.py        # 导入 8 个内置插件并注册；由 registry.load_builtin_executors() 触发
    name.py upload.py resume.py tokenize.py accumulate.py compile.py biblio.py fuse.py   # 已迁
    source.py comment.py process.py analysis.py visualize.py output.py                   # Phase 1b
```

`NodePlugin` 的最终形态（Phase 1 先只加 `execute`，其余字段在 Phase 3 补齐）：

```python
@dataclass(frozen=True)
class NodePlugin:
    type: str
    label_key: str
    category: str
    rows: Literal['table', 'pdf', 'none']
    quiet: bool
    execute: Callable[[dict, NodeCall], object]
    defaults: Callable[[], dict] | Mapping[str, object]      # Phase 2
    validate: Callable[[dict, ValidationContext], list[str]] # Phase 1 可先复用现有 validate
    emits: Callable[[dict, list[Schema] | None], tuple[str, ...] | None]  # Phase 3
    reads: Callable[[dict, dict], tuple[str, ...]]                       # Phase 3
```

约束（不是建议）：

- **执行器只依赖 `NodeCall`**（`headless / current_input / run_ctx / upstream / ctx / platform_of / label_of`），
  不直接读 `app` 的模块全局。现在 `app.py` 里的执行体大量使用 `execution_state`、`add_log`、`_llm_run_ctx` 等；
  Phase 1 的每个迁移都把这些依赖**作为 `NodeCall` 的显式字段**或通过 `services/` 访问，禁止 `import app`（会成环）。
- **执行体的行为逐字节不变**：迁移只改位置与签名，不改日志、状态码、返回形状。每一类型单独提交，
  跑该类型的矩阵用例（`test_node_matrix` / `test_nodes_execution` / `test_workflow_engine` / 对应 API 用例）。
- **注册是显式的**：`registry.py` 里一行一个插件；不做 import-time 自动扫描（扫描会让顺序、循环依赖和
  “文件放错目录”都变成隐式行为）。`tests/unit/test_node_plugins.py` 继续钉 `REGISTRY` 与 `catalog` 相等。
- **节点 id / DOM id / 指纹不参与重构**：这些是存储键，任何“顺手重命名”都会让历史运行与继续失效。

### 2.2 前端：目录由服务端下发

新增 `GET /api/node-types`（只读，无写操作）：

```json
{
  "types": [
    {"type": "source", "labelKey": "nodeType.source", "category": "data",
     "rows": "table", "quiet": false, "defaults": {"platform": "zhihu", ...}}
  ]
}
```

- `canvas.js` 的 `_VALID_NODE_TYPES`、`getDefaultParams`、新增节点菜单都从这份 payload 读；
  `nodeType.*` / `node.*` 词条仍留在 `app.js`（payload 只发 key，不发语言）。
- 引导顺序：payload 与 `/api/capabilities` 一样走 `boot('node-types', …)`，失败时给重试，不画空菜单。
- 值类型（checkboxes/selects/textarea）仍由各类型的设置面板决定；Phase 2 只搬“有哪些类型、默认值、分类”，
  不搬每个节点的复杂表单（那是 Phase 1 执行体与各面板自己的事）。
- 契约测试：`/api/node-types` 的类型集合 == `nodes.catalog.NODE_TYPES`；前端 harness 用真实 payload 渲染
  节点菜单与粘贴导入，断言集合一致。

### 2.3 目录分层（Phase 4，最后做）

```
backend/
  app.py                  # 组合根：创建 Flask、注册蓝图、启动后台服务；不放业务
  core/                   # config.py i18n.py state.py settings_store.py profiles.py machine deps
  capabilities/           # crawl_capabilities.py + node catalogue 的服务端聚合
  api/ engine/ nodes/ services/ crawlers/ analyzers/ utils/   # 保持不变
```

迁移规则：

- **不做 re-export 兼容层**（AGENTS：不要 backwards-compatibility shim）。一次提交内改完 import、测试与文档；
  用 `grep -rn "from config import\|import config"` 这类全树清点，而不是等测试逐个报。
- 根目录 `sys.path` 只有 `backend/`，所以包内一律绝对导入（`from core.config import Config`），
  不出现 `backend.` 前缀。
- 一次性搬一个包（先 `core/`，再 `capabilities/`），每步全量 fast + 三档 pylint + `node --check`。

## 3. 分阶段执行与验收

### Phase 0 — 节点目录 + 执行器注册表（已完成）

- 新增 `backend/nodes/catalog.py` 与 `backend/nodes/__init__.py`；`engine/workflow.py` 的三套集合改为派生；
  `app.py` 的 if 链改为注册表（Phase 1a 后统一进 `nodes/registry.py`）；`_QUIET_NODE_TYPES` 从目录读。
- 新契约 `tests/unit/test_node_plugins.py`：目录 == 执行器表；行形态三分；引擎集合同源；前端粘贴白名单同集；
  每个插件的 `label_key` 在中英两份词条里各存在一次；未知类型没有插件；分类分组。
- 验收：上述 7 例、`tests/api/test_node_matrix.py`、`test_nodes_execution.py`、`test_workflow_engine.py`、
  `test_workflow_api.py` 全绿；全量 fast 通过；ruff + 三档 pylint。

### Phase 1 — 执行体逐个搬进插件

**1a（已完成）**：8 个内置执行器已迁到 `backend/nodes/executors/`，每个模块暴露 `NODE_TYPE` 与
`run(node, call)`；`services/nodes.py` 已删除；`nodes/context.py` 提供 `NodeCall`；`nodes/registry.py`
统一注册（内置 8 个自注册，app 注册剩余 6 个）；`test_node_plugins` 新增「插件不得 import app」的静态断言。
验收：fast **8071 passed, 3 skipped**；设备档 **192 passed**（重构前一轮；本轮执行体迁移未改采集路径）；
ruff 431 files；pylint 产品档 196 文件 / tests 档 260 文件 exit=0。

**1b（待做）**：按从依赖少到多的顺序迁剩余 6 个：`output` → `visualize` → `analysis` → `process` →
`comment` → `source`。`source`（浏览器/队列/CatBus）与 `comment`（评论引擎）最后，避免重构期同时改采集行为。

每一步：

1. 在 `nodes/executors/<type>.py` 写 `run(node, call)`，把 `app.py` 的函数体原样搬过去；
   `NodeCall` 增加它需要的显式依赖（例如 `add_log` 由 `state` 提供，绝不 `import app`）。
2. `app.py` 的 `_run_<type>` 改为调用插件（迁移期间允许保留薄适配，结束删除）；
3. 跑该类型的用例 + `tests/unit/test_node_plugins.py`；全绿后单独提交；
4. 全部迁完后，`app.py` 只剩 `_execute_node` 的注册表查找与 `NodeCall` 组装。

验收：`app.py` 行数明显下降（目标 < 4,500）；所有节点矩阵用例不变；fast 与设备档全绿。
风险最高的 `source`（浏览器/队列/CatBus 分支）与 `comment`（评论引擎）放最后，避免在重构期同时改采集行为。

### Phase 2 — 前端目录服务化

- 新 `GET /api/node-types` + `tests/api/test_node_types_api.py`（只读、形状、类型全集、默认值与 `canvas.js` 旧值逐项相等）。
- `canvas.js` 的菜单/默认值/粘贴白名单改为读 payload；`NODE_TYPE_LABELS` 只留作词条；
  harness `harness_capabilities`/`harness_canvas_ix` 增加“payload 缺一项时菜单不画空”的场景；真机 `test_ui_layout` 复测。
- 验收：前端没有任何一份节点类型字面量清单；粘贴导入、菜单、默认值、语言切换全绿。

### Phase 3 — 节点 schema 插件化

- `services/node_schema.py` 的 `PROCESS_ADD_COLUMNS` / `PROCESS_REPLACE_COLUMNS` / `STEP_REPLACE` / …按节点类型
  拆进各自插件（`emits` / `reads`），`schema.py` 只做聚合与缓存。
- 验收：`test_node_schema.py` 全量通过（它已经覆盖每种 op 的列契约）；新增节点类型时不再需要改 `node_schema`。

### Phase 4 — 目录分层

- 建 `core/`、`capabilities/`，按 §2.3 搬；一次性改完全树 import 与测试；不做兼容层。
- 验收：`grep` 确认无旧路径；fast、设备档、打包契约、`desktop/` 构建脚本的路径全绿；README/docs 文件树同步。

### Phase 5 — 清理与文档

- 删除一次性文件与缓存（§1）；`docs/` 文件树、README 结构图、`AGENTS.md` 的规则引用同步；
- 用 `tools/` 里明确登记的工具替代散落脚本；被保留的探针一律进忽略目录。

## 4. 测试与门禁（每一阶段都适用）

- **契约测试先于迁移**：先写“新位置与旧位置必须相等”的测试，再搬代码；搬完测试仍绿才算完成。
- **行为不变以用例为证**：节点矩阵（`test_node_matrix.py` 用 importlib 走每个 op→类）、执行器用例、
  前端 harness、真浏览器 `test_ui_layout` 是四个不同层面，缺一层就会留下“只在某种调用方式下坏”的空间。
- **门禁**：`pytest -q` 全量；`ruff check` + `ruff format --check`（全树）；pylint 产品档 / tests 档
  （绝对路径清单 + `tr -d '\r'`，见 `docs/agent_practices.md`「Lint 标准」）；`node --check` 四个 JS；
  动了 UI/引擎/LLM 时加 `-m "integration or live_ollama"` 带两个 `CRAWLER_REQUIRE_*`。
- 每个阶段单独提交（中文类型前缀）；任何一次“改完没重跑”都不算完成。

## 5. 风险与取舍

| 风险 | 处理 |
|---|---|
| 搬 `source`/`comment` 时改变采集行为 | 放最后；只搬位置与签名；每步跑对应矩阵与设备档；出现行为差异先修代码，不改测试 |
| `import app` 造成循环 | 执行器只依赖 `NodeCall` 与 `services/`；契约测试禁止插件 import app（静态扫描） |
| 前端 payload 加载失败导致菜单空 | 走 `boot()` + 失败重试；harness 覆盖“没回答/坏回答”；绝不画一个看似正常的空菜单 |
| 文件移动破坏 `sys.path` / 打包 | Phase 4 最后做；全树 grep + 打包契约 + 真实构建；不保留 shim |
| 插件注册顺序影响行为 | 注册表显式一行一个；不自动扫描；顺序只在展示层使用，执行按类型查表 |

**明确不做**：一次性的“大爆炸”重写；为兼容而保留两套路径；把执行体拆成过细的基类；引入依赖注入框架。
本项目的扩展点是**节点/平台/引擎**三类，插件协议只服务这三类；其他抽象按实际重复再提取。
