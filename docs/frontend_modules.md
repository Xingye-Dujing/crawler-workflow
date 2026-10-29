# 前端模块化方案 / Frontend module plan

> 背景：`backend/static/js/workflow.js` 曾 **~13,000 行**、146 个顶层函数与十余个命名空间对象，
> 是仓库里最大的单文件；按序拆分后它剩 **2,089 行**。本文件记录**已落地的模块**、它们的**现行行数**与
> **伴生归属**，以及拆分时要守住的契约。每次拆分都必须全量测试通过、单独提交，且**不改变任何全局名字**
> （`onclick="…"` 与 harness 都按名字调用）。
>
> 行数会随后续提交漂移；下表是 **2026-10-29** 的快照，改文件前用 `wc -l` 重新核对。

## 1. 现状与约束

- 页面按固定顺序加载 `<script>`（`index.html`），无打包器；顶层 `function` 声明成为 `window`
  属性，顶层 `const` 只是全局词法绑定（`AGENTS.md` 的六条前端规则之一）。
- 测试通过 `tests/frontend/harness_*.mjs` 把**真实文件**装进 node `vm`。加载来源只有一处：
  `tests/frontend/page_scripts.mjs` 从 `index.html` 解析 `<script>` 顺序，按路径交给 harness 的
  驱动则经 `tests/frontend/companions.mjs`（node）与 `frontend_catalogue.with_companions`（Python）
  沿 `tests/frontend/splits.json` 展开**传递闭包**（伴生的伴生也要收到，否则 harness 装的是半个应用，
  页面却带着另一半跑）。所以拆分一个模块**不需要改任何 harness**——需要的是把新文件登记进
  `splits.json`（漏登记 = 装的是半个应用）。`companions.mjs` 里的 `SPLIT_OF` 已从字面量改为读取这份 JSON。
- 契约测试会按源码扫描模块（i18n 键、`PROCESS_OPS`、面板清单、图型清单、dock 接线）。扫描读
  `tests/static_assets.py::js_text(name)`，它沿同一张伴生表展开——指到单个文件的 grep 会在下一次
  拆分时把"搬走的半边"读成"不存在的事实"，这不是放宽，而是把检查留在它真正的位置。

## 2. 已落地（现行行数 + splits.json 归属）

「归属」列给出该模块在 `tests/frontend/splits.json` 里挂在哪个 owner 下（owner 被加载时连带它）；
`—` 表示它是 `<script>` 直接加载的独立模块，不进任何伴生闭包。

