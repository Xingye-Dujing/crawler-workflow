# API 参考

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。

Flask 后端全部 HTTP 端点（`app.py` 引导页 + 26 个 Blueprint；URL map 共 131 条规则、125 条去重路径），按功能分组。
CatBus / 采集矩阵 / 平台边界的规则与证据不在这里复述，见 [docs/crawler_rules.md](crawler_rules.md)。

### 认证（仅在设置 `CRAWLER_AUTH_PASSWORD` 时生效）

| 端点 | 方法 | 描述 |
|------|------|------|
| `/login` | GET | 登录页（`text/html`，跟随浏览器 `Accept-Language`，可用 `?lang=zh|en` 指定）；已登录时 302 到 `next` 或 `/`；未设置密码时 302 到 `/` |
| `/login` | POST | 表单 `username` / `password` / `next`：成功写会话并 302 到 `next`（只接受本站路径，`//host`、`\`、`http(s)://` 一律回 `/`）；失败 401 并重绘页面，无会话写入 |
| `/logout` | POST | 清会话并 302 到 `/login`；会话 id 在服务端**吊销**（重放旧 Cookie 无效）；GET 不到达处理函数（405 或静态兜底 404），宁可失败也不让跨站链接结束会话 |

未登录时：`/api/*` 一律 401（`{ok:false, error}` 且带 `X-Auth-Required: 1`，前端据此跳登录页），其余路径 302 到
`/login?next=<原地址>`。会话是签名的非持久 Cookie（`cixi_session`，HttpOnly / SameSite=Lax，`CRAWLER_HTTPS=1`
时 Secure），Cookie 里只有一枚随机会话 id，是否仍有效由服务端进程内的登记表回答——所以退出登录会真正吊销该
会话、改密码会撤销所有已发出的会话；服务重启则所有人重新登录。cloud 模式没设密码或仍用仓库默认
`SECRET_KEY` 时，`app.py` 在启动前按名拒绝。

