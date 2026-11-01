# 代码库全面审查报告

- **审查对象**：`crawler_workflow`（采析绘）— `backend/` 约 8.6 万行 Python（341 个模块）+ 约 1 万行前端 JS
- **审查日期**：2026-11-01
- **修复日期**：2026-11-01，按类别分 6 次提交（见文末「修复状态」）。凡标注 **已修复** 的条目
  都附了回归用例；**未改动** 的条目在文末统一说明原因，它们多数是需要产品决策或真实浏览器
  才能验证的项，不是「尚未处理」。
- **审查方法**：按子系统分区通读 + 交叉验证。每条结论标注核验等级：
  - **已复现**：在本机 `.venv` 中实际运行代码复现（含输出）
  - **代码确认**：逐行读代码可确定的缺陷
  - **待复核**：逻辑上成立、但触发条件或运行环境无法在此确认（统一放在「潜在风险」）
- **严重度定义**
  - **高**：崩溃 / 数据永久丢失或静默错误 / 安全漏洞 / 进程级不可用
  - **中**：特定条件下出错、结果不可信、影响可恢复
  - **低**：边角瑕疵、可读性级别的错误提示

---

## 一、总体结论

工程纪律整体高于同类项目：SQL 全部参数化（本次范围内**未发现可利用的注入点**）、鉴权用 scrypt + 常量时间比较 + 按 IP/账户双限流、CORS 与 Origin 守门写得很细、导出/画布文件名有白名单清洗、上传有体积上限、i18n 有启动自检。

但存在一个系统性弱点：**「降级与兜底」大量采用「静默给出一个看起来合法的值」**。这在本项目的语境下是最危险的模式——用户拿到的是一张完整、无告警、但结论相反的表格。下面 13 条高危里有 8 条属于这一类（虚构中立情感、误判网暴、时间列整体偏移、来源列混入时间、爆发信号恒为 0 等）。

---

## 二、高严重度（已确认）

### H1. 网暴检测的「隐私」正则退化成任意单字匹配，普通评论被判 `severe`
- **位置**：`backend/analyzers/aggression.py:74` — `PRIVACY` 元组 / `AggressionAnalyzer.score_text`
- **证据**
  ```python
  r'(\d{1,5}号楼?|[省市县区街道路巷小区栋单元室门牌])',
  ```
  字符类里没有量词，`[...]` 匹配的是**任意一个汉字**；而 `WEIGHTS['privacy']=0.6 ≥ SEVERE_AT=0.5`，单命中即判 `severe`。
- **已复现**（`.venv` 实测）
  ```
  '这个小学生太可怜了'  -> ('severe', 0.6, ['privacy:小'])
  '我们小区的物业'      -> ('severe', 0.7, ['privacy:小、区'])
  '今天路很堵'          -> ('severe', 0.6, ['privacy:路'])
  '100元'               -> ('severe', 0.6, ['privacy:元'])
  '分配不均'            -> ('mild',   0.3, ['attack:配'])
  ```
- **触发条件**：`mode='lexicon'`（该操作的默认模式）处理任何真实中文评论表。
- **后果**：`aggression` / `aggression_score` 两列的核心指标失真。「小学」「小区」「100元」「元芳」这类最高频日常用语被计为严重网暴，论文的「暴力言论演化曲线」整体失真；且 `aggression_hits` 写着 `privacy:小`，读者会误以为是模型判断而非规则 bug。**这是本次审查中影响面最大的一条**（污染所有历史分析产物）。
- **修复方向**：改成多字词表（`(?:省|市|县|区|街道|路|巷|小区|栋|单元|室|门牌号)`）并要求与地址上下文共现，否则单字不得计分。

### H2. 落库失败被当作「已采集」，游标与水位继续越过该行
- **位置**：`backend/crawlers/core/crawler.py:319-328` — `Crawler.emit`
- **证据**
  ```python
  try:
      kept = self._sink(item)
  except Exception as e:
      logger.warning(t('crawl.sink_failed', err=e))
      kept = True
  ```
- **代码确认**：`kept=True` 后该行进入 `_collected`，`collected()` 计数、`note_watermark(key)` 水位、`mark_position` 游标全部前进；但 sink 抛异常意味着这行**从未写库**。
- **触发条件**：`append_rows` 失败——SQLite 被锁、磁盘满、表结构变更。恰恰是最需要报错的时刻。
- **后果**：表格少行，节点仍按 DONE 结算；水位已越过该行，增量运行按 `watermark_boundary` 只会向后停，**这行永久摘不回来**，去重台账也无从补救。属于项目自己明令禁止的「静默少采」。

### H3. 毫秒级/非法时间戳抛 `OSError`，一条脏数据炸掉整个采集节点
- **位置**：`backend/crawlers/commenting/protocol.py:59-64`、`backend/crawlers/core/video.py:23-29` — `_stamp`
- **证据**
  ```python
  try:
      seconds = int(value or 0)
  except (TypeError, ValueError):
      return ''
  return datetime.fromtimestamp(seconds, tz=_CST).strftime(...) if seconds else ''
  ```
  `try` 只包住 `int()`；真正会抛的 `fromtimestamp` 在外面。
- **已复现**
  ```
  1700000000000 -> OSError [Errno 22] Invalid argument     # 13 位毫秒，国内平台接口极常见
  -1            -> OSError [Errno 22] Invalid argument
  10**20        -> OverflowError timestamp out of range
  ```
- **触发条件**：接口返回毫秒时间戳（13 位）、负值或越界值。调用点 `bilibili/crawler.py:412`、`douyin/rows.py:92`、`hongguo/comments.py:153` 均无外层兜底。
- **后果**：`_row()` 构造抛异常 → 沿 walk 上抛 → 整个源节点以裸 traceback 失败，后续页面不再采集（已流入库的行保留）。一条脏时间戳废掉一次采集。

