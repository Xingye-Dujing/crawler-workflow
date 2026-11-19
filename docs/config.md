# 配置

> 返回总览见 [README.md](../README.md)。跨系统与云端部署的规则本体见 [AGENTS.md](../AGENTS.md)，采集节奏带来的行为变化见 [crawler_rules.md](crawler_rules.md)。

配置分三层：启动时读取的环境变量、可在设置面板修改并写入 `data/settings.json` 的运行时设置、以及 `core/config.py` 里的固定常量。数据根由 `CRAWLER_DATA_ROOT` 决定，运行时状态在 `data/` 与 `logs/`。

## 环境变量

| 变量 | 说明 | 默认值 |
|---|---|---|
| `OLLAMA_MODEL` / `OLLAMA_HOST` | 本地模型名 / 服务地址 | `qwen3.5:9b` / `http://localhost:11434` |
| `SECRET_KEY` | 会话签名密钥；cloud 模式沿用仓库默认值会拒绝启动 | `crawler-workflow-secret-key` |
| `CRAWLER_ADMIN_USER` / `CRAWLER_ADMIN_PASSWORD` | 账号表为空时创建初始管理员；已有账号时忽略。回退 `CRAWLER_AUTH_USER`/`CRAWLER_AUTH_PASSWORD` | `admin` / 空 |
| `CRAWLER_SESSION_IDLE_MINUTES` / `CRAWLER_SESSION_MAX_HOURS` | 会话空闲与绝对有效期；写坏了按默认值继续启动 | `120` / `24` |
| `CRAWLER_HTTPS` | 代理终止 TLS 时设 `1`，会话 Cookie 标记 `Secure` | 关闭 |
| `CRAWLER_TRUST_PROXY_DEPTH` | 前面有几层反向代理。设了才读 `X-Forwarded-For` 的右数第 N 个地址，用于审计与登录失败窗口；`0` 完全不信该头 | `0` |
| `PORT` / `HOST` | 端口 / 监听地址。绑定非本机地址要求账号已启用，否则按名拒绝启动 | `5000` / `127.0.0.1` |
| `CRAWLER_DATA_ROOT` | `data/` 与 `logs/` 的父目录，优先级最高；未设时源码运行落在仓库根，打包启动器另有一套回退链 | 仓库根 |
| `CRAWLER_CLOUD` | 云端形状（`1`/`true`/`yes`/`on`）；`python app.py cloud` 等价 | 关闭 |
| `FLASK_DEBUG` | 调试模式（热重载、自动开浏览器、可执行任意代码） | 关闭 |
| `MAX_UPLOAD_MB` | 单请求体上限，超出返回 413 JSON | `64` |
| `CHROME_PATH` / `CHROME_BIN` | 浏览器可执行文件；指向不存在的文件时采集按名拒绝，不换浏览器顶上 | 空 |
| `CIXI_DRIVER_PATH` | chromedriver；留空由 Selenium Manager 匹配。安装器模式下只认启动器导出的路径 | 空 |
| `CIXI_COMPONENTS_DIR` | 在线安装器的组件目录（清单 `install-manifest.json` 在其上一级） | 安装根下的 `components/`；源码运行 `data/components` |
| `CIXI_COMPONENT_SOURCE` | `bundled`（只认安装器安装的 Chrome/驱动/Node/CatBus）或 `system`（只查本机） | 启动器写入；源码取 `component_source` 设置 |
| `CIXI_NODE_BIN` / `NODE_BIN` | CatBus 用的 Node 运行时，版本按 CatBus `engines` 核对 | 空 |
| `CIXI_CATBUS_CLI` / `CATBUS_CLI` / `CATBUS_HOME` | **采析绘适配器**入口（`dist/integrations/crawler-workflow/cli.js`）或源码检出根；找不到就不提供画布第二后端。与下面的 `CATBUS_BIN` 不冲突 | 空 |
| `CATBUS_BIN` | **catbus 主程序**（`catbus` 可执行文件或 `dist/cli/main.js`），由适配器找它来跑平台命令；AI 指令路径用全局 `catbus`（`npm i -g catbus-cli`），也走这个约定 | 空（适配器按 `PATH` 找） |
| `CIXI_PYTHON_BIN` / `AI_PYTHON_BIN` | Python 扩展用的解释器，优先于 `ai_python_path` 设置 | 空 |
| `PYTHONUTF8` / `LANG` | 控制台编码：`stdout/stderr` 写不了汉字时改用 UTF-8 | — |
| `CIXI_UPDATE_PUBKEY` | 更新清单的校验公钥（PEM 文本或路径）；配了就必须签名有效，见 [release.md](release.md) | 空 |
| `CIXI_UPDATE_FEED` | 覆盖更新清单地址 | Gitee 与 GitHub 的 `version.json` |

