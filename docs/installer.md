# 在线安装器与环境检测（Windows / macOS）

这是一个**可选**的安装方式：先下载一个几 MB 的 `CaiXiHui-Online-Setup.exe`，由它把主程序和需要的
第三方便携组件下载到用户选择的目录。离线安装包 `CaiXiHui-Setup.exe` 仍然保留，给没有网络或不想下载组件的人。

安装器窗口是**本进程自己的原生 WebView2 窗口**：页面由 `127.0.0.1` 上的本地服务提供（固定端口 3968 +
随机路径令牌，只监听本机），由 `desktop/native_window.py` 用 pywebview 装进 Windows 自带的
Microsoft Edge WebView2。界面用的就是应用前端的纸白/墨黑设计语言，浅色为默认，右上角可切换深色；
内容按一屏排布，不出现滚动条。这样就不需要把 Qt / Tcl-Tk 这类 GUI 工具包打进 exe。

**exe 是窗口程序**（`console=False`），且**双击先请求管理员**（manifest 为
`requireAdministrator`）：UAC 在 onefile 解包之前出现，机器对未提权进程禁止 `%TEMP%` 写入时也能解包。
主程序本身不带管理员清单。固定端口让页面来源稳定，语言/主题（`localStorage`）下次打开仍然有效；
关闭窗口即结束进程，正在下载时会拒绝关闭（先点“取消”）。Edge WebView2 运行时随 Win10/11 自带；
缺少它的机器会被原生对话框按名字拒绝并给出安装地址（`%LOCALAPPDATA%\CaiXiHui\installer.log` 记录
同一件事）。自动化验收可用 `--no-window` 只起服务，但它同样经过 UAC 清单。

小白默认走**国内直连**：主程序与 CatBus 来自 Gitee，Chrome for Testing / chromedriver / Node.js 来自
npmmirror，全程不需要翻墙。官方地址只作为备用；所有下载都核对 SHA-256，镜像不可信也不会被当成可信。

## 一键安装包含什么

| 组件 | 版本 | 体积 | 来源（默认，国内可直连） |
|---|---|---|---|
| 采析绘主程序 | 1.0.0 | 121 MB | Gitee Release（分两段） |
| Chrome for Testing | 157.0.8103.38 | 201 MB | npmmirror |
| chromedriver | 157.0.8103.38 | 11 MB | npmmirror（与 Chrome 同版本） |
| Node.js | 24.21.0 | 36 MB | npmmirror |
| CatBus 采析绘适配版 | 0.3.0 | 165 MB | Gitee Release（分两段） |

**默认一键 ≈ 535 MB**，装完主程序、Selenium 采集和 CatBus 采集都可用。

安装器列表还会列出**只检测、不下载**的依赖（灰色、不可勾选）：Ollama（本地模型）、BERT 微调模型包、
xelatex（MiKTeX），这样项目全部依赖都在同一页可见；它们不参与“一键安装”的体积。

**安装位置会被提前校验**：如果所选文件夹所在的盘被 Windows/CLR 当作“网络位置”（本项目实测 F: 就是；
`GetDriveType` 对它仍返回 Fixed），安装器会**在下载前**用一次真实的 `Assembly.LoadFrom` 探针拒绝，并
点名该文件夹、请改用 C: 或 D:，而不是装完后才在启动时失败。

以下组件默认**不选**：

- **Ollama 运行时 + 模型**：官方 Windows zip 约 1.5 GB，模型每个 2–4 GB；没有国内官方镜像。采析绘的
  非 LLM 分析、清洗、统计、图表、报告不受影响；LLM 节点需要本机 Ollama 或 OpenRouter。
- **MiKTeX / xelatex**：默认只检测；需要编译 PDF / 论文成稿时再装，国内可用清华 CTAN 镜像。
- **BERT 模型包**：约 780 MB，单独发布；不装时相关节点会降级到 ml/snownlp 并打印实际方法。

## 安装位置

默认 `%LOCALAPPDATA%\Programs\CaiXiHui`，不需要管理员权限；可以改成 `D:\CaiXiHui` 等其他盘。布局：

```
<安装目录>\
  app\                      主程序（上一版保留为 app.previous）
  components\<id>\<版本>\    Chrome / chromedriver / Node / CatBus
  install-manifest.json      每个组件的版本、路径、SHA-256、来源
```

