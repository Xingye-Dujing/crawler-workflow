# API 参考

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。

Flask 后端全部 HTTP 端点，按功能分组。工作流的编排、运行记录、数据集、导出、统计、AI、Cookie 与系统配置均通过这里的 REST 接口访问。

## API 参考

### 工作流

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/workflow/save` | POST | 保存工作流配置（含命名） |
| `/api/workflow/load` | GET | 加载指定工作流；有运行在跑时返回 409（换画布会改写在跑那份的工作流名） |
| `/api/workflow/list` | GET | 列出所有已保存工作流，**每个文件一条对象**（`name`/`nodes`/`labels`/`size`/`mtime`/`broken`），供底部「工作流文件」面板直接绘制；读不开的文件也占一行并带 `broken`，好让用户能删掉它 |
| `/api/workflow/rename` | POST | 重命名工作流文件（`{name, new_name}`）：同时改写文件内的 name 与数据集里对旧名的引用，返回 `{ok, name, path, datasets}`；目标名已存在 409、旧名不存在 404、新旧同名 400，正在跑的那份被改名 409，绝不覆盖已有文件 |
| `/api/workflow/delete` | POST | 删除工作流 |
| `/api/workflow/execute` | POST | 执行工作流；已有运行在跑则排队（返回 `queued` 与位次；`queue:false` 保留旧的直接拒绝）。「继续」一定带 `queue:false`——排队期间它指向的运行记录可能被保留策略清掉，那时宁可立刻 400 说明原因，也不会悄悄变成一次从零重爬 |
| `/api/workflow/stop` | POST | 停止执行：浏览器在后台关、请求立即返回；`browsers` 是这次交出去关掉的浏览器数，`records` 是本请求已经就地改判为 `stopping` 的运行行（结论仍由运行自己写） |
| `/api/workflow/status` | GET | 获取执行状态（含 `queue` 等待列表；`stopping`/`settling` 说明"已叫停但结论还没写"，浏览器据此续读而不是抢答） |
| `/api/workflow/queue` | GET | 列出排队中的请求 |
| `/api/workflow/queue/cancel` | POST | 按 `id` 取消一个排队请求（绝不触碰正在跑的运行） |
| `/api/workflow/queue/clear` | POST | 清空队列 |
| `/api/workflow/processes` | GET | 列出执行器/浏览器子进程 |
| `/api/workflow/processes/kill` | POST | 强杀残留进程 |

### 运行记录 / 断点续跑

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/runs/resumable` | POST | 查询指定工作流最近一次可续跑的中断运行（读之前先顺手判定本进程遗留的"运行中/正在停止"行，不重启服务也能进入续跑横幅） |
| `/api/runs/list` | GET | 分页列出运行记录（每条带 `workflow_name`（并行时为全部工作流名，` + ` 连接）、`wf_count`、`mode`、`headless`、`forced_visible`（遗留字段，恒 0：#148 后再没有把无头换成窗口的强制，故不再被写、也不再参与展示），面板据此打「并行 ×N / 串行 ×N」与「无头 / 窗口」标；`status` 可能是 `running` / `stopping` / `interrupted` / `completed` / `failed` / `abandoned`，其中 `stopping` 由「停止」请求就地写入、结论仍由运行自己写。每条还带 `duration_seconds`（运行时长 = `finished_at` − `started_at`；续跑从不刷新 `started_at`，故它是**跨所有尝试的总墙钟时间**；运行中/无法解析时为空），运行记录面板据此多出一列「运行时长」（`MM:SS`，过一小时 `H:MM:SS`，无值为破折号——不谎报 0）。这次读取同时是本进程遗留记录的修复时机） |
| `/api/runs/status` | GET | 单条运行的节点级状态 |
| `/api/runs/stats` | GET | 全局运行统计 |
| `/api/runs/purge` | POST | 按保留策略清理旧运行（中断的最后清理） |
| `/api/runs/discard` | POST | 丢弃一次中断运行（不再提供续跑） |
| `/api/runs/delete` | POST | 删除指定运行 |
| `/api/runs/<run_id>` | GET | 运行详情（含节点行数据摘要）；`run.nodes` 每个节点带 `duration_seconds`（该节点墙钟耗时 = 节点 `finished_at` − `started_at`，秒级、与运行时长同口径；节点未完成时为空，前端详情卡片据此渲染 `MM:SS`，无值为破折号——不谎报 0） |
| `/api/runs/<run_id>/log` | GET | 事后查阅该运行**持久化的控制台**（`runs.db` 的 `run_log`，每条物理行都存、不截断）。查询参数：`wf`（工作流标签下标，空为全部）、`level`（`info`/`warning`/`error`）、`q`（子串搜索）、`before`（「加载更早」游标=已显示最小 seq）、`limit`（缺省 500，夹到 2000）。返回 `{rows(oldest→newest), has_more, min_seq, max_seq}`。未知 run → 404。**只读持久表，绝不触碰 `execution_state`**——与实时控制台、刷新重连无关 |
| `/api/runs/<run_id>/log.txt` | GET | 把同一份持久控制台按**当前过滤**（`wf`/`level`/`q`）整段拼齐，作为 `text/plain` 附件下载（`run-<id>.log`），即「所见即所存」；未知 run → 404 文本 |
### 数据与数据集

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/data/upload` | POST | 上传 CSV/TSV/JSON/TXT/.xlsx/.xls/.xml/.ris/.bib/.enw/.nbib 文件并注册为持久化数据集（未知扩展名→400，不再当 CSV 猜）；CNKI/CSSCI/WoS/Scopus/PubMed/Dimensions/Lens/RIS/BibTeX/EndNote 自动解析为文献记录表，响应额外返回 `biblio_format`、`biblio_capabilities` 与 `warnings`，此时 `is_txt=false`；普通文本仍为单行 `content`、`is_txt=true` |
| `/api/data/paste` | POST | 将粘贴的 JSON 数组注册为数据集 |
| `/api/data/datasets` | GET | 列出已注册数据集 |
| `/api/data/datasets/<id>` | GET / DELETE | 查看 / 删除单个数据集 |
| `/api/data/inspect` | POST | 查看数据集的空值/类型/重复行统计 |
| `/api/data/preview` | POST | 分页查看数据集的原始表格（数据预览面板）；按 `node_id` 取历史行时须带 `workflow_name`——`node-2` 在每个画布上都存在，只凭 id 不猜（重启后没有身份就明确回答"无记录"，返回 `code:no_run_data`，前端显示"请先运行一次"而非原始报错） |
| `/api/data/clear` | POST | 数据集文件-store 的清理：**默认只扫孤儿**（没有已存工作流引用、且久未读取的文件），带 `{"all": true}` 或 `?all=1` 才是真正的清空（连被工作流引用的也删，面板「清空」按钮走这条）；返回 `{ok, removed, ...}` |
| `/api/runs/clear` | POST | 清空全部运行记录，**必须带 `{"confirm": true}`**（否则 400）：正在跑的那条被豁免而不是整体拒绝；被删运行占的"已采集"认领一并交回（清空是"从头开始"，留着台账会让下次同样的采集静默少给条目），而 LLM 答案缓存**故意留下**——一次回答是为它的提问付的钱，不是为那条运行记录 |

### 分析 / 可视化 / 导出（独立于工作流，可单独调用）

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/analysis/run` | POST | 对数据集执行清洗流水线，返回新数据集 id 及报告 |
| `/api/analysis/train` | POST | 从已有 LLM 标注数据集训练传统 ML 模型（情感/倾向） |
| `/api/visualize/render` | POST | 对数据集渲染图表，返回 ECharts option 或 Matplotlib 图片；带 `emit_latex`/`emit_latex_table`（两者默认开）时另返回 `latex`/`latex_file`、`latex_table`/`latex_table_file` 并写入导出目录；上游节点尚无运行数据时返回 **HTTP 200** + `code:no_run_data`（预期空态，不刷控制台 400），前端显示"请先运行一次" |
| `/api/export/save` | POST | 将数据集导出为指定格式文件 |
| `/api/exports/list` | GET | 按时间倒序列出导出文件（名称/类型/大小/可下载标记）与目录合计 |
| `/api/exports/download` | GET | 按**文件名**下载某个导出文件（越界名→404，脚本类扩展名→404） |
| `/api/exports/delete` | POST | 删除单个导出文件（不接受路径、前缀或递归） |
| `/api/exports/clear` | POST | 清空导出目录，**必须带 `{"confirm": true}`**（否则 400）：只逐个删面板列出的那些名字（复用单条删除的同一个解析器，所以子目录与被拒的符号链接不会因为"批量"就漏网），并**反复清到某一轮什么也没删掉为止**（面板列表有 500 条上限，只跑一轮会删掉最新的几百个然后重载出一堆"没清掉"的文件，还报一句已清空）；**有运行在跑时 409 整体拒绝**（流式节点正在往里写分片） |
| `/api/biblio/compare` | GET | 两次快照的差异，**在服务端算**（`biblio_store.compare_snapshots`）：`params_differ` / `nodes.added·removed·changed`（逐列 a→b）/ `edges.added·removed·weight_changed`（无向边按规范化端点对比较——节点表把每条边从两端各列一次，按原始行序比会谎报权重变化）/ `clusters.added·removed·relabeled·size_changed` / `bursts.added·removed·strength_changed`；每段超过 60 条只列前 60，但同时给出 `total`（截断的 diff 装作完整就是错的 diff）。`a`/`b` 缺一个或相同 → 400；任一快照不存在 → 404 并报出是哪个 id |
| `/api/biblio/projects` | GET | 每个项目连同其快照表头（标签 / 时间 / 形态 / 节点数 / 边数 / `params_verified`），一次调用给全面板所需；表头**不带**已存行，行只在 `/api/biblio/snapshots/<id>` 里给（预览上限 100 条，并写出 `node_total`/`edge_total`/`preview_limit`） |
| `/api/biblio/project` `/rename` `/delete` | POST | 建 / 改名 / 删项目；名字为空按 400 拒，项目不存在按 404 指名，删除连带清掉它下面的快照并回报数量 |
| `/api/biblio/snapshot` `/delete` | POST | 把某运行某节点的**全部**已存行捕获进项目（不是当前那一页——前缀相同的两份表比出来的差异是前缀的长度）；参数从**已保存的画布**读取并用运行记下的节点指纹核对，核对不上记 `params_verified=0`，不把面板当前设置当 provenance。非 `biblio` 节点 400、无已存行 400、项目/运行不存在 404，都指名 |
| `/api/exports/ledger` | GET | 列出**写过导出文件**的每一次运行及其文件清单（`run_id`/`workflow_name`/`started_at`/`files[{name,kind,node_id}]`）——「智能清除」选择器的数据源，读 `runs.db` 的运行→文件台账而非目录扫描，所以只给可操作的记录 |
| `/api/biblio/runs` | GET | 文献计量工作区的数据源：按时间倒序列出**含 `biblio` 节点的运行**，每条带该运行里的节点（`node_id/title/status/row_count/component_name`）与其登记产物（`biblio_*` / `latex`）。判定「哪些算文献计量运行」是服务端对 `node_runs.node_type` 的读取，浏览器不再自己判断，因此重启后、刷新后、画布改过后仍能找回那次付费运行 |
| `/api/biblio/table` | GET | 分页读回某运行某节点的已存表：`run_id` + `node_id` + `offset`/`limit`（默认 200，上限 1000，非法值收敛为更小的一页而非 500），返回 `columns/rows/total/offset/shape/files`。`shape` 由**列本身**判读（`classify_shape`：`nodes`/`edges`/`clusters`/`bursts`/`dual_map`，判不出为空串），面板据此显示「输出形态未知」而不是猜一个。运行不存在→404 并报出 id；节点不在该运行→404；节点不是文献计量→400；节点存在但没有已存行（被停止/失败/清理）→200 且带 `note` 指名该节点，绝不画成一张空表 |
| `/api/exports/clear-run` | POST | 按**一次运行**清除它产生的全部文件，**必须 `{"run_id","confirm":true}`**（缺 confirm→400、缺 run_id→400）：只删台账登记的这些名字（复用单条删除解析器），**「固定」条目跳过**、返回 `{removed,skipped_locked,missing,requested}`；有运行在跑时 409；只删磁盘产物，不动 `runs.db` 记录与其已存的行 |
| `/api/exports/clear-run-parts` | POST | 按**一次运行 × 一个数据源节点**只清除其分片文件（`kind='part'`），**保留合并文件**；必须 `{"run_id","node_id","confirm":true}`。作用域锁在 `(run_id,node_id,'part')`，绝不碰别的运行、别的节点或合并/实时文件。删成功的名字同步从台账遗忘 |
| `/api/exports/clear-name` | POST | 按**名字**清除某一批分片（面板分片行的「清除该批分片」按钮）：传入某个 `{stem}.part{NNN}{ext}`，删同名同扩展的全部 `.partNNN` 分片；**保留合并文件、别的 stem/扩展名与「固定」条目**，复用单条删除的解析器逐个删；必须 `{"name","confirm":true}`；传入的不是分片→400（点名）、有运行在跑→409；返回 `{removed,skipped_locked,missing,requested,name}` |
| `/api/report/generate` | POST | 生成自包含 HTML 运行报告（本次运行的表格，或按 `run_id` 读历史运行；可选 AI 结论；可选 `options` 定制：`show_charts/tables/facts`、`max_rows`、`node_ids` 选节点、`images` 内联导出目录里的成图） |
| `/api/report/view` | GET | 按名查看报告：仅接受 `report-` 前缀的 `.html`，响应带禁脚本 CSP |
| `/api/report/pdf` | POST | 把已生成的报告按名用无头 Chrome 打印成 PDF（找不到 Chrome 或非报告名 → 报错，HTML 不受影响） |
| `/api/report/studio-images` | GET | 列出导出目录里的成图（图片扩展名）供报告内联选择 |