### 工作流

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/workflow/save` | POST | 保存工作流配置（含命名） |
| `/api/workflow/load` | GET | 加载指定工作流；有运行在跑时返回 409（换画布会改写在跑那份的工作流名） |
| `/api/workflow/list` | GET | 列出所有已保存工作流，每个文件一条对象（`name`/`nodes`/`labels`/`size`/`mtime`/`broken`）；读不开的文件也占一行并带 `broken`，好让用户能删掉它 |
| `/api/workflow/rename` | POST | 重命名工作流文件（`{name, new_name}`）：同时改写文件内的 name 与数据集里对旧名的引用；目标名已存在 409、旧名不存在 404、新旧同名 400、在跑的那份被改名 409，绝不覆盖已有文件 |
| `/api/workflow/delete` | POST | 删除工作流 |
| `/api/workflow/execute` | POST | 执行工作流；已有运行在跑则排队（返回 `queued` 与位次；`queue:false` 保留旧的直接拒绝）。「继续」一定带 `queue:false`——排队期间它指向的运行记录可能被保留策略清掉，宁可立刻 400 也不悄悄变成一次从零重爬 |
| `/api/workflow/rerun-node` | POST | 重跑**一个节点及其下游**：定向擦除该子树的存储结果，再用同一 `resume_run_id` 重启运行——上游已存的行被复用，只有被点名的子树重新算 |
| `/api/workflow/diagnostics` | POST | 对工作流做只读诊断（校验/环/悬空连线等），不写运行 |
| `/api/workflow/stop` | POST | 停止执行：浏览器在后台关、请求立即返回；`browsers` 是这次交出去关掉的浏览器数，`records` 是本请求已就地改判为 `stopping` 的运行行 |
| `/api/workflow/status` | GET | 执行状态（含 `queue` 等待列表；`stopping`/`settling` 说明"已叫停但结论还没写"）。带 `run_ids`（本次尝试打开的全部记录 id）与 `node_states`（`{node_id:{status,row_count,error,run_id}}`），画布据此给节点画状态 |
| `/api/workflow/queue` | GET | 列出排队中的请求 |
| `/api/workflow/queue/cancel` | POST | 按 `id` 取消一个排队请求（绝不触碰正在跑的运行） |
| `/api/workflow/queue/clear` | POST | 清空队列 |
| `/api/workflow/processes` | GET | 列出执行器/浏览器子进程 |
| `/api/workflow/processes/kill` | POST | 强杀残留进程 |
| `/api/node-types` | GET | 服务端节点类型目录（`type` 等，供画布校验/种子；由 `nodes/catalog` 单一声明导出） |

### 画布历史与项目包

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/workflow/history` | GET | 画布历史列表：`{ok, snapshots:[{id,label,workflow_name,created_at,nodes,connections}], max}`；**不返回画布内容**（列表要轻），内容按 id 取 |
| `/api/workflow/history/save` | POST | `{label?, workflow_name?, workflow}` 存一份命名快照；超过 100 份时 409 按名拒绝，不淘汰旧快照 |
| `/api/workflow/history/get` | GET | `?id=` 取一份快照的完整 `workflow`；找不到 404，内容损坏 409，都带快照 id |
| `/api/workflow/history/rename` | POST | `{id, label}` 改一份快照的标签；缺 id 或类型不对按名拒绝 |
| `/api/workflow/history/delete` | POST | `{id}` 删除快照；`baselines_cleared` 列出因此被清空布局基准的工作流名；缺 id 幂等返回 `deleted:false` |
| `/api/workflow/history/layout` | GET | `?workflow=` 读该工作流的自动排布策略与基准快照头（`strategy`/`snapshot`/`baseline_missing`） |
| `/api/workflow/history/layout` | POST | `{workflow_name, strategy:'algorithm'|'baseline', snapshot_id?}` 按工作流保存策略；baseline 必须有存在的快照，未保存的草稿没有工作流名 → 400 |
| `/api/project/export` | GET | `?workflow=` 导出当前已保存工作流，`?all=1` 导出全部；返回 zip（`manifest.json` + `workflows/` + `datasets/` + `templates/`）。工作流引用的数据集必须存在否则按名拒绝；`X-Project-Warnings` 是警告条数 |
| `/api/project/import` | POST | multipart `file` 上传项目 zip；导入时重新分配数据集/模板 id、改写工作流引用，同名自动加 ` (2)`，绝不覆盖；版本/校验和/路径/大小/结构任一不对都 400 具名拒绝 |

### 可复用节点模板