### H4. 红果短剧评论链路的 mitmdump 插件路径指向不存在的文件
- **位置**：`backend/crawlers/platforms/hongguo/harvest.py:56`、`:786-801` — `_ADDON` / `_start_proxy`
- **证据**
  ```python
  _ADDON = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'harvest_addon.py')
  self._proxy = subprocess.Popen([mitmdump, '-s', _ADDON, ...])
  ```
  目录中只有 `addon.py`；`git ls-files` 同样只有 `addon.py`，`.gitignore` 也没有生成规则；全仓无构建步骤改名或复制。
- **触发条件**：任意红果评论节点（Windows 桌面能力齐备的正常机器）。
- **后果**：`mitmdump -s <缺失文件>` 立即退出；`_start_proxy` 等满 15 s 后抛「proxy did not come up on 127.0.0.1:8860」，**把「文件不存在」报成「端口没起来」**，用户会去排查端口/防火墙。红果评论采集 100% 不可用，「播放器当签名器」的整套设计完全失效。

### H5. 分类值未经转义直接拼进 pgfplots `coordinates`，含逗号即编译失败，含 `}` 可注入 TikZ
- **位置**：`backend/services/charts/tikz_console.py:55` — `ConsoleFigureMixin._bars_or_line`（同型：`:77-78` `_dual_line`、`:116-119` `_stack_pct`）
- **证据**
  ```python
  labels, values = VisualizationService.aggregate(df, x, y, agg)
  marks = ' '.join(f'({lab},{_num(v)})' for lab, v in zip(labels, values, strict=True))
  ```
  同一条命令里符号轴走 `_cat_axis`→`_sym`→`_esc` 转义了，**数据点坐标却用原始 `lab`**。