`X-Forwarded-Prefix` 只接受形如 `/cixi` 的路径前缀，含 `//`、反斜杠、`..` 或 scheme 的值被丢弃并记一行日志。

## 运行时设置

声明在 `runtime/settings_schema.py` 的 `SETTINGS`（一个键一条 `Setting`，含类型、范围、分组、中英文标签、读取方、可移植性），`runtime/settings.py` 负责加载、校验与持久化。设置页由 `GET /api/settings/schema` 渲染，慢速项默认收在“显示高级项”之后。

| 键 | 说明 |
|---|---|
| `driver_path` · `browser_binary` · `latex_binary` · `window_size` · `page_load_timeout` · `element_timeout` · `ollama_host` | 驱动、浏览器、`xelatex`、窗口尺寸（`960x920`）、页面/元素超时（40/15 秒）、Ollama 地址 |
| `component_source` · `catbus_cli` · `catbus_node` | 组件来源（重启生效）；CatBus 适配器与 Node 的本机路径，留空按系统查找 |
| `use_browser_profile` · `browser_profile_dir` · `max_visible_browsers` · `max_headless_browsers` | 每平台持久 Profile（默认开）与其根目录；窗口/无头并行浏览器上限（默认 4） |
| `crawl_pace_scale` · `crawl_scroll_scale` · `crawl_scroll_interval` · `crawl_expand_scale` · `crawl_click_scale` · `crawl_wait_scale` · `crawl_arrival_scale` · `crawl_page_scale` · `crawl_jitter` · `crawl_patience_scale` | 九个速度倍数（礼貌停顿、滚动落地、展开、点击、元素等待、页面到达、页面间隔、像人抖动（%）、耐心重试；默认 1，抖动 0）+ 一个秒数：`crawl_scroll_interval` 是两次滚动之间的间隔（默认 1.2 秒，每滚一下付一次） |
| `page_wait_timeout` · `same_platform_stagger` · `same_platform_queue` · `cookie_preflight_before_run` · `ask_overseas_network` · `clear_console_before_run` | 首屏预算（300 秒）、同平台错峰秒数、真排队（默认关）、跑前 Cookie 验证（默认关）、海外平台前询问（默认开）、开跑清控制台（默认开） |
| `wall_retry_backoff` · `wall_proofs` · `wall_poll` · `nav_retry` · `nav_settle` · `max_pending_waits` | 首行前撞墙的退避、读墙次数与间隔；导航重试与未到达页面的熔断 |
| `profile_lock_timeout` · `platform_gate_timeout` · `renderer_probe_timeout` · `renderer_close_timeout` | Profile 锁、同平台排队、渲染器健康检查与关闭宽限（秒） |
| `cookie_preflight_timeout` · `cookie_preflight_ttl` · `cookie_preflight_max_parallel` | 跑前验证的预算、结论缓存与并发（45 秒 / 300 秒 / 4） |
| `run_max_rows_per_node` · `dataset_max_rows` · `max_upload_mb` | 单节点落盘、单数据集与上传大小上限（500000 / 300000 / 64） |
| `run_keep_per_workflow` · `run_keep_days` · `dataset_keep_days` · `housekeeping_interval_minutes` | 保留策略与清理间隔（20 / 30 / 90 / 60）；中断/进行中的运行不会被“按天”清掉——它是继续要用的游标 |
| `log_max_mb` · `log_backup_count` | 日志轮转大小与份数（重启生效） |
| `default_run_mode` · `default_headless` · `default_target_count` · `default_comment_limit` · `default_comment_part_size` · `default_source_part_size` · `default_per_article_file` · `default_keep_parts` · `default_live_export` | 新节点的运行模式、目标数、评论上限、分片、按篇拆分、保留分片与实时导出 |
| `workflow_save_mode` | 工作流文件保存方式：`auto`（默认，改动后几秒静默写回打开的文件）或 `manual`（只有点“保存”才写文件；刷新/重启保留未保存的画布草稿，不覆盖它） |
| `pool_enabled` · `pool_cooldown_seconds` · `pool_network_cooldown_seconds` · `pool_max_attempts` · `pool_escalate` · `pool_allow_direct_fallback` · `pool_skip_wall_backoff` · `pool_preflight_live` | 账号池与出口池的开关、冷却、换号次数与预检；见 [account_pool.md](account_pool.md) |
| `hongguo_player_path` · `mitmdump_path` · `harvest_proxy_port` · `harvest_auto_install_ca` | 红果短剧评论收割的播放器、`mitmdump`、代理端口（8860）与自动安装抓包证书；Windows 桌面专属 |
| `ai_context_scope` · `ai_web_search_default` · `ai_safety_level` · `ai_max_context_chars` · `ai_max_tool_rounds` · `ai_request_timeout` · `ai_allow_code_context` · `ai_allow_python` · `ai_python_path` | AI 工作区的数据范围、默认联网、安全等级、上下文与工具轮次预算、请求超时、源码读取、Python 扩展与解释器路径 |

