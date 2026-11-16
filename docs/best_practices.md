# 最佳实践指南

规则本体见 [AGENTS.md](../AGENTS.md)，逐条取舍见 [agent_practices.md](agent_practices.md)。
本文是按顺序执行的开发手册：先定位、选跑道、放代码、验证、提交。

## 1. 开始前定位

| 问题 | 答案位置 |
|---|---|
| 行为的唯一真相在哪个文件？ | `docs/ARCHITECTURE.md`、`docs/frontend_modules.md`、`docs/crawler_rules.md` |
| 这条规则踩过什么坑？ | `docs/agent_practices.md`（按加粗标题搜索） |
| 三系统/两部署成立吗？ | AGENTS.md → Cross-platform；`ai/environment.py` |
| 改坏时哪个测试先红？ | 本文 §2 与 `.opencode/skills/*` 的文件地图 |

**两种技能不要混淆**：`.opencode/skills/` 是开发助手用的；AI 工作区技能是 `backend/ai/skills.py` 的
`SkillSpec`。开发套件：`cai-xihui-context`、`crawler-platform`、`workflow-runtime`、`analysis-charts`、
`frontend-omni`、`data-pipeline`、`accounts-security`、`ai-workspace-dev`、`plugin-authoring`、
`python-extension`、`testing-lanes`、`release-desktop`、`smoke-verify`。

## 2. 选择跑道

| 跑道 | 适用 | 必须跑 |
|---|---|---|
| A | 文档、注释、锚点 | `test_doc_paths.py` + 动过的 `.py` 的 `ruff check` |
| B | 纯移动/测试缝，行为不变 | 模块用例 + 契约测试 + 该文件 ruff/format；一批后补 full fast + pylint |
| C | 真行为改动 | full fast；碰 UI/引擎/LLM/采集加 device 层；批末 pylint |
| 闭环 | 任何“完成”声明 | 所有层完整一遍，不 deselect、不 skip、不再改文件 |

```powershell
.venv\Scripts\python.exe -m pytest -q -rs
$env:CRAWLER_REQUIRE_BROWSER='1'; $env:CRAWLER_REQUIRE_NODE='1'
$env:CIXI_DRIVER_PATH='C:\path\to\chromedriver.exe'
.venv\Scripts\python.exe -m pytest -q -m "integration or live_ollama" -rs
.venv\Scripts\ruff.exe check backend/ tests/
.venv\Scripts\ruff.exe format --check backend/ tests/
.venv\Scripts\python.exe tools\ci_lint_tiers.py product
.venv\Scripts\python.exe tools\ci_lint_tiers.py tests
```

- `live_*` 永不无人值守；先问网络方向（`live_cn`/`live_os`），它花用户账号。
- 跳过不等于跑过：`CRAWLER_REQUIRE_*` 让缺失依赖失败。
- 警告是测试发现了什么却仍通过——修掉，不用 `filterwarnings`。
- 测试失败默认是本次改动的 bug；只有钉住旧 bug 时才改测试，并在同一改动说明。

## 3. 代码放哪

| 要加的东西 | 位置 | 禁止 |
|---|---|---|
| 平台模式/字段 | `capabilities/platforms/<id>.py` + `crawlers/platforms/<id>/` | 在节点/前端加矩阵没有的选项 |
| 节点类型 | `nodes/catalog.py` + `nodes/executors/<type>.py` + 注册表 | 前端另写节点表 |
| 分析算子 | `services/analysis/ops/<op>.py` + 契约/`LLM_OPS` | 静默降级 |
| 图表 | `services/charts/registry.py` 一条 `ChartSpec` | 改渲染不声明读取列 |
| 设置项 | `runtime/settings_schema.py` 一条 `Setting` | 平台模块直接读设置 |
| 服务端文案 | `backend/i18n_catalog/<domain>.py` | 跨域重复 key |
| 浏览器文案 | `backend/static/js/i18n/<domain>.js` | 只写一种语言 |
| 前端行为 | `backend/static/js/<domain>.js` + `splits.json` | 新文件不登记 |
| AI 供应商/工具/技能/插件 | `backend/ai/*` + `backend/extensions/` | 前端第二份模型表 |

