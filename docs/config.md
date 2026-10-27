# 配置

> 本文是采析绘文档的一部分，返回总览见 [README.md](../README.md)。

环境变量、运行时设置（data/settings.json）、保留策略常量、内存说明、排队/错峰/预检常量，以及云端部署（cloud 模式）的完整说明。

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OLLAMA_MODEL` | Ollama 模型名 | `qwen3.5:9b` |
| `OLLAMA_HOST` | Ollama 服务地址 | `http://localhost:11434` |
| `SECRET_KEY` | Flask 会话密钥 | `crawler-workflow-secret-key` |
| `PORT` | 服务端口 | `5000` |
| `HOST` | 监听地址（默认只监听本机，局域网内其他机器访问需设为 `0.0.0.0`） | `127.0.0.1` |
| `CRAWLER_DATA_ROOT` | `data/` 与 `logs/` 的父目录（给某个进程一份**自己**的状态：验证脚本、测试里自启的那台服务，都不会碰你真正在用的那份） | 项目根目录 |
| `CRAWLER_CLOUD` | 云端部署形状（`1`/`true`/`yes`/`on`）：隐藏 Ollama 与「无头」设置、所有抓取强制无头、拒绝「浏览器生成」。**命令行 `python app.py cloud` 是同一件事的写法**，它在 import 之前把这个变量抬起来（类属性只在 import 时读一次，晚了就来不及了） | 关闭 |
| `FLASK_DEBUG` | 调试模式（`1`/`true`/`yes` 开启；含热重载与自动打开浏览器，调试器可执行任意代码，勿在他人可达的机器上开启） | 关闭 |
| `MAX_UPLOAD_MB` | 单个请求体上限（上传/粘贴数据过大时返回 413 JSON，而非把整机内存吃光） | `64` |
| `CHROME_PATH` / `CHROME_BIN` | 浏览器可执行文件。**按系统查的第二条路**：Windows 查 `PROGRAMFILES`/`LOCALAPPDATA` 下的安装根，Linux 查 `/usr/bin/google-chrome`、`/usr/bin/chromium`、`/snap/bin/chromium` 与 `PATH`，macOS 查 `/Applications/Google Chrome.app/…` 与用户目录下的同名 bundle。容器里通常就是 `CHROME_BIN=/usr/bin/chromium`（`Dockerfile` 就是这么写的）。设了值却指向不存在的东西 → 采集按名拒绝，**绝不换个浏览器顶上**（复制出来的登录态对站点风控就是第二台设备） | 空 |
| `CIXI_DRIVER_PATH` | chromedriver 路径的部署侧写法（等价于设置面板的「驱动路径」，空=让 Selenium Manager 取匹配版本）。`Dockerfile` 用的是这个名字——以前镜像里导出的是 `CHROMEDRIVER_PATH`，代码里没有读它的地方，于是那行只是个装饰 | 空 |
| `CIXI_NODE_BIN` / `NODE_BIN` | **第二采集后端（CatBus）** 用的 Node 运行时。与 Chrome 一样按系统查表：Windows 查 `PROGRAMFILES`/`LOCALAPPDATA` 下的 `nodejs\node.exe`，Linux 查 `/usr/bin/node`、`/usr/local/bin/node`、`/snap/bin/node` 与 `PATH`，macOS 查 `/usr/local/bin/node`、`/opt/homebrew/bin/node`。版本按 CatBus 的 `engines`（`22.22.2`／`24.15.0`／`26.0.0` 三段下限）核对，太旧**按名拒绝**而不是让它跑到一半报语法错误 | 空 |
| `CIXI_CATBUS_CLI` / `CATBUS_CLI` / `CATBUS_HOME` | CatBus 采析绘适配器入口。前两个直接指名文件（`dist/integrations/crawler-workflow/cli.js`）或一个可执行包装；`CATBUS_HOME` 指源码检出根。都没设就按 npm 全局前缀找（Windows `%APPDATA%\npm\node_modules`，Linux/macOS `/usr/local/lib`、`/usr/lib`、`/opt/homebrew/lib`、`$HOME/.npm-global`，以及 `PATH` 里某个 `bin` 的上一级 `lib/node_modules`）。**找不到就是不提供这个后端**：面板里那一位置灰并写明缺的是哪一样，而不是运行起来才拒绝 | 空 |
| `PYTHONUTF8` / `LANG` | 控制台编码。程序启动时会检查 `stdout/stderr` 能不能写汉字：不能（比如 `LANG` 未设置的 slim 镜像，编码是纯 ASCII）就改到 UTF-8 并打印一行说明；能写（比如中文 Windows 的 cp936）就只把 `errors` 设成 `replace`，**不改编码**——把能显示汉字的控制台强扭成 UTF-8 反而会把原本正常的窗口弄成乱码 | — |

