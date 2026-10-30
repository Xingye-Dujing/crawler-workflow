# 采析绘 重构总纲 / Whole-project refactor ledger

> **本文已精简为两段**：§A 状态（人类可读，一屏读完）；§B 归档账本（只增不改的逐刀流水，每刀 ≤3 行）。
> 每条规则「为什么」与实测数字在 [`docs/agent_practices.md`](agent_practices.md)；采集侧命令式规则只在
> [`docs/crawler_rules.md`](crawler_rules.md)——本文不复制它们，只链接。
> 全项目重构（Stage 0–11）**已完成**，收官任务 #56 于 2026-10-29 commit `70f3344` 关闭，已推 `crawler-github` 与 `gitee`。

---

# §A 状态（截至 2026-10-29，HEAD `70f3344`）

## A1 目标达成声明

「规范且可直接投产的模范项目」判定标准（见 A4）已逐条满足：

- **`app.py` 已归零到组合根**：579 行、仅 3 条 `@app.route`（`/` + 两处直调 `begin_run` 的门），运行编排全在 `engine/run.py`。
- **巨型单体已拆解**：`workflow.js` 13,027 → **2,089**、`app.js` 5,071 → **545**、`canvas.js` 3,893 → **2,553**、`zenviz.html` 16,852 → **218**（内联搬到 `js/zenviz-page.js` + `css/zenviz.css`）、`i18n.py` 4,620 → **252**（词条进 `i18n_catalog/<域>.py`）。
- **`engine/run.py` 闭包清零**：`begin_run` 246 行，文件内 **0 个嵌套函数**，十枚 run 助手全部升到模块层（见 B12 #56）。钉住：`tests/unit/gates/test_run_worker_module_scope.py`。
- **桌面 EXE 修复并审过**：`desktop/frozen_modules.py` 按文件树收集 314 个第一方模块（旧 spec 的 `collect_submodules` 在构建期看不见 `backend/`，`nodes.executors` 一个都没打进 exe）；PYZ TOC + 引导 + 9 个端点全 200 已验。
- **门禁全绿、CI 与本地同源**：fast ~8,246 passed / 3 skipped；ruff check + format；pylint 产品档 354 文件、tests 档 281 文件均 10.00/10 且 exit 0；设备档 189 passed / 5 skipped。

## A2 最终目录树（`backend/`，实测）

```
backend/
  app.py · i18n.py（只剩机制与合并）
  core/        地基：config · refs · machine · procs · coerce · text（zh/en 词条行为）
  runtime/     进程级运行态：state · stores · settings · gate · transport
  capabilities/ 声明层：model · requirements · registry · fields · catbus · nodes · platforms/<id>.py
  crawlers/    采集实现：core/{crawler,faults,browser,video} · engine · commenting/{session,walks,protocol}
               · backends/catbus · platforms/<id>/{crawler,comments}（红果另 harvest/player_ui/naming/trust/dialogs）
  nodes/       插件：catalog · context · registry · defaults · labels · schema · executors/<type>.py
  engine/      编排：run(1,289) · run_logs · run_schedule · workflow · dag · plan …
  sessions/    登录态域：cookies · flow · profiles · template · preflight · routes
  scheduling/  定时域：clock · store · cron
  services/    域包：analysis · biblio · charts · datasets · exports · ingest · reports · runs · workflows
               （+ 刻意留扁平的 lock_store.py，理由见 docs/ARCHITECTURE.md）
  analyzers/ · i18n_catalog/ · api/ · static/
```

## A3 每阶段交付（一行 = 阶段 | 日期 | 钉住它的门禁/契约测试）

