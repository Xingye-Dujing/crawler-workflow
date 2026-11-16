# 在线安装器与环境检测

在线安装器是可选入口：十几 MB 的 `CaiXiHui-Online-Setup.exe`（macOS 为 DMG），把主程序与第三方便携组件
下载到用户选择的目录。离线包 `CaiXiHui-Setup.exe` 保留给没有网络或不想下载组件的人。
安装器窗口是本进程的原生 WebView2 窗口（macOS 为 Cocoa/WebKit），页面由 `127.0.0.1:3968` 上的本地服务
提供，路径带随机令牌；界面沿用应用前端的纸白/墨黑设计语言，浅色为默认，可切深色，一屏内不出滚动条。

## 组件

| 组件 | 版本 | 来源（默认） |
|---|---|---|
| 采析绘主程序 | 安装时从 `version.json` 取当前平台最新包 | Gitee / GitHub Release |
| Chrome for Testing | 157.0.8103.38 | npmmirror（官方地址备用） |
| chromedriver | 157.0.8103.38 | npmmirror（与 Chrome 同版本） |
| Node.js | 24.21.0 | npmmirror |
| CatBus 采析绘适配版 | 0.3.0-crawler-workflow | Gitee Release |

- 国内默认全部直连（Gitee + npmmirror），官方地址只作备用；每项都核对 SHA-256，镜像不可信也不当可信。
- `requires` 自动补依赖：勾 CatBus 会连 Node 一起装，勾 chromedriver 会连 Chrome 一起装。
- **只检测、不下载**（灰显不可勾选）：Ollama、BERT 模型包、xelatex（MiKTeX）。它们不参与安装体积，也不起注定失败的任务。
- **默认不选**：Ollama 运行时与模型（无国内官方镜像；非 LLM 的分析、清洗、统计、图表、报告不受影响）、
  MiKTeX（国内可用清华 CTAN）、BERT 模型包（约 780 MB，不装时相关节点降级到 ml/snownlp 并打印实际方法）。
- 清单唯一来源是 `backend/services/components/default_catalog.json`；`tools/release_components.py` 从构建产物生成它。

## 安装流程

1. **校验安装位置（下载前）**：盘被 Windows/CLR 当网络位置时用一次真实的 `Assembly.LoadFrom` 探针拒绝，
   点名该文件夹并请改用 C: 或 D:，不等到启动才失败。
2. **取包**：`app` 条目只写安装参数与清单地址（`feed`），安装时经 `backend/services/components/feed.py`
   读 `version.json`，按当前平台/架构取包。清单读不到或没有当前平台的包时点名拒绝（显示 URL 与原因），
   绝不退回旧版本。因此一份安装器可以一直用下去。
3. **下载**：只接受 HTTPS；逐项核对清单 SHA-256，失败即删除字节并点名 URL；分片按序拼接后校验总包摘要；
   取消不删除已下载字节，下次断点续传。
4. **解包**：先解到 staging 再原子移到目标目录；`safe_extract` 拒绝绝对路径、`..` 和符号链接，限制条目数与总大小。
   macOS 的 Chrome/Node 资产必须保留符号链接与可执行位，改用系统 `ditto`/`tar`，仍是先校验固定字节再替换。
5. **落盘**（默认目录见下）：

   ```
   <安装目录>\
     app\                      主程序（上一版保留为 app.previous）
     components\<id>\<版本>\    Chrome / chromedriver / Node / CatBus
     install-manifest.json      每项的版本、路径、SHA-256、来源
   ```

6. **导出路径**：启动器在导入配置之前读 `install-manifest.json`，把 Chrome、chromedriver、Node、CatBus
   导出为 `CHROME_PATH`、`CIXI_DRIVER_PATH`、`CIXI_NODE_BIN`、`CIXI_CATBUS_CLI`。
7. **自检**：安装器调用刚装好的 `CaiXiHui.exe --doctor` 显示环境矩阵（每行带 `label_text`/`reason_text`，
   安装器不复制应用里的词条）。

## 安装位置与数据目录