| 模块 | 现行行数 | splits.json 归属 |
|---|---|---|
| `app.js`（入口、`boot()`） | 545 | — |
| `llm-settings.js`（LLM 传输/模型/密钥、`testAIConnection`） | 301 | `app.js` |
| `app-settings.js`（本机设置、`BrowserProfiles`） | 227 | `app.js` |
| `floating-panels.js`（面板作为窗口：拖拽、缩放、dock 高度、外点关闭） | 405 | `app.js` |
| `canvas.js`（图模型、节点增删） | 2,553 | — |
| `clipboard.js`（剪贴板抽屉、快捷键帮助浮层） | 366 | `canvas.js` |
| `canvas-view.js`（相机/捏合/minimap、携带相机的 draft） | 362 | `canvas.js` |
| `canvas-snapshot.js`（`getState`/`restoreState`/撤销历史） | 212 | `canvas.js` |
| `canvas-visuals.js`（禁用级联、运行徽标、校验描红、折叠） | 245 | `canvas.js` |
| `canvas-auto-layout.js`（`autoLayout`/`runAutoLayout`） | 207 | `canvas.js` |
| `workflow.js`（控制器对象：文件生命周期、运行前守卫、`execute`/`stop`/控制台重连、`nodeTypeWord`） | 2,089 | — |
| `chart-preview.js`（图表调色板/主题、标签避让、预览面板、LaTeX 工具条、按年回放、PNG/SVG 导出、全屏） | 973 | `workflow.js` |
| `capabilities.js`（`Capabilities`/`Machine`/`BertModels`/`CAPABILITY_REQUIREMENT_WORDS`） | 336 | `workflow.js` |
| `panels/cookies.js`（登录对话框、单飞登录轮询、已存登录停靠表、账号候选） | 970 | `workflow.js` |
| `panels/source-help.js`（导出指引浮层） | 175 | `workflow.js` |
| `panels/biblio.js`（文献计量工作区：运行/节点选择、分页表、产物链接、画布定位、快照对比） | 651 | `workflow.js` |
| `panels/runlog.js`（运行日志查看器，只读 `run_log` 表 + 下载 .txt） | 226 | `workflow.js` |
| `panels/exports.js`（导出产物面板：列表/下载/删除，名字原样回传） | 491 | `workflow.js` |
| `panels/runs.js`（运行控制台：视图状态与游标、`takeLines`、标签条、开关/清空/重置 + 运行记录管理器） | 1,284 | `workflow.js` |
| `panels/lexicon.js`（词表面板：停用词与 jieba 领域词） | 170 | `workflow.js` |
| `panels/datasets.js`（数据集管理器：重命名/删除/合并/谱系重置，被引用时拒绝） | 357 | `workflow.js` |
| `panels/files.js`（工作流文件管理器：已存画布/画布历史/可复用模板 三页签） | 799 | `workflow.js` |
| `panels/diagnostics.js`（编辑期诊断：emits/reads 对照、缺列/接线、成本估计与摘要） | 258 | `workflow.js` |
| `panels/settings.js`（节点设置面板：`openSettings`、源面板、参数渲染器、分析/文献/图表/续跑设置） | 1,158 | `workflow.js` |
| `panels/node-analysis.js`（分析节点设置：`ANALYSIS_OPS`/`FILTER_OPS`/`CONVERT_TYPES`） | 389 | `panels/settings.js` |
| `panels/node-biblio.js`（文献/融合节点设置：`BIBLIO_*` 清单、`FUSE_ROLE_FIELDS`） | 224 | `panels/settings.js` |
| `panels/node-chart.js`（可视化节点设置：`CHART_TYPES`/`ENGINES`/`ECHARTS_ONLY_CHARTS`） | 238 | `panels/settings.js` |
| `panels/data-views.js`（上传取文件/预览、训练 ML、通用数据预览、仪表盘网格、执行历史） | 1,150 | `workflow.js` |
| `panels/shell.js`（大纲侧栏、语言切换、toast、进程列表、通用对话框、`fetchJSON`） | 705 | `workflow.js` |
| `panels/run-results.js`（续跑横幅与已载入运行结果抽屉） | 360 | `workflow.js` |
| `workflow-layout.js`（`LayoutStrategy` 自动布局） | 165 | `workflow.js` |
| `theme-boot.js`（首帧主题引导，`<body>` 第一个阻塞脚本） | 39 | — |
| `node-types.js`（`NodeTypes`：服务端节点目录） | 83 | — |
| `schedules.js`（定时任务面板） | 475 | — |
| `reusable.js`（可复用节点：模板、展开、预览） | 1,021 | — |
| `zenviz-bridge.js` / `zenviz.js`（工作室桥/内嵌视图） | 371 / 829 | — |
| `zenviz-page.js`（图表工作室页面自身的 IIFE，从 `zenviz.html` 内联脚本原字节搬出） | 14,723 | — |

拆分史里反复撞到、值得钉住的三条教训（其余细节由测试守护，不再逐条复述）：

- **切之前先按顶层声明清点这一片**（`panels/runlog.js` 两次被连带切片）：第一次把夹在同一片里的
  `dataPreview` 与整个 `dashboard` 一起带走，第二次才发现 `escapeHtml`/`attrJsArg` 是**全页工具**
  （`workflow.js` 里上百处、`schedules.js` 也有），必须留在公共处。只看首尾标记不够。
