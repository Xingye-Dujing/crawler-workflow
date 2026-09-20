# 采析绘（数据的采集分析和可视化）

一个基于 Flask + Selenium + Ollama + scikit-learn 的多平台数据采集、数据清洗、情感分析、通用数据分析与可视化工作流系统。

## 功能特性

- **多平台爬虫**：支持知乎、微博、小红书、微信公众号的数据采集
- **情感分析（双模式）**：LLM（Ollama）逐行深度分析，或传统 ML（sklearn TF-IDF + 逻辑回归）批量高速推理，可在节点设置中随时切换
- **倾向性分析（双模式）**：同上，LLM 或 ML 可选
- **语义数据清洗**：自动过滤广告、无关内容与低质量数据（LLM 判定）
- **通用数据分析节点**：去空值、去重、条件筛选、重命名列、类型转换、排序、采样、分组聚合、表关联、列计算、数值分箱等确定性清洗，可独立于爬虫使用，直接处理任意上传的表格数据
- **关键词提取**：TF-IDF / TextRank 关键词抽取（依赖 jieba）
- **文本聚类**：K-Means / DBSCAN 自动发现文本分组
- **命名实体识别**：正则规则式中文 NER（人名/机构/地名/日期，零依赖）
- **异常检测**：Isolation Forest 自动标记数值异常行
- **相关性分析**：Pearson / Spearman / Kendall 相关系数矩阵
- **通用导出节点**：一个节点支持导出 CSV / JSON / Excel / TXT / HTML / Markdown 六种格式
- **通用可视化节点**：柱状图 / 折线图 / 饼图 / 散点图 / 直方图 / 箱线图 / 热力图 / 桑基图 / 词云（支持中文分词）/ 中国地图，支持 ECharts（前端渲染）与 Matplotlib（服务端渲染）两种引擎
- **数据预览面板**：任意数据集都能以可翻页的表格形式查看真实数据行
- **仪表盘看板**：把画布上所有 Visualize 节点的图表拼在一个网格里一起查看
- **执行历史与趋势对比**：自动记录情感/倾向性分布与各节点行数，可按工作流和指标画出时间序列
- **工作流画布**：拖拽式节点编辑，可视化配置数据采集/清洗/分析/可视化全流程
- **撤销/重做**：Ctrl+Z / Ctrl+Y 支持 50 步历史回退，菜单和右键菜单均有入口
- **节点折叠**：选中节点按 F 键或右键折叠，节省画布空间
- **自动布局**：按 DAG 层级 BFS 自动排列所有节点
- **节点颜色编码**：每种节点类型有独立颜色标识（蓝/红/黄/绿/紫）
- **模型训练**：从已有 LLM 标注数据一键训练传统 ML 模型，后续推理无需 Ollama
- **多线程执行**：支持并行/串行执行模式
- **实时统计**：ECharts 图表展示情感分布与倾向性统计
- **Cookie 管理**：持久化登录状态，避免重复扫码
- **极简界面**：极客风格黑白主题，网格背景画布

## 快速开始

### 1. 环境要求