- 默认装在 `%LOCALAPPDATA%\Programs\CaiXiHui`，不需要管理员权限；可改到其他盘。
- 数据默认在 `%APPDATA%\CaiXiHui`（或 `portable.txt` 的便携模式），与安装目录分开；卸载主程序不删用户数据。
- 安装器可单独指定**数据文件夹**（例如 `D:\CaiXiHui-data`），写进 `<安装目录>\app\data-root.txt`，启动器优先读它；
  清空该文件回到默认位置。
- 目标目录需要管理员权限时（如 `C:\Program Files`）只请求一次 UAC，拒绝时点名不可写的文件夹；
  manifest 已提权时不再弹第二次（按 `GetTokenInformation` 的 `TokenElevation` 判断）。“打开安装位置”用输入框当前路径。
- 两个目录不是一回事：**安装根**放 `app/`、`components/` 与清单；`CIXI_COMPONENTS_DIR` 指其中的 `components/`，
  清单在它上一级。源码运行时二者分别是 `data/` 与 `data/components/`。
- 桌面快捷方式名为“采析绘”（`采析绘.lnk`），离线包走 Inno 的 `desktopicon`，在线安装器用页面复选框，默认勾选；
  macOS 不提供该选项（应用进 `/Applications`，由 Launchpad 管理）。

## 组件来源（严格二选一）

“环境与组件”面板可切换“安装器安装的（默认）”与“本机已安装的”。两者都在时是二选一，不是优先：

- 选“安装器安装的”只认清单写入的路径，**不查本机安装根、`PATH`、npm 全局前缀**；缺任一份按名报“安装器未安装”
  （`env.sourceInstallerMissing`），不悄悄换成本机那份。
- 选“本机已安装的”只查本机，忽略安装器目录里的旧路径。
- 切换在重启采析绘后生效：持久化选择是 `component_source`，启动器把它冻结成 `CIXI_COMPONENT_SOURCE`，面板如实说“下次生效”。
- 没有安装器组件树的运行形态（源码、便携 zip、离线 Setup、云端容器）按本机来源处理，不会因此全部报“安装器未安装”。
- 安装器模式下清单是权威：它覆盖 `settings.json` 里旧版本留下的空值或本机路径，也替换进程环境里指向安装器目录之外的旧值
  （否则旧 Chrome 会配安装器驱动）。安装器目录内的导出值保留，不清空用户数据。
- 这个切换只在采析绘软件端提供，安装器本身不提供。

## 拒绝与降级

| 情形 | 行为 |
|---|---|
| 缺少 Edge WebView2 运行时 | 原生对话框按名拒绝并给安装地址，同时写 `%LOCALAPPDATA%\CaiXiHui\installer.log` |
| 安装位置被当网络位置 | 下载前拒绝，点名文件夹 |
| 目标目录不可写 | 点名文件夹与系统错误，请求一次 UAC |
| 清单读不到 / 无当前平台包 | 点名拒绝并显示 URL 与原因，不回退旧版本 |
| 请求安装只检测不下载的组件 | 按名拒绝，不起后台任务 |
| BERT 包缺 `model.onnx`/`tokenizer.json`/`cixi_bert.json` | 按名拒绝半包 |
| 来源为安装器但组件缺失 | 按名“安装器未安装”，不悄悄换成本机那份 |
| 环境探测本身失败 | 无法核对，绝不显示成绿色 |
| Chrome 版本读不出 | 可用（有降级），不冒充成对 |

环境检测只有四种状态：**可用**、**可用（有降级）**、**不可用**（点名缺 Chrome/chromedriver/Node/CatBus/Ollama/xelatex/中文字体）、
**无法核对**。Chrome 版本在 Windows 上读可执行文件的版本资源，不启动浏览器（`chrome.exe --version` 不打印版本，
还会把参数交给已开的浏览器）。矩阵覆盖：主程序、Selenium 采集、CatBus 采集、本机 LLM、云端 LLM、BERT、
PDF 编译、中文图表、上传/分析/报告。

## 主程序自更新

自更新只替换应用本体，不碰 `components/`、`data/`、`logs/`、Cookie、模型和 `install-manifest.json`。
页面启动后读 `version.json`（Gitee raw 优先，GitHub raw 兜底，可用 `CIXI_UPDATE_FEED` 覆盖），
发现更高版本、当前平台有包且摘要齐全时在菜单条下方弹卡片；只有用户点“立即更新”才下载，
“稍后”安静 24 小时并按版本记住，“不再提示此版本”只压住那一版，下载中多一个“取消”。

