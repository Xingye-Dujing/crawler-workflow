# Windows 桌面版（onedir）

> **这一整棵树是本项目唯一故意只服务 Windows 的地方**（PyInstaller + UPX + Inno Setup 只能产 exe）。
> 里面的 Windows 事实——`%APPDATA%` 数据根、命名互斥量、`MessageBoxW`、`chrome.exe` 安装根、cp936 控制台、
> PowerShell 脚本——**都不属于 `backend/`**：源码版要在 Linux 云服与 macOS 上跑，`backend/` 里出现任何
> Windows 专属路径或命令都要按当前系统分支（`core/machine.py` 的那些表），并按 AGENTS 的
> 「Cross-platform」一节办。打包版只按 Windows 验收。

这不是单文件 exe，而是一个可压缩分发的**文件夹**：`dist/CaiXiHui/CaiXiHui.exe` 是入口，
旁边是运行时和只读资源。双击 exe 会启动本地 Flask 服务（只绑定 `127.0.0.1`）并打开浏览器；
关闭那个控制台窗口即停止服务。首次运行会把数据目录放在 `%APPDATA%\CaiXiHui`。

单文件 exe 被刻意排除：它每次启动都要把几百 MB 解压到临时目录，启动慢、更容易被杀软误报，
而 Chrome/Ollama/MiKTeX 这些外部依赖本来也不会因为单文件而消失。

## 构建

要求：Windows x64、Python 3.11（仓库里的 `.venv` 即可）、能访问 PyPI。

```powershell
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1
# 可选：同时用 Inno Setup（6 或 7）生成安装包
powershell -ExecutionPolicy Bypass -File desktop\build_windows.ps1 -Installer
```

产物：

| 路径 | 用途 |
|---|---|
| `dist/CaiXiHui/` | 绿色版文件夹，双击 `CaiXiHui.exe` |
| `dist/CaiXiHui-win64.zip` | 分发用压缩包（约比文件夹小一半，取决于内容） |
| `dist/CaiXiHui-Setup.exe` | **单文件安装包**（`-Installer`，需要本机装有 Inno Setup） |
| `dist/CaiXiHui-bert-models-win64.zip` | 可选 BERT 模型包（`desktop/build_model_pack.py` 单独产出，见下文） |

**分发只有一个文件的人给 `CaiXiHui-Setup.exe`**：安装动作把 `Compression=lzma2/ultra64` 一次做完，
所以程序本体仍是解开的文件夹——启动不需要每次解压。运行时单文件（PyInstaller/Nuitka 的 onefile）被
明确排除：它每次启动都要把几百 MB 解到 `%TEMP%`（这台机器的 `%TEMP%` 会被安全策略拒写，我们在 pip 上
已经踩过同一形状），启动更慢，而且"未签名 + 自解压"正是杀软误报率最高的组合。

ISCC 的查找不写死版本也不写死磁盘：`$env:CIXI_ISCC` → Program Files / Program Files (x86) /
`%LOCALAPPDATA%`（递归两层）→ 每个盘根下的 `Inno Setup *\ISCC.exe` → PATH，并把实际用的路径打印出来。
理由是本机实测：工具装在 `E:\Inno Setup 7\ISCC.exe`，旧代码只找 `Program Files\Inno Setup 6` 于是
"明明装了却说没找到"。`.iss` 头部带 UTF-8 BOM（Inno 读无 BOM 的 `.iss` 用 ANSI 代码页，而里面的
向导文案是中文——这一点由 `test_the_files_other_tools_parse_are_pure_ascii` 按字节钉住）。
Inno 7 会警告 `LZMAUseSeparateProcess` 已过时并忽略它，所以那一行已从 `.iss` 删掉——警告在这里
不是噪音，是"你以为生效的开关其实没生效"。