依赖方向：`core` → 仅标准库；`services` 可依赖 `core`；`engine`/`api` 不反向；`engine/` 不 import `app`；
`backend/` 不用 `backend.` 前缀导入。

## 4. 三系统与两部署

- Windows / Linux / macOS 同一次改动；`backend/`、`tools/`、`ml_train/`、`tests/`、docs 不写死盘符、
  `\` 拼接、`.exe`、`%APPDATA%`、`taskkill`、cp936、Windows 专用字体。
- 机器事实只在 `core/machine.py`、`services/charts/pdf.py` 的按 OS 表，用目标分隔符拼接。
- 只有物理上不可能的能力才单系统；且必须服务端判决 + 按名拒绝 + UI 入口消失。
- 子进程统一 `procs.popen_kwargs()`；`detached=True` 是 `CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP`，
  绝不用 `DETACHED_PROCESS`。
- 打包只在 `desktop/`；macOS 载荷按 CPU、DMG `ditto` 复制，不解压。

## 5. 数据、账号与并发

- 运行时状态在 `data/` 与 `logs/`；`data/workflows/` 是唯一进版本库的例外，只按 id 引用数据集。
- 一个数据根一个服务端；第二个进程会判同根活运行中断。测试/冒烟用 `CRAWLER_DATA_ROOT`。
  起第二个服务端前先问，绝不杀 5000 上的进程。
- 账号路径在调用时解析（`runtime.paths.active()`），不缓存进模块常量。
- 队列条目带 `user_id`；工作线程/排水/时钟绑定账号，它们启动的线程重新绑定。
- 先授权再碰目标；管理员探针、删账号、强制下线都在正确的锁内完成。

## 6. 断点续跑

- 一行一事务；下一槽位 `MAX(seq)+1`，不是 `COUNT(*)`。
- 游标记位置不记内容；`Crawler.seed` 供 id；评论游标在该链接行落库后才写。
- 行账本键是站点身份（`平台`+`评论ID`），不是内容；指纹不放标签/开关，后端进指纹。
- 节点 id 是存储键，恢复时绝不重生成。
- “完成”只有一个定义：`runs.node_done` 与 `completed_nodes` 一致；skipped/failed/partial 不算，
  restored 算；计数在结算后取。
- 启动恢复与结束共用 `settle_nodes`。

## 7. 前端

- `index.html` 是唯一脚本顺序；无打包器/ES module/框架。顶层 `function` 进 `window`，顶层 `const` 不进。
- 拆分登记 `tests/frontend/splits.json`；companion 闭包传递。成员拆分用 `Object.assign`，各段成员不相交。
- harness 加载真实文件；结果相关 JS 改动同步场景；新文件 `node --check`。
- OMM-ZEN：纸/墨 token、发丝边框、一个圆角、内嵌墨色下划线、无纯黑/纯蓝、无第二套配色。
  动效仅 transform/opacity，`prefers-reduced-motion` 关闭。
- 六个坑：`window.X` 看不见顶层 `const`；DOM stub 匹配器是真的；wrapper 必须转发参数；
  `onclick="fn('…')"` 用 `attrJsArg`；`await` 前的节点之后失效；别的文件的 wrapper 不是 harness 加载的。
- 节点 id 也是 DOM id：用 `canvas._nodeEl(id)`，不 `getElementById(<id>)`。
- 页面启动走 `boot(name, fn)`；一个对话框外壳、一个待决答案；成功后重载页面。

## 8. 文案

- 用户可见字符串中英双语，落在自己的域；新域加进 `MODULES`。
- `t()` 缺关键字只打印模板；占位符由 AST 测试检查。
- 节点控制台用 `node_label`（`标题 #nid`）；一个失败一行，logger 与 `add_log` 不要双打。
- 每个打日志的线程钉住自己的语言。