| Stage | 交付 | 日期 | 钉住 |
|---|---|---|---|
| 0 | 加护栏：spec hiddenimports==实际顶层包、docs 路径守卫、Crawler 契约属性对账、D9 前三条死码 | 10-27 | `tests/unit/gates/test_doc_paths.py` |
| 1 | crawlers 插件化：`core/` 三拆、`commenting/walks.py` 注册表、十平台目录、`rows.py`、engine 站点事实归位 | 10-27→28 | `tests/unit/crawlers/test_crawler_platform_plugins.py` · `test_comment_walk_plugins.py` · `tests/unit/runs/test_engine_is_site_independent.py` |
| 2 | sessions/ + scheduling/ 归域；`/api/cookies/*`+`/api/profiles/*` 进 `sessions/routes.py` | 10-27→28 | `tests/api/test_api_hardening.py`（路由矩阵） |
| 3 | core/ 下沉 + capabilities/ 拆分（一平台一文件）+ coerce 解 D7 | 10-28 | `tests/unit/foundation/test_foundation_layering.py` · `test_capabilities_layout.py` |
| 4 | services/ → 9 域包（D6 同名统一） | 10-28 | 每域「集合相等」契约（`test_biblio_*` · `test_latex_*` · `test_run_store`） |
| 5 | 图表注册表：30 图型一处声明 | 10-28 | `tests/unit/charts/test_chart_registry.py` |
| 6 | app.py 归零：编排进 `engine/`，路由进蓝图 | 10-28 | `tests/api/test_run_races.py::TestTheRunStartHasOneAddress` |
| 7 | i18n Python 拆分：1,440 键×2 语言进 10 域文件 | 10-28 | `tests/unit/i18n/test_i18n.py::test_every_catalogue_module_is_merged` |
| 8 | 前端模块化：workflow.js 十四刀 + app.js 词典九域 + harness 装载统一向页面要 | 10-28→29 | `tests/unit/frontend/test_frontend_page_scripts_js.py`（伴生表契约） |
| 9 | 分析 op 注册表：34 op 各一文件 | 10-29 | `tests/api/test_node_schema.py`（契约 op 集合==执行 op 集合） |
| 10 | 测试树按被测域分目录 + deploy/ + samples/ 归类 | 10-29 | `tests/unit/gates/test_test_tiers.py`（marker 与收集数不变） |
| 11 | 大文件与插件收口：zenviz 文件化 · runtime/ · options/style 插件化 · css 拆分 · canvas/app/run.js 拆 · #40 六刀拆包 · #56 run 闭包清零 | 10-29 | `tests/unit/gates/test_run_worker_module_scope.py` · `test_console_seam_census.py` · `test_module_shadowing.py` · `tests/unit/frontend/test_frontend_canvas_sections_js.py` · `test_frontend_page_markup.py` |

## A4 判定标准（完成定义，逐条已满足）

1. 无 >900 行产品 py；JS 无 >1,200 行文件（余一处例外见 A6）。每个目录一个域、每个文件一个主题。
2. 加一个节点/平台/图型/op/导入格式/面板 = 改 1 个新文件 + 1 行注册，其余由契约测试兜底。
3. 命名唯一，`api/` 与 `services/` 不再同名模块。
4. 依赖单向 `core ← capabilities ← 域包 ← api ← app`；零 `import app`（组合根外）；服务层不再 import `api/`。
5. 存储兼容：历史运行可续跑、指纹不变、`runs.db`/`datasets.db` 状态兼容。
6. 门禁全绿：fast 全量 + 设备档三 `CRAWLER_REQUIRE_*` + ruff + pylint + `node --check` + 打包契约 + 真重建 exe 冒烟。
7. 文档与代码同构：README/`docs/ARCHITECTURE.md`/`docs/crawler_rules.md` 的路径全指新位置。

## A5 CI 现状（2026-10-29 实测，非推断）

`.github/workflows/ci.yml`（windows-latest）在每次 push/PR 跑 **两个 job**：
- `fast`：ruff check + ruff format --check + **两档 pylint**（`.pylintrc` 产品、`.pylintrc.tests`；probes 档是本地标准，CI 不跑）+ fast 档，带 `CRAWLER_REQUIRE_NODE=1`。
- `browser`：设备档 Chrome 半（`-m integration`）+ `CRAWLER_REQUIRE_BROWSER=1`。

