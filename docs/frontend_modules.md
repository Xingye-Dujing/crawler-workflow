# 前端模块化方案 / Frontend module plan

> 背景：`backend/static/js/workflow.js` 现有 **~13,000 行**、146 个顶层函数与十余个命名空间对象，
> 是仓库里最大的单文件。本文件是**已落地部分**与**后续按序拆分**的契约；每一步都必须全量测试
> 通过、单独提交，且不改变任何全局名字（`onclick="…"` 与 harness 都按名字调用）。

## 1. 现状与约束

- 页面按固定顺序加载 `<script>`（`index.html`），无打包器；顶层 `function` 声明成为 `window`
  属性，顶层 `const` 只是全局词法绑定（`AGENTS.md` 的六条前端规则之一）。
- 测试通过 `tests/frontend/harness_*.mjs` 把**真实文件**装进 node `vm`；每个 harness 自己列出
  要加载的文件。因此拆分一个模块时，**只有引用该模块符号的 harness** 需要加一行路径，
  其余 harness 不受影响（未加载的模块只在被调用时才解析）。
- 契约测试会按源码扫描 `workflow.js`/`app.js`（i18n 键、`PROCESS_OPS`、面板清单、图型清单）。
  拆分时同步把扫描路径指到新文件——这是"同一事实只有一个家"的检查，不是放宽。

## 2. 已落地

| 模块 | 内容 | 说明 |
|---|---|---|
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

## 3. 后续拆分顺序（每一行 = 一次提交）

按「依赖少、harness 引用少、语义清晰」排序；括号里是该模块的主要外部引用方（决定要改哪些 harness）。
**已落地的九站见 §2**（`node-types` / `schedules` / `reusable` / `chart-preview` / `capabilities` /
`panels/cookies` + `panels/source-help` / `panels/biblio` / `panels/runlog` / `panels/exports` /
`panels/runs`）与词典的九个域文件，下面只剩未做的：

1. **`panels/diagnostics.js`** — 编辑期诊断（约 250 行）。**注意**：那一段夹着
   `estimateCost`/`renderCostSummary`（成本摘要属于设置面板），切之前先按声明分家；涉及 `harness_panels`。
2. **`settings.js`** — `openSettings` 与各节点设置渲染（约 2,000 行，依赖最多，放最后）；涉及
   `harness_panels`、`harness_panel_actions`、`harness_state`。

`tests/frontend/page_scripts.mjs` 已经从 `index.html` 解析 `<script src="/js/…">` 顺序并提供
`loadPageScripts(sandbox, {jsDir, only})`，**7 个 harness 已改用它**（2026-10-28）；选中 `app.js`
时会连带 `js/i18n/*.js`（词典是 app.js 的数据，不是可选模块）。把文件路径直接交给 harness 的驱动
用 `tests/frontend_catalogue.py::with_catalogue()` 补同一条规则。加载顺序只有 `index.html` 一处。

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