## 9. 测量

- 浏览器断言报告测了多少：按 id 审容器、每容器下限、文案取 `I18n`、写明视口；
  Windows 用 `Emulation.setDeviceMetricsOverride` 并断言 CSS 尺寸。
- “面板关了”要像素上消失：关闭态与 `display:none` 逐字节比较，并有闭合态对照。
- 真站阈值从站点算，双侧；`live_site` 仅在 `login_wall` 重试一次，且断言拒绝点名。
- 数字必须来自实际读过的列/行；不靠抽样外推。

## 10. AI 工作区与成本

- 一份供应商目录（`ai/providers/registry.py`）同时服务工作和行分析器；JS 不持模型表。
- Key 留浏览器；`ai.db`/日志不出现 Key；只读工具 + 产物写入。
- 上下文生成、限额、脱敏；省略写进 `context_meta`。
- **先读最小证据**：`dataset_peek`（列名 + 5 行，120 字/格）→ `dataset_profile` → `dataset_page`（≤50 行）；
  `python_run` 返回行数 + 小样本；工具结果 >12k 字截断并注明。整张采集表不进上下文。
- **Python 是扩展接口**：脚本库 `services/python_scripts.py` 同时供 AI 与画布 Python 节点；节点存
  `script_id` 不内联代码；契约 `CIXI_INPUT`/`CIXI_OUTPUT`/`CIXI_ARGS`；仅本地/桌面，`ai_allow_python` 门控，
  云端按名拒绝；不是沙箱。写通用脚本，声明输入/输出，先保存再跑样本。
- 桌面构建可带只读 `source/` 快照供 AI 引用；不能改运行中的程序。
- 运行监控是订阅：AI 提条件、用户开启、引擎发事件、浏览器用本地 Key 反应；服务端不自行花钱。

| 宿主 | 差异 |
|---|---|
| 桌面版 | 本机模型/文件/代码插件/Python；只读源码快照；无用户本机以外能力 |
| 本地网页版 | 本机模型/文件/代码插件/Python；可读仓库源码（需 `ai_allow_code_context`） |
| 云端网页版 | 全部远程能力；无本机守护进程、用户本机文件、Python 与源码 |

## 11. 提交与发布

- 中文类型前缀：`功能更新：` / `问题修复：` / `修改：`。
- 用可追踪编辑，不用脚本重写文件；注释/文档字符串英文，README/提交中文。
- 引号用各语言自己的（中文 “ ”/‘ ’，英文 `" "`/`' '`），不用角括号。
- 新依赖装 `.venv/`、写 `requirements.txt`、缓存进 `.gitignore`，同一次改动。
- 用户可见变化同步 README；新测量写 `crawler_notes.md`；新采集规则写 `crawler_rules.md`；
  新规则理由写 `agent_practices.md`。
- 发布流程见 `release-desktop` 技能与 `docs/release.md`；macOS 包只在 GitHub runner 构建。

## 12. 反模式

1. 在节点/前端加采集矩阵没有的模式。
2. 登录墙/风控后落空表仍判 DONE。
3. `COUNT(*)` 算 seq，或评论游标写在行前。
4. 标签/开关进节点指纹，去重账本串台。
5. 恢复时重生成 node id。
6. `# noqa` / `# pylint: disable` / 放宽配置修 lint。
7. `filterwarnings` 压测试警告。
8. 单语言文案或漏占位符。
9. 新 JS 不登记 `splits.json`。
10. `backend/` 写死盘符/`.exe`/`taskkill`/码页。
11. 第二个服务端共用 `data/`，或杀 5000。
12. 云端声称读本机文件/起进程；桌面声称改了源码。
13. Key 进 SQLite/日志/提交。
14. 整表塞进上下文；先 peek，再分页。
15. 云端执行用户 Python，或绕过 `ai_allow_python`。
16. 画布节点内联 Python 代码。
17. 真站用选出来的阈值，或无人值守跑 `live_*`。