- **代码确认**：`lab` 来自 `aggregate()` 的类目值——题名、关键词、机构名、地区，全部是爬取/上传的数据。`labels=['Beijing, China']` 会生成 `coordinates {(Beijing, China,4)}`（逗号把 2 元坐标变成 3 元）；含 `}` 的类目可闭合 `coordinates` 并注入任意 TikZ（`\input{<本机文件>}` 会被 xelatex 默认放行，`\write18` 才是受限的）。
- **触发条件**：类目值含 `,`（机构名几乎必然）、`&`、`}`、`\`；随后 `.tex` 交给 xelatex（`services/charts/pdf.py`），PDF 经 `/api/studio/save-pdf`、compile 节点、论文报告回传给用户。
- **后果**：轻则整份 `.tex` 编译失败，用户只看到「xelatex 失败」；重则本机任意可读文件内容被拉进 PDF。`api/studio.py` 自己的注释就把这条通道列为要防的目标。
- **修复方向**：坐标里的类目一律走 `_esc`，且逗号级联需在 `_sym`/坐标两处同时替换（例如把 `,` 转成 `{,}` 或直接换成安全占位符）。

### H6. ML 模型任意异常 → 整列写入虚构的「中性 0.5」并宣告完成
- **位置**：`backend/analyzers/emotion.py:197-208` — `EmotionAnalyzer._analyze_ml`（同型：`sentiment.py:569`、`tendency.py:204`）
- **证据**
  ```python
  except Exception as e:
      if isinstance(e, ModelNotTrainedError):
          raise
      logger.error(t('ml.emotion_failed', err=e))
      predictions = [('Neutral', 0.5)] * len(texts)
  ```
  紧邻的注释写的是「A model there is nothing to load from is REFUSED, not answered with a column of invented Neutral」——**代码与注释相反**。
- **触发条件**：`mode='ml'` 且模型 pkl 损坏、sklearn 版本不匹配、维度不符、内存不足（非 `ModelNotTrainedError` 的任意异常）。
- **后果**：节点 DONE，表里 100% 单一类别、置信度恒 0.5；`StatsService.emotion_distribution` 把它当真实判定计入分布，与其它跑 bert 的表混在同一批图表里，**无法区分「测出来都是中性」与「一个都没测」**。

### H7. bot 检测绕过项目自建的时间解析，爆发信号恒为 0
- **位置**：`backend/analyzers/bot.py:69` — `BotLikelihoodAnalyzer.analyze_dataframe`
- **证据**
  ```python
  times = pd.to_datetime(work[time_column], errors='coerce')
  ```
  项目为自家产出的 `2022年01月27日 00:59` 专门建了 `analysis/kernels._to_datetime`（注释写明 `pd.to_datetime` 对这些行全答 NaT），bot.py 没用它。
- **已复现**
  ```
  pd.to_datetime(['2022年01月27日 00:59','2022年01月27日 00:59'], errors='coerce')
  -> [NaT, NaT]        # 并伴随 UserWarning: Could not infer format ...
  ```
- **触发条件**：`评论时间` 列是微博/抖音爬虫产出的中文时间串（最主流情形）。
- **后果**：`times` 全 NaT → `peaks` 空 → `median_peak=0` → `burst` 恒 0 → `bot_score` 只剩重复度一项。爆发信号被永久静默丢弃，`bot_evidence` 里什么都不写，列看起来是「测过、没发现」。同一个 `评论时间` 在 `extract_time`/`forecast` 里解析成功，两处结论互相矛盾。

### H8. 微博「发布来源」整列混入时间原文
- **位置**：`backend/crawlers/platforms/weibo/crawler.py:709-712` — `WeiboCrawler._get_from_line`
- **证据**
  ```python
  publish_time = times.absolute(self._node_text(anchors[0]))
  whole = self._text_of(card, '.from') or publish_time
  source = whole.replace(publish_time, ' ').strip(' \n\u00a0')
  ```
- **代码确认 + 复现**：`times.absolute('2022年01月27日 00:59')` 返回 **`'2022-01-27 00:59'`**（已实测），而 `whole` 是页面原文 `'2022年01月27日 00:59  iPhone客户端'`。用规范化后的串去 `replace` 原文，**一次都不会命中**。
- **触发条件**：任何一条微博搜索结果（相对时间「3小时前」同样命中——原文与规范化结果不同）。
- **后果**：`发布来源` 列变成「2022年01月27日 00:59 iPhone客户端」，时间被复制进来源列且原时间残留；按客户端/来源做的清洗与统计全部错，导出表里没有任何一列能看出这是错的。

### H9. 相对时间按服务器本机时区换算，UTC 云主机上整列偏移 8 小时
- **位置**：`backend/crawlers/engine/times.py:105` — `relative_to_absolute`
- **证据**
  ```python
  moment = now or datetime.now()      # 全文件无 _CST，naive 本机时间
  ```
  而同项目 `crawlers/core/video.py:20`、`crawlers/commenting/protocol.py:56` 都显式钉了 `timezone(timedelta(hours=8))` 并注明「跑在 UTC 云服务器上不得整体回退八小时」。
- **触发条件**：`Config.CLOUD_MODE`（Linux 容器默认 TZ=UTC）上抓任何相对时间标签（`3小时前`、`昨天 21:30`）——正是「最近发布的、最需要的行」。
- **后果**：`发布时间` / `评论时间` 静默错 8 小时，`昨天 21:30` 连日期一起错。时间序列分析拿到的是偏移数据，日志与列位没有任何提示。已实测本机（UTC+8）输出 `2026-11-01 11:24`，在 UTC 主机上将输出 `03:24`。

### H10. 画布保存非原子写，一次中断即毁掉已保存的工作流
- **位置**：`backend/services/workflows/manager.py:37-45` — `WorkflowManager.save`
- **证据**
  ```python
  path = self.path_for(clean)
  with open(path, 'w', encoding='utf-8') as f:
      json.dump(payload, f, ensure_ascii=False, indent=2)
  ```
  全仓其它写入者都刻意用 tmp + `os.replace`（`reusable.py:220-226`、`scheduling/store.py:90-94`、`services/lock_store.py:46-50`），唯独用户最贵的资产没有。
- **触发条件**：写盘中途进程被杀 / 断电 / 磁盘写满 / 杀软锁文件。
- **后果**：留下半截 JSON。`load()` 只捕获 `FileNotFoundError`/`JSONDecodeError` 并返回 `None`，调用方按「没有这个工作流」处理 → 画布打开空白 → 下一次保存覆盖残尾。作品无声消失且无备份。同源的 `/api/project/import`（`bundle.py:515`）与 `manager.rename` 也共用这条路径。

### H11. 日志推送在全局锁内做 SQLite 写，可重入同一把非递归锁 → 进程级死锁
- **位置**：`backend/runtime/state.py:339-358` — `_push_log`；`backend/engine/run_logs.py:113-126` — `RunLogWriter._drain`
- **证据**
  ```python
  _completed_lock = threading.Lock()          # state.py:152，非 RLock
  with _completed_lock:                        # state.py:339
      ...
      if _log_sink is not None:
          _log_sink(list(parts), idx, level)   # state.py:358
  ```
  sink 内部 `get_run_store()` 若首次打开该账户的库，构造会走 `promote_stale_runs()`，而它在有遗留行时执行 `logger.warning(t('run.promoted', ...))`（`store/ledger.py:105-106`）→ 根 logger 的 `LogBufferHandler`（`app.py:272`）→ `_push_log` → **同一线程再次 acquire 同一把 Lock**。
- **触发条件**：run 进行中出现一次 flush（≥200 行或任意 error 行）时，该账户 `runs.db` 恰好需要新建连接，且库里有上次崩溃遗留的 `running/stopping` 行。
- **后果**：run 线程、`/api/workflow/status`、以及进程内所有走 logger 的线程全部挂死，只能重启。即使不触发死锁，每次 flush 也在持锁期间同步写盘（`os.makedirs`/`PRAGMA`/commit），状态轮询被 DB 写阻塞。**建议**：sink 调用移出 `_completed_lock`，或改用 `RLock` 并把持久化放到独立队列。

### H12. `TaskExecutor` 是死代码：分层并行从未生效，停止按钮无法中断长节点
- **位置**：`backend/engine/executor.py:79-90`（`execute`/`stop`）、`backend/engine/run.py:1376`（唯一构造点）、`backend/engine/run.py:227`（唯一停止检查点）
- **证据**
  - 全仓 `grep "\.execute("` 在 `engine/`、`nodes/`、`api/` 中**零命中**；`run_parallel` 只被 `execute` 内部调用，而 `execute` 从不被调用。
  - 节点实际执行是串行的：`engine/run.py:518-547` 的 `for level in levels: for nid in level:`。
  - `execution_state['executor'] = TaskExecutor(...)` 之后，`stop()` 只是 `set()` 一个从未被任何任务观察的 Event，并遍历永远为空的 `_futures`。
- **触发条件**：正在跑 BERT/情感/聚类/导出等非爬虫长节点时按「停止」。
- **后果**：接口返回 ok、`running` 置 False，但节点继续跑完（可能几十分钟）才退出循环；单运行槽位与 `thread` 一直被占用，队列里后续 run 全部排队。用户看到「已停止」而真实状态不符。同时 `max_workers`/`max_headless_browsers` 这两个设置项在当前实现下**完全无效**（它们只影响这个空池）。
- **说明**：这不是「性能问题」，而是**承诺与实现不符**——面板与文档都在讲并行与可中断。

### H13. `/api/report/generate` 的 `ollama_host` 由请求体决定 → 服务端请求伪造（SSRF）
- **位置**：`backend/api/report.py:131-141` — `report_generate`；`backend/runtime/transport.py:25` — `_local_transport_refusal`
- **证据**
  ```python
  refusal = _local_transport_refusal(provider)   # 只在 Config.CLOUD_MODE 下拒绝
  ...
  host=(str(cfg.get('ollama_host') or '') if provider == 'ollama' else ''),
  ```
  `LLMClient` 把 `host` 直接交给 ollama `Client(host=base, ...)`，`_ollama_base_url` 只补 `http://`，不校验主机。运行路径（`engine/run.py`）取的是 `get_setting('ollama_host')`，只有这条报告路径用了请求体。
