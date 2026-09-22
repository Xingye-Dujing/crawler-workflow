# 采析绘（数据的采集、分析与可视化）

一个基于 Flask + Selenium + LLM (Ollama / OpenRouter) + scikit-learn 的多平台数据采集、数据清洗、
情感分析、通用数据分析与可视化工作流系统，内置**断点续跑**与运行记录管理：任务中断后可从检查点继续，
已花费的采集与 LLM 成本不会重复支付。

## 功能特性

### 数据采集
- **多平台爬虫**：支持知乎、微博、小红书、微信公众号的数据采集
- **评论采集**：数据源节点把「采集内容」切到**评论**，粘贴所选平台的文章链接（一行一个）即可批量抓评论；
  知乎/微博/小红书/微信各自只认本平台链接——面板样例、画布预检、引擎校验、抓取时过滤四层一致拒收外站链接，
  全部不符则报「与所选平台不符」可执行错误；
  可选每篇一个文件或合并输出；无评论/被登录墙拦截/链接失效三种状态分开上报，绝不静默吞成"空结果"
  （独立 Comment 节点仍保留，兼容旧画布，引擎共用，支持多平台混合粘贴）。
  **微信判据（实测后确定）**：浏览器会话既取不到留言、也看不到点赞/转发数字，而"这篇没数据"与
  "这次没进去"在页面上长得一样。因此微信评论节点只在**数字可见而留言区为空**时才报"该文无留言"，
  两者皆缺时一律报「没有正确进入」而不是 0 行成功
- **分批输出（不必等运行结束）**：采集节点可设「分批大小」，每满 N 行先落一个带编号的分片文件，
  运行中即可打开查看，节点结束时合并为单个文件（合并后是否保留分片可设置）；LLM 处理节点可勾选
  「实时导出」，每处理完一批就原子重写一份 `{节点}.live` 快照，随时打开都是当前完整结果
- **Cookie 管理**：持久化登录状态，避免重复扫码；扫码生成为后台单飞任务——登录期间设置面板保持打开，
  提供「已完成登录 / 取消登录」按钮，窗口被关闭会自动判错回收；全过程进控制台日志。
  面板现在按平台**说明用途与获取步骤**（由 `/api/cookies/flow` 提供，中英双语），并可粘贴
  「登录入口链接」——只接受该平台域名，越界链接会明确告知改用平台登录页，绝不把别站的 Cookie
  存进本平台文件。另有**「验证 Cookie」**：带已存 Cookie 实地访问一次，把结论逐条回显到面板，
  而不是让用户靠"抓出来 0 行"去猜 Cookie 是不是废了
- **微信 Cookie 与留言的可得性（实测结论）**：
  **按关键词搜索文章**只有 `mp.weixin.qq.com` **公众号后台**登录态这一条路（搜狗微信搜索一访问即被
  `antispider` 验证码拦截，机器无法自行通过）。
  **推文留言**：服务端只在认得是微信客户端会话时才下发留言凭证与 `show_comment` 开关；
  实测普通浏览器里文章 HTML（3.4 MB）中 `elected_comment` 出现 0 次、`show_comment=0`，
  留言接口回一段 2034 字节的验证页「请在微信客户端打开链接」。
  因此本项目**不做客户端伪装**去绕过该判定，改为把判据写清：
  有留言内容 → 正常返回；无留言但点赞/转发数字可见 → 报"该文无留言"；
  两者皆缺 → 报「没有正确进入」，绝不用 0 行冒充可用数据
  （`tests/live_site/test_live_wechat.py::TestCommentRefusal` 与 `tests/unit/test_wechat_comments.py::TestCrawl` 钉住）。
  抓取**自己公众号**文章的留言属平台允许的自有数据，如需要可在此路径上扩展。
- **微博"假登录墙"免疫**：微博搜索会先把浏览器闪到扫码页再弹回已登录结果流（站点设置的假象）；
  爬虫会等待页面进入终态（渲染出卡片 / 明确无结果 / 持续停留在登录页）后才判定登录墙，
  真掉线时照常明确报错，已采数据不受影响