数据默认在 `%APPDATA%\CaiXiHui`（或 `portable.txt` 的便携模式），与安装目录分开；卸载主程序不会删除用户数据。
**安装器里可以单独特定“数据文件夹”**（例如 `D:\CaiXiHui-data`），装完写进 `<安装目录>\app\data-root.txt`，
启动器优先读它——这样程序和用户数据都能完全放在 C 盘以外，换盘不用重装。清空这个文件就回到默认位置。

目标目录需要管理员权限时（例如 `C:\Program Files` 下），安装器**只请求一次** UAC，并用原来的两个路径重新打开；
拒绝授权时会点名是哪个文件夹不可写，而不是下载到一半才失败。主程序启动时如果数据目录不可写，也会同样请求一次。
安装器用进程 token（`GetTokenInformation` 的 `TokenElevation`）判断当前是否已经提权：manifest 已经把进程提权时不会再弹第二次 UAC；
真的写不进去时提示点名文件夹和系统错误。“打开安装位置”使用输入框里当前的路径，不会跳回默认 C:。

两个 Windows 安装器都有**创建桌面快捷方式**选项，快捷方式名字是“采析绘”（`采析绘.lnk`）：离线 Setup 用
Inno 的 `desktopicon` 任务，在线安装器用页面上的“创建桌面快捷方式（采析绘）”复选框，默认勾选；取消就不创建。
macOS 不显示这个选项——应用装到 `/Applications`，由 Launchpad 管理。

启动器会在应用导入配置之前读取 `install-manifest.json`，把 Chrome、chromedriver、Node、CatBus 的路径导出为
现有环境变量（`CHROME_PATH`、`CIXI_DRIVER_PATH`、`CIXI_NODE_BIN`、`CIXI_CATBUS_CLI`）。安装器模式下清单是权威：
设置面板里指向安装器组件目录内的路径仍然可用，指向本机或其他位置的路径会被忽略；进程里旧的、指向安装器目录外的同名
环境变量会被安装器路径替换（否则旧 Chrome 会配安装器驱动，第一次运行就报版本不匹配）。

“环境与组件”面板顶部可以选**组件来源**：默认“安装器安装的”（上表这些便携版），也可以改成“本机已安装的”。
这是严格二选一，不是“优先”：选“安装器安装的”时只认安装器写入的路径，**不再查本机安装根、`PATH` 或 npm 全局前缀**，
缺 Chrome/chromedriver/Node/CatBus 任一份就按名报“安装器未安装”（面板和运行拒绝都会点名），绝不悄悄换成本机那份；
选“本机已安装的”时只查本机，安装器目录里的旧路径也会被忽略。切换在重启采析绘后生效；选择和本次启动生效的来源
是两个字段（`component_source_preference` / `component_source`），面板不会把“下次才生效”说成“现在就用”。
这个切换只在采析绘软件端提供，安装器本身不提供。

安装器模式还以**清单为权威**：启动器导出的 Chrome/chromedriver/Node/CatBus 路径覆盖 `settings.json` 里由旧版本留下的空值或本机路径，
也会替换进程环境里指向安装器目录之外的旧值。否则旧设置会让“安装器安装的”实际拿本机 Chrome 配安装器驱动，首次运行就会报版本不匹配 /
首次联网下载驱动那种长错误。安装器目录内的导出值保留，不清空用户数据。

两个目录不是一回事：**安装根**放 `app/`、`components/` 和 `install-manifest.json`；`CIXI_COMPONENTS_DIR`
指的是其中的 `components/`，清单在它的上一级。源码运行时它们分别是 `data/` 和 `data/components/`。

## 主程序自更新

主程序更新频繁，组件更新很少，所以更新只替换应用本体，不碰 `components/`、`data/`、`logs/`、Cookie、模型和
`install-manifest.json`。页面启动后会读仓库根目录的 `version.json`（Gitee raw 优先，GitHub raw 兜底），
发现版本更高且**当前平台有可下载包**时，顶部弹出“发现新版本”提示；只有用户点“立即更新”才下载。

