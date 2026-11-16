# 前端模块

> 返回总览见 [README.md](../README.md)。前端安全 DOM、面板与 i18n 的规则见 [AGENTS.md](../AGENTS.md)，测试层的选择见 [development.md](development.md)。

前端没有打包器，按 `static/index.html` 的固定顺序加载 `<script>`。顶层 `function` 声明成为 `window` 属性，顶层 `const` 只是全局词法绑定；`onclick="…"` 与测试 harness 都按全局名字调用，所以拆分不改任何全局名。

## 加载顺序

主页面（`static/index.html`）：

1. `vendor/echarts*.js`，随后 `js/theme-boot.js`（`<body>` 第一个阻塞脚本，首帧主题）。
2. `js/canvas.js`，随后 `clipboard.js`、`canvas-view.js`、`canvas-snapshot.js`、`canvas-visuals.js`、`canvas-auto-layout.js`。
3. `js/workflow.js`，随后 `panels/data-views.js`、`panels/shell.js`、`panels/run-results.js`、`workflow-layout.js`、`panels/settings.js`、`panels/settings-panel.js`、`panels/phase-log.js`、`panels/node-analysis.js`、`panels/node-biblio.js`、`panels/node-chart.js`、`panels/node-verify.js`、`panels/node-python.js`、`chart-preview.js`、`capabilities.js`、`panels/cookies.js`、`panels/source-help.js`、`panels/biblio.js`、`panels/runlog.js`、`panels/exports.js`、`panels/runs.js`、`panels/lexicon.js`、`panels/datasets.js`、`panels/files.js`、`panels/diagnostics.js`。
4. `node-types.js`、`stats.js`、`menu.js`、`zenviz.js`、`custom-select.js`。
5. `i18n/` 词典：`settings`、`panels`、`biblio`、`chrome`、`charts`、`nodes`、`crawl`、`pool`、`checks`、`misc`、`accounts`、`components`、`update`、`ai`。
6. `update.js`、`app.js`、`job-poll.js`、`llm-settings.js`、`app-settings.js`、`floating-panels.js`。
7. `ai/stream.js`、`ai/render.js`、`ai/settings.js`、`ai/context.js`、`ai/watch.js`、`ai/studio.js`、`ai-workspace.js`。
8. `reusable.js`、`components.js`、`schedules.js`、`accounts.js`。

图表工作室页面（`static/zenviz.html`）单独加载 `vendor/zv/*`、`js/zenviz-parse.js`、`js/zenviz-page.js`、`js/zenviz-bridge.js`。

## 模块职责

| 模块 | 职责 |
|---|---|
| `app.js` | 入口与 `boot()`：点名每个要启动的模块 |
| `canvas.js` | 图模型、节点增删与画布 DOM |
| `workflow.js` | 控制器：文件生命周期、运行前守卫、`execute`/`stop`、控制台重连 |
| `panels/settings.js` | 节点设置、源面板、参数渲染器与各节点类型的设置分区 |
| `panels/runs.js` | 运行控制台、视图游标与运行记录管理器 |
| `panels/files.js` | 已存画布、画布历史与可复用模板三页签 |
| `panels/data-views.js` | 上传、通用预览、训练、仪表盘与执行历史 |
| `ai-workspace.js` | AI 工作区：会话、流式渲染、技能、插件、监视器与 Python 工具 |
| `zenviz-page.js` / `zenviz-bridge.js` | 图表工作室页面本体与画布侧桥接 |
| `reusable.js` | 可复用节点的模板、展开与预览 |
| `accounts.js` / `components.js` / `schedules.js` / `update.js` | 账号、环境与组件、定时任务、自更新面板 |

## 模块归属

`tests/frontend/splits.json` 记录每个切片挂在哪个 owner 下；owner 被加载时连带其伴生，闭包是传递的（伴生的伴生也收到）。`—` 表示由页面直接加载的独立模块。

| owner | 伴生模块 |
|---|---|
| `app.js` | `llm-settings.js`、`app-settings.js`、`floating-panels.js`、`job-poll.js` |
| `canvas.js` | `clipboard.js`、`canvas-view.js`、`canvas-snapshot.js`、`canvas-visuals.js`、`canvas-auto-layout.js` |
| `workflow.js` | `panels/data-views.js`、`panels/shell.js`、`panels/run-results.js`、`workflow-layout.js`、`chart-preview.js`、`capabilities.js`、`panels/cookies.js`、`panels/source-help.js`、`panels/biblio.js`、`panels/runlog.js`、`panels/exports.js`、`panels/runs.js`、`panels/lexicon.js`、`panels/datasets.js`、`panels/files.js`、`panels/diagnostics.js`、`panels/settings.js`、`job-poll.js` |
| `panels/settings.js` | `panels/node-analysis.js`、`panels/node-biblio.js`、`panels/node-chart.js`、`panels/node-verify.js`、`panels/node-python.js` |
| `ai-workspace.js` | `ai/stream.js`、`ai/render.js`、`ai/settings.js`、`ai/context.js`、`ai/watch.js`、`ai/studio.js` |
| — | `theme-boot.js`、`node-types.js`、`stats.js`、`menu.js`、`zenviz.js`、`zenviz-parse.js`、`zenviz-page.js`、`zenviz-bridge.js`、`custom-select.js`、`update.js`、`reusable.js`、`components.js`、`schedules.js`、`accounts.js`、`panels/settings-panel.js`、`panels/phase-log.js`、`i18n/*` |

## 拆分与加载规则

- 新文件必须登记进 `tests/frontend/splits.json`；漏登记时 harness 装的是半个应用。`companions.mjs` 的 `SPLIT_OF` 读这份 JSON。
- 加载顺序只有 `index.html` 一处：`tests/frontend/page_scripts.mjs` 解析 `<script src="/js/…">` 并提供 `loadPageScripts`；选中 `app.js` 时连带 `js/i18n/*.js`。
- 驱动按路径装文件时，node 侧用 `tests/frontend/companions.mjs::sourcesWithCompanions`（一次调用内每个文件只读一遍，重复读会是顶层 `const` 的重声明）；Python 侧用 `tests/frontend_catalogue.py::with_catalogue()` 补词典规则、`with_companions()` 补伴生。
- 契约测试按源码扫描模块时用 `tests/static_assets.py::js_text(name)`，它沿同一张伴生表展开，不会把搬走的半边读成“不存在”。
- 拆一个对象的成员用 `Object.assign(obj, { … })`，仍是同一个全局；同名成员的段之间必须互不重叠。`tests/unit/frontend/test_frontend_canvas_sections_js.py` 钉住 canvas 家族的这一形状。
- 切点取在下一个函数自己的注释之前，成员行逐字节不动；切之前按顶层声明清点这一片，确认没有全页工具被一起带走。
- 不引入打包器或 ES modules；约 800 行是软上限，主题内聚的单对象即便略超也保持原样。

## 验收

新模块先过 `node --check`，再跑它涉及的 harness；i18n 可达性与双语契约同步；涉及面板的真浏览器用例用 `CRAWLER_REQUIRE_BROWSER=1` 跑 `tests/integration/test_ui_layout.py`；最后跑全量 fast、ruff 与两档 pylint。