- **运行时浏览器设置**：chromedriver 路径、浏览器二进制、窗口尺寸、超时等可在设置面板修改，
  写入 `data/settings.json`，下次运行即生效，无需改代码重启

### AI 分析
- **双 AI 提供方**：本地 Ollama 或 OpenRouter API（免费模型列表一键拉取、连接测试），
  模型选择、批量保存行数、截断长度均可在 AI 面板配置；OpenRouter Key 仅存浏览器 localStorage，不落服务器
- **情感分析（双模式）**：LLM 逐行深度分析，或传统 ML（sklearn TF-IDF + 逻辑回归）批量高速推理，随时切换
- **倾向性分析（双模式）**：同上，LLM 或 ML 可选
- **语义数据清洗**：自动过滤广告、无关内容与低质量数据（LLM 判定）
- **关键词提取**：TF-IDF / TextRank（依赖 jieba）
- **文本聚类**：K-Means / DBSCAN 自动发现文本分组
- **命名实体识别**：正则规则式中文 NER（人名/机构/地名/日期，零依赖）
- **异常检测**：Isolation Forest 自动标记数值异常行
- **相关性分析**：Pearson / Spearman / Kendall 相关系数矩阵
- **模型训练**：从已有 LLM 标注数据一键训练传统 ML 模型，后续推理无需 Ollama

### 数据处理
- **通用数据分析节点**：去空值、去重、条件筛选、重命名列、类型转换、排序、采样、分组聚合、
  表关联、列计算、数值分箱等确定性清洗，可独立于爬虫直接处理任意表格数据
- **分词节点**：jieba 对任意文本列分词，输出词频对，供导出或词云使用
- **文件持久化**：上传/粘贴的文件注册为数据集（内容哈希寻址、zlib 压缩存库），
  保存的工作流随时可重新加载自己的输入文件；无引用且长期未用的文件自动清理
- **通用导出节点**：一个节点支持导出 CSV / JSON / Excel / TXT / HTML / Markdown 六种格式

### 可视化
- **通用可视化节点**：柱状图 / 折线图 / 饼图 / 散点图 / 直方图 / 箱线图 / 热力图 / 桑基图 /
  词云（支持中文分词）/ 中国地图，支持 ECharts（前端渲染）与 Matplotlib（服务端渲染）两种引擎
- **Chart Studio 图表工作台**：画布内嵌 ZENVIZ 工作台，可对任意节点/数据集的完整表格做自由图表创作，
  支持多数据源合并，成品 PNG 可保存回导出目录
- **数据预览面板**：任意数据集都能以可翻页的表格形式查看真实数据行
- **仪表盘看板**：把画布上所有 Visualize 节点的图表拼在一个网格里一起查看
- **实时统计**：ECharts 图表展示情感/倾向性分布与执行汇总

### 工作流引擎
- **工作流画布**：拖拽式节点编辑，可视化配置采集/清洗/分析/可视化全流程
- **工作流命名**：保存时可命名（画布 Name 节点即工作流名），历史与运行记录按名称归组
- **多线程执行**：支持并行/串行执行模式，可随时停止；进程管理面板可强杀残留浏览器进程
- **撤销/重做**：Ctrl+Z / Ctrl+Y 支持 50 步历史回退，菜单和右键菜单均有入口
- **节点重命名**：双击节点标题（或右键→重命名）即可命名节点；控制台与校验信息以「名称 #节点号」
  播报、工作流前缀显示工作流名（不再是 WF0/WF1），一眼对上画布上哪个节点在说话；跳过的节点不再
  谎报"完成"；自定义名在保存/加载、撤销重做、切换语言后都保留，清空即恢复类型默认名
