# 采析绘 — 架构地图

结构优先的代码地图，只描述当前的形状；规则与不变量见 [AGENTS.md](../AGENTS.md)。

## 运行模型
- 单进程 Flask，**从 `backend/` 启动**（`python app.py` → `:5000`）。`backend/` 是 `sys.path` 根，导入一律顶层
  （`from config import Config`，从不写 `backend.`）。
- 单服务进程：运行态全在 gitignore 的 `data/`（SQLite `runs.db`/`datasets.db`/`history.db`）与 `logs/`，
  `data/workflows/` 是唯一入库的例外。账号级状态在 `data/users/<id>/`，路径在调用时由 `runtime.paths.active()` 解析。
- `CRAWLER_DATA_ROOT` 给一个进程独立的 `data/`+`logs/`；同一份 `data/` 只应有一个服务进程。
- 一次只跑一个运行，第二次“执行”进内存队列；队列整表镜像进 `runs.db` 的 `run_queue`，重启按位置回填。

## 后端布局
| 区域 | 内容 |
|---|---|
| `app.py` | 组合根：WSGI 对象、请求钩子（来源守卫、登录门、no-store、语言钉住）、Blueprint 注册、时钟接线、启动恢复、PEP-562 读缝，唯一路由 `/`。运行门在 `api/workflow.py`，编排在 `engine/run.py`，运行记录簇在 `api/runs.py`。 |
| `core/` | `config.py`（路径/环境/常量）、`refs.py`（`as_bool`、`platform_for`、`sanitize_filename`）、`machine.py`（按 OS 的 Chrome/驱动/xelatex/Node 位置）、`procs.py`（`popen_kwargs()`、驱动进程树回收）。根上没有 `utils/`。 |
| `runtime/` | `state.py`（运行态、`_RUN_QUEUE`、数据集缓存、控制台缓冲）、`stores.py`（store 注册表与惰性 getter，测试的接缝）、`settings.py`（`data/settings.json`）、`settings_schema.py`（每个设置键的唯一声明）、`gate.py`（同平台采集闸门）、`transport.py`（本机才有的传输在云模式的具名拒绝）、`paths.py`（账号树解析）。 |
| `i18n.py` + `i18n_catalog/` | zh/en 机制（`t()`、线程本地 `set_lang`、`audit`、合并）；消息是数据，一域一模块（`crawl`/`collect`/`cookie`/`sched`/`run`/`analysis`/`biblio`/`charts`/`api`/`settings`/`accounts`），按 `MODULES` 顺序合并，重复键在导入时被拒。 |
| `capabilities/` | 唯一的采集矩阵，按归属拆分：`platforms/<id>.py`（一平台一文件，面板顺序由 `platforms/__init__` 钉住）、`fields.py`（字段原子与模式工厂）、`catbus.py`（第二引擎词汇）、`model.py`/`requirements.py`（数据类与机器门）、`registry.py`（校验、执行、面板共读的查询面）。 |
| `scheduling/` | 定时任务域：`clock.py`（进程内线程，按 `Config.SCHEDULER_TICK_SECONDS` 触发，只从 `__main__` 启动）、`store.py`（`data/schedules.json`）、`cron.py`（五段 cron 与 IANA 时区）。 |
| `engine/` | `workflow.py`（DAG 解析、`effective_workflow`、`node_label`）、`plan.py`（一次运行是什么：形态、传输、是否花模型钱、重跑作废谁）、`run.py`（`begin_run` + `_run_worker`、`run_node_durable`、`execute_node`、停止判定、队列排水，全部模块级函数）、`run_logs.py`（`print()` tee 与持久 `RunLogWriter`）、`run_schedule.py`（定时触发的两扇门）、`executor.py`、`logger.py`。这里不得导入 `app`。 |
| `api/` | 按域拆的 Blueprint + `http.py`（请求取值）+ `resolution.py`（`_resolve_dataframe`、`NoRunDataError`），全在 `app.py` 注册；`auth.py` 是登录页、会话门与云模式启动拒绝。模块：`workflow.py`、`runs.py`、`run_compare.py`、`workflow_history.py`、`data.py`、`analysis.py`、`biblio.py`、`capabilities.py`、`config.py`、`diagnostics.py`、`exports.py`、`history.py`、`lexicon.py`、`llm.py`、`locks.py`、`node_types.py`、`phases.py`、`project.py`、`report.py`、`reusable.py`、`schedules.py`、`settings.py`、`stats.py`、`studio.py`、`visualize.py`、`components.py`、`accounts.py`、`ai.py`、`update.py`。 |
| `nodes/` | 节点插件：`catalog.py`（类型/形态/分组/quiet 的唯一声明）、`context.py`（`NodeCall`）、`registry.py`（type→run）、`schema.py`（只走图并按注册表解析）、`executors/`（16 个节点，每个 `NODE_TYPE` + `run(node, call)` + 自己的列契约）。 |
| `services/` | `lock_store.py` 平铺；域包：`charts/`（`registry`/`contracts`/`style`/`visualizer`/`tikz`/`pdf`/`outputs`）、`reports/`（`html`/`paper`/`jobs`，`/api/jobs/<id>` 后面的有界内存执行器）、`runs/`（`store/` 断点续跑核心按 mixin 拆，另有 `files`/`windows`/`compare`/`history`/`housekeeping`/`queue`/`payload`/`settlement`）、`analysis/`（`pipeline`/`params`/`process`/`llm`/`lexicon`/`stats`/`contracts`/`ops/`，一算子一模块）、`biblio/`（`importer`/`schema`/`cluster`/`geo`/`store`/`monitor`/`sources` 与 `metrics/`/`charts/`/`formats/`）、`workflows/`（`manager`/`history`/`reusable`/`expand`/`bundle`）、`datasets/`（`store`/`merge`/`dedupe`）、`exports/`（`writer`/`browser`）、`ingest/`（`catbus`/`runtime`/`lifecycle`/`net`/`parts`）、`components/`（目录、断点下载、安全解包、安装/清单、环境探测）。 |
| `analyzers/` | `llm_client`（Ollama/OpenRouter）、`sentiment`/`emotion`/`tendency`（LLM + ML + BERT）、`keyword`、`ner`、`clustering`、`anomaly`、`correlation`、`significance`、`aggression`、`bot`、`cleaner`、`stopwords`。 |
| `ai/` | AI 工作台：`providers/`（一提供方一传输）、`agent.py`（回合循环、工具、提问、产物）、`context.py`（生成式项目事实 + 实时数据 + 预算）、`skills.py`、`tools.py`、`store.py`（账号级 SQLite）、`plugins.py`（声明式/代码插件宿主）；`api/ai.py` 是薄 HTTP/SSE 面，`extensions/` 持有共享的清单/权限注册表。 |
| `crawlers/` | `__init__.py` 的平台注册表与 `get_crawler`/`crawler_class`/`is_crawlable`；`core/`（`crawler.py` 契约、`browser.py`、`faults.py`、`video.py`）、`backends/catbus.py`（第二后端，列/身份/可采格读适配器清单）、`commenting/`（`session`/`walks`/`protocol`）、`engine/`（`pacing.py`、`wall.py` 等站点无关机械）、`platforms/<id>/`（目录名=平台 id：zhihu/weibo/xiaohongshu/bilibili/douyin/youtube/twitter/wechat/hongguo/cnki/instagram；`hongguo` 的桌面播放器收割是唯一 Windows 能力）。 |
| `sessions/` | 登录态：`cookies.py`（`data/cookies/<platform>@<account>.json` 与折叠规则）、`flow.py`、`profiles.py`（一账号一 Chrome profile）、`template.py`、`preflight.py`（运行前判定）、`routes.py`（`/api/cookies/*` 与 profile 删除）。 |