**图标必须是真 ICO**：`backend/static/icon.ico` 被两个打包器读——PyInstaller 把它刻进 `CaiXiHui.exe`，
Inno Setup 把它刻进安装包。它长期就是那张 PNG 换了个 `.ico` 名字：浏览器按内容嗅探，所以网页图标一直是对的；
PyInstaller 把无效字节照抄进 exe 资源，还打印一句 `Copying icon to EXE` 好像成功了；Inno 直接拒绝编译
（实测 `Resource update error: Icon file is invalid`），而且是在文件夹与 zip 已经花完十分钟之后才说。
现在它由 `tools/build_icon.py` 从 `backend/static/icon.png` 生成（16/24/32/48/64/128/256 七档），
构建脚本**动手之前**先检查头四个字节，`tests/unit/desktop/test_desktop_packaging.py` 逐帧钉住目录与画框。
改图标 = 改 `icon.png` 后跑一次 `.venv\Scripts\python.exe tools\build_icon.py`。

常用参数：`-Clean` 重建构建环境与产物；`-NoZip` 跳过压缩；`-KeepWork` 保留
PyInstaller 中间目录；`-RemoveBuildEnv` 构建后删掉 `desktop/.venv-build`（省几百 MB，
下次重建会重新安装依赖）；`-NoUpx` **关掉** UPX（默认开）；`-SkipInstall` 跳过依赖安装（构建环境
已经准备好时用）；`-Installer` 额外用 Inno Setup（6/7）出安装包。

**UPX**：本机实测把解压后体积从约 301 MB 降到约 **192 MB**，应用与工作流跑通。现在它是**默认步骤**，
但不再交给 PyInstaller：`caixihui.spec` 里 `upx=False`，构建后由 `desktop/compress_dist.py` 对
`_internal` 里的 pyd/dll 与主 exe 逐个跑 `upx --best`。换掉的理由是可验证性——PyInstaller 找不到
upx 时是**静默不压**（于是"压过了"只是一个猜测），而这里找不到 upx 会按名失败、压过的文件用
`upx -t` 校验、失败的文件还原、最后打印压缩个数与前后字节；已被 UPX 压过的文件跳过，不二次压缩。
Python/VC 运行时（`python311.dll`、`vcruntime*`、`msvcp140`、`ucrtbase`、`api-ms-win-*`）永不压，
否则 bootloader 起不来。**未签名 exe + UPX 更容易被杀软启发式误报**：分发给别人前，本机先双击验一次，
并按需考虑代码签名；只要原始字节就用 `-NoUpx`。

UPX 的代价与"启动快"直接冲突（每个 PE 在载入时要在内存里解压），所以体积与启动时间必须一起量：
同机同数据根、只差 UPX 开关，各测一次双击到 `/api/config` 返回 200 的毫秒数（见下面「验证构建」）。

如果依赖安装阶段在**非交互终端/后台任务**里停住而没有任何报错，先在同一台机器用交互式
PowerShell 执行 `desktop\.venv-build\Scripts\python.exe -m pip install --no-build-isolation -r desktop\requirements-runtime.txt`
（以及 `requirements-build.txt`），之后加 `-SkipInstall` 重新运行构建脚本。

构建环境是独立的 `desktop/.venv-build`，只安装 `requirements-runtime.txt` 和
`requirements-build.txt`: **不含** torch / transformers / sentence-transformers / pyarrow /
mitmproxy / pytest / ruff，因此这些包不会被 PyInstaller 收进发行包。`caixihui.spec` 再把
Matplotlib 的 GUI 后端、Selenium 的 Linux/macOS driver 等无用负载排掉；`prune_dist.py`
在构建后做一次保守的清理并报告释放了多少空间。

## 体积边界

