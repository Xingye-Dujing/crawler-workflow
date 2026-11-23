# API 参考

> 返回总览见 [README.md](../README.md)。采集矩阵与平台边界见 [crawler_rules.md](crawler_rules.md)，AI 端点背后的目录、上下文与工具体系见 [ai_workspace.md](ai_workspace.md)。

Flask 后端 HTTP 端点，按域名分组。未登录时 `/api/*` 答 401 `{ok:false,error}` 并带 `X-Auth-Required: 1`，页面跳 `/login?next=<原地址>`；写请求必须带 `X-CSRF-Token`（登录表单用一次性 `csrf` 字段）。会话 Cookie `cixi_session` 只含随机 token，服务端只存其 sha256。每个账号的数据根是 `data/users/<user_id>/`（`runtime/paths.py`），运行队列与定时任务按账号归属。
### 认证与账号

| 端点与方法 | 说明 |
|---|---|
| `GET`/`POST` `/login` · `POST` `/logout` | 登录页与提交（`username`/`password`/`next`/`csrf`），成功跳 `next` 或 `/`，失败 401 重绘且不写会话 / 吊销会话并跳 `/login` |
| `GET` `/api/account/me` · `POST` `/api/account/password` | 当前账号 `{user_id, username, role, must_change_password}` / 本人改密（吊销其它会话；猜错与登录共用失败窗口，超限 429） |
| `GET`/`POST` `/api/accounts` · `POST` `/api/accounts/<id>/password` · `POST` `/api/accounts/<id>/status` | 管理员列出 / 创建账号（列表带 `created_local`/`last_login_local`）/ 重置密码并吊销该账号会话 / `active` 或 `disabled`（禁用即吊销，有运行中任务 409） |
| `POST` `/api/accounts/<id>/unlock` · `POST` `/api/accounts/<id>/logout` · `DELETE` `/api/accounts/<id>` | 解除失败登录锁定 / 强制下线并释放库句柄 / `{confirm_username}` 删除：先吊销会话再把目录移入 `users/.trash/`；运行中或有登录窗口 409，最后一个管理员不可删 |
| `GET` `/api/accounts/audit` | 最近审计（`limit` ≤ 500，每条带 `ts_local`）；账号管理动作都会记审计 |
### 工作流、画布与项目包

| 端点与方法 | 说明 |
|---|---|
| `POST` `/api/workflow/save` · `GET` `/api/workflow/load` · `GET` `/api/workflow/list` | 保存 / 加载（有运行在跑 409）/ 列出（每文件一条，读不开的带 `broken`） |
| `POST` `/api/workflow/rename` · `POST` `/api/workflow/delete` | 改名（同步改文件内 name 与数据集引用，不覆盖已有文件）/ 删除 |
| `POST` `/api/workflow/execute` · `POST` `/api/workflow/rerun-node` | 执行（忙则排队并回 `queued` 与位次，`queue:false` 直接拒绝，“继续”必带）/ 重跑一个节点及其下游：抢到槽位后才擦除再以同一 `resume_run_id` 重启 |
| `POST` `/api/workflow/diagnostics` · `POST` `/api/workflow/stop` · `GET` `/api/workflow/status` | 只读诊断 / 停止（回 `browsers`/`records`）/ 状态（`queue`、`stopping`/`settling`、`run_ids`、`node_states`） |
| `GET` `/api/workflow/queue` · `POST` `/api/workflow/queue/cancel` · `POST` `/api/workflow/queue/clear` | 排队列表 / 按 `id` 取消 / 清空；都不触碰正在跑的运行 |
| `GET` `/api/workflow/processes` · `POST` `/api/workflow/processes/kill` · `GET` `/api/node-types` | 本次运行的线程与浏览器子进程 / 强杀残留线程（只限自己运行）/ 服务端节点类型目录（`nodes/catalog` 单一声明） |
| `GET`/`POST` `/api/workflow/history/layout` · `GET` `/api/workflow/history` · `POST` `/api/workflow/history/save` · `GET` `/api/workflow/history/get` · `POST` `/api/workflow/history/rename` · `POST` `/api/workflow/history/delete` | 读 / 存工作流排布策略（`algorithm` 或 `baseline` + `snapshot_id`）；快照列表（不返回内容，上限 100 份）、保存、取内容、改标签、删除 |
| `GET` `/api/project/export` · `POST` `/api/project/import` | 导出当前或全部工作流为 zip（`manifest.json` + `workflows/` + `datasets/` + `templates/`；`X-Project-Warnings` 为警告数）/ 导入时重分配 id、改写引用、同名加 ` (2)`，任一校验不对 400 |
### 模板与运行记录