| 角色 | 做什么 | 失败时 |
|---|---|---|
| 主程序（页面 + 本地服务） | 检查、征求同意、画进度、决定何时退出 | 关窗口不影响下载 |
| 下载进程（同一 exe `--update-worker`，无窗口） | 分片续传、逐片与总包 SHA-256、解压、形状校验 | 状态与原因写入 `job.json` 和 `update.log` |
| 替换脚本（Windows PowerShell / macOS bash） | 等两个进程退出 → 逐项替换并重试被占用文件 → 校验新版本活着 → 拉起或回滚 | 写日志、回滚、启动旧版本 |

- 任务状态在 `<data>/updates/job.json`（`downloading → staging → staged → applying → applied`），
  日志 `<data>/updates/update.log`（256 KB 轮转）。刷新页面、重开窗口、下载中关窗口都接回同一任务；
  刷新后由 `/api/update/status` 重画进度，下载完成后关窗口等同“重启并完成更新”。
- Windows：下载分片 → 合并 → 校验总摘要 → 解到 `<data>/updates/<version>/staged` → 形状校验（必须有 `CaiXiHui.exe`
  与 `_internal`）→ 替换 `<安装根>/app`，便携布局只换程序文件，旧版放 `app.previous` → 重启后观察 15 秒，起不来就回滚。
- macOS：DMG 经 `hdiutil` 挂载、`ditto` 复制 `.app` 到暂存目录，退出后替换整个 `.app`，失败移回
  `CaiXiHui.app.previous` 再启动（脚本每步显式判断，不用 `set -e`）。
- 源码运行与没有替换脚本的平台（Linux、非 `.app` 的 macOS 构建）`apply_supported` 为假，卡片只说“请用安装器更新”，
  绝不先下载再拒绝。
- 替换期间写 `<data>/updates/applying.marker`，此时双击启动会先等替换结束。
- 更新失败不改动当前安装：替换中途失败逐项移回，新版本启动后立刻退出也回滚；下次启动按名说明上次失败（`update.err.*`）。
- **安装回执跟着更新走**：新版本首启把 `job.json` 从 `applying` 收成 `applied` 时，按安装器同一套规则改写
  `<安装根>/current-version` 与 `<安装根>/versions/<新版本>/install.json`（`method: self-update`，经 `.partial` 改名；
  便携目录没有指针文件则跳过）。否则“安装器记录的版本”停在最后一次安装，审计与回滚都会读错。
- 发版顺序、版本号同步、分片与摘要模板见 [`release.md`](release.md)。

## BERT 模型包（可选）

两个路径不能混：**模型压缩包（源）** 是只读输入，安装器不移动也不覆盖；**模型存放位置**是
`<数据文件夹>/bert_models`，随数据文件夹自动同步、不单独选。下载前检查源路径与 zip 内容，装完组件后解压到存放位置，
再用 `desktop/bert_pack.py` 登记进 `<数据文件夹>/data/model_registry.json`（存放位置在安装根内则写相对 `app/` 的路径，
否则写绝对路径；macOS 总是绝对）。已有同名模型目录/条目保留，只补缺的；半包按名拒绝。源路径留空即跳过。
Windows 与 macOS 都带 onnxruntime + tokenizers，包是同一份 ONNX 目录。

## macOS 安装器

`CaiXiHui-Online-Setup-macOS-<arch>.dmg`（arm64 / x86_64 各一个），复用同一安装页面
（`desktop/bootstrap/installer.py` + `installer_page.html`/`installer_page.js` + `ui_theme.py`），
由 `desktop/bootstrap/installer_macos.py` 换掉三处平台差异：

- 窗口：pywebview 的 Cocoa/WebKit，不是 WebView2；
- 文件夹选择：`osascript` 的 `choose folder`；
- 安装：主程序是 DMG，用 `hdiutil` 挂载、`ditto` 复制 `CaiXiHui.app` 到安装位置（默认 `/Applications`，
  该账号不可写时 `~/Applications`），再 `hdiutil detach`。`ditto` 保留 framework 符号链接与可执行位，
  Python 的 zipfile 会丢掉它们。

