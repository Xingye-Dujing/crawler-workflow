# 配置

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。

环境变量、运行时设置（`data/settings.json`）、保留策略与排队常量、内存说明，以及云端部署（cloud 模式）的说明。

## 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OLLAMA_MODEL` | Ollama 模型名 | `qwen3.5:9b` |
| `OLLAMA_HOST` | Ollama 服务地址 | `http://localhost:11434` |
| `SECRET_KEY` | Flask 会话密钥（登录 Cookie 用它签名） | `crawler-workflow-secret-key`；**cloud 模式必须另设**，否则拒绝启动 |
| `CRAWLER_AUTH_USER` | 登录账号 | `admin` |
| `CRAWLER_AUTH_PASSWORD` | 登录密码；设置后启用登录页与全站会话门；**cloud 模式必须设置** | 空（不启用登录，本机自用的默认） |
| `CRAWLER_HTTPS` | 页面实际经 HTTPS 访问（反向代理终止 TLS）时设 `1`：会话 Cookie 标记 `Secure` | 关闭 |
| `PORT` | 服务端口 | `5000` |
| `HOST` | 监听地址（默认只监听本机，局域网内其他机器访问需设为 `0.0.0.0`） | `127.0.0.1` |
| `CRAWLER_DATA_ROOT` | `data/` 与 `logs/` 的父目录（给某个进程一份**自己**的状态：验证脚本、测试里自启的那台服务，都不会碰你真正在用的那份） | 项目根目录 |
| `CRAWLER_CLOUD` | 云端部署形状（`1`/`true`/`yes`/`on`）：隐藏 Ollama 与「无头」设置、所有抓取强制无头、拒绝「浏览器生成」。命令行 `python app.py cloud` 是同一件事，它在 import 之前把这个变量抬起来 | 关闭 |
| `FLASK_DEBUG` | 调试模式（含热重载与自动打开浏览器，调试器可执行任意代码，勿在他人可达的机器上开启） | 关闭 |
| `MAX_UPLOAD_MB` | 单个请求体上限（过大时返回 413 JSON，而非把整机内存吃光） | `64` |
| `CHROME_PATH` / `CHROME_BIN` | 浏览器可执行文件。按系统查的第二条路（Windows 查安装根、Linux 查 `/usr/bin/chromium` 等与 `PATH`、macOS 查 bundle）；容器里通常是 `CHROME_BIN=/usr/bin/chromium`。设了值却指向不存在的东西 → 采集按名拒绝，**绝不换个浏览器顶上** | 空 |
| `CIXI_DRIVER_PATH` | chromedriver 路径的部署侧写法（等价于设置面板的「驱动路径」，空=让 Selenium Manager 取匹配版本） | 空 |
| `CIXI_NODE_BIN` / `NODE_BIN` | 第二采集后端（CatBus）用的 Node 运行时，按系统查表；版本按 CatBus `engines` 核对，太旧按名拒绝 | 空 |
| `CIXI_CATBUS_CLI` / `CATBUS_CLI` / `CATBUS_HOME` | CatBus 采析绘适配器入口。前两个直接指名文件或可执行包装；`CATBUS_HOME` 指源码检出根；都没设就按 npm 全局前缀找。找不到就是不提供这个后端（面板里那位置灰并写明缺什么，而不是运行起来才拒绝） | 空 |
| `PYTHONUTF8` / `LANG` | 控制台编码：启动时检查 `stdout/stderr` 能不能写汉字，不能就改 UTF-8 并打印一行；能写就只把 `errors` 设成 `replace`，**不改编码**（强扭成 UTF-8 反而把正常窗口弄成乱码） | — |

> **三套系统都在范围内**：Windows 是开发机，Linux 是云端部署目标，macOS 也要求可用。只有 `desktop/`
> （PyInstaller + UPX + Inno Setup）与「红果短剧评论收割」是 Windows 专属（非 Windows 与 cloud 模式下由
> `capabilities.registry.requirement_met('windows_desktop')` 这一个答案决定）。云端 Linux 还需要 Chromium +
> 驱动、`fonts-noto-cjk`、可选 `texlive-xetex`/`texlive-lang-chinese`。第二采集方式（Node + CatBus）是可选依赖，
> 不装一切照常，只是「采集方式」另一项置灰。规则本体见 `AGENTS.md`「Cross-platform」，逐条实测证据见
> [agent_practices.md](agent_practices.md)，采集边界见 [crawler_rules.md](crawler_rules.md)。