> **三套系统都在范围内**：Windows 是开发机，Linux 是云端部署目标，macOS 也要求可用。
> 只有 `desktop/`（PyInstaller + UPX + Inno Setup）与「红果短剧评论收割」是 Windows 专属：后者在非 Windows 与
> cloud 模式下由 `crawl_capabilities.requirement_met('windows_desktop')` 这**一个**答案决定——面板把该采集内容
> 置灰并写明原因、四个只有桌面才需要的设置行从面板上消失、`validate` 在运行前按名拒绝、节点自己也会拒绝。
> 云端 Linux 还需要：Chromium + 驱动（镜像已装）、`fonts-noto-cjk`（Matplotlib 出的中文图）、
> 可选 `texlive-xetex texlive-lang-chinese`（纸质图与论文成稿；非 Windows 的中文由 ctex 的 fandol 字体集提供，
> 程序不再指名仿宋，因为那是一套 Windows 字体）。
> **第二采集方式是可选依赖**：镜像不装 Node 与 CatBus 也一切照常，只是面板里「采集方式」的另一项会置灰并写明
> 「本机没有」。要在服务器上用它：装 Node（CatBus 的 `engines` 范围）+ `npm i -g catbus-cli`，或
> `CATBUS_HOME=/srv/catbus` 指一份源码检出（`npm run build` 之后），然后 `catbus <平台> auth login` 存它自己的账号。
> CatBus 的 OCR / 验证码模型（`@cv-cat/catbus-assets-*`，约 100 MB 级）是它自己的事，本项目不打包、也不代为下载。

### 运行时设置（UI 设置面板 → `data/settings.json`）

| 键 | 说明 |
|------|------|
| `driver_path` | chromedriver 路径（覆盖 core/config.py 默认值） |
| `browser_binary` | Chrome 二进制路径 |
| `catbus_cli` / `catbus_node` | **第二采集后端（CatBus）的两个本机路径**，与「驱动路径」同一形状：填在这里就不用去改 `PATH`。`catbus_cli` 既能填适配器文件（`…/crawler-workflow/cli.js`）也能填一份 CatBus 目录（自动补上那个入口）；`catbus_node` 只接受程序本身，填成目录会被点名说明。两栏都可留空 = 按本机系统查找；优先级是**设置面板 > 环境变量（`CIXI_CATBUS_CLI` / `CATBUS_CLI` / `CATBUS_HOME`、`CIXI_NODE_BIN` / `NODE_BIN`）> 系统候选表 > `PATH`**。路径不存在只警告不拒绝（你可能在为一台将来才装好的机器配置），保存后面板立刻重新探测一次本机能力——否则缓存里那句「本机没有」会把刚修好的选项继续压灰 |
| `window_size` | 浏览器窗口尺寸 |
| `page_load_timeout` / `element_timeout` | 页面/元素超时（秒） |
| `ollama_host` | Ollama 地址（覆盖环境变量） |
| `cookie_preflight_before_run` | 运行前是否自动验证各平台 Cookie，过期就禁止执行（默认开；关掉则什么都不问） |
| `same_platform_queue` | **真排队**：同一平台一次只跑一条采集，前一条整个跑完才轮到下一条（默认开）。开启后并行同平台不再弹「用不用 Profile」确认框——这个决定已替整台程序做掉。关掉就只剩**错峰**：两条仍可能同时跑，只把发车时刻按下面的秒数隔开。**微博不受此开关影响，永远真排队**（矩阵 `serial_only`：并行翻页必撞登录墙），并行画布含多条微博时执行前单独弹窗说明 |
| `same_platform_stagger` | 同平台**错峰间隔**（秒，默认 12，可填 0~600；0 = 不额外隔）。只对**同时在跑**的同平台采集生效，串行永远无缝；真排队时它是交接后的停顿，关掉真排队时它就是全部的秩序 |
| `ask_overseas_network` | 画布里有海外平台时，运行前先问一句「外网开了吗」（默认开；见「网络分区」一节） |
| `use_browser_profile` | 是否为每个平台使用持久浏览器 Profile 目录（默认开；关闭 = 每次都是全新浏览器 + 种一份旧 Cookie 快照） |
| `browser_profile_dir` | Profile 根目录，留空 = 内置 `data/chrome_profile/<平台>`；填绝对路径可指向你自己为该工具建的目录 |
| `PROFILE_LOCK_TIMEOUT` | 一个平台的 profile 被另一次采集占用时，最多排队多久（默认 900 秒；超时即以可读的原因判该节点失败，不再抛驱动栈） |