Chrome/chromedriver/Node 装到 `~/Library/Application Support/CaiXiHui/components`，数据目录默认同处。
不请求管理员权限，目标不可写时点名该文件夹。安装完成写 `data-root.txt`（.app 旁边）与 `com.caixihui.desktop`
首选项，之后从 Finder 双击也能找到自定义数据目录。组件清单按 CPU 分开：`darwin-arm64` / `darwin-x64`，
Chrome、chromedriver、Node、CatBus 的资产都按架构分开，两个地址指向同一份构建；CatBus 的 mac 包自带 Node 依赖。

## 构建

```powershell
# 主程序
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1

# 在线安装器
powershell -ExecutionPolicy Bypass -File desktop\bootstrap\build.ps1
```

macOS 只在 macOS runner 上构建（`hdiutil`、`ditto`），见 `.github/workflows/macos-build.yml`：

```bash
python desktop/build_macos.py --clean
python desktop/build_macos_installer.py --clean --arch "$(uname -m)"
```

安装器页面由 `desktop/bootstrap/installer_page.html`（结构）、`installer_page.js`（只负责画和发请求）、
`ui_theme.py`（词条、调色板、CSS）组成；文本一律 `textContent` 写入，图标是内联 SVG，不用字体图标或 Unicode 符号。
只改安装器、主程序没变时，手动触发 workflow 勾 `installer_only`：只重建并上传两个安装器 DMG，不碰应用 DMG。

## 组件管理

`GET /api/components` 列清单与已装版本；面板可单项安装/更新/卸载，安装是后台任务
（`POST /api/components/install` + `GET /api/components/jobs/<id>` 轮询），不会让一个请求挂几十分钟。
组件按版本存放，默认只保留当前和上一版；卸载不删用户数据；装好组件需**重启采析绘**才生效（启动器在导入配置前导出路径）。
`app` 一行永远没有更新按钮：运行中的应用占着自己的文件，主程序更新一律交回在线安装器。
清单写了某组件但磁盘上已没有时显示未安装，不照旧记录说“已安装”。

## 安全与合规

- 只接受 HTTPS，逐项核对 SHA-256；解压先 staging 后原子替换。
- 不执行下载来的 exe/msi，第三方一律便携包解压；macOS 只挂载并复制 `.app`，不跑安装脚本。
- **Chrome 不随安装器重新分发**：从 Google 官方 Chrome for Testing 下载，国内走 npmmirror，两者同一份构建。
- 安装器与主程序建议代码签名；在线安装器不使用 UPX（降低杀软误报）；完整签名链见
  [`desktop/README.md`](../desktop/README.md) 的“分发链”一节。
- **签名会改变分发出去的字节**：`version.json` 的 `platforms.win32` 摘要与分片摘要必须在最后一次签名之后、
  以最终 `CaiXiHui-win64.zip` 为准生成；`platforms.darwin-*` 取自最终 DMG。安装器与自更新都按这份摘要拒绝对不上的字节。
- 页面只由本机 `127.0.0.1` 提供，路径带随机令牌，POST 用 `Content-Type: application/json`（跨站请求先被预检拦住）。
- 安装器窗口是窗口程序（`console=False`）且双击先请求管理员（manifest `requireAdministrator`，UAC 在 onefile 解包之前出现）；
  关闭窗口即结束进程，下载中拒绝关闭（先点“取消”）。自动化验收可用 `--no-window` 只起服务，但它同样经过 UAC 清单。

## 已知限制

- 平台登录、Cookie、OpenRouter API Key 是用户身份，不能预装；安装器只列出还缺什么。
- Ollama 模型没有国内官方镜像，默认不选；用本机 LLM 需能访问 `registry.ollama.ai` 或自备 Ollama。
- Windows 为 x64；macOS 为 11+（arm64 / x86_64）。`desktop/` 是唯一的 OS 打包目录，平台事实不进 `backend/`。
- macOS 的 DMG 未签名/未公证，首次打开需右键“打开”。
- torch/transformers 只在开发机使用，不进桌面包。