**预设**（`PRESETS`）把九个倍数加滚动间隔（秒）、同平台排队、跑前验证与并发写成具体值：`standard` 全部回基线（滚动间隔 1.2 秒）；`slow` 为 4/3/3 秒/3/3/2/1.6/3/30/2，开启排队与验证，窗口/无头并发 1/2；`night` 为 6/5/5 秒/5/5/3/2/6/50/3，并发 1/1。应用任一档都保存启用前的值，`restore` 原样退回。保存即生效；`component_source`、`log_max_mb`、`log_backup_count` 标 `restart`。

## 常量（`core/config.py`）

| 常量 | 说明 | 默认值 |
|---|---|---|
| `RUN_KEEP_PER_WORKFLOW` / `RUN_KEEP_DAYS` | 每工作流保留的运行数 / 最长保留天数 | `20` / `30` |
| `RUN_MAX_ROWS_PER_NODE` / `DATASET_MAX_ROWS` | 单节点磁盘行数硬上限 / 单个上传文件行数上限 | `500000` / `300000` |
| `DATASET_KEEP_DAYS` / `HOUSEKEEPING_INTERVAL_MINUTES` | 无引用文件清理天数 / 保留策略执行间隔 | `90` / `60` |
| `SCHEDULER_TICK_SECONDS` | 定时任务时钟的查看间隔 | `20` |
| `LOG_MAX_BYTES` / `LOG_BACKUP_COUNT` | 单个日志上限与保留份数 | `5242880` / `5` |
| `DEFAULT_HEADLESS` / `DEFAULT_MAX_WORKERS` | 运行默认无头 / 并行浏览器默认数 | `True` / `4` |
| `PAGE_WAIT_TIMEOUT` | 一页首块内容到达的总预算 | `300` |
| `RENDERER_PROBE_TIMEOUT` / `RENDERER_CLOSE_TIMEOUT` | 启动后读一次 UA 的上限 / `quit()` 宽限 | `15` / `10` |
| `SAME_PLATFORM_STAGGER` / `PROFILE_LOCK_TIMEOUT` / `PLATFORM_GATE_TIMEOUT` | 同平台错峰 / Profile 锁 / 排队等待 | `1.0` / `900` / `900` |
| `WALL_RETRY_BACKOFF` / `COOKIE_PREFLIGHT_TIMEOUT` / `COOKIE_PREFLIGHT_TTL` / `COOKIE_PREFLIGHT_MAX_PARALLEL` | 撞墙退避 / 预检预算 / 结论缓存 / 预检并发 | `45.0` / `45` / `300` / `4` |
| `WECHAT_BODY_MAX_CHARS` | 公众号正文保留字符数，0 表示全留 | `0` |

运行期间 `execution_state['results']` 会把每个节点的结果留在内存里，这一项没有上限。单节点产出超过 `engine/run.py` 的 `HEAVY_RESULT_ROWS`（默认 10 万行）时控制台打印提示，提示不改数据。

## 云端部署（cloud 模式）

```bash
cd backend
python app.py cloud          # 等价：python app.py --cloud，或 CRAWLER_CLOUD=1 python app.py
```

cloud 模式必须配好 `CRAWLER_ADMIN_PASSWORD` 与 `SECRET_KEY`，否则 `services/accounts/service.py` 的 `startup_error` 按名拒绝启动；Cookie 经 HTTPS 时再设 `CRAWLER_HTTPS=1`。