## 运行时设置（UI 设置面板 → `data/settings.json`）

定义在 `runtime/settings.py` 的 `DEFAULTS`，全部可在设置面板改；保存路径与 bool 分支在
`runtime/settings.py::save_settings`（`settings_store` 是它的旧名）。

| 键 | 说明 |
|------|------|
| `driver_path` | chromedriver 路径（覆盖 `core/config.py` 默认值） |
| `browser_binary` | Chrome 二进制路径 |
| `latex_binary` | `xelatex` 可执行文件（「编译」节点与论文成稿用它把 LaTeX 转 PDF；空=自动检测 PATH 与常见 MiKTeX 安装根） |
| `catbus_cli` / `catbus_node` | 第二采集后端（CatBus）的两个本机路径，与「驱动路径」同一形状。`catbus_cli` 可填适配器文件或一份 CatBus 目录（自动补入口）；`catbus_node` 只接受程序本身。都可留空=按本机系统查找；优先级 设置面板 > 环境变量 > 系统候选表 > `PATH`。路径不存在只警告不拒绝，保存后面板立刻重探本机能力 |
| `window_size` | 浏览器窗口尺寸（`--window-size=WxH`，默认 `1920x1080`） |
| `page_load_timeout` / `element_timeout` | 页面/元素超时（秒；默认 40 / 15） |
| `ollama_host` | Ollama 地址（覆盖环境变量） |
| `cookie_preflight_before_run` | 运行前是否自动验证各平台 Cookie，过期就禁止执行（默认开；关掉则什么都不问） |
| `same_platform_queue` | 真排队：同一平台一次只跑一条采集，前一条整个跑完才轮到下一条（默认开）。关掉只剩错峰。微博不受此开关影响，永远真排队（矩阵 `serial_only`） |
| `same_platform_stagger` | 同平台错峰间隔（秒，默认 12，可填 0~600；0=不额外隔）。只对同时在跑的同平台采集生效，串行永远无缝 |
| `ask_overseas_network` | 画布里有海外平台时，运行前先问一句「外网开了吗」（默认开） |
| `use_browser_profile` | 是否为每个平台使用持久浏览器 Profile 目录（默认开；关闭=每次全新浏览器 + 种一份旧 Cookie 快照） |
| `browser_profile_dir` | Profile 根目录，留空=内置 `data/chrome_profile/<平台>`；填绝对路径可指向你自己为该工具建的目录 |
| `max_visible_browsers` / `max_headless_browsers` | 一次并行运行最多同时开几台浏览器，按本次是窗口 / 无头分别取（默认都取 `DEFAULT_MAX_WORKERS=4`；窗口比无头更费机器）。串行轮流，不受此限 |
| `clear_console_before_run` | 新运行一开始就清控制台（每标签及其保留历史；默认关，关掉时上一轮的行留到下次轮询覆盖，会看起来像继承了旧输出） |
| `gentle_crawl` | 把采集的礼貌停顿按固定倍率拉长（只改节奏，不改指纹、不动页面到达预算；默认关）。刚被风控挑战过的会话宜退让，代价是墙钟时间变慢 |
| `hongguo_player_path` | 红果短剧评论收割用的桌面播放器路径（**不自动检测**——猜错路就会对着错误的构建收割，拒绝时点名这个设置；Windows 专属） |
| `mitmdump_path` | 收割用的 `mitmdump`；空=PATH，再退回本 venv 的 Scripts |
| `harvest_proxy_port` | 播放器与 mitmproxy 共用的代理端口（默认 8860） |
| `harvest_auto_install_ca` | 首次收割时把 mitmproxy 根证书装进当前用户可信根（默认开；关掉则收割拒绝并给出手动命令——动信任库不该是突袭） |

## 常量（`backend/core/config.py`）

保留策略：