### 保留策略常量（`backend/core/config.py`）

| 常量 | 说明 | 默认值 |
|------|------|--------|
| `RUN_KEEP_PER_WORKFLOW` | 每个工作流保留最近 N 次运行 | `20` |
| `RUN_KEEP_DAYS` | 运行记录最长保留天数 | `30` |
| `RUN_MAX_ROWS_PER_NODE` | 单节点持久化行数硬上限（**磁盘**上限，不是内存） | `500000` |
| `DATASET_MAX_ROWS` | 单个上传文件行数上限（**文件**上限，不是内存） | `300000` |
| `DATASET_KEEP_DAYS` | 无引用文件的清理天数 | `90` |
| `HOUSEKEEPING_INTERVAL_MINUTES` | 自动执行上述保留策略的时间闸（启动必清一次，之后每过此时长在运行结束时清） | `60` |
| `SCHEDULER_TICK_SECONDS` | 定时任务时钟多久看一次自己的清单（也是「到点」最坏迟到多久）；规则最小单位是分钟，所以低于 5 秒会被抬到 5，`0` 当作没设即 20 | `20` |
| `LOG_MAX_BYTES` | 单个日志文件上限，超出即滚动 | `5242880`（5 MiB） |
| `LOG_BACKUP_COUNT` | 保留多少个历史日志（`app.log.1 … .N`） | `5` |

### 关于内存：唯一没有上限的那一项

上面两个行数上限管的都不是内存。`RUN_MAX_ROWS_PER_NODE` 是**磁盘**上限（防止跑飞的采集把 `runs.db`
撑爆），`DATASET_MAX_ROWS` 是**单个上传文件**的上限。而运行期间 `execution_state['results']` 会把
**每个节点**的结果都留在内存里——预览读它，子节点也读它——这件事本身没有上限。

代价是实测出来的：同样是 10 万行 × 4 列，DataFrame 占 17 MB，而节点结果用的「字典列表」占 **53 MB**，
约 **3.1 倍**。也就是说一条十来个节点的流水线跑一张大表，内存里同时留着十几份字典列表。

所以运行会**主动说出来**：单节点产出超过 `HEAVY_RESULT_ROWS`（`backend/app.py`，默认 10 万行）时，
控制台会打印一行带节点名和行数的提示。它不是报错、也不改数据——大表往往正是你要的——只是别让
OOM 在三个节点之后发生而没有任何线索。

要让这个成本真正降下来，得把节点之间的传递从「字典列表」改成 DataFrame（只在预览/导出/落库的边界转换）。
那是一次动到执行器核心契约的改动，涉及 `_execute_node` 的返回值、`run_store` 的行写入、`upstream`
的传递形式与 HTTP 边界四处，值得单独一次改，而不是顺手带上。

### 排队、错峰与预检常量（`backend/core/config.py`）

站点把"同一账号一秒内的两次搜索"当成异常（微博弹登录页、知乎回 40362），profile 又只允许一个浏览器，
所以这几条不是性能参数而是正确性参数：