- **触发条件**：开启了账户（`CRAWLER_ADMIN_PASSWORD` 或已存在 `accounts.db`，或 `HOST=0.0.0.0` 的 LAN 部署——`public_bind_refusal` 明确允许）但**不是** `cloud` 启动；已登录用户对自己的一条 run 提交 `{"llm":{"provider":"ollama","ollama_host":"http://10.0.0.5:8080"}}`。
- **后果**：服务端向任意内网 host:port 发 `POST /api/chat`；错误文本经 `add_log(t('run.reportConclusionFailed', err=e))` 进入控制台与报告，返回正文还会写进 HTML 报告的「结论」段——**带部分回显的 SSRF**，可用于内网端口探测与元数据服务旁路。`GET /api/models` 同时向普通账户返回模型绝对路径（见 M9），直接提供了候选目标。
- **修复方向**：与运行路径一致，只读 `get_setting('ollama_host')`；或用 `_origin_is_local` 同款校验限制为回环/已配置主机。

---

## 三、中严重度（已确认）

### M1. `filter_rows` 的等值/集合比较不做类型归一，数值列过滤静默返回空表
- **位置**：`backend/services/analysis/ops/filter_rows.py:13`（`eq`/`ne`）、`:36-39`（`in`/`not_in`）
- **证据**：`mask = s == value`；面板传来的 `value` 是字符串，`gt/gte/lt/lte` 走了 `float(value)`，`eq/ne` 没有。
- **已复现**：`df[df['like'] == '25']` → `(0, 1)`（pandas 3，无报错无警告）。
- **后果**：节点 DONE、输出 0 行，下游全部「无上游数据」，用户以为「确实没有这类数据」；`not_in` 则相反——一行都不删，静默放行。

### M2. `_signed_polarity` 没有 neutral 分支，三分类情感模型在第一批就中止整列
- **位置**：`backend/analyzers/sentiment.py:296-309` — `_signed_polarity`
- **证据**：只判 `pos*` 与 `neg*`，其余 `raise PolarityError(...)`；而本操作的 `LABELS` 就是三值。
- **触发条件**：`mode='bert'` + 标签集为 positive/negative/neutral 的模型（本项目 `ml_train` 的标签集正是这三个词）。
- **后果**：节点在第一批 FAILED，前面已写入的行整表作废；错误信息是 `bert_bad_label` 而不是「这个模型有三类」。另外极性用**子串**判断（`'pos' in name`、`'neg' in name`）且 pos 优先，语义上不可靠。

### M3. 小红书评论「楼层」每轮滚动从 1 重来
- **位置**：`backend/crawlers/platforms/xiaohongshu/comments.py:61` → `parse_xhs_comments`（`:29` 的 `enumerate(items, 1)`）
- **证据**：`rows.extend(parse_xhs_comments(found))`，每批 `found` 独立从 1 编号；同仓 `bilibili/comments.py:193` 是显式传 `floor=len(rows)` 的全局递增约定。
- **后果**：第 2 轮起楼层号与第 1 轮完全重号（1..N 重复出现），按楼层引用/排序/去重全部失真。

### M4. X（Twitter）回复「楼层」恒为 1
- **位置**：`backend/crawlers/platforms/twitter/comments.py:95`（调用）与 `:45`（`index + 1`）
- **证据**：`parse_twitter_replies([data], url, root)` 每次只传一个元素，`enumerate` 的 `index` 恒为 0。
- **后果**：楼层列完全失去意义（全 1），与其它平台不可横向比较。

### M5. 知网批次「完整」判据把不可选行算进分母，游标永远不前进
- **位置**：`backend/crawlers/platforms/cnki/crawler.py:155`（`batch_rows += len(rows)`）与 `:222`（`complete = ... and selected >= rows_expected ...`）
- **问题**：`ids` 会剔除没有 `cbItem` 的行（`refused += len(rows) - len(ids)`），但 `batch_rows` 累加的是**全部** `rows`；`selected` 是站点勾选数，永远 ≤ 可选行数。只要某页出现过一行没有导出键，`selected >= rows_expected` 恒为假。
- **后果**：`complete` 恒 False → `mark_position` 永不执行 → 「继续」总从第 1 页重走、重新全选、重新导出（并重新消耗站点 500 条上限与风控配额），表里看不出游标没动。

### M6. 执行历史库每条方法裸 `close()`，异常即泄漏连接
- **位置**：`backend/services/runs/history.py:123` — `record_many`（同型：`list_runs:135`、`series:159`、`clear:186`、`delete_run:199`）
- **证据**：`conn = self._conn()` … `conn.commit()` / `conn.close()`，无 `try/finally`；`_conn()` 是 `sqlite3.connect(path)`，无 `timeout` 参数、无 WAL，默认 5 s 后抛 `database is locked`。
- **后果**：每次失败的写入漏一个 fd；`record_many` 的异常被 `record_execution_history` 的 `except Exception` 吞掉，用户只看到趋势图缺一段。多次累积后该库写入持续失败，只能重启进程。