CI 诚实覆盖不到的部分写死在文件头部注释、不用 `continue-on-error` 伪装：Ollama daemon 用例、CatBus 适配器用例（另一私有仓库）、冻结 exe 双击验收、`live_quick`/`live_site`（花真实账号，AGENTS 禁止无人值守）。HEAD `70f3344` **已推两个远端**（`crawler-github` 与 `gitee`，ahead/behind = 0/0）。

## A6 剩余表面（如实，不许改口）

- **`js/zenviz-page.js` 14,723 行未拆**：工作室页单一 IIFE 内共享 `state`，拆分要先立命名空间，**风险高于收益**——这是 A4-1 的唯一刻意例外，已在 §B11 记账。
- **真 Linux/macOS 启动未在箱上验证**（无 docker/WSL，用户决定）：代码 + 平台无关测试已落地，Linux 侧是明确的「待服务器实跑」表面；需装 Chrome/Chromium + driver、`fonts-noto-cjk`、可选 `texlive-xetex`/`texlive-lang-chinese`。
- **`live_quick`/`live_site` 未跑**：需用户在场并先问清在哪张网络（`live_cn`/`live_os`）。
- **CatBus 集成用例本机 skip**（未设 `CIXI_REQUIRE_CATBUS`；适配器是未发布的另一 checkout）。

---

# §B 归档账本（只增不改 · 每刀 ≤3 行：做了什么 | 证据形状 | 钉住测试）

> 一次性 carve/split/lift/verify/proof 脚本（原 `build/*.py`）**本会话已全部删除**，
> `build/` 现仅存 `build/make_lint_lists.py`（生成 pylint 清单，仍用）。凡旧文引 `build/<脚本>.py`
> 者，一律读作「一次性脚本（已删）；结果由下面列的测试钉住」。搬迁逐字节/AST 等价是当时已证明的事实，
> 其**当值证据**是表中列出的契约测试，不是脚本本身。

## B0 缺陷分类基线（2026-10-27 搬迁前，勿回改此表）

15 个 >900 行产品模块、18 个 <40 行 py 文件——两端都失控。缺陷 D1–D11（巨型单体 / 前缀假分包 /
一个实体散 N 处 / 孤儿模块 / 后端无层 / 命名漂移 / 依赖倒置 / `getattr` 假契约 / 代码级缺陷 / 测试树不同构 /
搬迁代价无守卫）已由 Stage 0–11 逐项消除。D9 四条：屏显调色板死码、`graph3d` 不可达分支、`toggleDatasetPanel`
重复定义（均无行为变化，已清）；popup prompts 从未挂上（属功能修复，真机另验，不混进搬迁）。

## B1 Stage 1 — crawlers 插件化（10-27→28）

- **base 三拆**：`crawlers/base.py`→`core/crawler.py`（1,495→1,144）；失败词汇进 `core/faults.py`(93)，单台 Chrome 装配进 `core/browser.py`(344)，pacing 进 `engine/pacing.py`。证据：逐条对照原方法体 + 23 import 点/4 打桩点全改指新模块，无 re-export。钉住：`tests/unit/crawlers/test_crawler_platform_plugins.py` · `test_driver_options.py` · `test_browser_startup_refusals.py`。
- **评论走路插件化**：`comments.py` 1,183→`commenting/session.py`(140)，七平台 `crawl_<p>` 与页内 JS 归 `platforms/<id>/comments.py`，分派改 `walks.py` 注册表（查不到具名拒绝），`CatbusCrawler.__getattr__` 消失。钉住：`tests/unit/crawlers/test_comment_walk_plugins.py`（12 例）。
- **hongguo 归位**：`hongguo_harvest.py` 1,825→`harvest.py`(994)，CA 信任→`trust.py`(213)、UIA 整类→`player_ui.py`(616)、名称规则→`naming.py`(83)。证据：整段搬迁要求「新文件里连续出现」+ 手写 naming 逐行对源区间。钉住：`test_hongguo_harvest`。
- **rows 抽取**：douyin `rows.py`(141)+`overlay.py` mixin(200)、weibo `rows.py`（926→831，导入别名 `shaping` 避开局部 `rows`）。钉住：`tests/integration/test_douyin_crawler.py` 93 例零改指。
- **engine 站点事实归位**：`innertube.py`→`platforms/youtube/`，三个首启对话框→各平台 `dialogs.py`（`wall.py` 词表刻意留：它是全站分类器，按平台裁剪是行为变更）。钉住：`tests/unit/runs/test_engine_is_site_independent.py`（5 例）。