| 常量 | 说明 | 默认值 |
|------|------|--------|
| `SAME_PLATFORM_STAGGER` | 同平台两条**同时在跑**的采集至少隔多久发车（默认值；串行永远无缝；面板里 `same_platform_stagger` 可改，真排队时它是交接后的停顿，关掉真排队它就是全部的秩序） | `12.0` |
| `WALL_RETRY_BACKOFF` | 第 0 行就撞墙时的退避重试等待；0 关掉重试（有过半数据的墙不在此列，那是 Cookie 死了，走续跑） | `45.0` |
| `PLATFORM_GATE_TIMEOUT` | 一次采集最多等多久轮到本平台的同平台排队 | `900` |
| `COOKIE_PREFLIGHT_TIMEOUT` | 运行前自动验证 Cookie 的总预算（超出即回答「无法核对」，不谎报失效） | `45` |
| `COOKIE_PREFLIGHT_TTL` | 一个验证结论可被复用的秒数；保存/删除/扫码取回 Cookie 会立即作废 | `300` |
| `COOKIE_PREFLIGHT_MAX_PARALLEL` | 预检同时最多开几个浏览器（每个都是一次真实页面加载） | `4` |

## 云端部署（详细）


这个项目按"本机单人"设计，但也可以放到服务器上给别人访问。启动时加一个词即可：

```bash
cd backend
python app.py cloud          # 等价写法：python app.py --cloud，或 CRAWLER_CLOUD=1 python app.py
```

服务端与前端**同时**换到"服务器形状"——旗标是服务器的事实，不是页面的猜测：`/api/config` 把
`cloud_mode` 报给前端，前端据此收掉那些"问这台机器要一台它没有的东西"的控件：

| 云端关掉的东西 | 为什么 | 被绕过时会发生什么 |
|---|---|---|
| **Ollama 全部界面**（AI 子菜单只剩 OpenRouter；设置面板的 Ollama 服务地址；处理节点里"本地 Ollama"那句话） | 云服务器带不动本地大模型，也没有一个监听在 `11434` 的守护进程 | 每个要模型的运行在建 record 之前**按名字拒绝**（`/api/llm/test`、`/api/llm/ollama/models` 同样拒），报告仍会写出，只是结论那句换成"这台服务器没有本地模型"——**不会**假装跑过然后静默少一段 |
| **「无头」开关**，且**所有抓取一律无头** | 服务器没有显示器 | 请求里写 `headless: false` 也会被改成无头，**运行记录里的标也按实际写的**（那个标是续跑横幅读的东西） |
| **Cookie 面板的「浏览器生成」** | 没有人站在这台服务器的屏幕前扫码 | 路由直接按名字拒绝（隐藏一个按钮从来不等于收回这个权限：旧标签页、存下来的工作流、手写的 POST 都还会来）。「验证 Cookie」与运行前预检则改走无头——#148 之后无头浏览器带桌面 UA 与真实窗口尺寸，各平台照常出内容 |

**新账号的浏览器目录从哪来**：云端既没有登录窗口、也**绝不允许**把用户日常使用的 Chrome 目录复制上
服务器，所以这一步归程序自己：第一次保存 Cookie 时（那时人还在屏幕前），程序先开一个空白 Chrome 生成
`<Profile 根>/_template`，之后每建一个账号目录（`<根>/<平台>/<账号>`）都从它克隆。它干净的理由是
**从来没有人登录过它**，不是"把看着私密的文件删掉了"——后一条路要猜中 Chrome 的全部存储，漏一个就是把
一个人的会话送上服务器给别人的账号用。克隆清单永远拒绝这些名字：`Cookies`、`Login Data`、`History`、
`Web Data`、`Preferences`、`Local State`（机器绑定的密钥）、`IndexedDB`、`Network`、`Session Storage`
等，也拒绝本程序自己的 `.crawler-profile.json`——种子带上它就会让「只导一次」的规则以为这账号已经有会话，
于是用户刚粘贴进来的 Cookie 永远不会被种进去。

判断模板脏不脏**看表里的行数，不看文件名**：实测空白首启的 Chrome 自己就会创建 `Cookies`、`Login Data`、
`History`、`Preferences`（都是空表），按名字判定会把每一个真模板都判成脏。目录只在**第一次被创建**时播种
（`os.makedirs(exist_ok=False)` 才分得清"是我建的"和"本来就有的"），已经在用的设备永远不会被重播。模板若
被检出登录痕迹，会在任何账号再用它之前**销毁重建**；设置面板的 Profile 表尾有一行说它的状态（已就绪 /
还没有 / 里面出现了登录痕迹），`POST /api/browser/profiles/template` 是给运维"现在就重建一次"的手动入口。