### M7. 队列镜像把 LLM `api_key` 明文写进 runs.db
- **位置**：`backend/services/runs/queue.py:104` — `'data': data`
- **证据**：`entry['data'] = data` 是整个请求体（含 `llm.api_key`），`mirror_queue()` 用 `json.dumps(entry.get('data'))` 落盘（`store/ledger.py:45`）。与 `run.py:1313` 的承诺（「key 只活在浏览器 localStorage」）相反。
- **后果**：密钥持久化在 `data/users/<id>/runs.db`，在队列被 drain/清空前一直存在；进程崩溃时残留；备份/分享数据目录即泄露。

### M8. `/api/lexicon` 无管理员校验，任何账户可清空全机器共用的分词表
- **位置**：`backend/api/lexicon.py:36-52`、`:55-73` — `POST` / `DELETE /api/lexicon`
- **证据**：`runtime/stores.py` 的 `get_lexicon_store()` 是**单例、无账户槽位**（`_LEXICON_STORE` + `_LEXICON_LOCK`），词典落在机器级 `Config.LEXICON_DB`；而同层级的 `/api/settings` 写入口有 `if accounts_mode() and not is_admin(): 403`（`api/settings.py:28-31`）。
- **后果**：任意已登录用户 `DELETE {"kind":"userdict","clear":true}` 即可清空所有账户共用的分词表/停用词并触发进程级 `reload_userdict()`，**直接改变其他账户后续所有分词、词云、主题分析的结果**，且不可追溯。

### M9. `/api/settings`、`/api/models` 向普通账户返回机器级配置与绝对路径
- **位置**：`backend/api/settings.py:21-23`（GET）、`backend/api/config.py:51-56, 74-83`
- **证据**：写入口有 `is_admin()`，读入口没有。
- **后果**：任何登录用户可拿到 `driver_path`、`browser_binary`、`latex_binary`、`catbus_cli`、`browser_profile_dir`、`ollama_host` 与每个模型的绝对 `path`。既是主机指纹，也直接给出 H13 的候选目标。多租户下属于信息越权。

### M10. `/api/workflow/diagnostics` 对缺 `id` 的节点抛未捕获 `KeyError` → 500
- **位置**：`backend/api/diagnostics.py:38`
- **证据**：`eff_nodes = {n['id']: n for n in effective.get('nodes', [])}`，而 `effective_workflow` 只用 `.get` 容忍缺 id，节点会被保留。
- **后果**：`{"nodes":{"a":{"type":"keyword"}}}` 即 HTML 500；前端 `resp.json()` 抛错，画布列徽标整体失效。运行路径已由 `services/runs/payload.py:44-52` 专门校验过同一形状，诊断路由没复用。

### M11. Windows 进程回收把「查无此进程」判定建立在英文文案上
- **位置**：`backend/core/procs.py:99-104` — `reap_process`
- **证据**
  ```python
  tail = (result.stderr or result.stdout or b'').decode('utf-8', 'replace').strip()
  if tail and 'not found' in tail.lower():
      return True, ''
  ```
  两处假设只对英文 Windows 成立：(a) 中文系统输出「错误: 没有找到进程 "1234"。」永不匹配；(b) `taskkill` 的错误文本走系统 ANSI 代码页（cp936），却按 UTF-8 解码。
- **后果**：浏览器恰好已自行退出（停止路径上很常见）时，被判为「没杀掉」，打出 `run.browserReapFailed` 并附带 `\ufffd` 乱码，用户去排查一个不存在的僵尸进程。应改用 `returncode == 128` 或与语言无关的检查。

### M12. `_esc` 把反斜杠转成 `\\`（换行）而不是 `\textbackslash`
- **位置**：`backend/services/charts/tikz_preamble.py:152-158` — `_esc`
- **证据**：`if ch in '\\&%#_{}$': out.append('\\' + ch)`；实测 `_esc(r'C:\data\a.csv')` → `C:\\data\\a.csv`。
- **后果**：`\\` 在 LaTeX 里是换行命令，不是字面反斜杠。题名、期刊名、DOI 后残留的 `\` 会让 `\node{}`/`xticklabels` 报 `There's no line here to end`；即使编译通过也显示为断行。正确做法是 `\textbackslash{}`。

### M13. 聚合出的 NaN 在印刷图里被写成 0，屏幕上是断点
- **位置**：`backend/services/charts/visualizer.py:150-153`（`aggregate`）+ `tikz_preamble.py:171-181`（`_num` 的 `if not math.isfinite(f): return '0'`）
- **触发条件**：`agg='mean'` 且某分组 y 全为空（实测 `['a','a','b'] / [None,None,4]` → 屏幕 `[nan, 4.0]`，LaTeX `(a,0) (b,4)`）。
- **后果**：图上出现一根「0」的柱子，而数据里这个分组根本没测到。`_num` 的「绝不输出 nan」变成了「把缺失伪装成零」，印刷图与屏幕图不一致。

### M14. 论文成稿按标题字典序排序，图号/表号不是运行产生顺序
- **位置**：`backend/services/reports/paper.py:354` — `generate`
- **证据**：`entries.sort(key=lambda item: item['caption'])`，紧随其后 `label=f'fig:cixi-{index}'`。
- **后果**：正文「图 1 支撑论点 A」的编号与运行/预览顺序不符，交叉引用指错图；中文标题按码位排序时顺序近乎随机。`build_document` 的 docstring 承诺的是「运行产生顺序」。

### M15. 抖音「作品数」读成 0 时，空表被当成「作者没发过作品」合法结束
- **位置**：`backend/crawlers/platforms/douyin/crawler.py:546` — `_published_count`（消费点 `:165-173`）
- **证据**：`-1`（未提供）只用「文本为空」判定，但 `parse_count` 对**没有数字的文本**返回 0（`counters.py:73-74`）。计数标签若渲染成「作品」/「暂无作品」或在未 innerText 化的子节点里，即被读成「站点说 0 个作品」。
- **后果**：一次真正的「页面没到位」被判为 `empty`（`LICENSED_ENDS` 成员），节点干净 DONE、0 行、不给「继续」，不足闸门完全静默。