## B2 Stage 2 — sessions + scheduling（10-27→28）

- **sessions/ 五模块合成**：`services/cookie_manager.py`→`cookies.py`、`services/cookie_flow.py`→`flow.py`、`browser_profiles.py`→`profiles.py`、34 行 `profiles.py`→`template.py`、`cookie_preflight.py`→`preflight.py`（无 shim，53 文件 import + 打桩全改；`template.py` 不并入 `profiles.py` 是因它 import `warm_profile_dir` 会成环）。钉住：`tests/api/test_profiles_api.py` · 预检/账号折叠用例。
- **sessions/routes.py**：`/api/cookies/*`(12) + `/api/profiles/delete` + `api/browser_profiles.py`(2) 合成 14 路由 Blueprint，app.py 4,411→3,534，`api/browser_profiles.py` 删。证据：`@app.route`→`@bp.route` 计数 + 「app 不再含这些路由」。钉住：`tests/api/test_api_hardening.py`（路由矩阵）。
- **scheduling/ 归域**：`scheduler.py`(246)→`clock.py`、`schedule_store.py`(490)→`store.py`、`cron.py`(274)→`cron.py`（一次性脚本已删；logger 名、`app_module.scheduler.start`→`clock.start` 等五处人改接缝）。钉住：`tests/unit/scheduling/test_cron.py` · `test_scheduler.py`。

## B3 Stage 3 — core + capabilities（10-28）