模板是用户编排的片段，存成 `data/reusable_nodes/<id>.json`；服务端只校验和存取，**不执行**模板。执行前的展开发生在浏览器。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/reusable` | GET | 模板列表（含损坏文件行，便于删除）；每项有 `id/name/nodes/connections/inputs/updated_at/broken` |
| `/api/reusable/get` | GET | `?id=` 取完整模板；损坏 409、不存在 404，均带 id |
| `/api/reusable/save` | POST | `{name, description?, nodes, connections, inputs, outputs, id?}` 新建或按 id 更新；名字重复/为空、无节点、未知类型、悬空或重复连线、有环、输出不是恰好一个末端节点都按名拒绝 |
| `/api/reusable/rename` | POST | `{id, name}` 改模板名；缺 id/name 或类型不对按名拒绝 |
| `/api/reusable/delete` | POST | `{id}` 删除模板文件；缺 id 返回 `deleted:false`（幂等），已插入的实例不受影响（它们存着自己的模板快照） |

### 运行记录 / 断点续跑

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/runs/compare` | GET | `?a=&b=&node=&key=&limit=` 对比两次运行：`{a,b,same_workflow,same_shape,nodes,node,diff,key_used}`；运行/节点不存在 404 或 400 具名拒绝；单节点超过 200000 行拒绝对比 |
| `/api/runs/resumable` | POST | 查询指定工作流最近一次可续跑的中断运行（读之前先顺手判定本进程遗留的"运行中/正在停止"行） |
| `/api/runs/for-workflow` | POST | 运行记录「当前工作流」页签数据源：`{workflow, limit?}`，按与「继续」相同的结构指纹列出该画布的运行（含已完成/运行中，新→旧），每条带 `nodes`/`resumable`/`rows_kept`/`duration_seconds` |
| `/api/runs/list` | GET | 分页列出运行记录（每条带 `workflow_name`、`wf_count`、`mode`、`headless`、`duration_seconds` 等，面板据此打「并行/串行 ×N」「无头/窗口」「运行时长」标）；这次读取同时是本进程遗留记录的修复时机 |
| `/api/runs/status` | GET | 单条运行的节点级状态 |
| `/api/runs/stats` | GET | 全局运行统计 |
| `/api/runs/purge` | POST | 按保留策略清理旧运行（中断的最后清理；`purge` 同时交回被裁剪运行的"已采集"认领） |
| `/api/runs/discard` | POST | 丢弃一次中断运行（不再提供续跑） |
| `/api/runs/delete` | POST | 删除指定运行（仍保留其已采集认领——用户知道这次爬是付过钱的） |
| `/api/runs/<run_id>` | GET | 运行详情（含节点行数据摘要）；每个节点带 `duration_seconds`（节点墙钟耗时；未完成时为空） |
| `/api/runs/<run_id>/log` | GET | 事后查阅该运行**持久化**的控制台（`runs.db` 的 `run_log`，每条物理行都存、不截断）。参数 `wf`/`level`/`q`/`before`/`limit`；返回 `{rows, has_more, min_seq, max_seq}`；未知 run → 404。**只读持久表，绝不触碰 `execution_state`** |
| `/api/runs/<run_id>/log.txt` | GET | 把同一份持久控制台按当前过滤整段拼齐为 `text/plain` 附件下载（所见即所存）；未知 run → 404 文本 |
| `/api/runs/clear` | POST | 清空全部运行记录，**必须带 `{"confirm": true}`**（否则 400）：正在跑的那条被豁免；被删运行占的"已采集"认领一并交回，而 LLM 答案缓存故意留下 |

### 数据与数据集

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/data/upload` | POST | 上传 CSV/TSV/JSON/TXT/.xlsx/.bib/.ris/.enw 等并注册为持久化数据集（未知扩展名→400）；实测过的文献导出件（CNKI/CSSCI/WoS/Scopus/Dimensions/Lens/PubMed 等）自动解析为文献记录表，响应带 `biblio_format`/`biblio_capabilities`/`warnings`；认得出但不能读的先点名拒绝，绝不静默存成一张看起来正常的表 |
| `/api/data/paste` | POST | 将粘贴的 JSON 数组注册为数据集 |
| `/api/data/datasets` | GET | 列出已注册数据集 |
| `/api/data/datasets/<id>` | GET / DELETE | 查看 / 删除单个数据集 |
| `/api/data/datasets/<id>/rename` | POST | 给一份已存数据集改**显示名**：id 是内容哈希，改名不重算身份、不动任何指针与行 |
| `/api/data/diff` | POST | 任意两张表的逐行对比（两份数据集、两个节点结果，或混合）：每侧是 resolver 载荷；可选 `key` 点名一列来判定**变化**行，不给 `key` 只报新增/消失 |
| `/api/data/lineages` | GET | 列出累积数据集谱系；`?name=` 另带版本历史；找不到 404 |
| `/api/data/lineages/reset` | POST | `{name}` 清空一个累积谱系及其版本指针（已存数据集版本保留）；找不到 404 |
| `/api/data/merge` | POST | `{dataset_ids:[...], name}` 把至少两个数据集按行合并成新数据集：列集合必须一致否则按名拒绝；相同内容复用已有 id；超过 300000 行按名拒绝 |
| `/api/data/inspect` | POST | 查看数据集的空值/类型/重复行统计 |
| `/api/data/preview` | POST | 分页查看数据集原始表格（数据预览面板）；按 `node_id` 取历史行须带 `workflow_name`，可选 `run_id` 精确锁定一次运行；无身份返回 `code:no_run_data` |
| `/api/data/clear` | POST | 数据集文件-store 的清理：默认只扫孤儿，带 `{"all": true}` 或 `?all=1` 才是真正清空 |

### 词表 / 锁定台账

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/lexicon` | GET | 列词表：`?kind=`（空 = 全部，未知 kind 按名 400）、`?limit=`；读 `data/lexicon.db` |
| `/api/lexicon` | POST | 写入词项；未知 kind / 载荷不合形按名拒绝 |
| `/api/lexicon` | DELETE | 删除词项；按 kind/词定位，缺项幂等 |
| `/api/locks` | GET | 每个面板当前的锁定键清单（一次给全部四个面板，好让列表上锁图标在载入时就画对） |
| `/api/locks` | POST | 锁定 / 解锁一条并返回该面板的完整锁清单（锁定是可逆的 UI 意图，不需要 confirm） |