- Python 3.11+ (`zip(..., strict=True)`)
- Chrome 浏览器 (Selenium 驱动)
- [Ollama](https://ollama.ai/) (本地大模型)
- 如需 Matplotlib 引擎渲染中文图表，服务器需安装中文字体
  （如 `fonts-wqy-microhei` / SimHei / Microsoft YaHei 任一即可，
  Linux 下可 `apt install fonts-wqy-microhei`）

### 2. 安装依赖

```bash
cd crawler_workflow
pip install -r requirements.txt
```

### 3. 下载 Ollama 模型

```bash
ollama pull qwen3.5:9b
```

### 4. 启动应用

```bash
cd backend
python app.py
```

访问 http://localhost:5000

## 项目结构

```
crawler_workflow/
├── backend/
│   ├── app.py                    # Flask 主入口
│   ├── config.py                 # 配置
│   ├── crawlers/                 # 爬虫模块
│   │   ├── base.py               # 爬虫基类
│   │   ├── zhihu.py              # 知乎爬虫
│   │   ├── weibo.py              # 微博爬虫
│   │   ├── xiaohongshu.py        # 小红书爬虫
│   │   └── wechat.py             # 微信公众号爬虫
│   ├── analyzers/                # 分析模块（LLM + ML 双模式）
│   │   ├── ml_base.py            # 传统 ML 底座（TF-IDF + 分类器）
│   │   ├── cleaner.py            # 广告/噪声语义清洗（LLM）
│   │   ├── emotion.py            # 情感分类（LLM + ML 可选）
│   │   ├── tendency.py           # 倾向性分析（LLM + ML 可选）
│   │   ├── keyword.py            # 关键词提取（TF-IDF / TextRank）
│   │   ├── clustering.py         # 文本聚类（K-Means / DBSCAN）
│   │   ├── ner.py                # 命名实体识别（正则规则）
│   │   ├── anomaly.py            # 异常检测（Isolation Forest）
│   │   └── correlation.py        # 相关性分析（Pearson / Spearman / Kendall）
│   ├── engine/                   # 工作流引擎
│   │   ├── workflow.py           # DAG 解析、调度与节点校验
│   │   ├── executor.py           # 线程池执行器
│   │   └── logger.py             # 日志管理
│   ├── services/                 # 服务模块
│   │   ├── stats.py              # 情感/倾向性统计服务
│   │   ├── cookie_manager.py     # Cookie 管理
│   │   ├── workflow_manager.py   # 工作流持久化
│   │   ├── exporter.py           # 通用多格式导出服务（Save 节点）
│   │   ├── data_analysis.py      # 通用数据清洗服务（Analysis 节点）
│   │   ├── visualizer.py         # 通用可视化服务（Visualize 节点）
│   │   └── execution_history.py  # 执行历史记录（SQLite）
│   ├── utils/
│   │   └── helpers.py            # 工具函数
│   └── static/                   # 前端静态文件
│       ├── index.html
│       ├── css/style.css
│       └── js/
│           ├── app.js
│           ├── canvas.js
│           ├── workflow.js
│           └── stats.js
├── data/
│   ├── cookies/                  # 平台 Cookie
│   ├── exports/                  # 导出数据
│   └── workflows/                # 工作流配置
├── logs/
├── requirements.txt
└── README.md
```

## 节点类型

| 节点 | 说明 | 能否独立运行 |
|------|------|------|
| Data Source（数据源） | 从知乎/微博/小红书/微信采集数据 | 否，需要平台+关键词 |
| Process（处理） | LLM 语义清洗 / 情感分类(LLM/ML) / 倾向性分析(LLM/ML) / 关键词提取 / 文本聚类 / NER / 异常检测 / 相关性分析 | 否，需要上游文本数据 |
| **Analysis（分析）** | 确定性数据清洗：去空/去重/筛选/改名/类型转换/排序/采样/分组聚合/表关联/列计算/分箱 | **是**，可直接处理上传的数据集 |
| **Visualize（可视化）** | 柱状/折线/饼图/散点/直方/箱线/热力/桑基/词云/地图，ECharts 或 Matplotlib 渲染 | **是**，可直接处理上传的数据集 |
| Output（保存） | 导出为 CSV / JSON / Excel / TXT / HTML / Markdown | 否，需要上游数据 |

## API 参考

### 工作流

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/workflow/save` | POST | 保存工作流配置 |
| `/api/workflow/load` | GET | 加载工作流 |
| `/api/workflow/list` | GET | 列出所有工作流 |
| `/api/workflow/execute` | POST | 执行工作流 |
| `/api/workflow/stop` | POST | 停止执行 |
| `/api/workflow/status` | GET | 获取执行状态 |

### 数据 / 分析 / 可视化 / 导出（独立于工作流，可单独调用）

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/data/upload` | POST | 上传 CSV/JSON 文件，注册为数据集 |
| `/api/data/paste` | POST | 将粘贴的 JSON 数组注册为数据集 |
| `/api/data/inspect` | POST | 查看数据集的空值/类型/重复行统计 |
| `/api/data/preview` | POST | 分页查看数据集的原始表格（供"数据预览"面板使用） |
| `/api/data/clear` | POST | 清空内存中的数据集缓存 |
| `/api/history/runs` | GET | 列出所有已记录的工作流执行 |
| `/api/history/series` | GET | 按工作流/指标查询时间序列数据（供"执行历史"面板画趋势图） |
| `/api/history/clear` | POST | 清空执行历史记录 |
| `/api/analysis/run` | POST | 对数据集执行清洗流水线，返回清洗后数据集 id 及报告 |
| `/api/analysis/train` | POST | 从已有 LLM 标注数据集训练传统 ML 模型（情感/倾向） |
| `/api/visualize/render` | POST | 对数据集渲染图表，返回 ECharts option 或 Matplotlib 图片 |
| `/api/export/save` | POST | 将数据集导出为指定格式文件 |

### 统计 / 其它

| 端点 | 方法 | 描述 |
|------|------|------|
| `/api/stats/emotion` | GET | 情感统计 |
| `/api/stats/tendency` | GET | 倾向性统计 |
| `/api/cookies/status` | GET | Cookie 状态 |
| `/api/config` | GET | 系统配置 |

## 使用示例

### 1. 从画布创建完整工作流

1. 从左侧节点库拖拽 "Data Source" 到画布
2. 双击节点打开设置面板，选择平台和关键词
3. 添加 Process 节点 (Clean / Emotion / Tendency)
4. 添加 Analysis 节点做进一步的确定性清洗（如去空值、去重）
5. 添加 Output 节点，选择导出格式 (CSV / JSON / Excel / ...)
6. 添加 Visualize 节点查看数据分布（可选，与 Output 并列挂在同一上游节点后）
7. 拖拽连线连接节点
8. 点击菜单 "Execute" 运行

### 2. 独立使用 Analysis / Visualize 节点（不采集，只处理已有数据）

1. 直接在画布上拖一个 Visualize（或 Analysis）节点，不连任何上游节点
2. 打开节点设置，把 "Data Source" 改成 "Upload File"，上传一份 CSV/JSON
3. 配置图表类型 / X、Y 字段后点击 "Preview Chart" 即可在右侧预览面板看到结果，
   不需要跑整个工作流

### 3. 加载示例工作流

```bash
cp data/workflows/sanya_crawl.json data/workflows/
```

在画布中点击 File → Load，输入 `sanya_crawl`。

## 配置

通过 `backend/config.py` 或环境变量配置：

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `OLLAMA_MODEL` | Ollama 模型名 | `qwen3.5:9b` |
| `OLLAMA_HOST` | Ollama 服务地址 | `http://localhost:11434` |
| `DEFAULT_HEADLESS` | 默认无头模式 | `True` |
| `DEFAULT_MAX_WORKERS` | 最大线程数 | `4` |

## 训练传统 ML 模型

情感分析和倾向性分析支持传统 ML 模式（sklearn TF-IDF + 逻辑回归），需要先用 LLM 标注一批数据来训练：

1. 在工作流中配置 Process 节点 → Emotion 或 Tendency → 保持默认 LLM 模式
2. 连接上游数据源，执行工作流
3. 完成后，将 Process 节点的模式切换为 `ml`，点击「训练 ML 模型」
4. 系统自动从上游节点结果中提取文本列和标签列训练模型
5. 训练完成后，后续执行将使用 ML 模式批量推理（无需 Ollama）

ML 模型保存在 `data/models/` 目录下，训练一次后持久可用。