**当前交付实测（同一台机、同一份源码，UPX 开，2026-10-26 三平台化轮重建 `build14`）**：
文件夹 **167.5 MB**、zip **125.2 MB**、安装包 `CaiXiHui-Setup.exe` **116.4 MB**（上一轮 164.8 / 124.0 / 115.4，
再往前 164.7 / 123.9 / 115.3；最早是 301.4 MB / 153.6 MB，而且那时根本产不出安装包——图标是张换了名字的 PNG，
Inno 直接拒绝编译）。拆开算：UPX 压 **268** 个二进制，`226.5 → 89.1 MB`（省 **137.3 MB**），0 跳过 0 失败。
**这轮 +2.7 MB 不是源码**：源码只加了几张按系统的表与文案（KB 量级），而 UPX 的输入体积只动了 0.1 MB——
差值来自 `-Clean` 重装构建环境时 pip 重新解析到的传递依赖版本（`tzdata` 2 MB、OpenBLAS/numpy/scipy 的补丁版本等）。
所以体积数必须与"哪一次重装"一起记：真要它可复现，就把 runtime 清单钉死到具体版本再重建。
**本轮新东西已随包**（都是真 exe 里读出来的，不是源码推断）：`workflow.js` 里的
`Capabilities.runnable` / `requirementWord` / `Machine.apply` / `CAPABILITY_REQUIREMENT_WORDS`、
`style.css` 的 `html[data-win-desktop="0"] .windows-only`、`index.html` 四行 `windows-only`、
`app.js` 双语的 `cap.requiresWindowsDesktop` 与 `validate.modeNeedsMachine`；
`/api/capabilities` 返回 `machine = {"windows_desktop": true}`（这台机就是 Windows 桌面），
红果评论模式 `requires = "windows_desktop"`、四个榜单模式 `requires = ""`；`/` 里没有任何 `cdn.` 且引用
`/vendor/echarts.min.js`（离线也能画图）。exe 旁 `tmp*` 残留 **0**（启动器自己扫掉了上一次留下的 1 个空目录），
验收后 `data/`、`logs/`、`mplconfig/`、`instance.json` 均已清掉。

> **这一节只按 Windows 验收。** `desktop/` 是本项目唯一故意只服务 Windows 的树；三平台分支本身
> （Chrome/xelatex 按系统查、中文字体栈与 ctex 字体集、进程清理、文件名字节上限、控制台编码、
> 桌面专属能力按名拒绝）在 `backend/` 里由**平台无关测试**覆盖，见 `docs/agent_practices.md`
> 「Cross-platform」一节与 `tests/unit/crawlers/test_platform_rules.py`。**Linux/macOS 上的真实启动没跑过**
> （本机无 Linux 运行时），那是要在服务器上补的一次实测，不是已通过。

**启动实测**（隔离数据根，`CIXI_NO_BROWSER=1` + exe 从终端跑，量到 `/api/config` 返回 200）：
本轮构建 **1547 ms**（上一轮 1863 / 1647 首启/再启，再前 1562，最早 3423 ms）。
UPX 是"载入时在每个进程内存里解压"，
理论上会拖慢启动，所以这两个数字必须和体积一起看；实测被自检挪后 + 少加载一整套 sklearn 的收益盖过，
相对最早的 301.4 MB / 3423 ms，**体积约 −44%、启动约 −55%**。换机器时这两条都要按下面「验证构建」
第 5、8 步重测（启动用同一隔离根，图标要和源图逐像素比——外壳读不出我们的图时会回落到默认图标并且照样 32×32）。

pandas/numpy/scipy/scikit-learn/matplotlib/snownlp/jieba 是包体的主要部分。以下能力被有意排除，以换取可接受的分发体积：

- **BERT 模型**：不放模型包时那三个节点按设计降级并打印实际方法；放法见下面「BERT 模型包」。
- **pyarrow / Parquet 导出**：按名拒绝，其它导出格式正常。
- **红果短剧评论采集**：需要 mitmproxy + uiautomation，按名拒绝；其它平台不受影响。
- **Ollama 与模型**：不在包内。运行中的 Ollama 会被启动自检识别；不装时仍可上传/清洗/分析/
  出图，需要模型的节点可改用 OpenRouter 或暂不使用。
- **MiKTeX / xelatex**：不在包内；只影响编译节点、图表 PDF 与论文成稿，其余功能正常。

`seed/models/*.pkl`（约 12 MB）与一个文献计量演示工作流会被复制到数据目录，作为首次体验；
已存在的用户文件永远不会被覆盖。

## BERT 模型包（可选，单独分发）

包里没有 torch/transformers，但**有 onnxruntime + tokenizers**，所以微调 BERT 能在打包版里真跑——
前提是把模型作为单独的压缩包放到应用旁边。四个模型即使按最小的"不掉判定"配方也是 780 MB，
把它们塞进应用本体只会让所有人都背这份字节，而大多数人不需要这三个节点。

生成（需要装有 torch 的开发机，产物目录 `ml_train/models/onnx/`）：

