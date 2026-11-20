# 演示工作流与录屏（可复用）

本目录是采析绘能力的演示库，已按用途分类：

| 目录 | 内容 |
|---|---|
| `templates/` | 演示画布 JSON（模型能力 + 你已保存的全链路画布） |
| `codebooks/` | 码本样例（质性/量化编码） |
| `datasets/` | 演示数据说明与粘贴载荷 |
| `videos/` | 实机录屏 MP4 |
| `manifest.json` | 演示清单：分组、数据根、端口、LLM 设置、画布模板 |
| `../../tools/record_demo.py` | 一键运行 + 录屏脚本（跨三系统，一次一个运行） |

## 一键录制

```bash
# 列出/直接运行单个演示
python tools/record_demo.py --group model --demo demo1
python tools/record_demo.py --group showcase --demo showcase_sentiment

# 跑完某组全部演示；--no-record 只验证不录制
python tools/record_demo.py --group model
python tools/record_demo.py --group showcase --no-record
```

脚本会自动：在清单指定的独立数据根启动服务 → 打开**项目内专属 Chrome 配置**的浏览器窗口 →
`SW_MAXIMIZE` + **F11 全屏** → 录制桌面（此时桌面就是浏览器页面，不是宿主窗口）→ 通过
`/api/workflow/execute` 串行执行画布 → MKV 录制、无损转 MP4 → 关闭本次启动的浏览器进程树与
服务进程树。不会误杀你原本开着的浏览器或服务器。

需要覆盖时：`CIXI_BROWSER_BIN` 指定浏览器，`CIXI_FFMPEG` 指定 ffmpeg，`--width 0` 保持全屏原生分辨率。

## 演示清单

| 分组 | 演示 | 展示 |
|---|---|---|
| `model` | demo1 | 质性编码开放编码，LLM 调用在 AI 工作区可见 |
| `model` | demo2 | 微调 BERT 情感批量分类 |
| `model` | demo3 | 语义去重 + 相似检索 |
| `model` | demo4 | 零样本用户自定义标签 |
| `model` | demo5 | NER 序列标注 |
| `model` | demo6 | 量化内容分析，双人编码 + Cohen kappa |
| `showcase` | showcase_sentiment | 情感分析 + 图表 + LaTeX 导出 |
| `showcase` | showcase_xhs | 小红书数据筛选 + 可视化 + 编译 |
| `showcase` | showcase_keywords | 关键词共现关系 |
| `showcase` | showcase_biblio | 文献计量与知识图谱 |

量化演示需要先把 `codebooks/content_analysis_sample.json` 通过 `POST /api/ai/codebooks` 导入账号码本；
其他演示使用对应数据根中已经准备好的数据集。所有下载与缓存仍只落项目目录。
