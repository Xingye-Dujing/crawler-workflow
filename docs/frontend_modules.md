# 前端模块化方案 / Frontend module plan

> 背景：`backend/static/js/workflow.js` 曾 **~13,000 行**、146 个顶层函数与十余个命名空间对象，
> 是仓库里最大的单文件；Stage 8 与 10b 的十四 + 四刀之后它剩 **2,089 行**。
> 本文件是**已落地部分**与**后续按序拆分**的契约；每一步都必须全量测试
> 通过、单独提交，且不改变任何全局名字（`onclick="…"` 与 harness 都按名字调用）。

## 1. 现状与约束

- 页面按固定顺序加载 `<script>`（`index.html`），无打包器；顶层 `function` 声明成为 `window`
  属性，顶层 `const` 只是全局词法绑定（`AGENTS.md` 的六条前端规则之一）。
- 测试通过 `tests/frontend/harness_*.mjs` 把**真实文件**装进 node `vm`。加载来源只有一处：
  `tests/frontend/page_scripts.mjs` 从 `index.html` 解析 `<script>` 顺序，按路径交给 harness 的
  驱动则经 `tests/frontend/companions.mjs`（node）与 `frontend_catalogue.with_companions`（Python）
  沿 `tests/frontend/splits.json` 展开**传递闭包**。所以拆分一个模块**不需要改任何 harness**——
  需要的是把新文件登记进那份表（漏登记 = harness 装的是半个应用，页面却带着另一半跑）。
- 契约测试会按源码扫描模块（i18n 键、`PROCESS_OPS`、面板清单、图型清单、dock 接线）。扫描读
  `tests/static_assets.py::js_text(name)`，它沿同一张伴生表展开——指到单个文件的 grep 会在下一次
  拆分时把"搬走的半边"读成"不存在的事实"，这不是放宽，而是把检查留在它真正的位置。

## 2. 已落地