```powershell
.venv\Scripts\python.exe ml_train\scripts\export_onnx_bert.py                 # 默认 fp16，四个模型
.venv\Scripts\python.exe desktop\build_model_pack.py fp16 dist\CaiXiHui-bert-models-win64.zip `
    ml_train\models\onnx emotion_ewect_six sentiment_weibosenti_bin tendency_stance_v1 tendency_stance_v2_cyberbully
```

安装：**解压到应用目录**，使 `bert_models/` 与 `CaiXiHui.exe` 同级（每个模型是它下面的一个子目录）。
下次启动时启动器会扫描这些目录并把完整的那个登记进 `<数据根>/data/model_registry.json`，
所以放好模型包不需要重装应用。登记遵守三条：**只登记 `model.onnx`+`tokenizer.json`+`cixi_bert.json`
齐备的目录**（半成品会在面板里出现然后在运行时拒绝，那是更坏的答案）；**同名条目以用户已有的为准**，
只播报"保留了你的条目"；**注册表文件读不出来时绝不覆盖它**——那是用户自己命名的模型清单。

精度是实测选的，不是惯例（每个模型 120 条**带人工标注**的语料，走应用自己的加载器打分，
fp32 图与 torch 逐条判定完全一致，所以它是对照基准）：

| 配方 | 单模型体积 | 与 torch 判定一致率 | Δmacro-F1 | 结论 |
|---|---|---|---|---|
| fp32 | 390.3 MB | 1.0000 | 0.0000 | 基准 |
| **fp16（默认）** | **195.3 MB** | **1.0000** | **0.0000** | 发这个 |
| int8（逐张量） | 98.2 MB | 0.858–0.933 | −0.003…+0.039 | 判定会变，默认不发 |
| int8（逐通道） | 98.7 MB | 0.917–0.958 | −0.009…+0.027 | 仍超阈值 |
| int8 仅情感二分类 | 98.2 MB | 1.0000 | 0.0000 | 想要极限体积可单发 |

阈值就是用户定的那条：int8 掉点就退。`--precision int8|fp32|all` 仍可显式选择，导出脚本对每个目录
都跑一遍"同一批输入过 torch 与过图"的核对，偏差超限或**判定类别有任何一行不同**就按名拒绝该目录并删掉它，
不会留下一个看着像模型包的半成品。

CPU 吞吐实测（120 行、batch 8/16/32）：fp16 约 27–31 行/秒，int8 约 34–41 行/秒；开发机上有 GPU 时
走 torch 路径会更快——日志会写明这次是 **哪个运行时、什么精度**答的（`runtime=onnx precision=fp16`），
不会只留一个"BERT 已加载"。会话按 `(模型, 任务, 运行时)` 缓存续用，最多留两个，
淘汰时打印说明（一个 fp16 会话约 200 MB 常驻，多模型对照会点到四个）。

## 首次运行与依赖自检

启动器会在控制台打印：

- Python/依赖：已随包携带，无需安装；
- 界面资源（ECharts + GL + 词云、中国与世界第一级底图、界面字体）：已随包携带，**断网也画得出图**（见下节）；
- Chrome：采集节点需要，未找到时只提示，不阻止上传/分析；
- chromedriver：优先用 `drivers/chromedriver.exe`（放在 exe 同目录）或设置里指定的路径；
  都没有时留空，由 Selenium Manager 在首次采集时下载匹配版本（需要联网）；
- Ollama：探测的是**设置里那个地址**（以前硬探 127.0.0.1:11434，把指向别处的守护进程报成"未检测到"）；
- xelatex：用 `services/latex_compile.find_xelatex()` 的答案（与编译节点同一个查找），缺了只影响 PDF/成稿。

**定时任务在打包版里一样会到点执行**：`python app.py` 在它的 `__main__` 里启动调度时钟，而打包启动器是
`import app` 后自己跑 Flask——所以启动器现在调用同一个 `app.start_background_services()`（保留策略 + 排队恢复 +
时钟）。此前 EXE 里那三件都不做，定时任务面板会如实报「调度线程没有运行」。实测：`clock_running=true`，
1 分钟 interval 任务自己跑出一次 completed 运行，日志里有 `[监测]` 建档行。

**`.xls`（老式 OLE2 Excel）靠包内的 `xlrd` 才读得动**：`openpyxl` 只处理 `.xlsx`，而 WoS 的 Excel 按钮
给的就是 `.xls`。`xlrd` 在 `580fb15` 才写进 `desktop/requirements-runtime.txt`，所以**在那之前构建的交付包
读不了 `.xls`**（上传会得到一句 400「解析失败：缺引擎」，不是 500）；2026-10-25 之后的构建已经带上它——
重建产物实测用真实 `WOS.xls` 上传得到 30 条记录。`.xlsx` 不受影响。

`drivers/chromedriver.exe` 不会在构建时下载，因为正确版本取决于**最终用户**的 Chrome；如果要
离线交付，请让用户按其 Chrome 版本放入该文件，或在设置面板里指定路径。

**自检不挡启动**：那四项探测（Chrome、chromedriver、xelatex、设置里那个 Ollama 地址）
以前夹在"选好端口"和"绑定端口"之间，冷盘上是几秒的空等窗口；现在它们在绑定之后的一条守护线程里跑，
五行文字逐字不变，但改成**一次写出**（Flask 的启动行会从另一个线程落在同一个控制台，分五次写会被劈开）。
探测本身抛异常时打印一条"依赖自检未能完成：…"，不会让四行文字静默消失——那看起来跟"检查过且都 healthy"
一模一样。喂给 `config.DRIVER_PATH` 的驱动查找仍然同步，因为服务需要那个答案。
四项探测现在**只有实现的一份**：Chrome 与 Ollama 走 `backend/core/machine.py`，xelatex 走
`services/latex_compile.find_xelatex()`。启动器原来自己抄了一份 Chrome 候选目录、一份 MiKTeX 扫描和
一个写死的 11434——两份意见的坏处不是多几行代码，是同一台机器上"自检说没有"与"节点说能跑"同时出现。

## 离线可用：前端资源为什么进了仓库

应用包过去在页面里引四个 CDN：ECharts 与其 GL / 词云扩展（jsdmirror）、界面字体 Literata（Google Fonts）、
中国省级底图（DataV.GeoAtlas）。后果不是"少个字体"，而是**断网的机器图区一片空白**——`echarts` 没定义时
产品只是画不出东西，面板上没有任何一句话解释为什么。`tools/vendor_frontend_assets.py` 把这些东西取回并写进
`backend/static/vendor/`（+ `backend/static/geo/china.json`），页面从此只向本站要文件：

| 文件 | 来源 | 许可 |
| --- | --- | --- |
| `vendor/echarts.min.js` | npm `echarts@5.4.3` | Apache-2.0（banner 在文件头） |
| `vendor/echarts-gl.min.js` + `LICENSE.echarts-gl.txt` | npm `echarts-gl@2.0.9` | BSD-3-Clause（Baidu） |
| `vendor/echarts-wordcloud.min.js` | npm `echarts-wordcloud@2.1.0` | ISC |
| `vendor/fonts/literata.css` + 14 个 `.woff2` | Google Fonts 的 css2（含 7 个子集，去重按 URL） | SIL OFL 1.1 |
| `geo/china.json` | DataV.GeoAtlas `100000_full.json`，**逐字节保留** | 行政区划数据；34 省级 + 九段线要素 |
| `geo/world.json` | Natural Earth 1:110m（`tools/build_world_geojson.py` 派生） | public domain |

三条刻意的规矩：

1. **每个文件钉 SHA-256**（写在工具里，`tests/unit/gates/test_vendored_assets.py` 复核）。第三方改了
   我们分发出去的字节，应当是一次有 diff 的复核，不是构建时的意外；工具遇到不匹配会打印它看到的哈希
   并拒绝覆盖。升级 = 同时改 URL 与 `sha256`，然后 `python tools/vendor_frontend_assets.py`。
2. **底图要过内容断言，不只是"能解析"**：中国那份必须仍有 34 个省级要素、含台湾/香港/澳门与
   `100000_JD` 九段线要素——少一个省照样能画图，那是事实错误而不是渲染错误。
3. **字体按 (style, subset) 去重**：Google 的 css2 会为 5 个字重重复声明同一个 woff2 文件；
   第一版按 `@font-face` 块命名，结果 42 个文件 2 MB 装的是 14 个文件 556 KB 的内容。工具会清掉
   自己的孤儿文件，测试断言"磁盘上的 = CSS 引用的"，因为打包是整目录拷贝，没人引用的字体也照样发出去。

`--check` 参数不联网，只核对磁盘上的字节与上面这些不变量（`python tools/vendor_frontend_assets.py --check`）。

## 数据与便携模式

- 默认数据根：`%APPDATA%\CaiXiHui`（`data/`、`logs/`、`mplconfig/` 都在这里）。
- 便携模式：在 `CaiXiHui.exe` 同目录放一个空的 `portable.txt`，数据根改为 exe 所在文件夹。
  适合 U 盘或不想写 AppData 的用户；请确保该文件夹可写。
- 环境变量 `CRAWLER_DATA_ROOT` 仍可覆盖（测试/高级部署）——**但它不参与下面的回退**：这个变量表达的
  是「我要一份隔离的数据」，写不进去就按名拒绝启动。悄悄改用共享的 AppData 根会让一次冒烟运行把用户
  正在跑的运行判为过期并结算掉。
- **写不进去时会自动换**，顺序是：`portable.txt`（exe 目录）→ **已经装着 `data/` 的那个目录** →
  `%APPDATA%\CaiXiHui` → `%LOCALAPPDATA%\CaiXiHui` → exe 所在文件夹。
  换位置一定在控制台点名被拒的目录和系统给的原因，绝不静默搬家——否则用户找不到自己的数据。
  「已有 `data/` 者优先」是让回退**留在原地**：只生效一次的回退，会在被拦的目录某天又能写时
  把用户带回一个空画布。杀软/受控文件夹访问拦掉 Roaming 写入是真实场景，不是假设。
- 同一数据根只允许一个实例（互斥量名带该数据根的哈希）：重复双击会直接打开已有窗口，而不是启动第二个
  服务器；**不同数据根可以各开一份**——装在 `%APPDATA%` 的那份与 U 盘里的便携份互不阻挡（此前互斥量名
  不分数据根，便携副本会被安装副本挡下，而它自己在的位置又没有地址记录，于是只剩一次闪窗）。
- 找到已在运行的实例就把它的地址交给浏览器；**找不到地址记录时是弹窗点名**（数据根写在消息里），
  不是往即将关闭的控制台打一行字。

## 启动失败时会看到什么

控制台窗口随进程一起消失，所以"闪一下就没了"等于没有报错。因此：

- 数据根一个都写不进去、端口全被占用、配置或应用模块加载失败、服务异常退出、以及任何没预料到的异常
  （`__main__` 兜 `BaseException`）——都会**弹一个 Windows 对话框**写出原因（对话框是阻塞的，窗口不会再
  自己关掉），同时把完整 traceback 追加写入 `startup_error.log`，落点依次是
  `<数据根>/logs` → `%APPDATA%\CaiXiHui` → `%LOCALAPPDATA%\CaiXiHui` → exe 目录 → 临时目录；
- **先落盘、先弹窗，最后才打印**：重定向的控制台在非中文代码页上遇到第一个汉字就抛
  `UnicodeEncodeError`，把打印排在前面等于让报告在最该出东西的地方断掉。打印本身也走
  `_print_safe`（失败时退回写字节流，绝不拿同一个坏流重试）；
- 弹窗里只放短句，traceback 只进控制台与日志文件（Windows 消息框不能滚动长文本）；
- 弹窗自己弹不出来时（无窗口站、服务会话）会在控制台说明「弹窗没能显示」，不静默吞掉；
- 首次示例文件/模型复制失败不会阻止启动，只点名说明。

## 受限终端里构建（本仓库实测）

`build_windows.ps1` 会把 pip 的临时目录指到 `build/tmp` 并加 `--no-cache-dir`。原因是实测到的
一个环境坑：pip 默认解包到 `%TEMP%`、缓存在 `%LOCALAPPDATA%\pip`，**受限工作区会拒绝这两处写入**，
症状是打印完 `Looking in indexes` 就再也不返回（网络本身是通的，索引 1.5s 返回 200）。
手工装依赖时用同一条规则：

```powershell
$env:TMP = "$PWD\build\tmp"; $env:TEMP = "$PWD\build\tmp"
desktop\.venv-build\Scripts\python.exe -m pip install --no-cache-dir --no-build-isolation -r desktop\requirements-runtime.txt
```

## 验证构建

构建脚本不会自动跑爬虫。发布前至少确认（**必须真的双击**，`CIXI_NO_BROWSER=1` + 指定
`CRAWLER_DATA_ROOT` 恰好绕过了唯一真正会失败的那条路径）：

1. 双击 `CaiXiHui.exe`，浏览器打开 `http://127.0.0.1:5000/`（端口被占用会自动顺延）；
2. 首页、`/api/config`、`/api/workflow/list`、`/api/data/datasets`、`/api/runs/list` 返回 200；
3. 打开文献计量演示工作流，能看到画布；上传 `samples/` 中的 CNKI 样例可跑通；
4. 设置页显示 chromedriver/Ollama 状态；不装 Chrome 时上传/分析仍可用；
5. **量一次启动**：从进程起来到 `/api/config` 返回 200 的毫秒数，UPX 开与关各测一次（同一台机、
   同一数据根），两个数字都要写进发布说明——只报体积就是拿启动换 KPI；