- **节点折叠**：选中节点按 F 键或右键折叠，节省画布空间
- **自动布局**：按 DAG 层级 BFS 自动排列所有节点
- **节点颜色编码**：节点库按 工作流 / 数据输入 / 数据处理 / 结果输出 四组排列，各节点有独立颜色与标识
  （NAM/SRC/CMT/UPL/RSM/PRC/ANL/TKN/VIZ/OUT）

### 断点续跑与运行记录
- **节点级检查点**：每步输出行持久化到 `data/runs.db`，工作流结构指纹 + 节点指纹决定哪些结果
  可复用、哪些因参数改动而失效重算
- **LLM 答案缓存**：按 操作+提供方+模型+列+截断+主机+主题+提示词版本 缓存回答，重跑或续跑不再为
  同一行付费；改了提示词模板或参数，旧答案自动失效，绝不"新提示词吃旧结果"
- **采集去重指纹（增量采集）**：已抓到的条目指纹按节点入库，续跑/重跑自动跳过已采集内容并在控制台
  明示跳过数；采集节点可勾选「重新采集」清除账本全量重抓
- **中断自动识别**：服务重启后遗留的"运行中"记录自动标记为"已中断"，画布顶部出现续跑横幅，
  一键「继续」或「重新开始」
- **Cookie 中途过期可续跑**：长采集常跑到一半 Cookie 失效被挡回登录墙——已抓的行早已落库，
  节点判为"部分完成"、整条运行标为失败进入续跑横幅；浏览器弹 toast + 控制台明示「更新 Cookie 后继续」，
  换新 Cookie 点「继续」即从断点接着抓、绝不重复已存条目；恰好在目标达成后才撞墙则视为完整，不误报
- **执行前 Cookie 确认（可关）**：含采集/评论节点的工作流运行前弹框提醒「Cookie 是否久未更新，
  先退出更新还是继续执行？」，退出即取消本次执行；默认开启，可在设置面板关闭（关闭后行为与从前一致直接执行）
- **Resume 节点**：直接收养历史运行的节点输出作为数据源——原始平台已登出/被封/已花过成本时使用
- **运行记录面板**：列出各工作流的运行历史、节点状态、行数统计，支持丢弃、删除与按保留策略清理
- **执行历史与趋势对比**：自动记录情感/倾向性分布与各节点行数，可按工作流和指标画出时间序列
- **保留策略**：每工作流默认保留最近 20 次运行、30 天内的记录；干净完成的先清理，
  中断的最后清理（还可能被续跑）；单节点行数与单文件行数均有硬上限防止撑爆磁盘。
  策略**自动生效**：服务启动时清一次，此后每次运行结束按时间闸（默认 60 分钟）再清，
  不必记得手动点「清理」；清理只删真正过期/孤立的条目，正在写的运行记录永远豁免
- **运行日志自动轮转**：`logs/app.log` 写满 5 MB 滚动为 `app.log.1 … app.log.5`，
  长时间抓取不会把日志撑到无法打开（上限与份数在 `config.py` 可调）

### 界面
- **中英双语**：前后端消息全套 i18n 目录，界面一键切换语言，日志按请求语言输出
- **亮色主题**：设计系统化的浅色界面，网格背景画布，主题色/圆角可调

## 快速开始

### 1. 环境要求