### 分析 / 可视化 / 导出（独立于工作流，可单独调用）

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/analysis/run` | POST | 对数据集执行清洗流水线，返回新数据集 id 及报告 |
| `/api/analysis/train` | POST | 从已有 LLM 标注数据集训练传统 ML 模型（情感/倾向） |
| `/api/visualize/render` | POST | 对数据集渲染图表，返回 ECharts option 或 Matplotlib 图片；带 `emit_latex`/`emit_latex_table` 时另返回 `latex`/`latex_table` 并写入导出目录；上游无运行数据时返回 HTTP 200 + `code:no_run_data`；按 `node_id` 取历史行同样接受可选 `run_id` |
| `/api/export/save` | POST | 将数据集导出为指定格式文件 |
| `/api/exports/list` | GET | 按时间倒序列出导出文件（名称/类型/大小/可下载标记）与目录合计 |
| `/api/exports/download` | GET | 按**文件名**下载某个导出文件（越界名→404，脚本类扩展名→404） |
| `/api/exports/delete` | POST | 删除单个导出文件（不接受路径、前缀或递归） |
| `/api/exports/clear` | POST | 清空导出目录，**必须带 `{"confirm": true}`**：只逐个删面板列出的名字，反复清到某一轮什么也没删掉为止；有运行在跑时 409 整体拒绝 |
| `/api/exports/clear-run` | POST | 按**一次运行**清除其全部文件，必须 `{"run_id","confirm":true}`：只删台账登记的名字，「固定」条目跳过；有运行在跑时 409；只删磁盘产物，不动 `runs.db` |
| `/api/exports/clear-run-parts` | POST | 按一次运行 × 一个数据源节点只清除其分片（`kind='part'`），保留合并文件；作用域锁在 `(run_id,node_id,'part')` |
| `/api/exports/clear-name` | POST | 按**名字**清除某一批分片：传入某个 `{stem}.partNNN{ext}`，删同名同扩展的全部分片，保留合并文件与「固定」条目；传入的不是分片→400 |
| `/api/exports/ledger` | GET | 列出**写过导出文件**的每一次运行及其文件清单——「智能清除」选择器的数据源，读 `runs.db` 的运行→文件台账而非目录扫描 |

### 文献计量（biblio）

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/biblio/compare` | GET | 两次快照差异，在服务端算（`biblio_store.compare_snapshots`）：节点/边/聚类/突发的增删改逐段；每段超 60 条只列前 60 但给出 `total`；`a`/`b` 缺一个或相同→400，任一快照不存在→404 并报 id |
| `/api/biblio/projects` | GET | 每个项目连同其快照表头（标签/时间/形态/节点数/边数/`params_verified`），一次调用给全面板所需；表头不带已存行 |
| `/api/biblio/snapshots/<snapshot_id>` | GET | 按 id 取一份快照的完整内容（节点/边表，预览上限 100 条并写出 `node_total`/`edge_total`/`preview_limit`）；不存在→404 并报 id |
| `/api/biblio/project` `/rename` `/delete` | POST | 建 / 改名 / 删项目；名字空 400、不存在 404，删除连带清掉快照并回报数量 |
| `/api/biblio/snapshot` `/delete` | POST | 把某运行某节点的全部已存行捕获进项目（不是当前那一页）；参数从已保存画布读并用节点指纹核对；非 `biblio` 节点 400、无已存行 400、项目/运行不存在 404，都指名 |
| `/api/biblio/runs` | GET | 文献计量工作区数据源：倒序列出含 `biblio` 节点的运行，每条带该运行里的节点与其登记产物；判定在服务端读 `node_runs.node_type` |
| `/api/biblio/table` | GET | 分页读回某运行某节点的已存表（`run_id`+`node_id`+`offset`/`limit`）；`shape` 由列本身判读；运行不存在→404、节点不在→404、非 biblio→400、无已存行→200 带 `note` |
| `/api/biblio/sources` | GET | 「数据来源」浮层内容：每个可读来源含官网链接、扩展名、可带字段与服务端翻好的导出指引；只读（POST→405） |