6. **放了模型包就跑一次三个 bert 节点**（情感/情绪/倾向），确认控制台打印的是
   `runtime=onnx precision=fp16`，且降级那条线仍然可用：把模型包临时改名，同一节点应打印它降级到了
   ml/snownlp——两句话都要看见，才算「打包版真跑 BERT」和「没模型也不骗人」都成立；
7. 瘦身分发物里的死数据文件确实没被读到：`snownlp` 的**情感回退**在裁掉 py2 marshal 与训练语料之后
   仍要能出分（`sentiment.marshal.3` 才是 Python 3 读的那份）；
8. **确认外壳真读得出**我们**的图标**：PyInstaller 拷无效图标时不报错（它照样打印 `Copying icon to EXE`），
   而 `ExtractAssociatedIcon` 对无效资源会**回落到系统默认图标且同样返回 32x32**，所以"没抛异常"不是证据。
   把外壳画出来的 32×32 存成 PNG，与 `backend/static/icon.png` 比平均色与逐像素差（本机实测两者差 **0.0154**，
    ASCII 亮度图肉眼同形）：
   `powershell -Command "Add-Type -AssemblyName System.Drawing; $i=[System.Drawing.Icon]::ExtractAssociatedIcon('dist\CaiXiHui\CaiXiHui.exe'); $b=New-Object System.Drawing.Bitmap 32,32; $g=[System.Drawing.Graphics]::FromImage($b); $g.Clear([System.Drawing.Color]::White); $g.DrawIcon($i,0,0); $b.Save('build\tmp\exe_icon.png',[System.Drawing.Imaging.ImageFormat]::Png)"`。
   同一个量法也用在 `CaiXiHui-Setup.exe` 上。生成的 ICO 七档画框是 PNG 压缩的（Pillow 默认），
   Win10/11 的 GDI 解得开——这一点上面那两次取样就是证据，不是推测。
9. **确认它真的不联网也能画图**：`python tools/vendor_frontend_assets.py --check`（不取网络，只核对
   入库字节与底图内容断言），再加真浏览器用例
   `pytest -q -m integration tests/integration/test_ui_layout.py::test_the_shipped_page_draws_its_figures_without_asking_anything_off_this_machine`
   ——它读 `performance.getEntriesByType('resource')`，凡是 origin 不是本站的就失败，并核对中国与世界
   底图都注册成功、Literata 字体状态是 loaded。这一步值得单独跑：CDN 依赖的失败形状是**空白图区**，
   不看资源清单就没人知道自己已经断网了。

**验收双击会往交付目录里写真数据**（`data/`、`logs/`、`mplconfig/`、`instance.json`），而 zip 与安装脚本
打包的就是这个目录——`prune_dist.py` 在压缩前把这些一律清掉（`portable.txt` 与 `drivers/` 是用户的选择，
保留）。发布前再核一次压缩包里没有顶层 `CaiXiHui/data/`：那里可能有维护者的 `runs.db` 和
`data/cookies/*`（一个已登录账号的第二台设备）。

构建脚本只负责打包，不修改源码；源码测试仍以仓库根目录的 `pytest` 为准。