### Chart Studio

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/studio/dataset` | POST | 把画布任意节点/数据集的完整表格交给 Studio（支持多源合并） |
| `/api/studio/sources` | POST | 预检哪些节点当前有可用的表格数据（与预览同一套取行规则：带 `workflow_name`，不按裸 id 猜） |
| `/api/studio/save-image` | POST | 把 Studio 成品图保存为 PNG 到导出目录 |

### 统计与历史

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/stats/emotion` | GET | 情感统计 |
| `/api/stats/tendency` | GET | 倾向性统计 |
| `/api/stats/summary` | GET | 执行汇总统计 |
| `/api/history/runs` | GET | 列出所有已记录的工作流执行 |
| `/api/history/series` | GET | 按工作流/指标查询时间序列（执行历史面板趋势图） |
| `/api/history/clear` | POST | 清空执行历史记录 |
| `/api/history/delete` | POST | 删除**单次运行**的执行历史（`{run_id}`）；返回 `deleted` 条数，0 表示这条运行已不在历史里（可能被保留策略清掉了），不谎报成"已删除"；不带 `run_id` 一律 400 |

### AI / Cookie / 系统

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/llm/models` | GET | 拉取 OpenRouter 免费模型列表 |
| `/api/llm/ollama/models` | GET | 列出本地 Ollama 已拉取模型 |
| `/api/llm/test` | POST | 测试所选提供方的连通性 |
| `/api/cookies/status` | GET | 各平台 Cookie 是否存在 |
| `/api/cookies/flow` | GET | 每个平台 Cookie 的用途、获取步骤、默认登录页与可接受域名（Cookie 面板据此渲染） |
| `/api/cookies/save` | POST | 保存指定平台 Cookie（不属于该平台的域名条目会被剔除，一条都不剩时直接拒绝而不是存个空文件） |
| `/api/cookies/generate` | POST | 打开浏览器引导扫码登录并捕获 Cookie；可选 `url` 指定入口链接（仅限该平台域名），取 Cookie 前先把浏览器带回本平台页面 |
| `/api/cookies/verify` | POST | 用已存 Cookie 实地探测该平台还放行什么（结论逐条回显：可用 / 仍被挡在登录页 / 回的是验证码·风控所以**没有结论**） |
| `/api/cookies/delete` | POST | 删除该平台的 Cookie 快照文件；回话里说清该平台的浏览器 profile 是否仍持有登录态（删文件不会把 profile 登出） |
| `/api/profiles/delete` | POST | 删除某**命名账号**自己的浏览器 Profile 目录（真正退休那台设备、把它登出），**不动 Cookie 文件**；默认账号结构性拒绝（它就是平台根目录、别的账号都嵌在里面）、被占用 409、没有可删 404、非法名 400，删后作废预检缓存 |
| `/api/cookies/rename` | POST | 给一个已存登录改名字——Cookie 文件与它自己的浏览器目录**一起搬或一样都不动**（目录先搬：被采集占用就 409「浏览器正被使用」、文件留原地）；默认那份结构性拒绝（它不拥有自己的目录），目标名被占用/非法/空/与原名相同各自点名拒绝，绝不静默覆盖或谎报成功 |
| `/api/cookies/preflight` | POST | 运行前一次性验证画布要用到的多个平台：`{platforms, use_profile?, fresh?}` → 逐平台 `valid/expired/unknown/nocookie/nologin/notcrawlable` + 已渲染文案 + `blocked`/`unclear` 两个清单（结果按 `COOKIE_PREFLIGHT_TTL` 缓存） |
| `/api/settings` | GET / POST | 读取 / 修改运行时设置（data/settings.json） |
| `/api/browser/profiles` | GET | 每个平台的持久浏览器 Profile 状态（是否启用、目录是否已建、是否已导入过 Cookie、占用空间、是否建议开启），外加 `template` 一行——`{exists, pristine}`，即"新账号能不能从它克隆"（pristine 由**读表里的行数**判定，不看文件名） |
| `/api/browser/profiles/template` | POST | 用一台空白 Chrome 生成/重建那个初始模板（`{force?}`；已存在的脏模板会先销毁再建）。建不出来时是 **502 带原因**（本机没有 chromedriver / Chrome 拒了），不是 200 加一句谎；平时由第一次保存 Cookie 的那条路自己调用 |
| `/api/config` | GET | 系统配置 |
| `/api/capabilities` | GET | 采集矩阵：每个平台支持哪些采集模式、每种模式要填什么（数据源面板整块由它渲染，中英词条用 key 送出） |
| `/api/models` | GET | 已注册微调模型清单（读 `data/model_registry.json`）：`{name, path, desc}`，情绪/倾向/情感节点的 `bert` 模式据此把「模型名」列成**显示名复选框**（如「网暴模型」）——可勾选多个，勾选写入 `bert_models`（逗号分隔的**路径**），≥2 个时该节点逐模型跑一遍并输出**多模型对比长表**（新增 `模型`/`原行` 两列），供热力图与 `model_agreement` 一致率图对比。文件缺失 / 不是列表 / JSON 损坏都回**空列表而非报错**（节点仍可手填路径），没有 `path` 的条目被丢弃。只读 |

### 定时任务

面板只认一个载荷：**每个回答都带全量 `{ok, tasks, canvases, status}`**，所以任何一次请求回来都能整块重画，页面上不会出现半旧半新的表。`tasks` 是已存任务（`trigger_text`/`next_run_local`/`last_run_local` 由服务端按**任务自己的时区**渲染，浏览器时区与之无关），`canvases` 是每个已存画布能否上定时的结论（`runnable`/`why_not`），`status` 是调度时钟本身（`running`/`wired`/`tick_seconds`/`now_local`/`local_zone`）。

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/schedules` | GET | 任务 + 画布可跑性 + 时钟状态，面板开合与每次改动后刷新 |
| `/api/schedules/save` | POST | 新建或按 `id` 原地更新一个任务。时间表达 `{kind:'daily'\|'weekly'\|'interval'\|'cron', ...}` 原样存；**保存期与触发期用同一条规则**——画布里有需要模型的节点就具名拒绝（400），画布不存在、时间写不通、cron 永不触发（如 `0 0 30 2 *`）、时区名不认识都各自点名拒绝，绝不猜一个差不多的 |
| `/api/schedules/delete` | POST | 删除一个任务（没有此 id 回 404） |
| `/api/schedules/toggle` | POST | 开关一个任务：关掉即清空 `next_run`（不再计时），重开当场重算 |
| `/api/schedules/run` | POST | 「立即执行」：立刻跑一次并记账，**即使这个任务被关掉**。`result.status` 是 `started`/`queued`——服务正忙时和别处一样**排队**，不另开一条路；失败回 400 并在任务历史里留一条 `refused` |