### 报告 / 论文成稿

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/report/generate` | POST | 生成自包含 HTML 运行报告（可选 AI 结论；可选 `options` 定制图表/表格/节点选择/内联成图） |
| `/api/report/view` | GET | 按名查看报告：仅接受 `report-` 前缀的 `.html`，响应带禁脚本 CSP |
| `/api/report/latex` | POST | **论文成稿**：只收 `{"run_id","title"}`，图与三线表从这次运行**已登记**的 LaTeX 源读回，合成 `article`+`ctex` 文档，先写 `.tex` 再用本机 `xelatex` 编译成 PDF 并记回台账；浏览器**永不**上传 LaTeX 源码。无运行/无登记源/无编译器→按名报错且不留半份 PDF |
| `/api/report/studio-images` | GET | 列出导出目录里的成图供报告内联选择 |

### Chart Studio

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/studio/dataset` | POST | 把画布任意节点/数据集的完整表格交给 Studio（支持多源合并） |
| `/api/studio/sources` | POST | 预检哪些节点当前有可用表格数据（与预览同一套取行规则：带 `workflow_name`，带 `run_id` 时只预检该次运行） |
| `/api/studio/save-image` | POST | 把 Studio 成品图保存为 PNG 到导出目录 |
| `/api/studio/save-vector` | POST | 把浏览器画好的 ECharts 图存为矢量 SVG；非 `<svg>`／缺 xmlns／被截断／含脚本或外部引用／超尺寸都按名拒绝 |
| `/api/studio/save-pdf` | POST | 把该图**已登记**的 LaTeX 源编译成矢量 PDF；浏览器只送文件名，不在台账里的一律按名拒绝 |