**在线安装器读的是同一份 `version.json`**：它的 `app` 组件条目不写地址和摘要，只写安装参数（`archive`、
`install_as`、`strip_prefix`、`verify`）和清单地址（`feed`），安装时取当前平台的最新包并校验。所以一份安装器
可以一直用下去，每次安装拿到的都是当时发布的最新主程序；清单读不到或没有当前平台的包时，安装器**点名拒绝**
（显示 URL 和原因），不会退回去装旧版本。

- **发布前**：把新包（Windows 的 `CaiXiHui-win64.zip` 分片；macOS 的 DMG）先上传到 Release，再把
  `version.json` 的 `version`、`sha256`、`size`、`parts`/`url` 更新为这一版；`version.json` 里的版本必须与
  `backend/services/version.py` 的 `APP_VERSION` 对应。资产没上传时不要先改 `version.json`：应用会因“当前平台没有包”而不提示。
- **Windows**：下载分片 → 合并 → 校验总 SHA-256 → 解压到 `<data>/updates/<version>/staged`；用户确认后启动
  PowerShell 脚本等待本进程退出，在线安装布局替换 `<安装根>/app`，便携布局只替换程序文件（保留用户数据），
  旧版本放 `app.previous` 供回滚，然后重启 `CaiXiHui.exe`。
- **macOS**：下载 DMG → 校验 → `hdiutil` 挂载、`ditto` 复制 `.app` 到暂存目录 → 退出后脚本替换整个 `.app`，
  失败则移回 `CaiXiHui.app.previous` 再启动。
- **源码运行**不执行自更新（`supported: false`），避免把开发检出替换成发布包；请更新代码后重启。
- 下载与替换都在 `<data>/updates/` 下进行；更新失败不会改动当前安装，重新检查/重试即可。
- 完整的发版顺序、版本号同步、分片/摘要模板见 [`release.md`](release.md)。

## BERT 模型包（可选，Windows / macOS）

这里有两个**不同**的路径，安装器把它们分开：

- **模型压缩包（源）**：你已有的 `CaiXiHui-bert-models-win64.zip`（或已经解压的 `bert_models` 文件夹）。
  这是只读输入，安装器不会移动或覆盖它。
- **模型存放位置**：`<数据文件夹>/bert_models`，**随“数据文件夹”自动同步**，不需要再单独选一次。
  页面会在“微调 BERT（可选）”下直接显示这个路径；改数据文件夹，它跟着变。

安装器会在**下载前**检查源路径和 zip 内容；装完组件后把完整的模型目录解压到模型存放位置，再用
`desktop/bert_pack.py` 登记进 `<数据文件夹>/data/model_registry.json`。Windows 的存放位置如果就在安装根内，
注册表写相对 `app/` 的路径；在数据文件夹或别处则写绝对路径（macOS 总是绝对路径）。已有同名模型目录/条目
保留，安装器只补缺的；只接受带 `model.onnx`、`tokenizer.json`、`cixi_bert.json` 的完整目录，半包按名拒绝。

源路径留空就跳过 BERT，不下载、不占空间；模型存放位置始终显示，因为它只是数据文件夹的派生。Windows 和
macOS 都带 onnxruntime + tokenizers，模型包是同一份 ONNX 目录。

## macOS 在线安装器

macOS 没有 `CaiXiHui-Online-Setup.dmg` 这种“Windows 安装器换皮”，而是同一个小 `.app` 的 DMG：
`CaiXiHui-Online-Setup-macOS-<arch>.dmg`（arm64 / x86_64 各一个）。它复用同一个安装页面
（`desktop/bootstrap/installer.py` + `installer_page.html/js` + `ui_theme.py`），由
`desktop/bootstrap/installer_macos.py` 换掉三处平台差异：

- 窗口：pywebview 的 Cocoa/WebKit（系统自带），不是 WebView2；
- 文件夹选择：`osascript` 的 `choose folder`；
- 安装：主程序不是 zip，而是一个 DMG。安装器下载并核对它，用 `hdiutil` 挂载、`ditto` 复制
  `CaiXiHui.app` 到安装位置（默认 `/Applications`；该账号不可写时用 `~/Applications`），再
  `hdiutil detach`。`ditto` 会保留 .app 内部的 framework 符号链接和可执行位——用 Python 的
  zipfile 解压会把这些丢掉，装好的程序将无法启动。

