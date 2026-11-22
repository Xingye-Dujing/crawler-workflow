# 宣传片 / Promo film

采析绘的宣传片：**快速浏览式的产品功能巡礼**。画面全部由产品自身产生——浏览器里的真实录屏、
真实面板截图、以及 `/api/visualize/render` 现场渲染的图表，没有一张重绘的示意图。无音轨。

| 版本 | 画幅 | 时长 | 成片 |
| --- | --- | --- | --- |
| 哔哩哔哩长屏版 | 2560×1440 · 16:9 | 约 118 秒 | `out/bilibili.mp4` |
| 抖音竖屏版 | 1440×2560 · 9:16 | 约 52 秒 | `out/douyin.mp4` |
| 封面 | 2560×1440 | 静帧 | `out/cover.png` |

节奏由 `src/FootageFilm.tsx` 的 `PACE` 统一控制（默认 0.42），每段短、信息密度高。
界面固定为中文、亮色主题；顶栏压到内容高度常驻，环境提示与折叠按钮隐藏，画面干净。

## 一键复现 / Reproduce

前置：Node 18+、本机 Chrome、PATH 中的 `ffmpeg`，以及项目自己的 `.venv`（Python 3.11）。

```bash
# 0. 依赖
cd video && npm install && cd ..

# 1. 采集界面素材（自动准备独立数据根、启动 Flask、kiosk 全屏驱动 Chrome）
.venv/Scripts/python.exe video/scripts/browser_capture.py       # Windows
# .venv/bin/python video/scripts/browser_capture.py              # Linux / macOS

# 2. 批量渲染 25 种真实图表（同一种渲染通道，PNG 无损）
.venv/Scripts/python.exe video/scripts/chart_gallery.py

# 3. 渲染成片
cd video
npm run render:bili
npm run render:douyin
npm run cover
```

只重采某一场：`--only canvas` / `--only ai-chat` / `--only data-scroll` 等。

## 三个采集脚本

- **[`scripts/browser_capture.py`](./scripts/browser_capture.py)** — 界面素材。
  用 CDP `Page.startScreencast` 抓帧（PNG 无损帧，避免 JPEG 压缩），ffmpeg CRF 12 编码；
  静态面板按其在 DOM 里的真实位置裁成 16:9 局部图。操作都是真实输入：节点齿轮、滚轮缩放、
  右键平移、点击执行、报告对话框、AI 工作区真实提问。Chrome 以 `--kiosk --start-fullscreen`
  启动，视口即录制区，没有标签栏/地址栏/边框。
- **[`scripts/chart_gallery.py`](./scripts/chart_gallery.py)** — 图表素材。
  对每种图表调 `/api/visualize/render` 拿到产品真实的 ECharts option，在浏览器里全屏绘制后
  截成 3200×1800 PNG。覆盖 16 种控制台图 + 9 种文献计量图。
- **[`scripts/make_demo_data.py`](./scripts/make_demo_data.py)** — 演示数据。
  从 `ml_train` 的微博语料抽 600 条真实评论注入独立数据根，使数据预览是几百行真数据翻页，
  不是 24 行占位。

## 场景与功能覆盖

录屏/截图段（真实操作）：画布放大聚焦、9 平台选择、CatBus 引擎、600 行评论翻页、清洗合并、
节点口径、运行执行、文献计量、运行记录、HTML 报告、产物导出、AI 工作区（本地 Ollama 真实问答）、
账号池、定时任务、设置。

图表段（`gallery/`，简单→复杂递进）：柱状/折线/双轴/堆叠/饼/散点/直方/箱线/词云/显著词 →
热力/桑基/关系/地图/模型一致率/主题距离 → 知识图谱/聚类时间线/突现/时区/环形/景观/
聚类热力/三维/同心环。

## 独立数据根 / Isolated data root

采集脚本不写仓库的 `data/`：

1. 优先复制 `scratchpad/demo_showcase_root/data/datasets.db`（`showcase_biblio` 的四份知网导出在此），
   并注入 600 条真实评论；缺失时按名拒绝；
2. 从 `samples/workflows/templates/` 复制 `showcase_biblio`、`showcase_sentiment`、`showcase_xhs`；
3. `CRAWLER_DATA_ROOT=video/.data` 起独立 Flask，退出时只关自己的进程树。

## 剪辑结构 / Editing

[`src/FootageFilm.tsx`](./src/FootageFilm.tsx) 定义段落：`Footage` 真实录屏、`StillFootage` 实机截图、
`ChapterCard` 纸面概念卡、`Effects` 高亮框/标注/步骤。画面铺满整帧不缩小；讲解文字是左下角的一行
小卡，不与画面重叠。字体、配色与节点强调色取自 `backend/static/css/base.css`。旁白见
[`SCRIPT.md`](./SCRIPT.md)。封面 [`src/Cover.tsx`](./src/Cover.tsx) 右侧嵌一张真实画布截图。

## 字体与依赖

- `public/fonts/LXGWWenKaiGB-Subset.ttf`：按**当前全部文案**用字裁剪，`scripts/subset_font.py` 可重生；
  新加文案后若出现字体不统一，重新生成即可。授权见 `OFL-LXGW.txt`。
- `public/fonts/literata-*.woff2` 与网页端一致；`APL385.ttf` 用于等宽标签。
- Python 依赖 `websocket-client`（CDP）、`psutil`（进程树），已在项目 `.venv`；`ffmpeg` 需在 PATH。
- Chrome 可用 `CHROME_BIN` / `CIXI_BROWSER_BIN` 指定；脚本不需要 ChromeDriver。

素材落在 `video/public/real/{film,gallery}/`，成片在 `video/out/`；两者都不进 git。