| 模块 | 内容 | 说明 |
|---|---|---|
| `theme-boot.js` | 首帧主题引导：把保存的 theme/bg/lang（含自动跟随系统）落到 `<html>`/`<body>` 上，并同步 `color-scheme` 与 `html.lang` | 2026-10-29 从 `index.html` 的**唯一一段内联脚本**搬出，仍是 `<body>` 的第一个阻塞脚本（`defer/async` 都会让浅色底先画出来）；`tests/unit/frontend/test_frontend_page_markup.py` 钉住「无内联脚本 + 它是第一个且阻塞」，首帧行为由 `harness_theme.mjs` 预置草稿后读取 |
| `node-types.js` | `NodeTypes`：服务端节点目录（类型/词条/分组/种子） | Phase 2；画布验证与种子优先读它，冷页用 `canvas.js` 的兜底表（双向钉住） |
| `schedules.js` | 定时任务面板 | 早于本方案，作为"面板整份搬出"的先例 |
| `reusable.js` | 可复用节点（模板、展开、预览） | 同上 |
| `chart-preview.js` | 图表调色板与主题、标签避让、预览面板与 LaTeX 工具条、按年份回放、PNG/SVG 导出、全屏窗口（961 行） | Stage 8（2026-10-28）按字节切片搬出（`build/carve_chart_preview.py` 证明三段切片正好还原原 `workflow.js`）；`workflow.js` 13,027 → 12,066 行。运行日志查看器仍留在 `workflow.js`（下一站） |
| `capabilities.js` | `CAPABILITY_REQUIREMENT_WORDS` / `Capabilities` / `Machine` / `BertModels`（336 行） | Stage 8（2026-10-28）整段切片搬出；`workflow.js` 12,066 → 11,739 行。**这一刀建立了「伴生模块」规则**：`tests/frontend/companions.mjs` 的 `SPLIT_OF` 声明 `workflow.js → chart-preview.js + capabilities.js`，loader 的 `only` 与按路径加载的 harness 都按它展开（14 个测试模块在搬完后以 `Capabilities is undefined` 报错，正是这条规则要防的形状） |
| `panels/cookies.js` + `panels/source-help.js` | Cookie 面板（登录对话框、单飞登录任务轮询、已存登录停靠表、账号候选）与导出指引浮层（970 + 175 行） | Stage 8（2026-10-28）：cookie 那段是**连续切片**，而导出指引正好夹在它中间，所以第一步把 1,125 行整段搬出、第二步再把指引切到自己的文件（`build/carve_cookie_panel.py` + `build/carve_source_help.py`，两次都按行切片并核对分区）。`workflow.js` 11,740 → 10,614 行；两件都进 `SPLIT_OF`。**测试跟着事实走**：cookie 删除对话框的调用点扫描、指引的 `GROUP_KEYS`/`style.display` 扫描、矩阵 action 存在性扫描（改为扫整棵 `js/`）与「死键」审计的 JS 面（改为 `rglob`，仍排除 `i18n/` 数据） |
| `panels/biblio.js` | 文献计量工作区（运行/节点选择、分页表、产物链接、画布定位、项目快照与对比）（651 行） | Stage 8（2026-10-28）整段切片搬出；`workflow.js` 10,615 → 9,971 行。`biblioColumnWord`/`toggleBiblioPanel` 与被剪的 `BIBLIO_DIFF_LINES`/`_diffItem` 只有工作区自己用，一起搬；进 `SPLIT_OF` |
| `panels/runlog.js` | 运行日志查看器（只读 `run_log` 表，服务端过滤 + 同样的参数下载 .txt）（226 行） | Stage 8（2026-10-28）；`workflow.js` 9,972 → 9,753 行。**这一刀两次被切片连带**：第一次把夹在同一片里的 `dataPreview` 与整个 `dashboard` 带走，第二次才发现 `escapeHtml`/`attrJsArg` 是**全页工具**（workflow.js 里 158 处、schedules.js 9 处），先把两个工具放回 `workflow.js`，再把 data preview + dashboard 整段退回（300 行）。教训：切之前按顶层声明清点这一片，不只看首尾标记 |
| `panels/exports.js` | 导出产物面板（列表/下载/删除，名字原样回传）（491 行） | Stage 8（2026-10-29）整段切片搬出；`workflow.js` 9,754 → 9,270 行。有了伴生表，这一刀**一次通过**（harness_exports 已用 `sourceOf`） |
| `panels/runs.js` | 运行控制台（视图状态与游标、`takeLines`、标签条构建、开关/清空/重置）与运行记录管理器（1,284 行） | Stage 8（2026-10-29）**四段**切片搬出（每段先按顶层声明清点过）；`workflow.js` 9,271 → 7,991 行。`_wfActiveTab`/`switchWfTab` 留在 `workflow.js`（标签页由轮询器画）；`harness_console` 改用 `sourceOf`，两处静态扫描改读两文件合体 |
| `panels/lexicon.js` | 词表面板（停用词与 jieba 领域词，一行一词、加词框在上）（170 行） | Stage 8（2026-10-29）整段切片搬出；`workflow.js` 7,992 → 7,827 行。切点取在下一个函数**自己的注释之前**（取在函数行会把注释留在原文件） |
| `panels/datasets.js` | 数据集管理器（重命名/删除/合并/累积谱系重置，名字与形状、被工作流引用时拒绝）（357 行） | Stage 8（2026-10-29）整段切片搬出；`workflow.js` 7,828 → 7,477 行。一次通过 |
| `panels/files.js` | 工作流文件管理器（已存画布 / 画布历史 / 可复用模板 三个页签）（799 行） | Stage 8（2026-10-29）整段切片搬出；`workflow.js` 7,478 → 6,686 行。一次通过；「一次一个运行」的闸门 `refuseWhileRunning` 不属此面板，留在 `workflow.js` |
| `panels/diagnostics.js` | 编辑期诊断（节点 emits/reads 对照、缺列与接线问题、成本估计与摘要）（258 行） | Stage 8（2026-10-29）整段切片搬出；`workflow.js` 6,687 → 6,436 行。**成本摘要不是设置面板的东西**：`renderCostSummary()` 由 `Diagnostics` 的 refresh 调用，`estimateCost` 用的是同段的 `_processLlm`/`_isLabelOp`/`_labelCallCap`，所以整段一起搬 |
| `panels/settings.js` | 节点设置面板：`openSettings`、源面板与全部参数渲染器（输入/下拉/勾选/数字）、分析/文献/图表设置、`renderResumeSettings`，以及它们读的 `ANALYSIS_OPS`/`FILTER_OPS`/`CONVERT_TYPES`/`BIBLIO_*`/`CHART_TYPES` 清单（1,985 行） | Stage 8（2026-10-29）**两段**切片：`nodeTypeWord` 被 `panels/files.js`/`panels/runs.js`/`reusable.js`/`zenviz.js` 共用，夹在两段之间，留在 `workflow.js`；重组核对 357,166 字节相等；`workflow.js` 6,436 → 4,458 行。进 `SPLIT_OF`；`harness_async_panels`/`harness_cloud` 改 `sourceOf`；`test_chart_registry`/`test_data_analysis`/`test_exporter`/`test_analysis_api`/`test_frontend_contract`/`test_frontend_js` 与五处 harness 扫描改读新文件 |