### M16. 知乎搜索/详情绕过 `Crawler.open()`，一次导航超时掀掉整个节点
- **位置**：`backend/crawlers/platforms/zhihu/crawler.py:196`（`search`）、`:830`（`get_detail`）
- **证据**：裸 `self.driver.get(url)`，无 try；`Crawler.open()`/`_navigate` 存在的意义正是把 `page_load_timeout` 降级为 `navigation_settled=False` 并继续轮询（`core/crawler.py:533-540`）。微信 `get_detail`（`wechat/crawler.py:150`）同样。
- **后果**：慢网络/首屏超时时，节点以 traceback 结束（已产出行还在盘上），而不是像其它平台那样按「页面没到位」继续判定；微信批量链接里任意一篇超时会让后续所有链接一条都不采。

---

## 四、低严重度

| # | 位置 | 问题 | 后果 |
|---|---|---|---|
| L1 | `crawlers/core/crawler.py:364-370` `mark_position` | `contextlib.suppress(Exception)` 吞掉游标持久化失败，连日志都没有 | 内存游标前进、磁盘没写，「继续」从更早位置重放整屏，无迹可寻 |
| L2 | `crawlers/engine/counters.py:108-113` `to_int` | `int(float('inf'))` 抛 `OverflowError`，不在捕获列表 | 脏数字把「解析回落」升级成整行构造失败 |
| L3 | `crawlers/engine/times.py:151-154` `absolute` | CJK 日期分支未保护 `datetime()` 构造，`2024年02月30日`/`24:00` 抛 `ValueError` | 一条坏日期让该行/该节点崩 |
| L4 | `crawlers/platforms/douyin/comments.py:61` | 点赞用 `line.isdigit()`，`1.2万` 判 False 被整行忽略 | 热门评论点赞数写 0 |
| L5 | `crawlers/platforms/xiaohongshu/comments.py:82-85` | `re.search(r'\d+')` 取数，`1.2万` 读成 1 | 点赞数误差 4 个数量级，排序结论反向 |
| L6 | `core/config.py:22` | `CRAWLER_DATA_ROOT` 不做 `expanduser`/`abspath` | `~`/相对路径静默落到 CWD，重启后「数据不见了」 |
| L7 | `core/refs.py:87` `split_urls` | 按逗号切分，`?ids=1,2,3` 被切成三条 | 一条真实链接变三条，报「链接不支持」 |
| L8 | `core/config.py:56` | `SECRET_KEY` 有公开固定默认值，拒绝启动的判断只在 `app.py:90` 导入期 | 任何不经 `app.py` 构造 Flask 的入口会用公开常量签发 session cookie |
| L9 | `services/ingest/parts.py:162` | CSV 分片重读只吞 `OSError`，`EmptyDataError`/`ParserError` 属 `ValueError` 族（JSON 分支却写了 `ValueError`） | 续跑纳入半截分片 → 整次导出失败，与注释承诺相反 |
| L10 | `services/runs/settlement.py:217` | `settle_nodes` 与 `finish_run` 同一 try，前者失败即跳过后者 | 记录停在「运行中」，续跑横幅不出现，控制台原因指向错误位置 |
| L11 | `services/ingest/catbus.py:525` | 超时提示硬编码 `RUN_TIMEOUT`(900)，而 `--version` 探针是 30 s、preflight 是 120 s | 30 秒就断了却告诉用户「超时 900 秒」，排障方向被引向网络慢 |
| L12 | `capabilities/model.py:22` `_int` | `int(float('1e400'))` 抛 `OverflowError`，未捕获 | `<input type=number>` 输入 `1e400` → 采集节点以裸 traceback 失败 |

---

## 五、潜在风险（逻辑可疑，条件未证实）

> 这些不是「可能有问题」，而是「代码形状明确有问题、但触发条件依赖运行环境或数据分布」。建议按此清单逐条复核后升级定级。

### P1. 运行 id 未转义进内联 `onclick`，一旦来源变化即成跨账户存储型 XSS
- **位置**：`backend/static/js/panels/runs.js:518,523,524,527,530,531,537,541`（同表 `data-run-id` 用了 `escapeHtml`，说明作者知道这是数据）
- **为什么暂不列为高危**：`resume_run_id` 虽在 `engine/run.py:1255` 被直接采信，但 `services/runs/payload.py:67-77` 的 `resume_refusal` 会在 `begin_run:1196` 拒绝**不存在**的 run id；运行记录又按账户分库（`data/users/<id>/runs.db`，`runs` 表无 `user_id` 列）。因此当前无法凭空造出一条含恶意 id 的记录。
- **风险仍在**：`resume_refusal` 在 store 抛异常时 `return ''`（放行）；`api/runs.py` 的 rerun 路由、未来任何「按名字派生 id」的改动，都会让同一条拼接线立刻可被利用。同文件已有现成的 `attrJsArg`（`data-views.js:491`）可用。

### P2. 队列非 `drop` 拒绝可能活锁，占满全员队列
- **位置**：`services/runs/queue.py:344-352` `drain_queue` → `put_back(entry)`（插回下标 0）
- **说明**：`begin_run` 对形状/模板/模式/`继续`失效都带 `'drop': True`，所以主要剩余路径是「槽位被抢占」（瞬时、正确）。但只要出现任一条**永久性且不带 drop** 的 400/409（例如未来新增的校验），它就会永远占据队首，每次有运行结束都重试一次，其他账户的请求永远轮不到（`QUEUE_MAX` 是全局的）。