可复用模板存 `data/reusable_nodes/<id>.json`，服务端只校验与存取，展开在浏览器。

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/reusable` · `GET` `/api/reusable/get` · `POST` `/api/reusable/save` | 列表（含 `broken` 行）/ 按 `id` 取内容 / 新建或更新；重名、空名、无节点、未知类型、悬空或重复连线、有环、输出不是恰好一个末端节点都按名拒绝 |
| `POST` `/api/reusable/rename` · `POST` `/api/reusable/delete` | 改名 / 删除；已插入实例保留自己的模板快照 |
| `GET` `/api/runs/list` · `GET` `/api/runs/stats` · `GET` `/api/runs/status` · `GET` `/api/runs/<run_id>` | 分页运行记录（含 `workflow_name`/`wf_count`/`mode`/`duration_seconds`）/ 全局统计 / 节点级状态 / 详情（每节点带 `duration_seconds`） |
| `POST` `/api/runs/resumable` · `POST` `/api/runs/for-workflow` · `GET` `/api/runs/compare` | 可续跑的中断运行 / 某画布按结构指纹列出的运行（新→旧）/ `?a=&b=&node=&key=&limit=` 对比；单节点超 200000 行拒绝对比 |
| `GET` `/api/runs/<run_id>/log` · `GET` `/api/runs/<run_id>/log.txt` | 读持久化控制台（`wf`/`level`/`q`/`before`/`limit`）/ 同内容下载为 `text/plain` |
| `POST` `/api/runs/purge` · `POST` `/api/runs/discard` · `POST` `/api/runs/delete` · `POST` `/api/runs/clear` | 按保留策略清理 / 丢弃中断运行 / 删除指定运行（保留其已采集认领）/ 清空全部（必须 `{"confirm": true}`，跳过正在跑的那条，留下 LLM 答案缓存） |
### 数据集与数据操作

| 端点与方法 | 说明 |
|---|---|
| `POST` `/api/data/upload` · `POST` `/api/data/paste` | 上传 CSV/TSV/JSON/TXT/.xlsx/.bib/.ris/.enw 等并注册数据集 / 粘贴 JSON 数组；文献导出件自动解析并回报 `biblio_format`/`biblio_capabilities` |
| `GET`/`DELETE` `/api/data/datasets/<id>` · `GET` `/api/data/datasets` · `POST` `/api/data/datasets/<id>/rename` | 查看或删除 / 列出 / 改显示名（id 是内容哈希，不改身份与指针） |
| `POST` `/api/data/diff` · `POST` `/api/data/inspect` | 两表逐行对比（可选 `key` 判定变化行）/ 空值、类型、重复行统计 |
| `GET` `/api/data/lineages` · `POST` `/api/data/lineages/reset` · `POST` `/api/data/merge` | 累积谱系与版本历史 / 清空谱系指针 / 合并数据集（列集合须一致，相同内容复用 id，超 300000 行拒绝） |
| `POST` `/api/data/preview` · `POST` `/api/data/clear` | 分页预览（按 `node_id` 取行须带 `workflow_name`，可选 `run_id`；无身份回 `code:no_run_data`）/ 默认只清孤儿文件，`{"all": true}` 才清空 |
### 词表、锁定与账号池

| 端点与方法 | 说明 |
|---|---|
| `GET`/`POST`/`DELETE` `/api/lexicon` | 词表（`?kind=`/`?limit=`，读 `data/lexicon.db`）/ 写入 / 删除；未知 kind 按名 400 |
| `GET`/`POST` `/api/locks` | 各面板锁定键清单 / 锁定或解锁一条并返回该面板完整清单 |
| `GET` `/api/pool/state` · `POST` `/api/pool/account/reset` · `POST` `/api/pool/account/disable` | 账号健康、绑定与出口清单 / 清除冷却（含未到期）/ 手工停用或恢复 |
| `POST` `/api/pool/exit/save` · `POST` `/api/pool/exit/delete` · `POST` `/api/pool/exit/import` · `POST` `/api/pool/bind` | 新建或编辑出口 / 删除 / 批量粘贴（一行一个代理）/ 把账号钉到出口或清空钉选；细节见 [account_pool.md](account_pool.md) |
### 分析、可视化与导出

| 端点与方法 | 说明 |
|---|---|
| `POST` `/api/analysis/run` · `POST` `/api/analysis/train` | 对数据集跑清洗流水线 / 从标注数据集训练情感、倾向模型 |
| `POST` `/api/visualize/render` | 渲染图表，返回 ECharts option 或图片；带 `emit_latex`/`emit_latex_table` 时另写导出；无运行数据回 200 + `code:no_run_data` |
| `POST` `/api/export/save` · `GET` `/api/exports/list` · `GET` `/api/exports/download` · `POST` `/api/exports/delete` | 导出数据集 / 列出 / 按文件名下载 / 删除单个文件 |
| `GET` `/api/data/datasets/<dataset_id>/download` | 把存下的数据集渲染成 CSV 直接下载（数据集面板的“下载”）；未知 id 404，不写入导出目录 |
| `POST` `/api/exports/clear` | 清空导出目录，必须 `{"confirm": true}`；有运行在跑 409 |
| `GET` `/api/exports/ledger` · `POST` `/api/exports/clear-run` · `POST` `/api/exports/clear-run-parts` · `POST` `/api/exports/clear-name` | 写过导出文件的每次运行及清单 / 按运行清除 / 按运行 × 节点清分片 / 按分片名清同一批；保留合并文件与固定项 |
### 文献计量

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/biblio/projects` · `GET` `/api/biblio/runs` · `GET` `/api/biblio/table` | 项目与快照表头 / 含 `biblio` 节点的运行及登记产物 / 分页读某运行某节点的已存表 |
| `GET` `/api/biblio/snapshots/<id>` · `GET` `/api/biblio/compare` | 快照内容（预览 100 条，附 `node_total`/`edge_total`）/ `?a=&b=` 在服务端算节点、边、聚类、突发差异，每段超 60 条只列前 60 并给 `total` |
| `POST` `/api/biblio/project` · `POST` `/api/biblio/project/rename` · `POST` `/api/biblio/project/delete` · `POST` `/api/biblio/snapshot` · `POST` `/api/biblio/snapshot/delete` | 建 / 改名 / 删项目（连带清快照）/ 捕获某运行某节点的全部已存行进项目 / 删除快照；非 `biblio` 节点或无已存行 400 |
| `GET` `/api/biblio/sources` | 可读来源的官网链接、扩展名、可带字段与导出指引；只读 |
### 报告、论文与 Chart Studio