| 常量 | 说明 | 默认值 |
|------|------|--------|
| `RUN_KEEP_PER_WORKFLOW` | 每个工作流保留最近 N 次运行 | `20` |
| `RUN_KEEP_DAYS` | 运行记录最长保留天数 | `30` |
| `RUN_MAX_ROWS_PER_NODE` | 单节点持久化行数硬上限（**磁盘**上限，不是内存） | `500000` |
| `DATASET_MAX_ROWS` | 单个上传文件行数上限（**文件**上限，不是内存） | `300000` |
| `DATASET_KEEP_DAYS` | 无引用文件的清理天数 | `90` |
| `HOUSEKEEPING_INTERVAL_MINUTES` | 自动执行保留策略的时间闸（启动必清一次，之后每过此时长在运行结束时清） | `60` |
| `SCHEDULER_TICK_SECONDS` | 定时任务时钟多久看一次清单（规则最小单位是分钟，低于 5 秒抬到 5） | `20` |
| `LOG_MAX_BYTES` | 单个日志文件上限，超出即滚动 | `5242880`（5 MiB） |
| `LOG_BACKUP_COUNT` | 保留多少个历史日志 | `5` |

爬虫与浏览器默认：

| 常量 | 说明 | 默认值 |
|------|------|--------|
| `DEFAULT_HEADLESS` | 运行默认是否无头（面板每次可改） | `True` |
| `DEFAULT_MAX_WORKERS` | 并行默认浏览器数（也是 `max_visible_browsers`/`max_headless_browsers` 的取值来源） | `4` |
| `PAGE_WAIT_TIMEOUT` | 一次采集等待**某页首块内容**到达的总预算（区别于只界定 load 事件的 `page_load_timeout`）；有界是设计——"永远等"是一条运行槽扛不住的策略，停止永远是用户在其中的出口 | `300` |
| `WECHAT_BODY_MAX_CHARS` | 一行公众号正文保留的字符数（0=全留：以前硬砍到 5000 会静默丢掉长文结尾，读起来像短文到此为止） | `0` |

排队、错峰与预检：

站点把"同一账号一秒内的两次搜索"当成异常（微博弹登录页、知乎回 40362），profile 又只允许一个浏览器，
所以这几条不是性能参数而是正确性参数：

| 常量 | 说明 | 默认值 |
|------|------|--------|
| `SAME_PLATFORM_STAGGER` | 同平台两条同时在跑的采集至少隔多久发车（面板 `same_platform_stagger` 可改） | `12.0` |
| `PROFILE_LOCK_TIMEOUT` | 一个平台的 profile 被另一次采集占用时，最多排队多久；超时即以可读原因判该节点失败，不再抛驱动栈（面板可改） | `900` |
| `WALL_RETRY_BACKOFF` | 第 0 行就撞墙时的退避重试等待；0 关掉重试（有过半数据的墙不在此列，那是 Cookie 死了，走续跑） | `45.0` |
| `PLATFORM_GATE_TIMEOUT` | 一次采集最多等多久轮到本平台的同平台排队 | `900` |
| `COOKIE_PREFLIGHT_TIMEOUT` | 运行前自动验证 Cookie 的总预算（超出即回答「无法核对」，不谎报失效） | `45` |
| `COOKIE_PREFLIGHT_TTL` | 一个验证结论可被复用的秒数；保存/删除/扫码取回 Cookie 会立即作废 | `300` |
| `COOKIE_PREFLIGHT_MAX_PARALLEL` | 预检同时最多开几个浏览器（每个都是一次真实页面加载） | `4` |

## 关于内存：唯一没有上限的那一项

上面两个行数上限管的都不是内存。`RUN_MAX_ROWS_PER_NODE` 是**磁盘**上限（防止跑飞的采集把 `runs.db`
撑爆），`DATASET_MAX_ROWS` 是**单个上传文件**的上限。而运行期间 `execution_state['results']` 会把
**每个节点**的结果都留在内存里——预览读它，子节点也读它——这件事本身没有上限。代价是实测的：10 万行
× 4 列，DataFrame 占 17 MB，而节点结果用的「字典列表」占 **53 MB**（约 3.1 倍）。

所以运行会**主动说出来**：单节点产出超过 `HEAVY_RESULT_ROWS`（定义在 `engine/run.py`，默认 10 万行，由
`note_heavy_result` 触发）时，控制台会打印一行带节点名和行数的提示。它不是报错、也不改数据——大表往往
正是你要的——只是别让 OOM 在三个节点之后发生而没有任何线索。要让这个成本真正降下来，得把节点之间的传递
从「字典列表」改成 DataFrame（只在预览/导出/落库的边界转换）：那会动到执行器核心契约的四处，值得单独一次改。