- Python 3.11+（使用 `zip(..., strict=True)`）
- Chrome 浏览器（Selenium 驱动，驱动路径可在设置面板修改）
- [Ollama](https://ollama.ai/) 本地大模型，或 OpenRouter API Key（二选一即可）
- 如需 Matplotlib 引擎渲染中文图表，服务器需安装中文字体
  （如 `fonts-wqy-microhei` / SimHei / Microsoft YaHei 任一即可，
  Linux 下可 `apt install fonts-wqy-microhei`）

### 2. 创建虚拟环境并安装依赖

> 所有运行与安装一律在项目虚拟环境 `.venv/` 中进行，勿使用系统 Python。

```bash
cd crawler_workflow
python -m venv .venv
source .venv/Scripts/activate        # Windows Git Bash；cmd 下用 .venv\Scripts\activate
pip install -r requirements.txt
```

### 3. 下载 Ollama 模型（可选，用 OpenRouter 可跳过）

```bash
ollama pull qwen3.5:9b
```

### 4. 启动应用

```bash
cd backend
python app.py
```

访问 http://127.0.0.1:5000（端口通过环境变量 `PORT` 修改，监听地址通过 `HOST` 修改）。默认只监听本机、
且不自动开浏览器；开发时用 `FLASK_DEBUG=1` 打开调试模式（含自动打开浏览器与代码热重载）。

## 项目结构

```
crawler_workflow/
├── backend/
│   ├── app.py                    # Flask 主入口（路由 + 执行编排）
│   ├── config.py                 # 配置与数据路径
│   ├── i18n.py                   # zh/en 消息目录（X-Lang 请求头切换）
│   ├── settings_store.py         # 运行时可改设置（data/settings.json）
│   ├── crawlers/                 # 爬虫模块
│   │   ├── base.py               # 爬虫基类
│   │   ├── zhihu.py              # 知乎爬虫
│   │   ├── weibo.py              # 微博爬虫
│   │   ├── xiaohongshu.py        # 小红书爬虫
│   │   └── wechat.py             # 微信公众号爬虫
│   ├── analyzers/                # 分析模块（LLM + ML 双模式）
│   │   ├── ml_base.py            # 传统 ML 底座（TF-IDF + 分类器）
│   │   ├── llm_client.py         # Ollama / OpenRouter 客户端
│   │   ├── cleaner.py            # 广告/噪声语义清洗（LLM）
│   │   ├── emotion.py            # 情感分类（LLM + ML 可选）
│   │   ├── tendency.py           # 倾向性分析（LLM + ML 可选）
│   │   ├── keyword.py            # 关键词提取（TF-IDF / TextRank）
│   │   ├── clustering.py         # 文本聚类（K-Means / DBSCAN）
│   │   ├── ner.py                # 命名实体识别（正则规则）
│   │   ├── anomaly.py            # 异常检测（Isolation Forest）
│   │   └── correlation.py        # 相关性分析（Pearson / Spearman / Kendall）
│   ├── engine/                   # 工作流引擎
│   │   ├── workflow.py           # DAG 解析、调度、节点校验与指纹
│   │   ├── executor.py           # 线程池执行器
│   │   └── logger.py             # 日志管理
│   ├── services/                 # 服务模块
│   │   ├── run_store.py          # 断点续跑核心：运行/节点/行/指纹/LLM缓存（runs.db）
│   │   ├── dataset_store.py      # 上传文件持久化与工作流引用（datasets.db）
│   │   ├── stats.py              # 情感/倾向性统计服务
│   │   ├── cookie_manager.py     # Cookie 管理
│   │   ├── cookie_flow.py        # 各平台 Cookie 的用途/获取步骤/入口链接白名单
│   │   ├── workflow_manager.py   # 工作流持久化
│   │   ├── exporter.py           # 通用多格式导出服务（Output 节点）
│   │   ├── data_analysis.py      # 通用数据清洗服务（Analysis 节点）
│   │   ├── visualizer.py         # 通用可视化服务（Visualize 节点）
│   │   └── execution_history.py  # 执行历史记录（history.db）
│   ├── utils/
│   │   └── helpers.py            # 工具函数
│   └── static/                   # 前端静态文件
│       ├── index.html
│       ├── css/style.css
│       └── js/
│           ├── app.js            # 入口（i18n fetch 注入、节点库）
│           ├── canvas.js         # 画布与节点渲染
│           ├── workflow.js       # 执行、文件管理、全部对话框
│           ├── menu.js           # 顶栏菜单状态
│           ├── stats.js          # 情感/倾向性 ECharts 统计
│           ├── custom-select.js  # 主题化下拉组件
│           ├── zenviz.js         # 内嵌 Chart Studio 图表库
│           └── zenviz-bridge.js  # Studio 与画布的数据桥接
├── data/                         # 运行时数据（gitignore）
│   ├── runs.db                   # 断点续跑状态（节点行/指纹/LLM缓存）
│   ├── datasets.db               # 持久化的上传数据集与引用
│   ├── history.db                # 执行历史与趋势
│   ├── settings.json             # 运行时设置（驱动路径等）
│   ├── cookies/                  # 平台 Cookie
│   ├── exports/                  # 导出数据
│   ├── workflows/                # 工作流配置
│   ├── checkpoints/              # LLM 逐行检查点（runs.db 不可用时的兜底）
│   └── models/                   # 训练好的 ML 模型
├── logs/
├── requirements.txt
└── README.md
```

## 节点类型

| 节点 | 标识 | 说明 | 能否独立运行 |
|------|------|------|------|
| Name（命名） | NAM | 工作流元数据，其标签作为工作流名供历史/运行记录归组 | 是（纯元数据） |
| Data Source（数据源） | SRC | 从知乎/微博/小红书/微信采集数据；「采集内容」切到**评论**即变为评论采集器 | 是，需平台+关键词（或评论链接） |
| Upload（上传） | UPL | 从持久化数据集中读取 CSV/JSON 作为输入 | 是 |
| Process（处理） | PRC | LLM 语义清洗 / 情感(LLM/ML) / 倾向(LLM/ML) / 关键词 / 聚类 / NER / 异常 / 相关性 | 否，需要上游文本数据 |
| Analysis（分析） | ANL | 确定性数据清洗：去空/去重/筛选/改名/类型转换/排序/采样/分组聚合/表关联/列计算/分箱 | **是**，可直接处理数据集 |
| Visualize（可视化） | VIZ | 柱状/折线/饼图/散点/直方/箱线/热力/桑基/词云/地图，ECharts 或 Matplotlib | **是**，可直接处理数据集 |
| Tokenize（分词） | TKN | jieba 分词输出词频，供导出或词云使用 | 否，需要上游数据 |
| Output（保存） | OUT | 导出为 CSV / JSON / Excel / TXT / HTML / Markdown | 否，需要上游数据 |
| Resume（续跑） | RSM | 收养历史运行的节点输出作为数据源（原上游不可用/已付费时） | 是 |
| Comment（评论采集） | CMT | 评论采集引擎（现为数据源的「采集内容=评论」模式）；独立节点仅保留给旧画布 | 是 |

## API 参考

### 工作流

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/workflow/save` | POST | 保存工作流配置（含命名） |
| `/api/workflow/load` | GET | 加载指定工作流 |
| `/api/workflow/list` | GET | 列出所有已保存工作流 |
| `/api/workflow/delete` | POST | 删除工作流 |
| `/api/workflow/execute` | POST | 执行工作流 |
| `/api/workflow/stop` | POST | 停止执行 |
| `/api/workflow/status` | GET | 获取执行状态 |
| `/api/workflow/processes` | GET | 列出执行器/浏览器子进程 |
| `/api/workflow/processes/kill` | POST | 强杀残留进程 |

### 运行记录 / 断点续跑

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/runs/resumable` | POST | 查询指定工作流最近一次可续跑的中断运行 |
| `/api/runs/list` | GET | 分页列出运行记录 |
| `/api/runs/status` | GET | 单条运行的节点级状态 |
| `/api/runs/stats` | GET | 全局运行统计 |
| `/api/runs/purge` | POST | 按保留策略清理旧运行（中断的最后清理） |
| `/api/runs/discard` | POST | 丢弃一次中断运行（不再提供续跑） |
| `/api/runs/delete` | POST | 删除指定运行 |
| `/api/runs/<run_id>` | GET | 运行详情（含节点行数据摘要） |

### 数据与数据集

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/data/upload` | POST | 上传 CSV/JSON 文件，注册为持久化数据集 |
| `/api/data/paste` | POST | 将粘贴的 JSON 数组注册为数据集 |
| `/api/data/datasets` | GET | 列出已注册数据集 |
| `/api/data/datasets/<id>` | GET / DELETE | 查看 / 删除单个数据集 |
| `/api/data/inspect` | POST | 查看数据集的空值/类型/重复行统计 |
| `/api/data/preview` | POST | 分页查看数据集的原始表格（数据预览面板） |
| `/api/data/clear` | POST | 清空内存中的数据集缓存 |

### 分析 / 可视化 / 导出（独立于工作流，可单独调用）

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/analysis/run` | POST | 对数据集执行清洗流水线，返回新数据集 id 及报告 |
| `/api/analysis/train` | POST | 从已有 LLM 标注数据集训练传统 ML 模型（情感/倾向） |
| `/api/visualize/render` | POST | 对数据集渲染图表，返回 ECharts option 或 Matplotlib 图片 |
| `/api/export/save` | POST | 将数据集导出为指定格式文件 |

### Chart Studio

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/studio/dataset` | POST | 把画布任意节点/数据集的完整表格交给 Studio（支持多源合并） |
| `/api/studio/sources` | POST | 预检哪些节点当前有可用的表格数据 |
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

### AI / Cookie / 系统

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/llm/models` | GET | 拉取 OpenRouter 免费模型列表 |
| `/api/llm/ollama/models` | GET | 列出本地 Ollama 已拉取模型 |
| `/api/llm/test` | POST | 测试所选提供方的连通性 |
| `/api/cookies/status` | GET | 各平台 Cookie 是否存在 |
| `/api/cookies/flow` | GET | 每个平台 Cookie 的用途、获取步骤、默认登录页与可接受域名（Cookie 面板据此渲染） |
| `/api/cookies/save` | POST | 保存指定平台 Cookie |
| `/api/cookies/generate` | POST | 打开浏览器引导扫码登录并捕获 Cookie；可选 `url` 指定入口链接（仅限该平台域名） |
| `/api/cookies/verify` | POST | 用已存 Cookie 实地探测该平台还放行什么（微信分报「后台可搜索」与「评论凭证是否下发」） |
| `/api/settings` | GET / POST | 读取 / 修改运行时设置（data/settings.json） |
| `/api/config` | GET | 系统配置 |

## 使用示例

### 1. 从画布创建完整工作流

1. 从左侧节点库拖拽 "Data Source" 到画布
2. 双击节点打开设置面板，选择平台和关键词
3. 添加 Process 节点 (Clean / Emotion / Tendency)，在 AI 面板选好提供方与模型
4. 添加 Analysis 节点做进一步的确定性清洗（如去空值、去重）
5. 添加 Tokenize 节点产出词频（可选，供词云/导出使用）
6. 添加 Output 节点选择导出格式，并添加 Visualize 节点查看分布
7. 拖拽连线连接节点，加一个 Name 节点命名工作流
8. 点击菜单 "Execute" 运行

### 2. 独立使用 Analysis / Visualize 节点（不采集，只处理已有数据）

1. 直接在画布上拖一个 Visualize（或 Analysis）节点，不连任何上游节点
2. 打开节点设置，把 "Data Source" 改成 "Upload File"，上传一份 CSV/JSON
3. 配置图表类型 / X、Y 字段后点击 "Preview Chart" 即可在右侧预览面板看到结果，
   不需要跑整个工作流；上传的文件会持久化，下次打开这个工作流还能用

### 3. 中断后续跑（断点续跑）

1. 执行中点击 Stop、直接关服务、或爬虫/LLM 中途失败——都没关系，
   已完成的节点和已处理的行都记录在 `data/runs.db`
2. 重新打开该工作流，画布顶部出现"检测到中断的运行"横幅
3. 点「继续」：未变化的节点直接复用检查点（LLM 结果走缓存不重付费），
   只重跑缺失部分；改了某节点参数则该节点及其下游自动失效重算
4. 点「重新开始」则忽略检查点全量重跑；不想要这次续跑可在运行记录面板「丢弃」

### 4. 用 Resume 节点接管旧运行的数据

原平台已登出/风控、或那批数据已经花过 LLM 成本时：拖入 Resume 节点，
选择某次历史运行及其节点，它的输出行就直接成为当前工作流的输入。

## 配置

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OLLAMA_MODEL` | Ollama 模型名 | `qwen3.5:9b` |
| `OLLAMA_HOST` | Ollama 服务地址 | `http://localhost:11434` |
| `SECRET_KEY` | Flask 会话密钥 | `crawler-workflow-secret-key` |
| `PORT` | 服务端口 | `5000` |
| `HOST` | 监听地址（默认只监听本机，局域网内其他机器访问需设为 `0.0.0.0`） | `127.0.0.1` |
| `FLASK_DEBUG` | 调试模式（`1`/`true`/`yes` 开启；含热重载与自动打开浏览器，调试器可执行任意代码，勿在他人可达的机器上开启） | 关闭 |
| `MAX_UPLOAD_MB` | 单个请求体上限（上传/粘贴数据过大时返回 413 JSON，而非把整机内存吃光） | `64` |

### 运行时设置（UI 设置面板 → `data/settings.json`）

| 键 | 说明 |
|------|------|
| `driver_path` | chromedriver 路径（覆盖 config.py 默认值） |
| `browser_binary` | Chrome 二进制路径 |
| `window_size` | 浏览器窗口尺寸 |
| `page_load_timeout` / `element_timeout` | 页面/元素超时（秒） |
| `ollama_host` | Ollama 地址（覆盖环境变量） |

### 保留策略常量（`backend/config.py`）

| 常量 | 说明 | 默认值 |
|------|------|--------|
| `RUN_KEEP_PER_WORKFLOW` | 每个工作流保留最近 N 次运行 | `20` |
| `RUN_KEEP_DAYS` | 运行记录最长保留天数 | `30` |
| `RUN_MAX_ROWS_PER_NODE` | 单节点持久化行数硬上限 | `500000` |
| `DATASET_MAX_ROWS` | 单个上传文件行数上限 | `300000` |
| `DATASET_KEEP_DAYS` | 无引用文件的清理天数 | `90` |
| `HOUSEKEEPING_INTERVAL_MINUTES` | 自动执行上述保留策略的时间闸（启动必清一次，之后每过此时长在运行结束时清） | `60` |
| `LOG_MAX_BYTES` | 单个日志文件上限，超出即滚动 | `5242880`（5 MiB） |
| `LOG_BACKUP_COUNT` | 保留多少个历史日志（`app.log.1 … .N`） | `5` |

## 训练传统 ML 模型

情感分析和倾向性分析支持传统 ML 模式（sklearn TF-IDF + 逻辑回归），需要先用 LLM 标注一批数据来训练：

1. 在工作流中配置 Process 节点 → Emotion 或 Tendency → 保持默认 LLM 模式
2. 连接上游数据源，执行工作流
3. 完成后，将 Process 节点的模式切换为 `ml`，点击「训练 ML 模型」
4. 系统自动从上游节点结果中提取文本列和标签列训练模型
5. 训练完成后，后续执行将使用 ML 模式批量推理（无需 Ollama / 不耗 token）

ML 模型保存在 `data/models/` 目录下，训练一次后持久可用。

## 开发与验证

- 依赖安装、lint（ruff + pylint）、启动与测试均使用项目虚拟环境 `.venv/`
- 代码风格由 `ruff.toml` 约束（行宽 120、单引号），提交前必须通过
  `ruff check` 与 `ruff format --check`，且只允许真正修复，禁止 `# noqa` 式忽略

### 自动化测试（pytest，约 1215 用例）

测试体系分五层，位于 `tests/` 目录：所有写入都落在临时目录（绝不触碰真实 `data/`）；
`live_site` 层会真实读取 `data/cookies/` 里的登录态去访问目标站点：

| 层 | 内容 | 外部依赖 |
|----|------|----------|
| `tests/unit` | 纯逻辑：断点续跑存储、数据集存储、DAG 引擎、执行器、14 种清洗算子、10 种图表、6 种导出、分析器、i18n、浏览器启动参数、**日志轮转**（滚出 .1…​.N、上限、纯追加退路）、**保留策略时间闸**（首发/窗内跳过/一个库报错不阻断另一个）、**Cookie 入口链接白名单**（伪后缀、userinfo 夹带、scheme 注入一律拒）、**微信 Cookie 诊断**（后台 token 重定向=已登录、评论凭证有/无、URL 参数回填）；**前端 JS 行为层**：`tests/frontend/*.mjs` 用 node 直接加载真实的 canvas.js / workflow.js / app.js，测 validate 预检门、设置面板渲染（平台样例链接、评论混合提示）、弹窗外点关闭、目录双语对齐、undo/redo、工作流保存/打开/新建全链路、运行记录面板转义与按钮、**Cookie 面板**（按平台渲染步骤、切换不重复堆叠、入口链接随请求送出、被拒链接提示、验证中隐藏登录按钮、重开面板接管在跑的任务）；另含 node 无关的静态契约测试（序列化字段、键目录） | 无（JS 行为层需 node，缺 node 自动跳过） |
| `tests/api` | Flask test_client：覆盖 50+ 端点，含「上传→清洗→导出」完整执行链路、Cookie 登录状态机、**Cookie 用途接口与验证任务**（无 Cookie 直接拒、越界链接拒、探测崩溃判 error 不挂面板、登录按钮不得应答验证、验证与登录共用单飞锁）、**Cookie 中途过期→节点判失败→换 Cookie 续跑不重复**的完整模拟、**十类节点逐一执行验证（分词/图表/导出格式/续跑收养）**、**停止（空闲/运行中）→记录判中断且数据保全、线程强杀保护主线程、卡死浏览器按 PID 定向回收**、设置面板布尔开关、API 加固（畸形请求→400） | 无（外部调用全 mock） |
| `tests/integration` | LLM 传输边界（OpenRouter 一律 mock，绝不真实请求）、行运行器（断点/熔断/取消）、真 Chrome 解析 `file://` 夹具、微博/知乎假驱动登录墙判定、**真浏览器 UI 回归：自启服务器后实测设置/AI 子菜单中英文双语均无水平滚动条，看板/历史弹窗外点关闭与内部点击保留** | 夹具层需 Chrome |
| `live_ollama`（marker） | 真调本地 Ollama 的活模型用例（服务不可达自动跳过） | Ollama |
| `live_site`（marker） | **全平台真实爬取 × 双浏览器模式**：知乎/微博/小红书/微信各自的搜索或文章抓取都分别以 无头 与 可见窗口 两种模式真跑真断言，另加评论节点三平台真测（微博/小红书无头、知乎强制可见）与**真浏览器 Cookie 中途失效→续跑**用例；知乎无头风控零结果按设计语义处理（明确无结果页→可执行报错，未触发请求的空壳→合法 0 行）；无对应 Cookie 自动跳过 | Chrome + 已存 Cookie |

```bash
# 快速套件（默认，<60 秒，CI 友好；上面三层未打 marker 的部分）
python -m pytest -q

# 设备套件（真 Chrome + 真 Ollama）
python -m pytest -q -m "integration or live_ollama"

# 真站套件（需已保存的登录 Cookie；逐平台顺序执行，每次仅 3~5 条，礼貌间隔）
python -m pytest -q -m live_site

# 覆盖率
python -m pytest -q --cov=backend --cov-report=term
```

修改代码后的完整验证流程见 `AGENTS.md` 的 "Change workflow"。
