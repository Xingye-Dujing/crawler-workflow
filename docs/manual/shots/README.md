# 手册截图脚本

这份脚本用来重拍 `docs/manual` 里的界面截图。它只读界面，不改数据：打开工作流、自动排布、截画布或面板，然后退出。
手册里的图都是用它拍出来的。

## 前提

- 采析绘正在运行，默认地址 `http://127.0.0.1:5000/`，换端口用 `--url`。
- 本机 Chrome 与匹配的 chromedriver。程序按环境变量找，不写死任何平台路径。
  - `CHROME_BIN` 指向 Chrome 可执行文件
  - `CIXI_DRIVER_PATH` 指向 chromedriver
  - 两个都不设时交给 Selenium 自己找。
- 依赖已在 `.venv/` 里（selenium 随 `requirements.txt` 装）。

## 用法

```bash
# 整张画布
.venv/Scripts/python.exe docs/manual/shots/capture.py canvas --workflow "测试：图表可视化" --out zh-canvas
# 节点设置面板（按类型筛，--limit 限制张数）
.venv/Scripts/python.exe docs/manual/shots/capture.py panels --workflow "刘学州-评论-情感演化分析-BERT" --out liu --types analysis --limit 1
# 停靠面板（runs/exports/datasets/schedules/lexicon/workflows/cookies/processes/console）
.venv/Scripts/python.exe docs/manual/shots/capture.py dock --out runs-panel --panel runs
# 顶栏菜单（style/ai/settings/help/clipboard）
.venv/Scripts/python.exe docs/manual/shots/capture.py menus --out style-menu --panel style
# 大纲
.venv/Scripts/python.exe docs/manual/shots/capture.py outline --workflow "刘学州-评论-情感演化分析-BERT" --out outline
# 图表预览、全屏、看板、数据预览
.venv/Scripts/python.exe docs/manual/shots/capture.py chart --workflow "刘学州-评论-情感演化分析-BERT" --out chart-preview
.venv/Scripts/python.exe docs/manual/shots/capture.py fullscreen --workflow "刘学州-评论-情感演化分析-BERT" --out dashboard-zoom
.venv/Scripts/python.exe docs/manual/shots/capture.py dashboard --workflow "刘学州-评论-情感演化分析-BERT" --out dashboard
.venv/Scripts/python.exe docs/manual/shots/capture.py datapreview --workflow "刘学州-评论-情感演化分析-BERT" --node-type upload --out data-preview
```

`chart` / `fullscreen` / `dashboard` / `datapreview` / `history` 会先调用 `hydrate_results`，把这张画布最新一次
存下来的运行载入页面，面板才有真实的行和图，不会只剩一句“先跑一次”。

输出落在 `docs/manual/img/<out>.png`，两倍像素，浅色主题，画布已经自动排布并适应过。

## 约定

- 拍画布前一定先 `autoLayout` 再 `resetView`，手册里的画布都是排布后的样子。
- 面板用元素截图，只留面板本身，文字才够大。
- 浅色主题是论文用的，深色只作一页示例。
- 账号与云端那一组图要在 cloud 模式、独立数据根上拍，别动正式账号库。
- 定时任务一张要先建一个真任务再拍，拍完删掉，别把演示任务留在用户的计划表里。