- **切点取在下一个函数自己的注释之前**：取在函数行会把它的注释留在原文件，搬走的半边从此没有头。
- **拆对象成员用 `Object.assign(obj, { … })`，仍是同一个全局**：`canvas` 是图对象，页面 onclick 与各面板
  都按名字调 `canvas.x()`，而后来的脚本无法重绑定顶层 `const`。所以每个 `canvas-*.js` 段成员行逐字节未动，
  `test_frontend_canvas_sections_js.py` 钉住三件事：整页只有 `canvas.js` 绑定 `canvas`、每片恰好一个
  assign 语句且以 `});` 收尾、各片成员互不重叠且并集 == 家族表面（重复成员在 JS 里不是错误而是静默覆盖）。

## 3. 当前状态

拆分工作已落到「剩下两个大对象 + 一个巨型 IIFE」的形态：

- **`workflow.js`（2,089）与 `canvas.js`（2,553）各是「一个对象」**。它们的成员分散在整个字面量里，
  不能再做「连续切片」——下一刀必须是 `Object.assign` 分区（同 `canvas-*.js` 那一刀的形状），属独立决策。
  `workflow.js` 余下的是控制器对象本身（文件生命周期、运行前守卫、`execute`/`stop`/控制台重连）与
  `nodeTypeWord` 等跨面板工具；`canvas.js` 余下的是图模型与节点增删。
- **`app.js`（545）** 已切出三段（`llm-settings`/`app-settings`/`floating-panels`），`boot()` 留在入口——
  它点名每个要启动的模块，是入口的一部分。
- **`zenviz-page.js`（14,723）** 仍是单个 IIFE，内部共享 `state`：拆它要先立命名空间，风险高于收益，暂不动。
- 其余面板（`panels/` 共 17 个模块）与主题段都已各自独立、登记在 `splits.json`。

`tests/frontend/page_scripts.mjs` 从 `index.html` 解析 `<script src="/js/…">` 顺序并提供
`loadPageScripts(sandbox, {jsDir, only})`；选中 `app.js` 时连带 `js/i18n/*.js`（词典是 app.js 的数据，
不是可选模块）与它的三段切片。把文件路径直接交给 harness 的驱动用
`tests/frontend_catalogue.py::with_catalogue()` 补词典规则、`companions.mjs` 的 `sourcesWithCompanions`
补伴生规则（一次调用内每个文件只读一遍——同时点名 owner 与其伴生时，第二遍是顶层 `const` 的重声明）。
加载顺序只有 `index.html` 一处。

> 拆分/切片用的一次性核对脚本（`build/carve_*`、`build/split_*`、`verify_*`）均已删除，结果由测试钉住；
> `build/` 现只剩 `make_lint_lists.py`。

## 4. 每一步的验收

- 该模块涉及的 harness 全绿；`node --check` 新文件通过。
- i18n 可达性/双语契约仍全绿（扫描路径同步）。
- `CRAWLER_REQUIRE_BROWSER=1` 的 `tests/integration/test_ui_layout.py` 至少跑一条涉及该面板的
  真浏览器用例（首屏、交互、语言切换）。
- 全量 fast + ruff + 两档 pylint；单独提交（`修改：…`）。

## 5. 不做

- 不引入打包器/框架；不把模块改成 ES modules（`<script type="module">` 会改变作用域与加载时序，
  `onclick` 与 harness 全部要重写）。
- 不为了拆而拆。**「约 800 行」是软上限而非硬线**：主题内聚的单对象即便略超也保持原样——
  `custom-select.js`（803）、`zenviz.js`（829）都过 800 却不拆，因为各自是一个内聚组件；
  真正触发拆分的是「一个文件里塞了两个不相关主题」，不是行数本身。`menu.js`（227）、`stats.js`（136）
  这类小而内聚的同样保持原样。