Chrome for Testing、chromedriver、Node.js 装到 `~/Library/Application Support/CaiXiHui/components`；
主程序的数据目录也默认在这里。安装器不请求管理员权限，目标不可写时**点名该文件夹**并请改选
用户目录，而不是静默失败。安装完成会写入 `data-root.txt`（.app 旁边）和 `com.caixihui.desktop`
的首选项，所以之后从 Finder 双击也能找到自定义数据目录。

macOS 的组件清单按 CPU 分开：`darwin-arm64` / `darwin-x64`。Chrome for Testing、chromedriver、
Node.js 和 **CatBus** 的官方资产都按架构分开；两个地址（npmmirror + Gitee/Google）指向同一份构建。
CatBus 的 mac 包会自动带上 Node 依赖，安装后在启动器导出 `CIXI_CATBUS_CLI` / `CIXI_NODE_BIN`，
设置里的“环境与组件”和 CatBus 节点都能直接使用。

构建（macOS runner 上，见 `.github/workflows/macos-build.yml`）：

```bash
python desktop/build_macos.py --clean
python desktop/build_macos_installer.py --clean --arch "$(uname -m)"
```

安装器**不再**把刚构建的 DMG 摘要写进自己的清单：它的 `app` 条目只写平台架构、`archive: dmg`、
`install_as: app` 和 `verify`，下载地址/体积/SHA-256 在安装时从 `version.json` 读取（和 Windows 同一套
`backend/services/components/feed.py`）。所以同一个安装器可以跨版本使用，构建步骤也就不再需要应用 DMG 或
Release tag 作为输入；`version.json` 里还没有当前架构的 DMG 时，安装器会点名拒绝而不是装错架构。

只改了安装器、主程序没变时，手动触发 workflow 勾上 `installer_only`：只重建并上传两个安装器 DMG，不碰
`version.json` 已经钉住摘要的应用 DMG。只改了主程序时，照常跑完整构建，产出四个 DMG，再用应用 DMG 的摘要
更新 `version.json`。

## 环境检测

安装完成后，安装器会调用刚装好的 `CaiXiHui.exe --doctor`，把同一份矩阵显示出来（安装器不复制应用里的
词条，`--doctor` 每行同时带 `label_text`/`reason_text`，所以窗口里看到的是中文句子而不是键名）；应用运行后也可以在
“设置 → 环境与组件”打开同一个面板（`GET /api/environment`）。

每一行只有四种状态：

- **可用**：依赖存在且版本匹配；
- **可用（有降级）**：能跑，但缺少某项会降级（例如没有 BERT 模型）；
- **不可用**：点名缺什么（Chrome / chromedriver / Node / CatBus / Ollama / xelatex / 中文字体）；
- **无法核对**：探测本身失败，绝不显示成绿色。

Chrome 的版本在 Windows 上通过可执行文件的版本资源读取，**不会启动浏览器**（`chrome.exe --version` 在
Windows 上不打印版本，还会把参数交给已经打开的浏览器）；读不出版本时这一行是“可用（有降级）”，不会冒充成对。

矩阵覆盖：主程序、Selenium 采集、CatBus 采集、本机 LLM、云端 LLM、BERT、PDF 编译、中文图表、上传/分析/报告。

## 组件管理

`GET /api/components` 列出清单与已安装版本；面板可以单项安装 / 更新 / 卸载，安装是后台任务
（`POST /api/components/install` + `GET /api/components/jobs/<id>` 轮询），不会让一个浏览器请求挂几十分钟。
组件按版本存放，默认只保留当前和上一版；卸载组件不删除用户数据。只检测不下载的组件（如 MiKTeX）按名拒绝安装，
不会起一个注定失败的任务。取消安装**不删除**已经下载的字节，下次从断点续传。装好组件后**重启采析绘**才会让采集
和运行用上新组件（启动器在导入配置前导出路径），面板会提示这一点。

**主程序自己不在面板里更新**：运行中的应用开着它自己的文件，替换会失败，所以“更新主程序”一律交回在线安装器
（它把旧版移到 `app.previous` 以便回滚）。面板里 `app` 一行永远没有更新按钮。

