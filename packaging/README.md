# Windows 桌面版（onedir）

这不是单文件 exe，而是一个可压缩分发的**文件夹**：`dist/CaiXiHui/CaiXiHui.exe` 是入口，
旁边是运行时和只读资源。双击 exe 会启动本地 Flask 服务（只绑定 `127.0.0.1`）并打开浏览器；
关闭那个控制台窗口即停止服务。首次运行会把数据目录放在 `%APPDATA%\CaiXiHui`。

单文件 exe 被刻意排除：它每次启动都要把几百 MB 解压到临时目录，启动慢、更容易被杀软误报，
而 Chrome/Ollama/MiKTeX 这些外部依赖本来也不会因为单文件而消失。

## 构建

要求：Windows x64、Python 3.11（仓库里的 `.venv` 即可）、能访问 PyPI。

```powershell
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
# 可选：同时用 Inno Setup 6 生成安装包
powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1 -Installer
```

产物：

| 路径 | 用途 |
|---|---|
| `dist/CaiXiHui/` | 绿色版文件夹，双击 `CaiXiHui.exe` |
| `dist/CaiXiHui-win64.zip` | 分发用压缩包（约比文件夹小一半，取决于内容） |
| `dist/CaiXiHui-Setup.exe` | 可选安装包（需要本机装有 Inno Setup 6） |

常用参数：`-Clean` 重建构建环境与产物；`-NoZip` 跳过压缩；`-KeepWork` 保留
PyInstaller 中间目录；`-RemoveBuildEnv` 构建后删掉 `packaging/.venv-build`（省几百 MB，
下次重建会重新安装依赖）；`-Upx` 用 UPX 压缩 pyd/dll；`-SkipInstall` 跳过依赖安装（构建环境
已经准备好时用）。

**UPX**：本机实测把解压后体积从约 301 MB 降到约 **192 MB**，应用与工作流跑通；但未签名 exe +
UPX 更容易被杀软启发式误报，所以默认关闭。给普通用户分发建议用默认包；要极限压缩再加 `-Upx`。

如果依赖安装阶段在**非交互终端/后台任务**里停住而没有任何报错，先在同一台机器用交互式
PowerShell 执行 `packaging\.venv-build\Scripts\python.exe -m pip install --no-build-isolation -r packaging\requirements-runtime.txt`
（以及 `requirements-build.txt`），之后加 `-SkipInstall` 重新运行构建脚本。

构建环境是独立的 `packaging/.venv-build`，只安装 `requirements-runtime.txt` 和
`requirements-build.txt`: **不含** torch / transformers / sentence-transformers / pyarrow /
mitmproxy / pytest / ruff，因此这些包不会被 PyInstaller 收进发行包。`caixihui.spec` 再把
Matplotlib 的 GUI 后端、Selenium 的 Linux/macOS driver 等无用负载排掉；`prune_dist.py`
在构建后做一次保守的清理并报告释放了多少空间。

## 体积边界

本机实测：解压后约 **301 MB**，zip 约 **153 MB**（pandas/numpy/scipy/scikit-learn/matplotlib/
snownlp/jieba 是主要部分）。以下能力被有意排除，以换取可接受的分发体积：

- **BERT 情感/情绪/倾向模型**：数 GB，仍是单独的模型包/目录；不装时对应模式会按设计降级并
  打印实际方法。把模型放到 exe 同级的 `ml_train/models/` 下即可被相对路径解析。
- **pyarrow / Parquet 导出**：按名拒绝，其它导出格式正常。
- **红果短剧评论采集**：需要 mitmproxy + uiautomation，按名拒绝；其它平台不受影响。
- **Ollama 与模型**：不在包内。运行中的 Ollama 会被启动自检识别；不装时仍可上传/清洗/分析/
  出图，需要模型的节点可改用 OpenRouter 或暂不使用。
- **MiKTeX / xelatex**：不在包内；只影响编译节点、图表 PDF 与论文成稿，其余功能正常。

`seed/models/*.pkl`（约 12 MB）与一个文献计量演示工作流会被复制到数据目录，作为首次体验；
已存在的用户文件永远不会被覆盖。

## 首次运行与依赖自检

启动器会在控制台打印：

- Python/依赖：已随包携带，无需安装；
- Chrome：采集节点需要，未找到时只提示，不阻止上传/分析；
- chromedriver：优先用 `drivers/chromedriver.exe`（放在 exe 同目录）或设置里指定的路径；
  都没有时留空，由 Selenium Manager 在首次采集时下载匹配版本（需要联网）；
- Ollama / xelatex：可选能力，缺了只影响对应节点。

`drivers/chromedriver.exe` 不会在构建时下载，因为正确版本取决于**最终用户**的 Chrome；如果要
离线交付，请让用户按其 Chrome 版本放入该文件，或在设置面板里指定路径。

## 数据与便携模式

- 默认数据根：`%APPDATA%\CaiXiHui`（`data/`、`logs/`、`mplconfig/` 都在这里）。
- 便携模式：在 `CaiXiHui.exe` 同目录放一个空的 `portable.txt`，数据根改为 exe 所在文件夹。
  适合 U 盘或不想写 AppData 的用户；请确保该文件夹可写。
- 环境变量 `CRAWLER_DATA_ROOT` 仍可覆盖（测试/高级部署）。
- 同一数据根只允许一个实例：重复双击会直接打开已有窗口，而不是启动第二个服务器。

## 验证构建

构建脚本不会自动跑爬虫。发布前至少确认：

1. 双击 `CaiXiHui.exe`，浏览器打开 `http://127.0.0.1:5000/`（端口被占用会自动顺延）；
2. 首页、`/api/config`、`/api/workflow/list`、`/api/data/datasets`、`/api/runs/list` 返回 200；
3. 打开文献计量演示工作流，能看到画布；上传 `samples/` 中的 CNKI 样例可跑通；
4. 设置页显示 chromedriver/Ollama 状态；不装 Chrome 时上传/分析仍可用。

构建脚本只负责打包，不修改源码；源码测试仍以仓库根目录的 `pytest` 为准。