### P3. `RunStore.__init__` 以「无 owner 限制」结算整库 running 行
- **位置**：`services/runs/store/base.py:235`（`_ensure_tables` → `promote_stale_runs()`，`only=None`）
- **说明**：启动时这是正确语义，但它是**构造函数副作用**。任何一次 `release_user` → 重开、或第二个实例指向同一目录，都会把仍在写的运行标成 `interrupted` 并 `settle_nodes` 成 `partial`——而 `partial` 正是「续跑可复用」的状态，一次误结算可能让「继续」拿到半张表。`queue.py` 的镜像路径（`_save_owner_mirror`）也会触发这条链。

### P4. 数据集缓存按引用返回，调用方原地修改污染后续所有读者
- **位置**：`backend/runtime/stores.py:325` `_load_dataset`（命中即 `return cached`，不 copy）
- **说明**：仓内已有原地修改先例（`datasets/merge.py:73-75` 的 `frame.insert(0, ...)`）。一旦某消费者对返回值做 `df['x']=...`，缓存、预览接口与后续所有 run 都会看到被改过的表，而 `datasets.db` 里是干净的——同一会话两次预览可能不一致。缓存键已按账户隔离，所以不是串户，是同账户脏读。

### P5. `DatasetStore.put` 不拒绝重复列名，静默丢列并让不同文件撞同一 id
- **位置**：`backend/services/datasets/store.py:206` `put`（配合 `safe_records:67` 的 `df.to_dict('records')`）
- **说明**：pandas 对重复列名只发一条 `UserWarning`，`to_dict('records')` 会**丢掉**前面同名列的值；而 `columns` 列表保留两份，读回时两列都填第二列的值。`content_id` 基于丢失后的记录计算，两份内容不同的表会得到同一 id，`put` 返回 `stored=False` 并复用先存那份。
- **复核方式**：`DatasetStore.put(pd.DataFrame([[1,2]], columns=['a','a']))` 后 `get()`。

### P6. `/api/project/import` 与 xlsx 上传的「解压膨胀」无上限
- **位置**：`services/workflows/bundle.py:373-380`（2 GiB 解压上限 / 单文件 512 MiB）、`api/data.py:94-107`
- **说明**：`MAX_CONTENT_LENGTH` 只拦**上传字节**；一个几十 MB 的 deflate 包可声明 2 GiB，单个 512 MiB 的 JSON 会被整体 `read` + `decode` + `json.loads` + `DataFrame(records)`，内存数倍膨胀。任一已登录账户即可把进程内存打满（OOM killer 会杀掉整个服务，中断所有账户的运行）。无账户级配额或并发限制。

### P7. 排序/聚类类图表在退化输入上产出「假图」或直接编译失败
- **位置**：`services/charts/tikz_console.py:170-195` `_box`（`ymin==ymax` → pgfplots 除零）、`:247-257` `_heatmap`（负值生成 `cA!-55` → xcolor 致命错误）、`:584` `_map`/`:303` `_topic_map`（`math.sqrt(负数)` → `ValueError`，被 `outputs.py:90` 的宽 `except` 变成一句 `latex_error='math domain error'`）
- **说明**：均可由真实数据触发（评分列全相同、情感指数含负值）。用户既拿不到图也不知道要改什么。

### P8. 前端「面板级列表」普遍没有 in-flight 保护
- **位置**：`panels/biblio.js:284/296`、`panels/files.js:203`、`panels/exports.js:48`、`panels/cookies.js:835` 均无 `_loadSeq`/`AbortController`（全站零 `AbortController`）
- **说明**：`runs.js`、`run-results.js`、`data-views.js` 已有成熟的序号守卫，这几处没有。可复现一例：`biblio.js` 连点两次「下一页」，两个 `load()` 并发，后落地者按自己的 `offset` 写 `_table`，而 `render()` 读的是已推进的 `this._offset`——页码是第 3 页、内容是第 2 页的行。

### P9. 抖音热榜沿用「搜索结果卡」作为到达判据
- **位置**：`crawlers/platforms/douyin/crawler.py:268` `hot` → `:446` `_wait_for_page` → `:513` `_card_ids`
- **说明**：`CARD_ANCHOR = '[data-e2e="scroll-list"] a[href*="/video/"]'` 是搜索结果的形状，而热榜条目通常指向 `/hot/<sentence>`；`_page_outcome` 返回的 `NOT_MOUNTED` 在 `hot()` 里没有分支，等不到也不会提前退出，一直耗到 `PAGE_WAIT_TIMEOUT=300`。同文件 `_harvest_pool` 的注释自己记录过这个坑。

### P10. 红果评论滚动循环无预算上限
- **位置**：`crawlers/platforms/hongguo/harvest.py:302-335` `HongguoCommentHarness.walk`
- **说明**：终止条件只看「服务端说还有」和用户 `limit`；`stalled` 只统计「页面没来」，任何**来了但没有新评论**的页面都会把它清零。若抽屉 cursor 不前进/重复下发同一页（本仓 `pager.py:5-9` 已记录过这类服务端行为），循环无上界，`limit=0`（默认不限）时节点永不结束。

---

## 六、值得保留的部分（避免修复时误伤）

- **SQL 注入面干净**：`services/` 全量检索只有 4 处 f-string，全部是常量白名单（`base.py` 的 `_ADDED_COLUMNS`、`ledger.py` 的占位符个数与固定表名元组）；`ORDER BY`/`LIMIT` 全走绑定参数，日志搜索用 `instr(line, ?)` 而非 LIKE 拼接。唯一可加固处是 `progress.py:390` 的 `cache_clear(prefix + '%')`——前缀里的 `%`/`_` 会被当通配符，是**范围超出**而非注入。
- **鉴权做得扎实**：scrypt、`MAX_PASSWORD_LENGTH` 前置拦截、未知用户也 `burn_unknown_password`（防用户名枚举计时）、先验证口令再报「锁定」（防状态探测）、`must_change_password` 白名单、session cookie HttpOnly + SameSite=Lax + `HTTPS_ONLY` 时才 Secure。
- **Origin 守门与 CORS**：`_origin_is_local` 用 `urlsplit` 解析 host 而非子串匹配，正则 end-anchored 挡住 `localhost.evil.com`，且 `before_request` 直接 403（不只靠 ACAO 拦读）。
- **路径清洗**：导出/工作流名过 `sanitize_filename` 且限长 60，模板 id 过 `^r-[0-9a-f]{12}$`，bundle 条目过 `^(workflows|datasets|templates)/\d{3}\.json$` 再 `archive.getinfo`——`..`、绝对路径都进不来（`refs.py:217` 的设备名问题是边角，见 L8 同族）。
- **前端表格渲染**：`data-views.js:604` 的单元格走 `escapeHtml`，没有把爬取正文直接塞进 `innerHTML`（这是最容易出 XSS 的地方，作者做对了）。