## 根模块与拆分约束
- `create_app()` 不是无痛改造：`tests/conftest.py` 直接 `import app` 并伸手进模块单例（`app.execution_state`、
  `app._dataset_cache`、`module.app.test_client()`）。任何拆分必须先把共享状态移到 `runtime/state.py` 与
  `runtime/stores.py`，否则隔离机制会静默失效（`data/`、`logs/` 被写脏）。
- `app.py` 的模块全局同时是测试的 monkeypatch 缝。规则：**R1**（`app` 保留别名）会让补丁按调用方分裂；
  **R2（采用）** 每个写者只绑新属主，`app` 不再转出别名，调用方统一 `from runtime.stores import get_run_store`。
  搬走一个名字就必须重指补丁目标，且不得在搬走的函数里留下读旧全局的语句。
- **PEP-562 读缝**（`app.__getattr__`）：`_RUN_STORE`/`_DATASET_STORE`/`_HOUSEKEEPER` → `runtime.stores`；
  `_dataset_cache`/`add_log`/`execution_state` → `runtime.state`；`get_crawler` → `crawlers`；
  `get_run_store` → `runtime.stores`。经此读是诚实的，**写或 patch 一律落在属主上**。
- `engine/run.py` 全程模块级：`begin_run` 认领并起 `_run_worker`，其余助手以参数接住认领时的名字；手动、
  重跑、定时、队列排水都只问 `engine.run.begin_run` 这一个地址（`tests/unit/gates/test_run_worker_module_scope.py` 钉住）。