## 云端部署（cloud 模式）

这个项目按"本机单人"设计，但也可以放到服务器上给别人访问。启动时加一个词即可：

```bash
cd backend
python app.py cloud          # 等价：python app.py --cloud，或 CRAWLER_CLOUD=1 python app.py
```

**云端必须先配好登录，否则拒绝启动**（`api/auth.py::startup_error` 按名指出缺哪一项）：

```bash
export CRAWLER_AUTH_PASSWORD='一长串只有你知道的密码'   # 必须；账号默认 admin，可用 CRAWLER_AUTH_USER 改名
export SECRET_KEY="$(python -c 'import secrets; print(secrets.token_hex(32))')"
export CRAWLER_HTTPS=1                                  # 反向代理已终止 TLS 时（会话 Cookie 标记 Secure）
```

设置密码后，`/`、全部 `/api/*`、静态资源都要求登录：页面跳 `/login`，接口答 401（带 `X-Auth-Required`
响应头，前端据此跳回登录页），登录成功是一枚签名会话 Cookie（`cixi_session`，HttpOnly、SameSite=Lax、
非持久——关浏览器即退出）。顶栏出现「退出登录」（POST `/logout`，服务端同时吊销该会话 id，重放旧 Cookie
无效）。Cookie 里只放一枚随机 id；改密码会让已发出的会话立即失效，服务重启需要重新登录。只要启用了登录（cloud 模式，
或本机设了 `CRAWLER_AUTH_PASSWORD`），仓库默认的 `SECRET_KEY` 都会被按名拒绝——密钥公开等于会话可伪造。
登录失败固定等 0.3 秒；没有锁定计数，公网部署请在反向代理再加一层限速。

服务端与前端**同时**换到"服务器形状"——旗标是服务器的事实，不是页面的猜测：`/api/config` 把 `cloud_mode`
报给前端，前端据此收掉那些"问这台机器要一台它没有的东西"的控件：

| 云端关掉的东西 | 被绕过时会发生什么 |
|---|---|
| **Ollama 全部界面**（AI 子菜单只剩 OpenRouter；设置面板的 Ollama 地址；处理节点里"本地 Ollama"那句） | 每个要模型的运行在建 record 之前**按名字拒绝**（`/api/llm/test`、`/api/llm/ollama/models` 同样拒）；报告仍写出，结论那句换成"这台服务器没有本地模型"，绝不假装跑过 |
| **「无头」开关**，且所有抓取一律无头 | 请求里写 `headless: false` 也会被改成无头，运行记录里的标也按实际写 |
| **Cookie 面板的「浏览器生成」** | 路由直接按名字拒绝（隐藏按钮从来不等于收回权限：旧标签页、存下的工作流、手写 POST 都还会来）；「验证 Cookie」与运行前预检改走无头 |

**新账号的浏览器目录从哪来**：云端既没有登录窗口、也绝不允许把用户日常 Chrome 目录复制上服务器，所以这一步归程序自己——
第一次保存 Cookie 时（人还在屏幕前）程序开一台空白 Chrome 生成 `<Profile 根>/_template`，之后每建一个账号目录都从它克隆。
它干净的理由是从来没有人登录过它，而不是"把看着私密的文件删掉了"（后一条要猜中 Chrome 全部存储，漏一个就是把一个人的
会话送上去）。克隆清单永远拒绝这些名字：`Cookies`、`Login Data`、`History`、`Web Data`、`Preferences`、`Local State`
（机器绑定密钥）、`IndexedDB`、`Network`、`Session Storage`，也拒绝本程序自己的 `.crawler-profile.json`。

判断模板脏不脏**看表里的行数，不看文件名**：实测空白首启的 Chrome 自己就会创建 `Cookies`/`Login Data`/`History`/`Preferences`
（都是空表），按名字判定会把每一个真模板判成脏。目录只在第一次被创建时播种；模板若被检出登录痕迹，会在任何账号再用它之前
销毁重建；`POST /api/browser/profiles/template` 是给运维"现在就重建一次"的手动入口。

## 三个系统：Windows / Linux / macOS