安装器按 `requires` 自动补依赖：只勾 CatBus 会连 Node 一起装，只勾 chromedriver 会连 Chrome 一起装；只检测的组件
（MiKTeX）不会被自动加入。清单里写了某个组件文件夹而磁盘上已经没有时，面板显示未安装，而不是照着旧记录说“已安装”。

## 安全与合规

- 所有下载只接受 HTTPS；逐项核对清单里的 SHA-256，失败删除字节并点名 URL。
- 解压拒绝绝对路径、`..`、符号链接，限制条目数与总大小；先解压到 staging，再原子移动到目标目录。
  用户选择的 BERT 模型包也走同一条 `safe_extract` 检查；只接受带完整三件套的模型目录。
  macOS 的 Chrome/Node 资产必须保留符号链接和可执行位，所以改用系统 `ditto`/`tar` 解包；它们同样是
  先核对 SHA-256 的固定字节，且仍解到 staging 后再替换。
- 不执行下载来的 exe / msi；第三方一律便携 zip 解压。主程序在 macOS 上是 DMG 里的 `.app`，安装器只
  挂载和复制它，不执行安装脚本。
- **Chrome 不随安装器重新分发**：安装时从 Google 官方 Chrome for Testing 下载，国内默认走 npmmirror 镜像；
  两个地址指向同一份官方构建。
- 安装器与主程序建议代码签名；在线安装器不使用 UPX，降低杀软误报。离线包/主程序的完整签名链
  （编译不持密钥 → 签 exe → 打 Setup → 签 Setup → 时间戳 → `SHA256SUMS`）见
  [`desktop/README.md`](../desktop/README.md) 的"分发链"一节。
- **签名会改变分发出去的字节**：`version.json` 里 `platforms.win32` 的 `sha256`/`size` 和两个分片的摘要，
  必须在最后一次签名之后、以最终 `CaiXiHui-win64.zip` 为准生成——安装器和自更新都按这份摘要拒绝
  对不上的字节。macOS 同理：`platforms.darwin-*` 的摘要要取自最终 DMG。
- 安装器不调用系统 shell 执行下载内容；页面只由本机 `127.0.0.1` 提供服务，路径带随机令牌，并用
  `Content-Type: application/json` 的 POST（浏览器跨站请求会先被预检拦住）。

## 已验证

2026-11-06 用安装器自己的下载路径（`services.components.fetch.download_asset`，含镜像回退与分片拼接）
重新下载了默认一键的全部五项，并逐项核对清单：主程序 127,300,751 B、Chrome 210,600,182 B、chromedriver
11,594,835 B、Node 37,618,919 B、CatBus 173,307,321 B，共约 534.5 MB，大小与 SHA-256 全部一致。
主程序那一项在发布后又从 Gitee 重下两个分片并拼接，摘要与清单一致。

`install-manifest.json` 的位置也在真机上核对过：用 `python -m services.components --root <目录> install node`
装到 `<目录>/components/node/<版本>`，清单在 `<目录>/install-manifest.json`；设置 `CIXI_COMPONENTS_DIR=<目录>/components`
后 `doctor` 能读到这一行。

2026-11-09 安装器改为**原生 WebView2 窗口**后复核：打包的 `CaiXiHui-Online-Setup.exe` 为
**13,878,349 B（约 13.2 MB）**（无 Qt / Tcl-Tk；多出来的部分是 pywebview + pythonnet + WebView2 的 .NET
包装，运行时本体用系统已装的 Edge）。`--no-window` 只起服务时，`/`、`/api/state`、`installer_page.js`、
`icon.ico` 均返回 200，页面来源固定为 `127.0.0.1:3968`；窗口模式在 C: 上解包运行（onefile 解在 exe 旁边
而不是 `%TEMP%`）时没有控制台，进程和 `msedgewebview2` 子进程都正常，`%LOCALAPPDATA%\CaiXiHui\webview-installer\EBWebView`
被创建，30 秒内没有触发“页面没加载”的失败分支。`preset=app` 只剩主程序，勾选 `app + catbus` 时体积自动
加上 Node（338,226,991 B，逐项相加一致）；页面默认浅色、右上角可切深色，一屏内不出现滚动条。环境检查报告
由应用以 UTF-8 字节输出，安装器按 UTF-8 解码，不再出现乱码。