- **账号**：账号、服务端会话与审计在 `data/accounts.db`，密码用 scrypt 加盐，库里只存会话 id 的 sha256。管理员在“账号”面板创建、重置、禁用、强制下线或删除；新建或重置的账号带 `must_change_password`，改密前除改密接口外全站 API 403。
- **隔离**：每个账号拥有 `data/users/<user_id>/`（工作流、数据集、各库、Cookie、Profile、导出、检查点、模板、locks/schedules）；`accounts.db`、`settings.json`、`lexicon.db`、`models/`、`logs/` 系统共享。删除账号把目录移入 `data/users/.trash/`；最后一个启用的管理员不可删。旧单账号数据用 `python tools/migrate_accounts.py --user admin --apply` 迁入（默认 dry-run）。
- **门禁**：页面跳 `/login`，接口回 401。连续失败按账号与“来源地址 + 用户名”计窗，密码错误一律同一句提示；锁定期内再猜**不改**期限也不加计数（否则每次到期前猜一次就能把主人永久锁在外面），管理员可解除。运行槽、队列与定时器全站各一份，按账号归属；其它账号访问运行端点只得到 `foreign_run` 或空结果。
- **禁用 / 强制下线关库**：账号自己的库（`runs.db` 等）在“没有它的运行、也没有它的请求”时才关；如果此时它正有普通请求在跑（上传、删除、AI 对话），关闭推迟到那个请求结束时执行，不会把 SQLite 句柄从正在写的请求下面抽走。
- **服务器形状**：`/api/config` 的 `cloud_mode` 决定界面：隐藏全部 Ollama 入口并让需要模型的运行按名拒绝、隐藏无头开关并强制无头、拒绝“浏览器生成 Cookie”（验证与预检改走无头）。
- **浏览器目录**：首次保存 Cookie 时用空白 Chrome 生成 `<Profile 根>/_template`，之后每个账号目录从它克隆；`Cookies`、`Login Data`、`History`、`Web Data`、`Preferences`、`Local State`、`IndexedDB`、`Network`、`Session Storage` 永不复制。模板脏不脏看表里的行数，`POST /api/browser/profiles/template` 可手动重建。
- **隐私**：API Key 只存在浏览器 localStorage，Cookie 值只存服务器；采集数据、工作流与运行记录都在服务器 `data/`，能访问服务器的人就能读到。`tests/api/test_privacy_leaks.py` 走遍每条 GET 规则，要求磁盘上放置的独特标记不出现在任何响应里。

## 三个系统：Windows / Linux / macOS

机器事实集中在 `core/machine.py` 与 `services/charts/`，按目标系统的分隔符拼接；`desktop/` 是唯一的打包树，逐条证据见 [agent_practices.md](agent_practices.md)。

| 要查的东西 | Windows | Linux | macOS |
|---|---|---|---|
| Chrome/Chromium | `PROGRAMFILES`/`LOCALAPPDATA` 下的 `chrome.exe` | `/usr/bin/google-chrome[-stable]`、`chromium[-browser]`、`/snap/bin/chromium`，再扫 `PATH` | `/Applications/Google Chrome.app/…`，再扫 `PATH` |
| Node（CatBus 用） | `nodejs\node.exe`，再扫 `PATH` | `/usr/bin/node`、`/usr/local/bin/node`、`/snap/bin/node` | `/usr/local/bin/node`、`/opt/homebrew/bin/node` |
| CatBus 适配器 | `%APPDATA%\npm\node_modules\catbus-cli\…\cli.js` | npm 全局前缀下同名入口 | `/usr/local/lib`、`/opt/homebrew/lib`、`$HOME/.npm-global` |
| xelatex | MiKTeX 安装根 | `/usr/bin/xelatex`、`/usr/local/bin/xelatex` | `/Library/TeX/texbin/xelatex`、`/usr/texbin/xelatex` |
| 中文排版 | 显式 `\setCJKmainfont{FangSong}` | `ctex` 的 `fontset=fandol` | `ctex` 的 `fontset=macnew` |
| Matplotlib 中文 | SimHei / Microsoft YaHei | Noto Sans CJK SC / Source Han Sans SC | PingFang SC / Hiragino Sans GB |

云端 Linux 需要 Chromium + 驱动、`fonts-noto-cjk`，论文图另需 `texlive-xetex`/`texlive-lang-chinese`（`deploy/Dockerfile` 已装前两项）。启用登录时容器里的 `/api/config` 答 401 是门禁在工作，健康检查接受 `200|302|401`。

红果短剧评论收割只在 Windows 桌面可用，其它系统与 cloud 模式按名拒绝。文件名按 UTF-8 字节与字符双重设限（`core/refs.py` 的 `sanitize_filename`），因为 ext4/APFS 的 `NAME_MAX` 是 255 字节而 Windows 是字符。