| `panels/data-views.js` | 上传节点取文件与预览、训练 ML、通用数据预览、仪表盘网格、执行历史（1,147 行） | Stage 10b（2026-10-29）整段切片搬出；`workflow.js` 4,458 → **2,089** 行（连同下三片）。这套 `SPLIT_OF` 从 `tests/frontend/companions.mjs` 的字面量搬到 `tests/frontend/splits.json`，Python 驱动（`frontend_catalogue.with_companions`）与 node loader 读同一份；`harness_reusable` 改为接受「canvas、workflow、伴生…、reusable」 |
| `panels/shell.js` | 大纲侧栏、语言切换、toast、进程列表、通用对话框、`fetchJSON`（702 行） | Stage 10b 整段切片搬出；`setLang` 里对 `biblioWorkspace`/`schedulesManager` 的语言回调随之移动，两处扫描改读本文件 |
| `panels/run-results.js` | 续跑横幅与已载入运行结果抽屉（357 行） | Stage 10b 整段切片搬出 |
| `workflow-layout.js` | `LayoutStrategy` 自动布局（Style 菜单）（163 行） | Stage 10b 整段切片搬出 |
| `clipboard.js` | 剪贴板抽屉（复制历史的持久列表、粘贴/改名/置顶/删除）与快捷键帮助浮层：`Clipboard` / `toggleClipboardDrawer` / `toggleShortcutsHelp`（366 行） | 2026-10-29 从 `canvas.js` 尾部原字节搬出（拼回核对：canvas.js 现存 3,535 行 + 本片正文 == 原 3,893 行文件逐行相同，零差异）。`canvas.js` 是图对象，抽屉与帮助框不是它的成员；名字仍是页面全局，因为 `index.html` 的 onclick 按名字调它们。进 `splits.json['canvas.js']` |
| `panels/node-analysis.js` | 分析节点的设置：`ANALYSIS_OPS`/`FILTER_OPS`/`CONVERT_TYPES` 与 `renderAnalysisSettings`（389 行） | 2026-10-29 从 `panels/settings.js` 按**连续切片**拆出（切片脚本核对四片拼接与原件逐字节相同）。它同时是 `splits.json` 里 `panels/settings.js` 的伴生：**伴生展开改成传递闭包**（node loader 与 `frontend_catalogue.with_companions` 同一规则），否则"命名 workflow.js 的 harness"只会拿到面板外壳而拿不到这一片 |
| `panels/node-biblio.js` | 文献计量与融合节点的设置：`BIBLIO_*` 十张清单、`FUSE_ROLE_FIELDS`、`renderBiblioSettings`/`renderFuseSettings`（224 行） | 同上一次切片 |
| `panels/node-chart.js` | 可视化节点的设置：`CHART_TYPES`/`BIBLIO_CHARTS`/`ENGINES`/`ECHARTS_ONLY_CHARTS`/`CHARTS_WITH_*` 与 `renderVisualizeSettings`（238 行） | 同上；`test_chart_registry`/`test_visualization`/`test_frontend_contract` 的清单扫描改读**面板合体**（`static_assets.js_text('panels/settings.js')` 沿伴生表展开，扫描不再自己猜文件名） |
| `llm-settings.js` + `app-settings.js` + `floating-panels.js` | `app.js` 的三段：LLM 传输/模型/密钥与 `testAIConnection`（301 行）、本机设置与 `BrowserProfiles`（227 行）、面板作为窗口的行为（拖拽、缩放、控制台弹出、九个 dock 的高度、外点关闭、首次打开的包装，405 行） | 2026-10-29 **连续切片**拆出（`build/split_app_js.py`：四个文件的行段按原顺序拼回 == 原 1,456 行文件，只少了三行空行，正文逐行零差异）。`boot()` 留在 `app.js`——它点名每个要启动的模块，是入口的一部分；三段里的加载期语句只有 `window.X = X` 与 `document.addEventListener(...)`，没有 DOMContentLoaded 监听，所以「boot 注册」相对它们的先后与原来一致（新文件排在 `app.js` 之后、`reusable.js` 之前）。进 `splits.json['app.js']`。**顺带补齐了三处绕过伴生表的读法**：`harness_menu`/`harness_app_state`/`harness_schedules` 自己 `readFileSync(argv)`，拆分后 boot 里少了搬走的对象；`companions.mjs` 因此给 `sourcesWithCompanions` 加了「一次调用里同一文件只读一遍」（驱动同时点名 owner 与它的伴生时，第二遍是顶层 `const` 的重声明） |
| `zenviz-page.js` + `css/zenviz.css` | 图表工作室页面自身：14,720 行的 IIFE（引擎渲染、属性面板、导入导出、持久化）与 1,927 行样式 | 2026-10-29 从 `zenviz.html`（16,852 行）的**内联 `<style>`/`<script>`** 原字节搬出，页面剩 218 行；JS 仍是**一个 IIFE、缩进未动**（模板字符串跨行，去缩进会改到字符串内容），CSS 只去了行首页面对齐的六格。文件化换来 `node --check`、可审 diff 与严格 CSP（禁用内联）。`zenviz-page.js` 只由 `zenviz.html` 加载（与 `zenviz-bridge.js` 同），`tests/unit/frontend/test_frontend_page_markup.py` 把同一套文档契约（id 唯一/成对/可访问名/无内联/模块在盘）套到工作室页 |