| 端点与方法 | 说明 |
|---|---|
| `POST` `/api/report/generate` · `GET` `/api/jobs/<job_id>` · `GET` `/api/report/view` | 启动自包含 HTML 报告任务并回 202 + `job` / 轮询文档任务（仅启动它的账号）/ 按名查看报告（仅 `report-` 前缀 `.html`，带禁脚本 CSP） |
| `POST` `/api/report/latex` · `GET` `/api/report/studio-images` | `{run_id, title}`：用该运行已登记的 LaTeX 源合成 `article`+`ctex` 并用本机 `xelatex` 编译 PDF / 可内联进报告的成图 |
| `POST` `/api/studio/dataset` · `POST` `/api/studio/sources` · `POST` `/api/studio/save-image` · `POST` `/api/studio/save-vector` · `POST` `/api/studio/save-pdf` | 把节点或数据集交给 Studio（支持多源合并）/ 预检可用表格 / 存 PNG / 存 SVG（校验 `<svg>`、xmlns、脚本与外部引用、尺寸）/ 用已登记源编译矢量 PDF |
### 统计与执行历史

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/stats/emotion` · `GET` `/api/stats/tendency` · `GET` `/api/stats/summary` · `GET` `/api/run/phases` | 情感 / 倾向 / 执行汇总统计 / 控制台的阶段耗时条 |
| `GET` `/api/history/series` · `POST` `/api/history/clear` | 按工作流与指标查时间序列（同时回 `workflow_names`）/ 清空执行历史指标；运行列表只由 `/api/runs/*` 提供 |
### AI 工作区

供应商目录在 `ai/providers/registry.py`，密钥只由浏览器发送、服务端在一次请求内持有，不落盘；会话、技能、插件、附件与 Python 脚本都按 `runtime/paths.py` 的账号隔离。

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/ai/ws/bootstrap` · `GET` `/api/ai/ws/providers` · `GET` `/api/ai/ws/providers/<id>/models` · `POST` `/api/ai/ws/providers/<id>/test` | 启动载荷（供应商、技能、会话、用量、设置、插件、工具、监视器）/ 目录 / 实时模型（取不到回退声明目录）/ 一次极小往返验证 |
| `POST` `/api/ai/ws/chat` · `POST` `/api/ai/ws/answer` · `POST` `/api/ai/ws/stop` | 一轮对话（SSE，`?stream=0` 回事件 JSON）/ 回答 `ask_user_question` 并继续同一轮 / 设置该会话取消事件 |
| `GET`/`POST` `/api/ai/ws/conversations` · `GET`/`PATCH`/`DELETE` `/api/ai/ws/conversations/<id>` · `POST` `/api/ai/ws/context` · `POST` `/api/ai/ws/conversations/<id>/context` | 会话列表、新建、详情（含消息与附件）、改名或置顶、删除 / 预览一次上下文构建 |
| `GET`/`POST` `/api/ai/ws/skills` · `GET`/`DELETE` `/api/ai/ws/skills/<id>` · `POST` `/api/ai/ws/skills/<id>/fork` | 技能目录 / 保存用户技能 / 完整技能 / 删除 / 从内置 Fork |
| `GET` `/api/ai/ws/plugins` · `POST` `/api/ai/ws/plugins/install` · `POST` `/api/ai/ws/plugins/<id>/enable` · `DELETE` `/api/ai/ws/plugins/<id>` | 插件清单 / 安装声明式插件（代码插件仅本地与管理员）/ 启停 / 卸载 |
| `GET`/`POST` `/api/ai/ws/memories` · `DELETE` `/api/ai/ws/memories/<id>` · `POST` `/api/ai/ws/files` · `GET` `/api/ai/ws/conversations/<id>/files` · `DELETE` `/api/ai/ws/files/<id>` | 长期记忆的列、存、删 / 上传附件（当前仅 DeepSeek）/ 列会话附件 / 删附件 |
| `GET`/`POST` `/api/ai/ws/monitors` · `DELETE` `/api/ai/ws/monitors/<id>` · `GET` `/api/ai/ws/monitors/catalog` · `GET` `/api/ai/ws/monitors/events` · `POST` `/api/ai/ws/monitors/events/<id>/ack` | 监视器列表、创建、取消 / 手动构建器的事件名清单（来自服务端匹配表）/ 待投递事件与确认；事件只带 id、状态与计数，不花 token |
| `POST` `/api/ai/ws/rerun` | 从**已保存的工作流文件**重跑一个失败节点及其下游（失败节点卡片的按钮）；指纹不符、文件缺失、节点未知或运行仍进行时按名拒绝，不载入画布 |
| `GET` `/api/ai/ws/python/status` · `POST` `/api/ai/ws/python/install` · `GET`/`POST` `/api/ai/ws/python/scripts` · `GET`/`DELETE` `/api/ai/ws/python/scripts/<id>` · `POST` `/api/ai/ws/python/scripts/<id>/fork` · `POST` `/api/ai/ws/python/run` | 解释器探测与安装、脚本库增删改查与 Fork、按 `script_id` 或内联 `code` 运行；云端与普通账号按名拒绝（脚本库是机器级共享状态） |
| `GET` `/api/ai/ws/usage` · `GET` `/api/ai/ws/health` | 本账号 token 汇总 / 健康检查（联网搜索与抓页只在回合内作为工具调用，密钥随该请求） |
### 供应商、Cookie、设置与系统

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/llm/models` · `GET` `/api/llm/ollama/models` · `POST` `/api/llm/test` | OpenRouter 免费模型 / 本地 Ollama 模型 / 测试所选提供方 |
| `GET` `/api/cookies/status` · `GET` `/api/cookies/flow` · `POST` `/api/cookies/save` · `POST` `/api/cookies/delete` | 各平台 Cookie 状态 / 用途与步骤 / 保存（剔除不属于该平台的条目）/ 删除并说明 profile 是否仍持有登录态 |
| `POST` `/api/cookies/generate` · `GET` `/api/cookies/generate/status` · `POST` `/api/cookies/generate/confirm` · `POST` `/api/cookies/generate/cancel` | 打开浏览器扫码登录并捕获 / 任务状态 / 立即捕获 / 取消 |
| `POST` `/api/cookies/verify` · `POST` `/api/cookies/preflight` · `POST` `/api/cookies/rename` · `POST` `/api/profiles/delete` | 实地探测一份 Cookie / 跑前验证画布涉及的多个平台（`valid`/`expired`/`unknown`/`nocookie`/`nologin`/`notcrawlable`）/ 改名 / 删命名账号的 Profile；默认账号结构性拒绝 |
| `GET`/`POST` `/api/settings` · `GET` `/api/settings/schema` · `GET` `/api/settings/export` · `POST` `/api/settings/import` · `POST` `/api/settings/preset` | 读写设置（写与导入导出仅管理员，其余账号只读）/ 面板渲染的声明 / 导出 / 导入（可 `dry_run`）/ 应用或恢复预设 |
| `GET` `/api/browser/profiles` · `POST` `/api/browser/profiles/template` · `GET` `/api/config` · `GET` `/api/capabilities` · `GET` `/api/models` | Profile 状态与 `template` / 重建模板 / 默认模型、`cloud_mode`、`installer_available`、CSRF / 平台 × 引擎 × 功能矩阵加 `machine` 与 `backends.catbus` / 微调模型 `{name, path, desc, operation}` |
### 定时任务

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/schedules` · `POST` `/api/schedules/save` · `POST` `/api/schedules/delete` | 任务、画布可跑性与时钟状态（每次全量 `{ok, tasks, canvases, status}`）/ 新建或按 `id` 更新（需模型的画布、坏时间、永不触发的 cron、未知时区都按名拒绝）/ 删除 |
| `POST` `/api/schedules/toggle` · `POST` `/api/schedules/run` | 开关（关掉清 `next_run`，重开当场重算）/ 立即执行一次并记账，服务忙则排队 |

`next_run_local`/`last_run_local`/`trigger_text`/`runnable`/`why_not` 与时钟状态都由服务端按任务自己的时区算好。
### 环境、组件与自更新

| 端点与方法 | 说明 |
|---|---|
| `GET` `/api/environment` · `GET` `/api/components` | 能力矩阵（主程序、Selenium、CatBus、LLM、BERT、PDF、中文图表等，每行 `state` 与 `reason_key`）/ 组件清单、版本、体积、可下载性与更新 |
| `POST` `/api/components/install` · `GET` `/api/components/jobs/<job_id>` · `POST` `/api/components/jobs/<job_id>/cancel` · `POST` `/api/components/remove` | 启动后台安装 / 轮询任务 / 取消（已完成字节可续传）/ 删组件；主程序本身 400 |
| `GET` `/api/update/check` · `POST` `/api/update/download` · `GET` `/api/update/status` · `POST` `/api/update/cancel` · `POST` `/api/update/restart` | 查更新 / 下载或续传 / 状态与日志 / 取消 / 有运行在跑 409，否则结束本进程交给替换脚本；仅管理员，见 [release.md](release.md) |
