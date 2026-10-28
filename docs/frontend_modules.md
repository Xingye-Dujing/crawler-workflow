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

## 3. 后续拆分顺序（每一行 = 一次提交）

按「依赖少、harness 引用少、语义清晰」排序；括号里是该模块的主要外部引用方（决定要改哪些 harness）。
**已落地的四站见 §2**（`node-types` / `schedules` / `reusable` / `chart-preview`）与词典的九个域文件，
下面只剩未做的：

1. **`capabilities.js`** — `CAPABILITY_REQUIREMENT_WORDS`、`Capabilities`、`Machine`、`BertModels`
   及其渲染辅助（约 350 行）；涉及 `harness_capabilities`、`harness_profiles`、`harness_cloud`、
   `harness_engine_dimension`。
2. **`panels/cookies.js`** — cookie 面板与登录窗口（约 1,100 行）；涉及 `harness_cookie`、
   `harness_cookie_gate`、`harness_profiles`、`harness_panels`。
3. **`panels/runs.js`** — 运行控制台、运行记录、`runLogViewer`（约 2,300 行；`runLogViewer` 目前仍在
   `workflow.js` 里，随这一站搬）；涉及 `harness_console`、`harness_runlog`、`harness_runsmgr`、
   `harness_run_results`。
4. **`panels/biblio.js`** — 文献计量工作区 + 设置渲染（约 1,000 行）；涉及
   `harness_biblio_workspace`、`harness_fuse_panel`。
5. **`panels/files.js` / `panels/datasets.js` / `panels/exports.js` / `panels/lexicon.js` / `panels/diagnostics.js`**
   — 各自管理器与停靠面板（每个 150–800 行）；涉及对应 harness 与 `harness_panels`。
6. **`settings.js`** — `openSettings` 与各节点设置渲染（约 2,000 行，依赖最多，放最后）；涉及
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