> **2026-11-09 的窗口修复**：onefile 改为默认解到用户 `%TEMP%`（与参考桌面项目
> `D:\blog\web\public` 相同），不再用 `runtime_tmpdir='.'` 把 .NET 程序集解到 exe 旁边的 F: 盘上，
> 于是不再出现 `Failed to resolve Python.Runtime.Loader.Initialize` 或纯白窗口。窗口数据目录会依次尝试
> `%LOCALAPPDATA%\CaiXiHui`、`%APPDATA%`、程序数据目录、`%TEMP%`，不会再报
> `Storage path … is not writable`。主程序 exe 如果是整个文件夹放在 F: 这类被 .NET 当“网络位置”的盘上，
> 会明确提示复制到 C: 或 D:；这不是 WebView2 缺失，也不再误弹“请安装 WebView2”。
>
> 离线 `CaiXiHui-Setup.exe`：Inno 的 loader 固定 asInvoker，在 UAC 之前就要往用户 `%TEMP%` 解压内层
> setup，被策略拒绝时正是“unable to create the directory "...\is-XXXX.tmp" ... Error 5”。构建脚本现在用
> `desktop/patch_manifest.py` 把外层 exe 的 manifest 改成 `requireAdministrator`，双击**先弹 UAC**，
> loader 在管理员令牌下解包；`PrivilegesRequired=admin` 只是内层 setup 的声明。安装路径与 HKCU PATH
> 仍是 per-user，装完后程序本身不带管理员清单。

2026-11-09 macOS 的 arm64 / x86_64 应用 DMG 由 GitHub Actions 构建并上传到 Release；在线安装器的
生成清单（`app.platforms.darwin-arm64` / `darwin-x64` 的 SHA-256、体积、URL）和页面契约由
`tests/unit/desktop/test_macos_installer.py` 在 Windows 上覆盖。这个 checkout 没有 macOS，
**未做真实 Mac 启动验证**；安装器 DMG 也在同一次 workflow 中产出。

macOS 的三项组件资产也从 npmmirror 实际下载并核对：Chrome for Testing arm64 196,562,867 B /
x64 207,117,913 B；chromedriver arm64 9,378,279 B / x64 10,409,330 B；Node arm64 52,909,993 B /
x64 54,203,979 B。SHA-256 见 `backend/services/components/default_catalog.json` 的 `darwin-arm64` /
`darwin-x64` 条目。

2026-11-11 的 macOS workflow（`main@a45510c`，发布 tag `exe-2026-11`）也产出了两组产物：应用 DMG arm64
**177,675,158 B**（SHA-256 `471fb4a1b915ca6c7f8a8b9cd4698b0cb8da3b4744a61528ae05952ada3fdfc1`）/ x86_64
**187,529,072 B**（`da0e4362b0b4a0b21f4279e38bb36106f49c56f678de79120751fb02f95771eb`）；在线安装器 DMG
arm64 **14,844,863 B**（`a886c8bb7b927bc5e6bb50941509289c99f0535cc10a11aff63d4074b8f09851`）/ x86_64
**15,640,403 B**（`9204fc91b31d829ac38f6fd32065d9f6a3b819b7f21bcf6be0a45f09686c6df4`）。
两个安装器分别写了对应架构应用 DMG 的摘要；**没有在真实 Mac 上运行过**。

2026-11-11 的 Windows 发布（主程序自更新、关闭窗口彻底退出、安装器组件模式以清单为准）：`CaiXiHui-win64.zip`
**130,169,985 B**（`e055dc1295eb9796c0123e31b6855c6a1902ce003dd3bb3fde0febf057a933ab`）、离线
`CaiXiHui-Setup.exe` **121,712,901 B**（`55926a539fb7ae4a29bfaa7fb516f3d13f5f37b532abdfdc1c5b81dff7665783`）、
在线 `CaiXiHui-Online-Setup.exe` **13,878,349 B**（`23fc313ece7f57e75cf3583da1e0ab82e3cf017b4887b7e4577abaaf20d18b80`）。
三个 exe 图标都从同一份圆形 ICO 资源实测为 32×32、四角 alpha=0、中心 alpha=255；zip/Setup 内是同一份新主程序。

2026-11-12 把安装器改成**安装时读 `version.json`**（`main@cd1c914`）后只重建了安装器，主程序的 zip/Setup/应用 DMG
一个字节没动：