---

## 七、建议修复顺序

1. **今天**：H1（aggression 正则）— 一行改动，止住仍在污染数据的指标；同时把该列已产出的历史结论标注为不可信。
2. **本周**：H2 / H3 / H4（丢数据与必崩）、H6 / H7 / H8 / H9（静默错误结果）、H10（画布原子写）。
3. **本迭代**：H5（TikZ 转义，涉安全）、H11（死锁）、H12（要在「让并行真正生效」与「删掉这套并修正文案」之间做决定，不能维持现状）、H13（SSRF）。
4. **随后**：M 系列按「影响分析结论」优先（M1/M2/M3/M4/M5 都是错误的表值），再处理权限与资源类（M8/M9/M6/M7）。
5. 建议把 H1/H2/H6/H7 各补一条**断言数据真实性**的用例——它们共同的特征是「没有任何测试在检查结果是不是真的」。

---

## 八、修复状态（2026-11-01）

按类别分次提交，顺序与上文一致：

| 提交 | 类别 | 覆盖条目 |
|---|---|---|
| `0395092` | 采集链 | H2 H3 H4 M15 M16 L1 L2 L3 L4 L5 |
| `5c235c4` | 分析器 | H1 H6 H7 M1 M2 |
| `15bfba8` | 图表与报告 | H5 M12 M13 M14 P7 |
| `8e32160` | 存储 / 并发 / 安全 | H10 H11 H12 H13 M6 M7 M10 M11 |
| `81d24bd` | 设置权限 | M8 M9（并按用户要求：设置只有管理员可改，其他账号只读） |
| `67a0bcf` | 收尾 | L6 L7 L9 L10 L11 L12 P1 P2 P5 |

### 已修复并补了回归用例（51 条中的 40 条）

高 13 条里 12 条已修（H12 见下方说明）、中 16 条全修、低 12 条中 10 条已修（L8 见下方）、
潜在风险里 P1 / P2 / P5 / P7 已修。每条都补了断言「结果是不是真的」的用例：

- `tests/unit/analysis/test_aggression.py` —「这个小学生」「100元」「今天路很堵」全部回到 `none`，
  真实地址形状仍判 severe。
- `tests/unit/crawlers/test_comments.py` — 毫秒/负数/越界时间戳返回空串而不是崩掉；
  小红书楼层跨屏接续；`1.2万` 解析成 12000。
- `tests/unit/charts/test_latex_charts.py` — 类目名不再进入坐标：逗号不再破坏二元组，
  `}` 不再能开出 TeX 命令（断言输出的坐标里只有 `c1..cN`）。
- `tests/unit/runs/test_task_executor.py` — 重写为守护「停止句柄」这一真实职责。
- `tests/api/test_accounts_api.py` — 普通账号读设置拿不到主机路径、写被 403；
  词典同样；无账户的单机模式仍可写。
- `tests/unit/frontend/test_frontend_app_state_js.py` — 面板在只读态下控件 disabled、
  不发写请求、显示说明行；管理员态恢复。

### 有意未改动的 4 条

- **L8（`SECRET_KEY` 的公开默认值）** — 这是被测试钉住的设计，不是漏洞：
  `tests/api/test_privacy_leaks.py` 明确 pin 了「出厂默认值必须是公开常量」，
  而 `api/auth.startup_error()` 拒绝在「有密码 + 仍用默认密钥」时启动；cloud 模式还额外
  拒绝无密码启动。改动它会同时打破文档、README 和这条 tripwire。真正需要的是「任何新建的
  入口都要调用 `startup_error()`」，建议作为独立议题处理。
- **P3（`RunStore.__init__` 在构造时结算全库 running 行）** — 修它等于改变「启动时结算」与
  「使用中重开」的语义边界，需要把结算收进显式启动钩子并重排 `queue.py` 的镜像路径，
  属于一次重构而非缺陷修补；改动面比其余各项加起来还大。
- **P9（抖音热榜沿用搜索结果卡作到达判据）** — 判据取决于热榜页实际 DOM 形状，
  本仓无法验证；贸然改会引入「榜单还没挂载就提前退出」。需要一次真站观察再定。
- **P10（红果抽屉滚动循环无预算）** — 循环终止条件与服务端 cursor 行为绑定，
  需要真站复现才能定出「无新行」的正确轮数上限，否则会把「采不满」变成「提前结束」。

### 仍未处理的 6 条（非缺陷，属于加固建议）

P4（数据集缓存返回引用、建议返回拷贝）、P6（导入包/表格的解压膨胀上限）、
P8（biblio/files/exports/cookies 面板列表缺 in-flight 序号守卫）、
以及报告正文提到的：`cache_clear` 的 LIKE 前缀应按 `substr` 比较、
`accounts_mode()` 是实时判断（运行中移走 `accounts.db` 会静默关闭鉴权）、
`.svg` 下载仅靠黑名单过滤。这些都不改变当前已确认的错误行为，
建议作为下一轮加固，不作为本轮修复的一部分。