隐私上要注意的两件事：**API Key 一直只存在浏览器 localStorage**，服务端只在一次请求里用它；
但**采集到的数据、工作流文件与运行记录都存在服务器那份 `data/` 里**，谁能访问这台服务器，
谁就能翻到这些表——公开部署前请把它想清楚（Cookie 值同理：它只存在服务器上，任何接口都
不会把它发给浏览器）。

同一份代码在本机跑时，上面这些一个都不变：不设旗标就是原来的形状。

## 三个系统：Windows / Linux / macOS

> 开发机是 Windows，**云端部署目标是 Linux**，macOS 也在支持范围内。规则本体在 `AGENTS.md`
> 的「Cross-platform」一节，逐条实测证据在 `docs/agent_practices.md` 的「Cross-platform」一节。
> `desktop/` 是唯一故意只服务 Windows 的目录（PyInstaller/UPX/Inno 只能产 exe）。

**按当前系统查的东西**（都在一处，`core/machine.py` 与两个 services）：

| 要查的东西 | Windows | Linux | macOS |
|---|---|---|---|
| Chrome/Chromium | `PROGRAMFILES`/`PROGRAMFILES(X86)`/`LOCALAPPDATA` 下的 `Google\Chrome\Application\chrome.exe` | `/usr/bin/google-chrome[-stable]`、`/usr/bin/chromium[-browser]`、`/opt/google/chrome/chrome`、`/usr/lib/chromium/chromium`、`/snap/bin/chromium`，再扫 `PATH` | `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`（含 Beta 与 Chromium、`~/Applications` 那份），再扫 `PATH` |
| Node 运行时（第二采集后端 CatBus 用；`CIXI_NODE_BIN`/`NODE_BIN` 可指名） | `PROGRAMFILES`/`LOCALAPPDATA` 下的 `nodejs\node.exe`，再扫 `PATH` 里的 `node.exe` | `/usr/bin/node`、`/usr/local/bin/node`、`/snap/bin/node`，再扫 `PATH` | `/usr/local/bin/node`、`/opt/homebrew/bin/node`，再扫 `PATH` |
| CatBus 采析绘适配器（`CIXI_CATBUS_CLI`/`CATBUS_CLI` 指名文件，`CATBUS_HOME` 指名源码检出根） | `%APPDATA%\npm\node_modules\catbus-cli\dist\integrations\crawler-workflow\cli.js` | `/usr/local/lib/node_modules`、`/usr/lib/node_modules`、`$HOME/.npm-global/lib/node_modules` 下的同名入口，外加 `PATH` 里某个 `bin` 的上一级 `lib/node_modules` | `/usr/local/lib/node_modules`、`/opt/homebrew/lib/node_modules`、`$HOME/.npm-global/lib/node_modules` |
| xelatex | MiKTeX 的两处安装根 + `%LOCALAPPDATA%\Programs\MiKTeX\…` | `/usr/bin/xelatex`、`/usr/local/bin/xelatex` | `/Library/TeX/texbin/xelatex`（MacTeX；GUI 起的进程 `PATH` 里没有它）、`/usr/texbin/xelatex` |
| 纸质图的中文（ctex） | 显式 `\setCJKmainfont{FangSong}`（仿宋） | `\usepackage[fontset=fandol]{ctex}`，**不指名任何字体** | `\usepackage[fontset=macnew]{ctex}` |
| Matplotlib 中文 | SimHei / Microsoft YaHei 在前 | Noto Sans CJK SC / Source Han Sans SC / WenQuanYi Zen Hei | PingFang SC / Hiragino Sans GB |

仿宋（FangSong）是一套 **Windows 字体**：TeX Live 与 macOS 都没有它，以前每个纸质图都写死要它，
于是在服务器上「论文图」整条功能直接死在 `The font "FangSong" cannot be found`。现在非 Windows 改用
ctex 自带的字体集，并把"这台机器的中文来自哪个字族"写进生成的 `.tex` 注释里——差别照实说，不用一份
编译不过的文档去隐瞒。缺字体/缺宏包的拒绝语也按系统分支（Linux 说 `apt-get install …`，macOS 说
MacTeX/`tlmgr`，Windows 说 MiKTeX 控制台）。