### 统计与历史

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/stats/emotion` | GET | 情感统计 |
| `/api/stats/tendency` | GET | 倾向性统计 |
| `/api/stats/summary` | GET | 执行汇总统计 |
| `/api/history/runs` | GET | 列出所有已记录的工作流执行 |
| `/api/history/series` | GET | 按工作流/指标查询时间序列（执行历史面板趋势图） |
| `/api/history/clear` | POST | 清空执行历史记录 |
| `/api/history/delete` | POST | 删除**单次运行**的执行历史（`{run_id}`）；返回 `deleted` 条数，0 表示已不在历史里；不带 `run_id` 一律 400 |

### AI / Cookie / 系统

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/llm/models` | GET | 拉取 OpenRouter 免费模型列表 |
| `/api/llm/ollama/models` | GET | 列出本地 Ollama 已拉取模型 |
| `/api/llm/test` | POST | 测试所选提供方的连通性 |
| `/api/cookies/status` | GET | 各平台 Cookie 是否存在 |
| `/api/cookies/flow` | GET | 每个平台 Cookie 的用途、获取步骤、默认登录页与可接受域名 |
| `/api/cookies/save` | POST | 保存指定平台 Cookie（不属于该平台的域名条目会被剔除，一条都不剩时拒绝） |
| `/api/cookies/generate` | POST | 打开浏览器引导扫码登录并捕获 Cookie；可选 `url` 指定入口链接（仅限该平台域名） |
| `/api/cookies/generate/status` | GET | 扫码取 Cookie 任务的当前状态（`active`/`kind`/`platform` 等） |
| `/api/cookies/generate/confirm` | POST | "我登好了"——立即捕获并保存 Cookie；无进行中的登录任务→400 |
| `/api/cookies/generate/cancel` | POST | 取消当前扫码任务；无进行中的登录任务→400 |
| `/api/cookies/verify` | POST | 用已存 Cookie 实地探测该平台还放行什么（逐条回显：可用 / 仍挡在登录页 / 回的是验证码·风控所以没有结论） |
| `/api/cookies/delete` | POST | 删除该平台 Cookie 快照文件；回话说清 profile 是否仍持有登录态 |
| `/api/profiles/delete` | POST | 删除某**命名账号**自己的浏览器 Profile 目录（不动 Cookie 文件）；默认账号结构性拒绝、被占用 409、没有可删 404、非法名 400 |
| `/api/cookies/rename` | POST | 给一个已存登录改名字——Cookie 文件与它自己的浏览器目录一起搬或一样都不动；默认那份结构性拒绝 |
| `/api/cookies/preflight` | POST | 运行前一次性验证画布要用到的多个平台：逐平台 `valid/expired/unknown/nocookie/nologin/notcrawlable` + 已渲染文案 + `blocked`/`unclear`（按 `COOKIE_PREFLIGHT_TTL` 缓存） |
| `/api/settings` | GET / POST | 读取 / 修改运行时设置（`data/settings.json`） |
| `/api/browser/profiles` | GET | 每个平台的持久浏览器 Profile 状态，外加 `template` 一行（`{exists, pristine}`，pristine 由读表里的行数判定） |
| `/api/browser/profiles/template` | POST | 用一台空白 Chrome 生成/重建初始模板（`{force?}`）；建不出来时是 502 带原因，不是 200 加一句谎 |
| `/api/config` | GET | 系统配置 |
| `/api/capabilities` | GET | 采集矩阵，按平台 × 引擎 × 功能送出（Selenium / CatBus 各自 `available`/`reason`；每格 `runnable`/`columns`/`identity`；模式 `requires` + 顶层 `machine`/`backends.catbus`）。数据源面板整块由它渲染。判定与平台边界规则见 [crawler_rules.md](crawler_rules.md) |
| `/api/models` | GET | 已注册微调模型清单（读 `data/model_registry.json`）：`{name, path, desc}`，情绪/倾向/情感节点的 `bert` 模式据此把模型列成可勾选的显示名（多选写入 `bert_models`）。文件缺失/损坏回空列表而非报错。只读 |

### 定时任务

面板只认一个载荷：每个回答都带全量 `{ok, tasks, canvases, status}`，所以任何一次请求回来都能整块重画。`next_run_local`/`last_run_local`/`trigger_text`/`runnable`/`why_not`/时钟状态都由服务端按任务自己的时区算好送出，浏览器不在前端算时间。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/schedules` | GET | 任务 + 画布可跑性 + 时钟状态，面板开合与每次改动后刷新 |
| `/api/schedules/save` | POST | 新建或按 `id` 原地更新一个任务；时间表达原样存，保存期与触发期用同一条规则——需要模型的画布具名拒绝（400），画布不存在/时间写不通/cron 永不触发/时区不认识都各自点名拒绝 |
| `/api/schedules/delete` | POST | 删除一个任务（没有此 id 回 404） |
| `/api/schedules/toggle` | POST | 开关一个任务：关掉即清空 `next_run`，重开当场重算 |
| `/api/schedules/run` | POST | 「立即执行」：立刻跑一次并记账，即使任务被关掉；服务正忙时和别处一样排队 |