> 规则本体在 `AGENTS.md`「Cross-platform」一节，逐条实测证据在 `docs/agent_practices.md`。`desktop/`
> 是唯一故意只服务 Windows 的目录。按当前系统查的机器事实都集中在一处（`core/machine.py` 与两个 services）：

| 要查的东西 | Windows | Linux | macOS |
|---|---|---|---|
| Chrome/Chromium | `PROGRAMFILES`/`LOCALAPPDATA` 下的 `chrome.exe` | `/usr/bin/google-chrome[-stable]`、`chromium[-browser]`、`/snap/bin/chromium`，再扫 `PATH` | `/Applications/Google Chrome.app/…`（含 Beta/Chromium/`~/Applications`），再扫 `PATH` |
| Node 运行时（CatBus 用） | `nodejs\node.exe`，再扫 `PATH` | `/usr/bin/node`、`/usr/local/bin/node`、`/snap/bin/node`，再扫 `PATH` | `/usr/local/bin/node`、`/opt/homebrew/bin/node`，再扫 `PATH` |
| CatBus 适配器 | `%APPDATA%\npm\node_modules\catbus-cli\…\cli.js` | `/usr/local/lib`、`/usr/lib`、`$HOME/.npm-global` 下同名入口 | `/usr/local/lib`、`/opt/homebrew/lib`、`$HOME/.npm-global` |
| xelatex | MiKTeX 两处安装根 | `/usr/bin/xelatex`、`/usr/local/bin/xelatex` | `/Library/TeX/texbin/xelatex`、`/usr/texbin/xelatex` |
| 纸质图中文（ctex） | 显式 `\setCJKmainfont{FangSong}` | `\usepackage[fontset=fandol]{ctex}`，不指名任何字体 | `\usepackage[fontset=macnew]{ctex}` |
| Matplotlib 中文 | SimHei / Microsoft YaHei 在前 | Noto Sans CJK SC / Source Han Sans SC | PingFang SC / Hiragino Sans GB |

仿宋（FangSong）是一套 Windows 字体：TeX Live 与 macOS 都没有它，于是服务器上「论文图」整条功能曾直接死在
`The font "FangSong" cannot be found`——现在非 Windows 改用 ctex 自带字体集，并把中文来源字族写进 `.tex` 注释里如实说明。
云端 Linux 要装的系统包（`deploy/Dockerfile` 已装前两项）：

```bash
apt-get install -y chromium chromium-driver fonts-noto-cjk
apt-get install -y texlive-xetex texlive-lang-chinese   # 可选：论文图与论文成稿
```

**只有 Windows 桌面做得到的能力**：红果短剧评论收割（驱动本机播放器进程 + 把 mitmproxy 的 CA 装进系统证书库）。
它在 Linux、macOS 与 cloud 模式下被按名拒绝，见 [crawler_rules.md](crawler_rules.md) 的「平台边界」。单机实例互斥、
双击启动、系统弹窗、`%APPDATA%` 数据根都是 `desktop/` 那棵树的事。

**Linux 文件名算字节，Windows 文件名算字符**：ext4/APFS 的 `NAME_MAX` 是 255 UTF-8 字节，100 个汉字是 300 字节——
Windows 上写得出去、服务器上 `open()` 直接 `ENAMETOOLONG`。`core/refs.py::sanitize_filename` 两个上限都卡
（`MAX_FILENAME_LENGTH=100` 字符、`MAX_FILENAME_BYTES=200` 字节）。**控制台编码**见上 `PYTHONUTF8`/`LANG` 一节。

**隐私边界**：OpenRouter API Key 一直只存在浏览器 localStorage，服务端只在一次请求里用它；Cookie 值只存服务器，
任何接口都不把它发给浏览器。但**采集到的数据、工作流文件与运行记录都存在服务器那份 `data/` 里**，谁能访问这台服务器
谁能翻到这些表——这不是漏洞，是"本机单人"前提被换掉了，公开部署前请想清楚（首次进入的云端弹窗会把这件事说明一次，
「知道了」下次还会问、「不再提醒」记在本地 localStorage）。隐私上被**测着**的几件事见 `tests/api/test_privacy_leaks.py`：
它走 `app.url_map` 上每一条 GET 规则，要求在磁盘上放一份带独特标记的 Cookie 后那标记在任何响应里都不出现。