## 前端布局
零构建，全部是固定顺序的平铺 `<script>`。可调用面是标记：`index.html` 的 `onclick`/`oninput` 属性直接点名全局，
所以拆分只搬代码、不改全局名。
| 文件 | 职责 |
|---|---|
| `canvas.js` | `canvas` 对象（图模型、节点 CRUD、选择、连线、绘制、序列化）；**一个全局由多文件 `Object.assign`**：`canvas-view.js`（相机）、`canvas-snapshot.js`（`getState`/`restoreState`/撤销）、`canvas-visuals.js`、`canvas-auto-layout.js`。 |
| `workflow.js` | 工作流控制器（文件生命周期、运行前闸门、`execute`/`stop`、控制台重连）与跨面板工具；停靠面板在 `panels/*.js`，排布在 `workflow-layout.js`。 |
| `app.js` | 入口：`X-Lang` fetch 补丁、`I18n`/`_mergeCatalogues`、`RunState`、`Settings`、主题、`CloudMode`、`boot()`；切片为 `llm-settings.js`/`app-settings.js`/`floating-panels.js`。 |
| `ai-workspace.js` + `ai/*.js` | 右侧智能体工作台：`stream.js`（SSE）、`render.js`（安全 Markdown/提问/产物）、`settings.js`（密钥只在浏览器）、`context.js`、`studio.js`。 |
| `zenviz-page.js` | Chart Studio 页应用，刻意不拆；`zenviz.html` 只是标记，页面另加载 `zenviz-bridge.js`。 |
| 其他 | `reusable.js`、`schedules.js`（不算时间）、`node-types.js`、`custom-select.js`/`menu.js`/`stats.js`、`panels/*.js`。 |
| CSS | 按域一张表：`base`/`menu`/`canvas`/`panels`/`controls`/`console`/`reusable`/`workspace`/`dialog`/`overlays`，另有 `zenviz.css`。 |
| 静态资源 | 底图在 `backend/static/geo/{china,world}.json`；`backend/static/vendor/` 只有 echarts 家族与字体。 |

- `tests/frontend/harness_*.mjs` 把**真实**文件装进 node `vm`，由 `tests/unit/frontend/test_frontend_*` 驱动；
  分片必须在 `tests/frontend/splits.json` 登记，伴随模块闭包是传递的。

## 测试分层
`pytest.ini` 默认只跑快速层并带 `--disable-socket`。每层证明什么见 [development.md](development.md)。
- `unit`：纯逻辑 + 前端 JS 真加载 + 三向对齐门。
- `api`：临时隔离的 `test_client`，外部调用全 mock。
- `integration`：真 Chrome（及 `live_ollama` 的真 Ollama），UI 层不写服务器。
- `live_quick` / `live_site`：真站采集，按 `live_cn`/`live_os` 网络分组；只在有人看管时跑。
- 前端需要 `node`；缺依赖时默认 **skip**，`CRAWLER_REQUIRE_NODE=1`/`CRAWLER_REQUIRE_BROWSER=1`/`CRAWLER_REQUIRE_OLLAMA=1`
  改为失败。
