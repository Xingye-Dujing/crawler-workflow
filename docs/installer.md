# 在线安装器与环境检测（Windows）

这是一个**可选**的安装方式：先下载一个约 12 MB 的 `CaiXiHui-Online-Setup.exe`，由它把主程序和需要的
第三方便携组件下载到用户选择的目录。离线安装包 `CaiXiHui-Setup.exe` 仍然保留，给没有网络或不想下载组件的人。

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

数据仍然在 `%APPDATA%\CaiXiHui`（或 `portable.txt` 的便携模式），与安装目录分开；卸载主程序不会删除用户数据。

启动器会在应用导入配置之前读取 `install-manifest.json`，把 Chrome、chromedriver、Node、CatBus 的路径导出为
现有环境变量（`CHROME_PATH`、`CIXI_DRIVER_PATH`、`CIXI_NODE_BIN`、`CIXI_CATBUS_CLI`）。**设置面板里手填的路径仍然优先**，
用户自己导出的环境变量也不会被覆盖。

两个目录不是一回事：**安装根**放 `app/`、`components/` 和 `install-manifest.json`；`CIXI_COMPONENTS_DIR`
指的是其中的 `components/`，清单在它的上一级。源码运行时它们分别是 `data/` 和 `data/components/`。

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
- 不执行下载来的 exe / msi；第三方一律便携 zip 解压。
- **Chrome 不随安装器重新分发**：安装时从 Google 官方 Chrome for Testing 下载，国内默认走 npmmirror 镜像；
  两个地址指向同一份官方构建。
- 安装器与主程序建议代码签名；在线安装器不使用 UPX，降低杀软误报。

## 已验证

2026-11-06 用安装器自己的下载路径（`services.components.fetch.download_asset`，含镜像回退与分片拼接）
重新下载了默认一键的全部五项，并逐项核对清单：主程序 127,300,751 B、Chrome 210,600,182 B、chromedriver
11,594,835 B、Node 37,618,919 B、CatBus 173,307,321 B，共约 534.5 MB，大小与 SHA-256 全部一致。
主程序那一项在发布后又从 Gitee 重下两个分片并拼接，摘要与清单一致。

`install-manifest.json` 的位置也在真机上核对过：用 `python -m services.components --root <目录> install node`
装到 `<目录>/components/node/<版本>`，清单在 `<目录>/install-manifest.json`；设置 `CIXI_COMPONENTS_DIR=<目录>/components`
后 `doctor` 能读到这一行。

## 构建

```powershell
# 主程序（已有）
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1

# 在线安装器（约 12 MB）
powershell -ExecutionPolicy Bypass -File desktop\bootstrap\build.ps1
```

清单：`backend/services/components/default_catalog.json`。发布新版本时更新其中的版本、URL、SHA-256 与体积；
`tools/release_components.py` 负责从构建产物生成这份文件。

## 已知限制

- 平台登录、Cookie、OpenRouter API Key 是用户身份，不能预装；安装器只把“还缺什么”列出来。
- Ollama 模型没有国内官方镜像，默认不选；选择本机 LLM 的用户需要能访问 `registry.ollama.ai` 或自备 Ollama。
- 只有 Windows x64；`desktop/` 是仓库里唯一的 Windows-only 目录。