- 源码模式实测：安装器进程的 `/api/state` 返回 `feed: ok / 2026.11.11.1`，`app` 行版本、体积
  **130,169,985 B** 与已发布 zip 一致，默认预设勾上了 `app`，总体积 563,291,242 B；`feed.resolve` 对
  `win32` / `darwin-arm64` / `darwin-x64` 三个条目取到的 URL、摘要与 `version.json` 完全相同。
- 打包的 `CaiXiHui-Online-Setup.exe` **13,887,902 B**
  （`28dc8bf9a9f712259ff516c4d7a04cf3906733c17f8042b1c70354baaeec6a99`）里确认带上了
  `services.components.feed`（`build/pyinstaller-bootstrap/installer/PYZ-00.toc`），PE manifest 仍是
  `requireAdministrator`；Gitee 上重新下载回来的字节与该摘要一致。窗口版这次没有重跑（需要 UAC 交互），
  自更新链路未改。
- `installer_only` 的 macOS run（`42825279883`）只替换了两个安装器 DMG：arm64 **14,852,875 B**
  （`b1c4377db4a72c246a5364f2d8fe629d947957ef8a5d94b5f7e76f67e45cbfd7`）/ x86_64 **15,647,102 B**
  （`58a72a0943041de9129f2ac4294e7332691538ee60cb99a8d3ef37458ce97baa`），应用 DMG 的摘要与
  `version.json` 里的 `471fb4a1…` / `da0e4362…` 保持一致。**同样没有在真实 Mac 上运行过。**

## 构建

```powershell
# 主程序（已有）
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1

# 在线安装器（几 MB：标准库 HTTP 服务 + 组件核心，不带 GUI 工具包）
powershell -ExecutionPolicy Bypass -File desktop\bootstrap\build.ps1
```

macOS 的构建命令见上面的“macOS 在线安装器”；它只能在 macOS runner 上执行（`hdiutil`、`ditto`）。

安装器界面由三个文件组成：`desktop/bootstrap/installer_page.html`（结构）、`installer_page.js`
（只负责画和发请求）和 `ui_theme.py`（词条、调色板、CSS；和 `base.css` 用同一组令牌）。页面文本一律用
`textContent` 写入，图标全部是内联 SVG（勾选、太阳/月亮），不使用字体图标或 Unicode 符号。

清单：`backend/services/components/default_catalog.json`。发布新版本时更新其中的版本、URL、SHA-256 与体积；
`tools/release_components.py` 负责从构建产物生成这份文件。一个组件现在可能同时有 `win32`、
`darwin-arm64`、`darwin-x64` 三项，`--component chrome=...` 默认只改**当前机器**的那一项；要改另一项必须写
`--component chrome:darwin-arm64=<zip>`，这样一个 Windows zip 不会覆盖 Mac 的摘要。最终产物的 `SHA256SUMS` 与
`release-manifest.json` 由 `desktop/release_manifest.py` 在签名链的最后一步写出，`--check` 可复核。

例外是 `app`：它没有 URL/摘要，只有 `feed`（`version.json` 的地址）和安装参数。主程序的版本、体积、摘要
由 `version.json` 一处决定，安装器与自更新都读它；`tools/release_components.py` 不再写 `app` 的字节，也不要
手工把旧摘要塞回清单。清单里另有一项 `ollama`/`bert`/`xelatex` 这类 `manual` 条目，只检测不下载。

## 已知限制

- 平台登录、Cookie、OpenRouter API Key 是用户身份，不能预装；安装器只把“还缺什么”列出来。
- Ollama 模型没有国内官方镜像，默认不选；选择本机 LLM 的用户需要能访问 `registry.ollama.ai` 或自备 Ollama。
- Windows 版为 x64；macOS 版为 11+（arm64 / x86_64）。`desktop/` 是唯一的 OS 打包目录，Windows 和
  macOS 的平台事实都留在里面，不进 `backend/`。
- macOS 的 DMG 未签名/未公证，首次打开需右键“打开”；CatBus 有 macOS 官方构建，安装器会连同 Node 一起安装。
- Windows 与 macOS 都带 onnxruntime + tokenizers；BERT 模型包是同一份 ONNX 目录。torch/transformers
  仍只在开发机使用，不进桌面包。