**云端 Linux 要装的系统包**（`Dockerfile` 里已经装了前两项）：

```bash
apt-get install -y chromium chromium-driver          # 采集：浏览器 + 匹配版本的驱动
apt-get install -y fonts-noto-cjk                   # Matplotlib 出的 PNG 里的汉字
apt-get install -y texlive-xetex texlive-lang-chinese   # 可选：论文图与「论文成稿」的 xelatex
```

**只有 Windows 桌面做得到的能力**：红果短剧评论收割（驱动本机播放器进程 + 把 mitmproxy 的 CA 装进
系统证书库）。它在 Linux、macOS 与 cloud 模式下被**按名拒绝**——四处同一个答案，见
`docs/crawler_rules.md` 的「平台边界」一节。**单机实例互斥、双击启动、系统弹窗、`%APPDATA%` 数据根**
都是 `desktop/` 那棵树的事：Linux 与 macOS 上源码版照常以 `python app.py` 跑，没有互斥量那种"一次只能开一个"
的保证，也不会有任何桌面通知。

**Linux 文件名算字节，Windows 文件名算字符**：ext4/APFS 的 `NAME_MAX` 是 255 **UTF-8 字节**，
100 个汉字是 300 字节——Windows 上写得出去、服务器上 `open()` 直接 `ENAMETOOLONG`。
`core/refs.py::sanitize_filename` 两个上限都卡（`MAX_FILENAME_LENGTH=100` 字符、
`MAX_FILENAME_BYTES=200` 字节，留出余量给 `.part001.csv` 这类追加的后缀），切的时候不会把一个多字节字符劈成两半。

**控制台编码**：程序的日志与节点名是汉字，而流的编码由机器决定。`LANG` 未设置的容器给出的是纯 ASCII，
第一行中文会在 logging 的 handler 里抛 `UnicodeEncodeError`——handler 自己吞掉它，于是那行**静默消失**，
看起来像程序安静而不是坏了。`app.py` 在 import 时检查 `stdout/stderr`：写不出汉字就改到 UTF-8 并打印一行
说明；写得出的（中文 Windows 的 cp936）**不改编码**，只把 `errors` 设成 `replace`——把本来正常的控制台强扭
成 UTF-8 反而会把那个窗口变成乱码。镜像另设 `PYTHONUTF8=1`/`LANG=C.UTF-8` 作为容器自己的答案。

**首次进入会说明一次数据放在哪里**（只有云端弹）：哪些存在服务器磁盘上（粘贴的 Cookie、上传与
采集到的表、工作流文件、运行记录），哪些只留在你这个浏览器里（OpenRouter API Key、画布草稿、
界面设置）。两个按钮——**知道了**只是这次关掉，下次还会问；**不再提醒**把选择记在本地
localStorage（"别再提醒"是对这台浏览器说的，服务器并不认识你是谁）。点遮罩与 Esc 等同于「知道了」。

隐私上已被**测着**的几件事（`tests/api/test_privacy_leaks.py`）：它不列一张"我们检查过的路由"
清单，而是走 `app.url_map` 上**每一条 GET 规则**，在磁盘上放一份带独特标记的 Cookie，然后要求
那个标记在任何响应里都不出现——所以以后新加一条路由，只要它把 jar 交出去就会当场红；文件里
还有一格故意把某条路由换成"会漏"的实现，证明这道门真的拦得住。Cookie 面板的行只带条数、日期
与 profile 状态；保存与删除只往控制台报"是哪个账号"，不报内容。`SECRET_KEY` 的内置默认值也钉住了
理由：整个后端不 import `flask.session`，所以那个公开常量签不出任何东西——哪天有人开始用 session，
那一格会先叫。

要注意的边界仍然写着：**采集到的数据、工作流文件与运行记录都存在服务器那一份 `data/` 里**，
谁能访问这台服务器，谁就能翻到这些表。这不是漏洞，是这个工具的设计前提被换掉了——公开部署前请
把它想清楚（这也正是首次弹话说的那些内容）。