## 3. 后续拆分顺序（每一行 = 一次提交）

按「依赖少、harness 引用少、语义清晰」排序；括号里是该模块的主要外部引用方（决定要改哪些 harness）。
**Stage 8 的十四站已全部落地**（见 §2：`node-types` / `schedules` / `reusable` / `chart-preview` / `capabilities` /
`panels/cookies` + `panels/source-help` / `panels/biblio` / `panels/runlog` / `panels/exports` / `panels/runs` /
`panels/lexicon` / `panels/datasets` / `panels/files` / `panels/diagnostics` / `panels/settings`），
`workflow.js` 13,027 → 4,458 行。Stage 10b 又搬出四片（`panels/data-views.js`/`panels/shell.js`/`panels/run-results.js`/`workflow-layout.js`），`workflow.js` → **2,089 行**。余下的是 `workflow` 控制器对象（文件生命周期、运行前守卫、`execute`/`stop`/控制台重连）与 `nodeTypeWord` 等跨面板工具：它们是同一主题的一个对象，再拆需要把对象成员改成 `Object.assign` 分区，属单独一刀。

`app.js` 同法已在 2026-10-29 落地三段（见 §2 最后一行的前三片）：1,456 → **545 行**，`boot()` 留在入口。
`panels/settings.js` 再按节点类型切三片（1,985 → 1,155），`canvas.js` 搬出尾部抽屉（3,893 → 3,535）。
仍未动的两座大文件：`canvas.js` 3,535（图对象成员：小地图/自动布局/撤销，同样要 `Object.assign` 分区）与
`zenviz-page.js` 14,723（IIFE 内共享 `state`，拆分要先立命名空间，风险高于收益）。

`tests/frontend/page_scripts.mjs` 已经从 `index.html` 解析 `<script src="/js/…">` 顺序并提供
`loadPageScripts(sandbox, {jsDir, only})`，**15 个 harness 已改用它**（2026-10-29）；选中 `app.js`
时会连带 `js/i18n/*.js`（词典是 app.js 的数据，不是可选模块）与它的三段切片。把文件路径直接交给 harness 的驱动
用 `tests/frontend_catalogue.py::with_catalogue()` 补词典规则、`companions.mjs` 的 `sourcesWithCompanions`
补伴生规则（一次调用内每个文件只读一遍）。加载顺序只有 `index.html` 一处。

## 4. 每一步的验收

- 该模块涉及的 harness 全绿；`node --check` 新文件通过。
- i18n 可达性/双语契约仍全绿（扫描路径同步）。
- `CRAWLER_REQUIRE_BROWSER=1` 的 `tests/integration/test_ui_layout.py` 至少跑一条涉及该面板的
  真浏览器用例（首屏、交互、语言切换）。
- 全量 fast + ruff + 两档 pylint；单独提交（`修改：…`）。

## 5. 不做

- 不引入打包器/框架；不把模块改成 ES modules（`<script type="module">` 会改变作用域与加载时序，
  `onclick` 与 harness 全部要重写）。
- 不为了拆而拆：单文件低于约 800 行且主题内聚的（`menu.js`、`stats.js`、`custom-select.js`）保持原样。