- **utils/ 入 core/**：`helpers.py`→`core/refs.py`、`machine_deps.py`→`core/machine.py`、`procs.py`→`core/procs.py`，`utils/` 删（一次性脚本已删；改写 69 文件）。新契约：core 恰四模块（config/refs/machine/procs）、不得 import 上层/Flask/Selenium/ML（pandas/numpy/requests 允许）、旧 utils 不复生。钉住：`tests/unit/foundation/test_foundation_layering.py`。
- **config 入 core/**：`config.py`→`core/config.py`（104 文件）。真实依赖核对否掉了计划里的 state/stores/settings——它们不是地基。
- **capabilities/ 包 + 拆分**：`crawl_capabilities.py`(1,805)→`capabilities/registry.py`，再切 `requirements.py`(61)+`model.py`(186)+`fields.py`+`catbus.py`+`platforms/<id>.py`×9（registry 只剩查询面 ~751，不再构造 `Capability`）。证据：旧/新 `as_dict()` JSON 逐字节相同、每 mode/field 逐字段相等。钉住：`tests/unit/foundation/test_capabilities_layout.py`（6 例）。

## B4 Stage 4 — services 归域（10-28）

`services/` 48 扁平模块 → 9 域包 + 1 刻意扁平（`lock_store.py`）。`bibliometrics`→`biblio/metrics`、`latex_charts`→`charts/tikz`、`latex_compile`→`charts/pdf`、`latex_report`→`reports/paper`、新增 `ingest/`（不叫 crawl，避免一概念两名）。钉住：每域集合相等契约 + `test_biblio_*`/`test_latex_*`/`test_run_store` 全绿。

## B5 Stage 5 — 图表注册表（10-28）

新 `services/charts/registry.py`：一个 `ChartSpec` 一行（30 图型：family/echarts_only/latex_buildable/reads/no_x），`CHART_TYPES` 等六组集合全部派生、名称顺序不变。D9 的 `CATEGORY_COLORS` 双绑定与 `graph3d` 死分支更早里程碑已不存在。钉住：`tests/unit/charts/test_chart_registry.py`（7 例）。

## B6 Stage 6 — app.py 归零（10-28）

- **前两片**：队列/payload/settlement 进 `services/runs/{queue,payload,settlement}.py`，`execute_lock` 进 `state.py`（认领与结算同一把锁）。
- **路由搬出**：`/api/runs/*`(12)→`api/runs.py`、`/api/workflow/*`(12)→`api/workflow.py`，url_map 129 规则「路径+方法」逐字节不变（仅 endpoint 前缀）。
- **编排搬出**：运行主体进 `backend/engine/run.py`（app 以 `run_engine.begin_run(...)` 调用），app.py 4,412→783；最后两条路由 `execute`/`rerun-node`→`api/workflow.py`，app.py **578 行、仅 `/` 一条 `@app.route`**。钉住：`tests/api/test_run_races.py::TestTheRunStartHasOneAddress`（①禁 `from engine.run import begin_run` ②`begin_run(` 只带 `run_engine.`/`engine.run.` 前缀）。

## B7 Stage 7 — i18n Python 拆分（10-28）

`i18n.py` 4,620→252（只剩 `t()`/线程本地/audit/normalize/STOP_REASONS + 合并），1,440 键×2 语言进 `i18n_catalog/` 10 域文件（crawl 907/run 821/analysis 747/collect 417/biblio 373/api 359/settings 282/cookie 280/charts 221/sched 108）。证据：逐值 AST 相同（按 **token** 切分而非按行）。合并两道守卫：导入时拒同键双域声明、磁盘文件必须列于 `MODULES`。钉住：`tests/unit/i18n/test_i18n.py::test_every_catalogue_module_is_merged`。

## B8 Stage 8 — 前端模块化（10-28→29）

- **harness 装载统一**：7 个 harness 改走 `tests/frontend/page_scripts.mjs` 的 `loadPageScripts`（读 index.html 唯一顺序，不再各自维护 `FILES=[`）。钉住：`tests/unit/frontend/test_frontend_page_scripts_js.py`。
- **app.js 词典九域**：5,071→1,450（`dict`→`_mergeCatalogues()`，九域文件共 4,009 行）。证据：旧/新世界 `I18n.dict` 1,875 键×2 语言 0 处差异（一次性脚本已删）。
- **workflow.js 十四刀**：13,027→4,458（−66%），切出 `chart-preview.js`/`capabilities.js`/`panels/{cookies,source-help,biblio,runlog,exports,runs,lexicon,datasets,files,diagnostics,settings}.js`。伴生表进 `tests/frontend/splits.json`，`loadPageScripts({only:['workflow.js']})` 自动展开（闭包是传递的）。
- 钉住：`test_frontend_page_scripts_js.py` · `test_frontend_contract.py` · `test_frontend_schedules.py` 等前端家族（~1,465 例）。

## B9 Stage 9 — 分析 op 注册表（10-29）

`services/analysis/pipeline.py` 3,899→272：34 个单 op 文件进 `ops/`（`OPS` 一行一注册，类外 `setattr(...staticmethod)` 绑定，pylint E1101 逼出的真写法）+ `contracts.py`(282) + `topic_kernels.py`(720) + `kernels.py`。12 进程 op 已是每 op 一处描述子。钉住：`tests/api/test_node_schema.py`（契约 op 集合==执行 op 集合）。

## B10 Stage 10 — 测试树 + 外围（10-29）

- **部署三件**：Dockerfile/entrypoint→`deploy/`，新增「compose 指向的 Dockerfile 必须存在」。
- **测试树按域分目录**：`tests/unit` 根清零，进 `frontend/`(42)·`analysis/`(9)·`crawlers/`(16)·`runs/`(10)·`sessions/`(3)·`i18n/`(2)·`charts/`(3)·`datasets/`(3)·`exports/`(4)·`workflows/`(5)·`scheduling/`(3)·`biblio/`(10)·`foundation/`(10)·`gates/`(6)·`ml/`(3)·`desktop/`(1)·`reports/`(1)。跨域共享 helper 留 `tests/` 顶层（目录名 `crawlers` 不能当包导入，会撞 `backend/crawlers`）。钉住：`tests/unit/gates/test_test_tiers.py`（marker 与收集数不变）。

## B11 Stage 11 — 大文件与插件收口（10-29）

- **zenviz 文件化**：`zenviz.html` 16,852→**218**，内联 `<style>`/`<script>` 原字节搬 `css/zenviz.css` + `js/zenviz-page.js`(14,723，未拆见 A6)。钉住：`tests/unit/frontend/test_frontend_page_markup.py`（id 唯一/标签成对/idref 存在/无内联脚本样式/模块只加载一次）。
- **backend 根收口→runtime/**：`state/stores/settings_store/crawl_gate/transport`→`runtime/`（`crawl_gate`→`runtime/gate.py`：`crawlers/__init__` 会急 import 全部平台，从那里取闸门会把 Selenium 拖进只问设置的测试）。95 引用文件同步。钉住：根模块集合固定 + runtime 不得 import app（`test_foundation_layering.py` 同族）。
- **图表选项插件化**：`charts/options.py`(799)→`options/{base,series,distributions,relations,topics}.py`，`@builder('type')` 注册进 `BUILDERS`（同图型两次注册直接拒）。证据：改前/改后 22 用例 `_build_option` 输出 JSON 逐字节相同。
- **样式表按域拆**：`css/style.css` 5,017→`base/menu/canvas/panels/controls/console/reusable/workspace/dialog/overlays` 十份连续切片，index.html 按原规则顺序 link。测试统一走 `tests/static_assets.py::css_text()`。钉住：三枚样式表契约（页面 link 都在盘且不重复、盘上样式都被某页加载、首尾段顺序不变）。
- **节点列契约归插件**：`nodes/schema.py` 340→125（18 条 `elif ntype==…` 链 → 每插件自声明 `emit_columns`/`read_columns`，缺省即「未知」）。钉住：四枚针（每类型要么声明要么在刻意未知集、读取者集合==声明插件、插件不反向 import 线图视图、未注册类型是未知非报错）。
- **#40 后端拆包六刀**（一次性脚本已删；行为逐字节不变）：`biblio/charts`(1,553)→`charts/{base,graph,timeline,maps,overlay}`；`biblio/metrics`(1,996)→`metrics/{records,network,measures,build,export}`；`charts/tikz`(2,430)→6 mixin + 168 行门面；`charts/visualizer`(1,805)→`style.py`(582)+`options.py`(799)+`visualizer.py`(507)；`runs/store.py`(1,610)→`store/{identity,base,ledger,progress,upkeep}`（`RunStore` 五 mixin）。钉住：各域集合相等 + `test_biblio_*`/`test_latex_*`/`test_run_store`。
- **#44**：`exports/writer.py` 7 分支 if 链 → `WRITERS={fmt:方法名}` 注册表。钉住：每广告格式有写手、每写手被广告。
- **死代码清理**：删与 `metrics/` 包同名并存、永远 import 不到的 `services/biblio/metrics.py`(1,996)（Python 先找包目录，文件从此不可能被 import，却仍被 lint/统计）。钉住：`tests/unit/gates/test_module_shadowing.py`（全树不得同名文件/包）。

## B12 Stage 11 续 — app.js/canvas.js/run.js 拆分 + #56 闭包清零（10-29，四刀）

- **app.js 三段搬出**：1,456→**545**，切 `llm-settings.js`(301)/`app-settings.js`(227)/`floating-panels.js`(405)，`splits.json['app.js']` 登记伴生。证据：四段行段按原顺序拼回==原文件（少三行空行，正文逐行零差异）+ `node --check`。连带三 harness 改走 `sourcesWithCompanions`（**一次调用内同一文件只读一遍**，顶层 const 重声明会报 `Identifier 'Outline' has already been declared`）。`I18N_USERS` 手名单(14)→`rglob` 派生（37 模块，709 处 `I18n.t` 此前在词典审计之外）。
- **canvas 对象按主题分段**：`canvas.js` 3,535→**2,553**，切 `canvas-view`(362)/`canvas-snapshot`(212)/`canvas-visuals`(245)/`canvas-auto-layout`(207)。非连续切片——成员散布字面量，`canvas` 必须仍是同一全局，故每片写 `Object.assign(canvas,{原成员行})`。证据：七行段按原序拼回==原文件 + node 比对 `Object.keys(canvas)` **158 成员名字/种类/形参数完全相同**（一次性 verify 脚本已删；表面由此测试钉住）。钉住：`tests/unit/frontend/test_frontend_canvas_sections_js.py`（只有 owner 绑 canvas、每片恰一个 assign 以 `});` 收尾、各片成员互不重叠且并集==家族表面）。
- **`engine/run.py` 两扇门搬出（#56 第一片）**：1,406→1,261，`run_logs.py`(115，LogTee/RunLogWriter) + `run_schedule.py`(79，scheduled_canvas/start_scheduled_run)。`start_scheduled_run` 在函数内 `from engine import run as run_engine` 再 `run_engine.begin_run(...)`——按名调用时取，桩只一个地址。钉住：`tests/unit/gates/test_console_seam_census.py`（AST 双向清点 `engine/*.py` 的 `add_log` 转发名单）。
- **十枚 run 助手升模块层（#56 第二–四片，#56 至此完结）**：`_wf_display_name`·`_run_single_workflow`·`_continue_record`·`_close_component_record`·`_carries_artifact`·`_node_of`·`_inputs_for`·`_component_run`·`_run_workflow_wrapper` 与 `run()` 本体（claim 时八个闭包名全变 `_run_worker` 形参）。`begin_run` 858→**246**，文件 1,271→**1,289**，**文件内不再有函数嵌套**。线程 `target=_run_worker`、`name='run'` 一字不动（`kill_process` 按 `('MainThread','run')` 拒向运行线程注入 SystemExit）。证据：逐函数 `ast.dump` 相同 + `symtable` 免费变量空（这是 AST 证明非字节差，因重新缩进会变；`ruff format` 后对当前文件重跑一遍）。钉住：`tests/unit/gates/test_run_worker_module_scope.py`（模块层函数里不得嵌套 FunctionDef、六枚名字必须在模块层、thread 必须 `target=_run_worker` 且 `name='run'`——升上去就回不来）。

## B13 桌面打包修复（10-29，commit `4a715fc`）

- **缺陷**：装好的 `CaiXiHui.exe` 一启动即死 `ModuleNotFoundError: No module named 'nodes.executors'`。根因不在本批拆分——`hiddenimports += collect_submodules(package)` 循环里 `pathex=[BACKEND]` 几行后才交给 `Analysis`，spec 自己的解释器此时看不见 `backend/`，`collect_submodules('nodes')` 静默返回空列表；`nodes.executors` 只被 `importlib.import_module('nodes.executors')` 字符串到达，静态图跟不上 ⇒ 一个插件都没打进。**对任何一次构建都成立**（上一个 10-28 的 exe 同样起不来）。
- **修法**：新增 `desktop/frozen_modules.py`——纯 `pathlib` 按文件树列 `backend/<pkg>` 每个模块（`__init__.py`⇒包名本身），不 import 任何东西；spec 用它替掉 `collect_submodules`，测试与构建读同一函数。实测收集 **314** 个第一方模块。
- **审计**：PYZ TOC（`PyInstaller.archive.readers`，不跑 exe）+ 隔离根引导 + 9 端点全 200 已验。钉住：`tests/unit/desktop/test_desktop_packaging.py`（命名包每个 `.py` 必在收集集合、`nodes.executors`/`runtime.gate`/`engine.run_logs`/`engine.run_schedule` 四个「图追不到或刚搬出」的名字必须在、`frozen_modules` 不得 import 第一方或 PyInstaller、拿掉 `nodes` 必须真让 `nodes.executors` 消失）。

## B14 程序性门禁配方（一次性，勿摸索）

- **lint 清单**：`build/make_lint_lists.py`（仍存，生成 CI 同形制绝对/正斜杠/LF 清单：产品 = backend 递归减 `test_*.py` + desktop + tools + ml_train/scripts；tests 全量）→ `pylint --rcfile=.pylintrc --disable=C,R --fail-on=W,E,F --jobs=2 $(tr -d '\r' < build/lint_product.txt | tr '\n' ' ')`，tests 档换 `.pylintrc.tests`。**分数不是门禁，退出码才是**（两档常 10.00/10 却 exit 4）。当值计数：产品 354 文件、tests 281 文件。钉住：`tests/unit/gates/test_lint_gate.py`。
- **设备档**：带三 `CRAWLER_REQUIRE_*` + `CIXI_CATBUS_CLI` + `--timeout=300`，本机 189 passed / 5 skipped（5 条为未设 `CIXI_REQUIRE_CATBUS` 的 CatBus 用例）。**本机须带 `CIXI_DRIVER_PATH`**：`~/.cache/selenium` 的 driver 缓存不见了，Selenium Manager 无网可下载会静默挂 300s（真用户 settings 已填，属本机环境非代码缺陷）。
- **跑全量期间不改任何文件**（i18n 可达性与 `test_doc_paths` 会半路读新字节假红）；每条后台门禁步骤自己打 `exit=`，重定向目录先存在。

## B15 早期样板（勿重做，`app.py` 7,182→4,412 阶段）

节点插件化（`nodes/{catalog,context,registry,defaults,labels,schema}` + `executors/<type>`×14，重复注册按名拒、插件禁 `import app`，`4b68f3f`→`ac733bc`）· 目录服务化（`GET /api/node-types`+`static/js/node-types.js`，冷页兜底与 defaults 双向钉，`70da03e`）· 列契约归所有权（`61f1738`）· 测试加载顺序收口（`page_scripts.mjs` 从 index.html 读唯一顺序，`2e71646`）· CI fast 五类「本机绿 ≠ runner 绿」修复（#38 闭环：13 bert / 2 字节 pin / 1 UPX / 1 红果播放器 / 1 stdout=None），逐条 why 在 `docs/agent_practices.md`。

---

# §C 明确不做

- 不引入打包器/框架/ES modules/依赖注入容器；**也不为拆而拆**（一堆互相传话的小文件同样算失败）。
- 不做 re-export 兼容层、不保留旧路径别名；一次搬迁一次改完。
- 不借重构改行为：日志措辞、判据、列名、调色板一律另开功能提交。
- 不触碰存储键与指纹输入（节点 id、参数名、游标语义、`item_key`）。
- 不无人值守跑 `live_quick`/`live_site`；真站验证需用户在场并先问清在哪张网络。
- `desktop/` 保持 Windows 专用树（AGENTS 唯一例外）；`zenviz.html` 的 CDN 库是否入库仍等用户决定。
- **两件等用户定的事**（非重构一部分，不擅自做）：① 浏览器交接窗口要不要在产品侧 `_create_driver` 重试（测试侧已有界重试，真机验证另判）；② 三维「平台→引擎→功能」选择器的打包版真机布局验收（用例已写，见 #25）。
