"""Server-side message catalogue (zh / en) for everything the console shows.

Console output reaches the browser through three pipes — ``add_log()``,
``logging`` (via LogBufferHandler) and ``print()`` (via LogTee) — and it used
to be hardcoded, half in Chinese and half in English depending on which file
emitted it. Every user-visible line now goes through :func:`t`, which renders
it in the language of whoever triggered the run:

- HTTP requests carry ``X-Lang`` (the frontend patches ``fetch`` once, so
  every call gets it for free).
- A workflow runs in its own thread(s), and thread-locals are not inherited,
  so the language captured when the run starts is re-applied in each worker
  thread explicitly.

Unknown keys render as the key itself: a missing translation shows up loudly
in the console instead of silently falling back to a foreign language.
"""

import logging
import re
import threading

logger = logging.getLogger(__name__)

# printf-style placeholders ('%s', '%(name)d') that str.format cannot fill.
_BAD_PLACEHOLDER = re.compile(r'%(?:\(\w+\))?[#0-9+.-]*[sdfgrx]')

DEFAULT_LANG = 'zh'
LANGS = ('zh', 'en')

_local = threading.local()


# ─── Catalogue ──────────────────────────────────────────────────
# Keys are grouped by the emitter: wf.* (workflow engine / app.py),
# llm.* (analyzers/llm_client.py), crawl.<platform>.* (crawlers), and
# misc.* / analysis.* for the rest. The two tables must stay in sync —
# ``missing_keys()`` checks that in the tests.

_ZH = {
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] 正在执行节点：{nid}（{ntype}）',
    'wf.node_failed': '[{wf}] 节点 {nid} 执行失败：{err}',
    'wf.unnamed': '未命名工作流{i}',
    'wf.node_completed': '[{wf}] 节点 {nid} 完成（{done}/{total}）',
    'wf.multi_input': '节点 {nid} 有 {n} 条上游连线，主输入取第一条（来自 {up}）；合并表用第二条当右表',
    'wf.validation_error': '校验错误：{err}',
    'wf.found': '发现 {n} 条工作流',
    'wf.starting': '开始执行工作流「{name}」',
    'wf.component_indexed': '{name}（第 {i}/{n} 条）',
    # No 'wf.completed' / 'wf.all_completed': `run.finished` says how the run
    # ended and carries the node counts, so a second sentence could only disagree.
    # One line per failure, and it says where the detail is: the log handler
    # forwards every logger call to the console, so the pair of messages this
    # replaced printed the same sentence twice.
    'wf.exec_exception': '执行失败，完整堆栈见服务端日志',
    'wf.wf_exception': '工作流「{wf}」执行失败，完整堆栈见服务端日志',
    # These refusals are printed by the executor as the node's own failure
    # (「节点 X 执行失败：…」), so they state the reason only — a second
    # 「分词失败：」/「可视化失败：」 inside them repeats the wrapper, and the node
    # used to be logged twice: once here without a name, once attributed.
    'wf.analysis_step': '[分析] {op}：{before} → {after} 行',
    'wf.analysis_step_removed': '（-{removed}）',
    'wf.analysis_step_nochange': '（无变化）',
    'wf.tokenize_no_column': '未配置要分词的文本列',
    'wf.tokenize_no_input': '没有上游数据，请连接数据源或文件上传节点',
    'wf.tokenize_no_col': '列“{col}”不在 {cols} 中',
    'wf.tokenize_done': '[分词] {mode} 已切分 {col} → {n} 行',
    'wf.visualize_no_input': '没有上游数据，请连接数据源或文件上传节点',
    'wf.visualize_done': '[可视化] 已渲染 {chart} 图表（{engine}），共 {n} 行',
    'wf.browser_opened': '已打开浏览器用于 {platform} 登录（{url}），等待 {n} 秒完成登录…',
    'wf.cookies_generated': '已生成 {platform} 的 Cookie（{n} 项）',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API Key 未填写',
    'llm.no_model': 'OpenRouter 模型名未填写',
    'llm.ollama_pkg_missing': 'ollama 包不可用：{err}',
    'llm.ollama_empty': 'Ollama 返回了空内容',
    'llm.ollama_fail_attempt': 'Ollama 调用失败（尝试 {i}/{n}）：{err}',
    'llm.ollama_exception': 'Ollama 调用异常（尝试 {i}/{n}）：{err}',
    'llm.ollama_failed': 'Ollama（{model}）调用失败：{err}',
    'llm.no_ollama_model': 'Ollama 模型名未填写（AI → 模型，可点“刷新”读取本地已拉取的模型）',
    'llm.ollama_unreachable': '连不上 Ollama 服务 {host}——请确认 ollama 已启动、服务地址正确：{err}',
    'llm.ollama_client_failed': 'Ollama 客户端初始化失败（{host}）：{err}',
    'llm.ollama_model_missing': 'Ollama 本地没有模型“{model}”——请在面板中改选一个已拉取的模型（{err}）',
    'llm.ollama_http': 'Ollama 拒绝请求（{code}）：{err}',
    'llm.net_error': '网络错误：{err}',
    'llm.or_net_exception': 'OpenRouter 网络异常（尝试 {i}/{n}）：{err}',
    'llm.or_bad_format': 'OpenRouter 响应格式异常：{err}',
    'llm.or_empty': 'OpenRouter 返回了空内容',
    'llm.or_401': 'OpenRouter：API Key 无效（401），请检查密钥',
    'llm.or_402': 'OpenRouter：余额不足（402）——免费模型不需要余额，请改选 :free 模型',
    'llm.or_404': 'OpenRouter：模型不存在（404）——"{model}"，请重新选择模型',
    'llm.or_429': 'OpenRouter：触发限流（429）——免费模型为共享额度，建议减小并发',
    'llm.or_429_wait': 'OpenRouter 429 限流（尝试 {i}/{n}），等待 {wait} 秒',
    'llm.or_5xx': 'OpenRouter 服务端错误（{code}）',
    'llm.or_5xx_attempt': 'OpenRouter {code}（尝试 {i}/{n}）',
    'llm.or_http_fail': 'OpenRouter 请求失败（{code}）：{body}',
    'llm.or_failed': 'OpenRouter 调用失败',
    'llm.checkpoint_loaded': '断点续跑：载入 {n} 行已完成结果（{file}）',
    'llm.cancelled': '已手动停止——已完成的行均已保存，可修复后从断点续跑',
    'llm.parse_failed': '[{label}] 第 {i}/{total} 行输出解析失败（连续失败 {f}）',
    'llm.row_exception': '[{label}] 行处理异常：{err}',
    'llm.row_done': '[{label}] 第 {done}/{total} 行完成',
    'llm.progress': '[{label}] 进度 {done}/{total}（已保存）',
    'llm.circuit_break': '连续 {f} 行调用失败——疑似网络断开 / Key 失效 / 模型不可用，本节点已中止。'
    '已完成 {done}/{total} 行并全部保存，恢复后重新执行会自动从断点续跑。',
    'llm.node_done': '[{label}] 节点完成 {done}/{total} 行',
    'llm.missing_column': 'DataFrame 缺少必需的列“{col}”——{label} 节点失败，请检查文本列配置',
    'llm.no_rows': '[{label}] 没有需要处理的行（“{col}”列为空）。',
    'llm.start': '[{label}] 共 {total} 行待处理，调用方式：{transport}（每条数据一次询问，文本越长越耗 token）',
    # Neither line carries the failure text: the executor states it once, attributed
    # to the node. These two say only what that line cannot — what survived.
    'llm.aborted': '[{label}] 已完成 {done} 行，结果已保存',
    'llm.stopped': '[{label}] 已停止，已完成行的结果已保存',
    'llm.unfinished': '[{label}] {n} 行未处理（标记为 {mark}）。重新执行同一节点将从断点续跑，只补这些行。',
    # ── upload node ───────────────────────────────────────────
    'upload.no_file': '文件上传节点未选择文件，请在节点设置里上传 CSV / JSON / TXT',
    'upload.stale': '已上传的数据集失效（服务可能重启过），请重新上传文件',
    'upload.loaded': '已载入上传文件 {name}：{n} 行',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': '清洗',
    'label.emotion': '情感分析',
    'label.tendency': '倾向性分析',
    'label.ner': '实体识别',
    'ner.dropped': '实体识别：{n} 条模型答案未在原文中出现，已丢弃（不记录推测出的实体）',
    # ── node type labels (console fallbacks; mirror frontend app.js) ──
    'node.name': '工作流命名',
    'node.source': '数据源',
    'node.upload': '上传文件',
    'node.process': '处理',
    'node.analysis': '分析',
    'node.visualize': '可视化',
    'node.tokenize': '分词',
    'node.output': '输出',
    'node.resume': '断点续跑',
    'node.comment': '评论采集',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': '开始搜索知乎关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.zhihu.authorStart': '[知乎] 采集作者「{author}」的回答与文章，目标 {n} 条',
    'crawl.zhihu.authorEmpty': '[知乎] 没有填写作者（主页链接或 /people/ 后面的 id）：{author}',
    'crawl.zhihu.authorTabEmpty': '[知乎] 作者「{author}」的「{tab}」标签页没有内容（这类作品他确实没发过），跳过',
    'crawl.zhihu.authorTabDone': '[知乎] 「{tab}」标签页采集结束，累计 {n} 条（原因：{reason}）',
    'crawl.zhihu.fallbackSearch': '知乎深链搜索返回空壳，改用搜索框重新提交关键词',
    'crawl.zhihu.emptyOrBlocked': (
        '知乎搜索页未返回任何结果（触发风控/登录墙或页面失效）：'
        '请在执行设置中关闭无头模式，或稍后重试；已采集的数据不受影响'
    ),
    'crawl.cookiesSeeded': 'Cookie 预置：{host} 接受 {n}/{total} 条',
    # Observation only — never a claim about what the crawl then did. This line is
    # written by ``check_login_wall``, which cannot know the caller's policy: weibo
    # and zhihu stop, while WeChat's batch skips that one article and carries on to
    # the next. Saying 「已停止本次抓取」 there told the user their batch had ended.
    # The stop, when it happens, is announced by the node refusing with
    # ``run.cookieExpired``, which also says what to do about it.
    'crawl.loginWall': '登录墙：{platform} 的 {where} 被重定向到登录页',
    'crawl.riskBlocked': '风控拦截：{platform} 的 {where} 返回了安全验证而非内容（会话未必失效，稍后重试）',
    'crawl.promptDismissed': '{label} 的首屏弹窗已自动点掉：「{button}」',
    'crawl.promptUnmatched': '{label} 的首屏弹窗无法对应按钮（页面提供：{buttons}），本次可能需等待其自动消失',
    'crawl.zhihu.url': '搜索URL: {url}',
    'crawl.zhihu.loaded': '搜索页面已加载，开始滚动加载更多内容...',
    'crawl.zhihu.processed': '已处理第 {i} 条结果，当前有效数据: {n} 条',
    'crawl.zhihu.skipped': '第 {i} 条结果无有效内容，已跳过',
    'crawl.zhihu.process_error': '处理第 {i} 条结果时出错: {err}',
    'crawl.zhihu.finished': '搜索完成，共获取 {n} 条有效结果（目标 {total} 条）',
    'crawl.zhihu.scrolling': '滚动第 {i} 次，等待内容加载...',
    'crawl.zhihu.no_more': '检测到"没有更多了"，停止滚动（滚动 {i} 次）',
    'crawl.zhihu.scroll_round': '滚动第 {i} 次完成，当前卡片数: {n} 条（目标: {total} 条）',
    'crawl.zhihu.target_reached': '已达到目标数量 {n} 条，停止滚动',
    'crawl.zhihu.stuck': '连续 {n} 次滚动未加载新内容，停止滚动',
    'crawl.zhihu.no_growth': '卡片数未增长 ({n}/3)，再次滚动确认...',
    'crawl.zhihu.confirmed': '二次确认后卡片数仍为 {n}，内容已加载完毕',
    'crawl.zhihu.phase_done': '滚动加载阶段完成，最终获取 {n} 个卡片',
    # One fact, one line: what the 正文 column actually holds. The search page only ever
    # carries an excerpt, so a crawl that did not expand has to say so once at the end.
    'crawl.zhihu.excerpt_only': '未展开正文：本次所有正文都是搜索页摘要（可在数据源节点勾选「展开全文」）',
    'crawl.zhihu.bodies_short': '另有 {n} 条回答未能展开，其正文仍为搜索页摘要',
    'crawl.zhihu.expand_stopped': '连续 {n} 次展开均无回应，本次剩余行改用搜索页摘要',
    # ── crawlers: weibo ───────────────────────────────────────
    'crawl.weibo.keyword': '关键词: {kw}',
    'crawl.weibo.range': '时间范围: {start} 至 {end}',
    'crawl.weibo.links': '共生成 {n} 个搜索链接（每小时1个）',
    'crawl.weibo.keyword_plain': '关键词: {kw}（无时间范围，单链接搜索）',
    'crawl.weibo.processing': '正在处理第 {i}/{total} 个搜索链接',
    'crawl.weibo.url': 'URL: {url}',
    'crawl.weibo.link_done': '第 {i} 个链接爬取完成，获取 {n} 条数据',
    'crawl.weibo.accumulated': '当前累计数据: {n} 条',
    'crawl.weibo.visiting': '访问搜索链接: {url}',
    'crawl.weibo.no_result': '该时间段无搜索结果，跳过',
    'crawl.weibo.waiting': '等待页面加载...',
    'crawl.weibo.page_loaded': '页面加载完成',
    'crawl.weibo.total_pages': '检测到总页数: {n}',
    'crawl.weibo.page_crawling': '  正在爬取第 {i}/{total} 页...',
    'crawl.weibo.page_empty': '  第 {i} 页无有效卡片，跳过',
    'crawl.weibo.page_done': '  第 {i} 页爬取完成，共 {n} 条，累计 {total} 条',
    'crawl.weibo.link_error': '处理搜索链接时出错: {err}',
    'crawl.weibo.page_timeout': '    页面加载超时，可能无内容',
    'crawl.weibo.max_page': '最大页码: {n}',
    'crawl.weibo.pages_fail': '获取总页数失败: {err}',
    'crawl.weibo.page_cards': '    本页共发现 {n} 个卡片',
    'crawl.weibo.card_error': '    卡片 {i}: 处理出错，已跳过',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': '未提供 URL，返回空结果。',
    # ── 断点续跑与去重（爬虫侧） ──────────────────────────────
    'crawl.resume_have': '断点续跑：已采集 {n} 条，接着往下采而不是重来',
    'crawl.resume_urls': '断点续跑：沿用上次生成的 {n} 个链接，不重新翻页',
    'crawl.sink_failed': '增量落盘失败（这条仍然在本次结果里，但可能没进库）：{err}',
    'crawl.wechat.duplicate': '跳过重复的推文链接：{url}',
    'crawl.xhs.note_dup': '跳过重复的笔记：{url}',
    'crawl.zhihu.duplicate': '跳过重复的第 {i} 条回答',
    'ds.too_many_rows': '文件共 {n} 行，超过数据集上限 {limit} 行，无法保存',
    'crawl.wechat.batch_start': '开始批量抓取 {n} 篇微信公众号文章',
    'crawl.wechat.processing': '正在抓取第 {i} / {total} 篇',
    'crawl.wechat.url': 'URL: {url}',
    # No 阅读/点赞/打赏: WeChat publishes none of the three to a browser that is not
    # the client (measured), so a line naming them would be a column with a plausible
    # face and no source — and this template once printed its own placeholders,
    # because the call site passed four keywords and the text asked for seven.
    'crawl.wechat.success': '第 {i}/{total} 篇已抓取：《{title}》（{author}）',
    'crawl.wechat.failed': '第 {i}/{total} 篇抓取失败：正文没有取到',
    'crawl.wechat.wait': '等待 1 秒后继续下一篇',
    'crawl.wechat.batch_done': '批量抓取完成：{n} / {total} 篇成功',
    'crawl.wechat.navigating': '正在打开文章链接',
    'crawl.wechat.wait_title': '等待文章标题 (#activity-name) 加载',
    'crawl.wechat.loaded': '文章页面加载成功',
    'crawl.wechat.timeout': '页面加载超时: {url}',
    'crawl.wechat.scroll': '滚动到底部以触发懒加载',
    'crawl.wechat.scroll_done': '滚动完成',
    'crawl.wechat.extracting': '正在提取文章字段',
    'crawl.wechat.title': '标题: {title}',
    'crawl.wechat.author': '作者（公众号）: {author}',
    'crawl.wechat.pub_time': '发布时间: {time}',
    'crawl.wechat.content_len': '正文长度: {n} 字',
    'crawl.wechat.preview': '正文预览: {preview}',
    'crawl.wechat.no_content': '重试后仍未找到正文元素。',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[小红书搜索] 开始搜索关键词: "{kw}"，目标数量: {n}',
    'crawl.xhs.url': '[小红书搜索] 已访问搜索URL: {url}',
    'crawl.xhs.page_ready': '[小红书搜索] 初始搜索结果页加载完成',
    'crawl.xhs.page_timeout': '[小红书搜索] 初始内容加载超时，可能没有搜索结果，将继续尝试滚动',
    'crawl.xhs.links': '[小红书搜索] 共收集到 {n} 条笔记链接',
    'crawl.xhs.note_ok': '[小红书搜索] 成功提取: {title}...',
    'crawl.xhs.note_error': '[小红书搜索] 处理笔记时出错: {err}',
    'crawl.xhs.finished': '[小红书搜索] 搜索完成，共获取 {n} 条有效笔记数据',
    'crawl.xhs.scroll_round': '[收集链接] 第 {i} 次滚动',
    'crawl.xhs.cards': '[收集链接] 滚动后卡片数量: {n}',
    'crawl.xhs.target_reached': '[收集链接] 已达到目标数量 {n}，停止加载',
    'crawl.xhs.no_growth': '[收集链接] 卡片数量未增加，尝试再次滚动...',
    'crawl.xhs.exhausted': '[收集链接] 页面已无更多内容，停止加载',
    'crawl.xhs.collect_done': '[收集链接] 收集完成，共 {n} 条链接',
    'crawl.xhs.detail_visit': '[爬取详情] 正在访问详情页: {url}',
    'crawl.xhs.detail_ready': '[爬取详情] 详情页加载完成',
    'crawl.xhs.detail_timeout': '[爬取详情] 详情页加载超时',
    'crawl.xhs.content_len': '[爬取详情] 正文长度: {n} 字',
    'crawl.xhs.author': '[爬取详情] 作者: {author}',
    'crawl.xhs.pub_time': '[爬取详情] 发布时间: {time}',
    'crawl.xhs.metrics': '[爬取详情] 互动数据 - 点赞: {likes}, 收藏: {favs}, 评论数: {comments}',
    'crawl.xhs.comment_count': '[爬取详情] 评论列表: {n} 条',
    'crawl.xhs.comment_skip': '[提取评论] 预览数=0，跳过评论面板（不等待）',
    'crawl.xhs.comment_start': '[提取评论] 开始提取评论，最多 {n} 条',
    'crawl.xhs.comment_found': '[提取评论] 共找到 {n} 个评论元素',
    'crawl.xhs.comment_error': '[提取评论] 提取第 {i} 条评论时出错: {err}',
    'crawl.xhs.comment_done': '[提取评论] 共提取 {n} 条评论',
    # ── analysis / services ───────────────────────────────────
    'export.done': '已导出 {n} 行至 {path}（{fmt}）',
    'analysis.type_convert_failed': '列 {col} 转换为 {dtype} 失败：{err}',
    'analysis.calc_failed': '计算列 {col} = {expr} 失败：{err}',
    'analysis.bin_failed': '列 {col} 分箱失败：{err}',
    'analysis.col_missing': '未找到列“{col}”',
    'cluster.not_enough': '有效行数不足，无法聚类（至少需要 2 行）',
    'cluster.dbscan': 'DBSCAN 发现 {n} 个簇 + {noise} 个噪声点',
    'cluster.done': '聚类完成：{rows} 行分为 {clusters} 簇（轮廓系数={score:.3f}）',
    'anomaly.no_numeric': '没有可用于异常检测的数值列',
    'anomaly.no_usable_columns': '异常检测：你指定的列都不是数值列（{columns}）',
    'anomaly.ignored_columns': '异常检测：以下列不是数值列，已跳过（{columns}）',
    'anomaly.too_few': '行数过少（{n} < {min}），异常检测无法给出结论',
    'anomaly.done': '异常检测：{n}/{total} 行被标记（contamination={c:.2f}）',
    'corr.need_cols': '相关性分析至少需要 2 个数值列',
    'corr.no_usable_columns': '相关性分析：你指定的列都不是数值列（{columns}）',
    'corr.ignored_columns': '相关性分析：以下列不是数值列，已跳过（{columns}）',
    'corr.done': '相关性分析（{method}）：找到 {n} 对（min_abs={min_abs:.2f}）',
    'ml.model_missing': '模型 {name} 未训练且无已保存模型——回退为默认值',
    'ml.missing_col': 'DataFrame 缺少必需的列“{col}”。跳过分析。',
    'ml.no_rows': '没有需要处理的行（目标列为空）。',
    'ml.emotion_failed': 'ML 情感预测失败：{err}——回退为 Neutral',
    'ml.tendency_failed': 'ML 倾向性预测失败：{err}——回退为 Objective Statement',
    'ml.emotion_done': '[ML] 情感分类完成，共处理 {n} 行，模式: ML',
    'ml.tendency_done': '[ML] 倾向性分析完成，共处理 {n} 行，模式: ML',
    'cookie.saved': '已保存 {platform} 的 Cookie',
    'cookie.started': '已启动登录浏览器，请在弹出的窗口完成登录，然后点「已完成登录」',
    'cookie.jobCancelled': '{platform} 登录已取消',
    'cookie.windowClosed': '登录窗口被关闭，未捕获 Cookie；请重新发起登录',
    'cookie.noCookies': '等待结束仍未获得 Cookie——若登录未完成，请重试',
    'cookie.droppedForeign': (
        '已忽略 {n} 条不属于 {platform} 的 Cookie：登录常会经过第三方站点，它们不进本平台的 Cookie 文件'
    ),
    'cookie.allForeign': '{platform} 的 Cookie 一条都没保存：粘贴的内容全属于其它站点，请粘贴该平台自身的 Cookie',
    # ── Cookie 用途与获取步骤（面板直接把这些讲给用户） ──────────
    'cookie.zhihu.purpose': '解锁知乎搜索结果与回答、评论正文；未登录时知乎常常只回一个登录引导页。',
    'cookie.zhihu.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录知乎（扫码或手机号）\n'
        '2. 随便翻一页，确认右上角已是你的头像\n'
        '3. 回到本面板点「已完成登录」'
    ),
    'cookie.weibo.purpose': '解锁微博搜索（s.weibo.com）与评论 JSON 接口；未登录会被跳回 passport 二维码页。',
    'cookie.weibo.steps': (
        '1. 点「浏览器生成」，在窗口里登录微博\n2. 手动搜一次关键词，能看到微博列表即可\n3. 回到本面板点「已完成登录」'
    ),
    'cookie.bilibili.purpose': '解锁 B 站搜索、视频详情与评论区；未登录时搜索会被折叠，评论只给前几条。',
    'cookie.bilibili.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录哔哩哔哩（扫码或手机号）\n'
        '2. 打开任意视频并滚到评论区，能看到评论列表即可\n'
        '3. 回到本面板点「已完成登录」'
    ),
    'cookie.douyin.purpose': '解锁抖音网页版搜索、视频文案与评论区；未登录常常只给首屏且看不到评论。',
    'cookie.douyin.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录抖音网页版（扫码或手机号）\n'
        '2. 打开任意视频，右侧能看到评论区即可\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：抖音网页版对自动化浏览器较敏感，若窗口里出现滑块验证，请在窗口内手动完成后再保存。'
    ),
    'crawl.dy.start': '[抖音搜索] 开始搜索关键词: "{kw}"，目标 {n} 条（抖音只接受可见窗口，已自动改用可见窗口）',
    'crawl.dy.target_reached': '[抖音] 已达到目标数量 {n} 条，停止',
    'crawl.dy.round': '[抖音] 第 {i} 屏：{n} 张卡片（新 {fresh} 个，已收录 {done} 条）',
    'crawl.dy.processed': '[抖音] 已收录视频 {i}，当前有效数据: {n} 条',
    'crawl.dy.finished': '[抖音搜索] 搜索完成，共获取 {n} 条有效结果（目标 {total} 条，翻了 {rounds} 屏）',
    'crawl.dy.authorStart': '[抖音作者] 开始采集该作者的作品，目标 {n} 条（计数要逐条打开视频页取）',
    'crawl.dy.authorEmpty': '[抖音作者] 没有给出作者（粘贴 douyin.com/user/… 链接或那串 sec_uid）：{author}',
    'crawl.dy.authorNoWorks': '[抖音作者] 该作者的主页自报作品数为 0，本就没有可采集的内容',
    'crawl.dy.authorDone': '[抖音作者] 作品列表采集结束，共 {n} 条（主页自报 {works} 条）',
    'crawl.dy.authorDoneNoCount': '[抖音作者] 作品列表采集结束，共 {n} 条（主页未给出作品数，无法判断是否已到末尾）',
    'crawl.dy.authorNoCards': (
        '[抖音作者] 该作者主页始终没有渲染出作品列表，本次未采集。页面自报：{page}；地址：{url}。'
        '主页自报作品数 {works} 条，所以这是被拦截或页面出错，不是「这个人没发过作品」'
    ),
    'crawl.dy.authorNotMounted': (
        '[抖音作者] 该作者主页既没有渲染出作品列表、也没有给出作品数，本次未采集。'
        '页面自报：{page}；地址：{url}。这两种缺省同时出现只可能是被拦截或页面出错'
    ),
    'crawl.dy.wall': (
        '[抖音] 浏览器被挡在「验证码中间页」：抖音网页版对无头浏览器与频繁请求都会弹验证。'
        '请确认已在 Cookie 面板用「可见窗口」登录并保存，稍后再重试本关键词'
    ),
    'crawl.dy.detailEmpty': '[抖音] 视频 {i} 的详情页没有渲染出数据，已跳过该行',
    'crawl.dy.noCards': (
        '[抖音] 结果页始终没有给出任何视频卡片，本次未采集。页面自报：{page}；地址：{url}。'
        '抖音对根本不存在的关键词也会用相关视频兜底，所以「零卡片」只可能是被拦截或页面出错，'
        '不是「这个关键词没有结果」'
    ),
    'crawl.bili.start': '[哔哩哔哩搜索] 开始搜索关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.bili.url': '[哔哩哔哩搜索] 搜索URL: {url}',
    'crawl.bili.page': '[哔哩哔哩搜索] 第 {page} 页：{n} 个视频（新 {fresh} 个，已收录 {done} 条）',
    'crawl.bili.empty_page': '[哔哩哔哩搜索] 第 {page} 页没有视频卡片，停止翻页',
    'crawl.bili.no_more': '[哔哩哔哩搜索] 连续两页都是已抓过的视频，列表已到末尾（第 {page} 页）',
    'crawl.bili.processed': '[哔哩哔哩搜索] 已收录 {i}，当前有效数据: {n} 条',
    'crawl.bili.duplicate': '[哔哩哔哩搜索] {i} 已存在于本次运行，跳过',
    'crawl.bili.target_reached': '[哔哩哔哩搜索] 已达到目标数量 {n} 条，停止翻页',
    'crawl.bili.authorStart': '[哔哩哔哩] 采集 UP主 {mid} 的投稿视频，目标 {n} 条',
    'crawl.bili.hotStart': '[哔哩哔哩] 采集{board}，目标 {n} 条（榜单接口自带全部数字，不逐条请求）',
    'crawl.bili.hotPage': '[哔哩哔哩] 榜单第 {page} 页：{n} 条（新 {fresh} 条，已收录 {done} 条）',
    'crawl.bili.hotDone': '[哔哩哔哩] 榜单采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.bili.boardPopular': '热门榜',
    'crawl.bili.boardRanking': '周排行榜',
    'crawl.bili.authorEmpty': '[哔哩哔哩] 没有填写 UP主（space.bilibili.com 链接或数字 mid）：{author}',
    'crawl.bili.authorNoVideos': '[哔哩哔哩] UP主 {mid} 的投稿列表没有渲染出视频（可能真的没投过稿）',
    'crawl.bili.authorDone': '[哔哩哔哩] 投稿列表采集结束，共 {n} 条（原因：{reason}）',
    'crawl.bili.finished': '[哔哩哔哩搜索] 搜索完成，共获取 {n} 条有效结果（目标 {total} 条）',
    'crawl.bili.blocked': (
        '[哔哩哔哩] 接口拒绝返回数据（code={code}）：Cookie 可能已失效或触发了风控，'
        '请在 Cookie 面板重新登录并保存后继续运行'
    ),
    'crawl.platformNotCrawlable': '该平台目前只支持保存登录 Cookie，还不支持采集（{platform}）——'
    '请先改用已支持的平台，或等待该平台的抓取实现完成',
    'cookie.xiaohongshu.purpose': '解锁小红书搜索、笔记正文与评论；未登录会撞登录墙且只给首屏。',
    'cookie.xiaohongshu.steps': (
        '1. 点「浏览器生成」，在窗口里登录小红书\n2. 打开任意一篇笔记，能看到评论区即可\n3. 回到本面板点「已完成登录」'
    ),
    'cookie.twitter.purpose': (
        '解锁 X（推特）的搜索、用户时间线、推文正文与回复；未登录时这些页面基本只回一个登录引导页。'
    ),
    'cookie.twitter.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录 x.com（账号密码或手机号+验证码）\n'
        '2. 随便打开一条推文，确认回复区能加载出来（auth_token 与 ct0 两条 Cookie 缺一不可）\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：X 对新设备登录常会追加一次验证码，请在同一个窗口里做完再保存。'
    ),
    'cookie.instagram.purpose': '解锁 Instagram 的博主帖子、标签页与评论；未登录时页面只给登录墙，接口也会拒绝。',
    'cookie.instagram.steps': (
        '1. 点「浏览器生成」，在窗口里登录 instagram.com\n'
        '2. 打开任意一个帖子页，能看到评论区即可\n'
        '3. 回到本面板点「已完成登录」\n'
        '提示：若登录被转到 Facebook，请等它回到 Instagram 之后再点保存。'
    ),
    'cookie.youtube.purpose': (
        '解锁 YouTube 的订阅、播放列表、历史记录与评论；未登录也能看公开视频，但这些页面常被限流或折叠。'
    ),
    'cookie.youtube.steps': (
        '1. 点「浏览器生成」，在弹出的 Chrome 窗口里登录 YouTube（Google 账号）\n'
        '2. 回到 youtube.com 首页，确认右上角已是你的头像\n'
        '3. 回到本面板点「已完成登录」——保存前浏览器会自动回到 YouTube 页面，'
        'Google 账号自身的 Cookie 不会被写进本平台文件'
    ),
    'cookie.entryRejected': (
        '该链接不属于 {platform} 的域名，已改用平台登录页（不允许把别的站点的 Cookie 存进本平台的 Cookie 文件）'
    ),
    'cookie.verifying': '正在用已保存的 Cookie 试探该平台…',
    'cookie.verifyFailed': '验证失败：{err}',
    'cookie.verify.ok': '{platform} 的 Cookie 可用',
    'cookie.verify.loginWall': '{platform} 仍被挡在登录页：请重新登录并保存',
    'cookie.verify.noCookie': '{platform} 还没有 Cookie：请先登录保存',
    'cookie.verify.checkedUrl': '验证地址：{url}',
    # 运行前自动验证（cookie_preflight）：三条结论对应三种下一步，合并任何一条都会把
    # 用户支到错误的动作上——重新登录，或者什么也不做地等待。
    'cookie.pre.valid': '{platform} 的 Cookie 可用',
    'cookie.pre.expired': '{platform} 的 Cookie 已失效：页面被弹回登录页',
    'cookie.pre.unknown': '{platform} 的 Cookie 无法核对（不代表有效，本次不拦截）',
    'cookie.pre.noLogin': '{platform} 的抓取不需要登录',
    'cookie.pre.notCrawlable': '{platform} 目前只能取 Cookie，还不能采集',
    'cookie.pre.notListed': '这个平台谁都不认识，没有验证：{platform}',
    'cookie.pre.busy': '{platform} 的浏览器正被占用',
    'cookie.pre.timeout': '验证超时（{n} 秒）',
    'cookie.pre.riskControl': '页面回的是验证码/风控',
    'cookie.verify.unclear': '{platform} 的验证没有结论：页面回的是验证码/风控，与 Cookie 是否有效无关',
    'cookie.delete.none': '{platform} 没有已保存的 Cookie 可删除',
    'cookie.delete.profileHolds': '注意：{platform} 的浏览器 profile 仍是登录状态，删这个文件不会把它登出',
    'cookie.delete.failed': '删除 Cookie 文件失败：{err}',
    'api.platformsRequired': 'platforms 字段必须是平台名列表',
    'api.cookieBusy': '已有 {platform} 的登录窗口打开中——请先完成或取消它',
    'api.bodyNotObject': '请求体必须是 JSON 对象',
    'api.paramInvalid': '参数 {name} 无效',
    'api.payloadTooLarge': '请求体超过上限 {limit} MB，请分割后重试',
    'api.workflowNameRequired': '缺少有效的工作流名称',
    'api.fieldTypeInvalid': '字段 {name} 类型不正确',
    'api.stepsMustBeObjects': 'steps 必须是对象列表，每项含 "op" 与可选 "params"',
    'api.noCookieJob': '当前没有进行中的登录窗口',
    'cookie.deleted': '已删除 {platform} 的 Cookie',
    'store.workflow_saved': '工作流已保存：{path}',
    'store.dataset_saved': '文件已持久化：{name}（{rows} 行，id {did}）',
    'store.datasets_bound': '工作流 {wf} 已绑定 {n} 个上传文件',
    'ds.corrupt': '数据集 {did} 读不出来（记录已损坏），请重新上传',
    'ds.purged': '已清理 {days} 天未使用且无工作流引用的文件：{n} 个',
    'ds.purge_result': '清理孤立文件 {n} 个，保留 {kept} 个仍在使用的文件',
    'ds.cleared': '已清空全部已保存文件：{n} 个',
    'ds.rebound': '按文件名重新接上数据集 {name}（{did}）——工作流可以直接跑了',
    'ds.missing': '工作流引用的上传文件已不在库中：{name}',
    'api.datasetMissing': '没有这个已保存的数据集：{did}',
    'api.datasetNameInvalid': '这个名称不能用作数据集名（去掉路径字符后为空）：{name}',
    'api.datasetInUse': '这些已保存的工作流仍在引用该文件，删除后它们会变成空数据源：{workflows}',
    'api.datasetTooBig': '文件太大没法存：{err}',
    'history.recorded': '「{wf}」已记录 {n} 条历史指标',
    'history.run_deleted': '执行历史：删除运行 {rid} 的 {n} 条记录',
    'executor.task_failed': '任务失败：{err}',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': '记录执行历史失败（不影响流程）',
    'misc.save_workflow_failed': '保存工作流失败',
    'misc.i18nAudit': '文本目录有问题（不影响运行，但请修复）：{issue}',
    'misc.exportDeleteFailed': '无法删除导出文件 {name}：{err}',
    'misc.cookie_save_failed': '保存 Cookie 失败',
    'misc.cookie_gen_failed': '生成 Cookie 失败',
    'misc.studio_source_failed': '图表工坊合并载入：来源读取失败',
    'misc.source_probe_failed': '数据源探测失败',
    'misc.studio_saved': '图表工坊已保存 {path}（{bytes} 字节）',
    'misc.browser_open_failed': '无法打开浏览器：{err}',
    'misc.server_starting': '爬虫工作流服务启动，端口 {port}',
    'misc.visualize_failed': '图表渲染失败：{err}',
    'misc.export_failed': '导出文件写入失败',
    # ── 爬虫内部的调试信息 ────────────────────────────────────
    # 这些走 logging.debug，默认级别下不打印；仍走 i18n，别让控制台里
    # 混进写死的中文/英文。
    'crawl.cookies_failed': '{platform}：载入 Cookies 失败（{err}），本次爬取可能因未登录而结果为空',
    'crawl.xhs.untitled': '无标题',
    'crawl.debug.title_missing': '未找到标题元素',
    'crawl.debug.content_missing': '未找到正文元素',
    'crawl.debug.author_missing': '未找到作者/公众号元素',
    'crawl.debug.time_missing': '未找到发布时间元素',
    'crawl.debug.comments_missing': '评论区域未加载或不存在',
    'crawl.debug.comment_item': '第 {i} 条评论：{author} - {text}...',
    'crawl.debug.card_skip': '卡片 {i}：跳过（无发布者）',
    'crawl.debug.card_author': '卡片 {i}：发布者="{v}"',
    'crawl.debug.card_time': '卡片 {i}：发布时间="{v}"',
    'crawl.debug.card_len': '卡片 {i}：正文长度={v}',
    'crawl.debug.card_metrics': '卡片 {i}：转发={f} 评论={c} 点赞={l}',
    'crawl.debug.card_images': '卡片 {i}：图片={n} 张',
    'crawl.debug.pager_missing': '未检测到分页按钮，只有一页',
    'crawl.debug.content_retry': '正文未提取到，稍后重试一次',
    # ── 参数校验 / 接口错误（会直接显示在提示条里） ────────────
    'crawl.weibo.bad_date': '日期格式不对：{value}（应为 YYYY-MM-DD）',
    'crawl.weibo.need_both_dates': '开始时间与结束时间必须同时填写（只填一个会被忽略，搜索范围会完全不同）',
    'crawl.weibo.bad_range': '结束时间（{end}）必须晚于开始时间（{start}）',
    'chart.count': '数量',
    'ml.no_training_rows': '没有可用的训练数据：所有行的文本或标签都是空的',
    'ml.need_two_labels': '训练至少需要 2 个不同的标签，当前只有：{label}',
    'cluster.no_features': '文本无法分词（可能只有符号），已跳过聚类：{err}',
    'engine.source_no_platform': '节点 {nid}：数据源节点没有选择平台',
    'engine.source_unknown_platform': '节点 {nid}：{platform} 还没有可用的采集实现，请改用已支持的平台',
    'engine.source_unknown_mode': '节点 {nid}：{platform} 没有这种采集内容，请在该节点的「采集内容」里改选一种',
    'engine.source_missing': '节点 {nid}：必填项「{field}」还没有填写',
    'engine.source_link_mismatch': '节点 {nid}：{n} 个链接与所选平台（{platform}）不符',
    'field.keyword': '关键词',
    'field.urls': '文章链接',
    'field.author': '作者',
    'engine.upload_no_file': '节点 {nid}：上传节点还没有选择文件',
    'engine.comment_no_urls': '节点 {nid}：评论节点还没有填写文章链接',
    # The supported list is generated from the comment router's own domain table,
    # because that table is what actually decides the answer — naming the platforms
    # in the sentence left two messages that kept claiming the old four long after
    # the fifth landed.
    'comment.no_urls': '评论节点没有可抓取的链接（支持：{platforms}）',
    'comment.unsupported': '评论节点忽略了 {n} 个不支持的链接（仅支持：{platforms}）',
    'comment.noAdapter': '{platform} 还没有评论抓取实现，该链接无法处理：{url}',
    'comment.commentsClosed': '该内容未开放评论区（或未产生评论）：{url}',
    'comment.ytNoPage': 'YouTube 页面没有加载成视频页（可能需要登录或被拦截）：{url}',
    'comment.xNoList': '[X 评论] 这条推文页面没有渲染出任何内容（链接失效、被删或被拦截）：{url}',
    # YouTube is crawled as JSON from inside its own page, so its console lines
    # talk about rounds and answers, not about scrolling a list.
    'crawl.yt.noContext': '[YouTube] 页面未提供 innertube 配置（被拦截或结构已变）：{url}',
    'crawl.yt.callFailed': '[YouTube] {endpoint} 接口调用失败',
    'crawl.yt.badAnswer': '[YouTube] {endpoint} 返回 {status}，非 JSON',
    'crawl.yt.wall': '[YouTube] 触发了人机验证页：{url}',
    'crawl.yt.searchStart': '[YouTube] 关键词「{kw}」，目标 {n} 条',
    'crawl.yt.authorStart': '[YouTube] 作者「{author}」的作品，目标 {n} 条',
    'crawl.yt.authorEmpty': '[YouTube] 没有填写作者（@handle、频道链接或 UC… ID）：{author}',
    'crawl.yt.authorNotFound': '[YouTube] 该地址不是频道主页，读不到频道 ID：{author}',
    'crawl.yt.authorNoVideos': '[YouTube] 该作者的视频页没有作品：{author}',
    'crawl.yt.page': '[YouTube] 第 {page} 轮：{n} 条（{fresh} 条新增，已采 {done}）',
    'crawl.yt.noPage': '[YouTube] 第 {page} 轮没有返回条目，停止翻页',
    'crawl.yt.processed': '[YouTube] 已存第 {i} 条：{title}',
    'crawl.yt.targetReached': '[YouTube] 已达目标 {n} 条，停止采集',
    'crawl.yt.drained': '[YouTube] 接口不再给出下一页游标，列表已到末尾',
    'crawl.yt.replay': '[YouTube] 第 {page} 轮没有新增，判定列表已耗尽',
    'crawl.yt.noResults': '[YouTube] 关键词「{kw}」没有匹配的公开视频（或本次会话被限制）',
    'crawl.yt.finished': '[YouTube] 本次共采集 {n} 条',
    # X（推特）只渲染一个虚拟列表：卡片数不增长而推文一直换血，所以它的日志说
    # 「留住了多少」，不说「页面上有几张卡」。
    'crawl.x.start': '[X] 关键词「{kw}」，目标 {n} 条（最新优先）',
    'crawl.x.target_reached': '[X] 已达目标 {n} 条，停止滚动',
    'crawl.x.authorStart': '[X] 作者「{author}」的推文，目标 {n} 条',
    'crawl.x.authorEmpty': '[X] 没有填写作者（@handle 或主页链接）：{author}',
    'crawl.x.wall': '[X] 被拒绝访问（登录墙或 403）：{url}',
    'crawl.x.loadSlow': '[X] 页面未在预期时间内加载完，已按当前 DOM 继续：{url}',
    'crawl.x.no_cards': '[X] 时间线里一条推文都没有渲染出来（被拦截、关键词过窄或账号无推文）：{url}',
    'crawl.x.finished': '[X] 共保留 {n} 条（结束原因：{reason}）',
    'comment.biliBadAnswer': '哔哩哔哩评论接口未返回数据（code={code}）：{url}',
    'comment.dyNoId': '链接里没有视频 ID，无法抓评论：{url}',
    'comment.dyNoPanel': '评论区没有渲染出来（可能被折叠或需要登录）：{url}',
    'comment.dyNone': '该视频计有 {n} 条评论，页面未展开评论列表：{url}',
    'comment.weiboShowFailed': '[微博评论] 评论接口取不回来（Cookie 可能失效或被限流）：{url}',
    'comment.zhihuNoPanels': '[知乎评论] 这个回答页面上没有评论面板（可能已关闭或未加载）：{url}',
    'comment.prefix': '[评论]',
    'comment.platformMismatch': '已忽略 {n} 个与所选平台（{platform}）不符的链接',
    'comment.allMismatched': '所有链接都与所选平台（{platform}）不符，请检查文章链接',
    'comment.article': '评论：{url} 新增 {n} 条（{status}）',
    'comment.done': (
        '评论采集完成：{urls} 个链接（正常 {ok}、拦截 {blocked}、失效 {dead}），共 {rows} 条评论，输出 {files} 个文件'
    ),
    'comment.status.ok': '正常',
    'comment.status.blocked': '被登录墙/风控拦截',
    'comment.status.dead': '链接不可读',
    'engine.process_no_op': '节点 {nid}：处理节点没有选择操作',
    'engine.output_no_op': '节点 {nid}：输出节点没有选择操作',
    'engine.analysis_no_op': '节点 {nid}：分析节点没有配置操作或步骤',
    'engine.cycle': '工作流存在环，以下节点无法排序：{nodes}',
    # A wire whose end is not on the canvas is not a cycle. Reporting it as one
    # (with an empty node list, which is what the old code produced) sent users
    # hunting a loop that did not exist.
    'engine.dangling_connection': '连线指向画布上不存在的节点：{src} → {dst}',
    # An empty canvas is refused, never "completed": 0/0 nodes with a 已完成 toast
    # reads as a run that worked.
    'engine.empty_canvas': '画布上没有任何节点，没有可运行的工作流',
    'engine.tokenize_no_column': '节点 {nid}：分词节点缺少文本列',
    'engine.visualize_no_chart': '节点 {nid}：可视化节点没有选择图表类型',
    'engine.visualize_no_x': '节点 {nid}：可视化节点缺少 X 字段',
    'engine.name_no_label': '节点 {nid}：命名节点的工作流名称不能为空',
    'engine.name_not_head': '节点 {nid}：命名节点必须打头，不能有上游节点接入',
    'engine.name_no_downstream': '节点 {nid}：命名节点后面必须连接下游节点',
    'wf.unknown_process_op': '使用了未知操作「{op}」',
    'wf.join_no_right_table': '合并表需要两条上游连线：第一条是左表，第二条是右表',
    'analysis.join_no_right': '合并失败：没有拿到右表数据（请把第二条连线接到作为右表的节点）',
    'analysis.join_need_keys': '合并失败：请填写左右两边的关联列',
    'analysis.join_missing_cols': '合并失败：这些列不存在：{cols}',
    'api.alreadyRunning': '已有工作流正在运行，请先停止或等它跑完',
    'api.needApiKey': 'OpenRouter API Key 未填写（设置 → AI）',
    'api.needModel': 'OpenRouter 模型未选择（设置 → AI）',
    'api.needOllamaModel': '未选择 Ollama 模型（设置 → AI → 模型，可点“刷新”读取本地模型）',
    'api.platformRequired': '平台不能为空',
    'api.cookiesRequired': 'Cookies 数据不能为空',
    'api.unsupportedPlatform': '不支持的平台：{platform}',
    'api.llmModelsFailed': '获取 OpenRouter 模型列表失败：{err}',
    'api.ollamaModelsFailed': '读取本地 Ollama 模型列表失败：{host}（请确认 ollama 已启动、服务地址正确）：{err}',
    'api.parseFailed': '文件解析失败：{err}',
    'api.unsupportedUpload': '不支持的文件类型：{name}（可用 .csv .tsv .json .txt .xlsx .xls）',
    'api.columnMissing': '数据里没有这一列：{column}',
    'api.needLabeledRows': '至少需要 10 行带标签的数据，当前只有 {n} 行',
    'api.noSourceTable': '所选节点都没有可用的数据表',
    'api.badRequest': '请求格式不对：{what}',
    # ── 运行时设置校验 ────────────────────────────────────────
    'set.driverMissing': '驱动文件不存在：{path}',
    'set.driverEmpty': '驱动路径为空，已恢复默认值',
    'set.browserMissing': '浏览器程序不存在：{path}',
    'set.badWindow': '窗口大小格式应为 宽x高（如 1920x1080），已恢复默认 {default}',
    'set.badNumber': '{setting} 不是数字，已恢复默认 {value}',
    'set.outOfRange': '{setting} 超出范围 {lo}-{hi}，已恢复默认 {value}',
    'set.badOllamaHost': 'Ollama 地址需以 http:// 或 https:// 开头，已恢复默认',
    'set.badFlag': '{setting} 需要 true/false 值，已恢复默认',
    'set.badProfileDir': '浏览器 Profile 目录必须填绝对路径（收到：{value}），已恢复为内置目录',
    'set.saveFailed': '设置未能写入磁盘（本次会话内仍生效）：{err}',
    # ── 断点续跑（durable run state） ────────────────────────
    'run.row_limit': '节点 {nid} 已达到保存上限 {limit} 行，超出部分不再落库',
    'run.interrupted_by_restart': '服务重启时被打断',
    'run.promoted': '发现 {n} 条上次没跑完的记录，已标记为「可续跑」',
    'run.started': '本次运行已记账：{rid}（随时可中断，数据逐条落库）',
    'run.resume_from': '续跑模式：接着 {at} 那次往下跑，此前已保存 {rows} 行',
    'run.restored': '节点 {nid} 沿用上次结果（{n} 行），不再重跑',
    'run.resume_crawl': '节点 {nid} 从上次中断处继续抓取（已有 {have} 行）',
    'run.recrawl': '重新采集：已释放 {n} 条历史去重记录，本节点将重新抓取',
    'run.dedupe_skipped': '增量采集：{n} 条结果此前已采集，本次被跳过（如需重抓请在采集节点开启「重新采集」）',
    'run.dedupe_all_skipped': (
        '本节点的结果此前已全部采集，本次没有新数据传给下游；'
        '要重抓请在采集节点开启「重新采集」，要用旧数据请从运行记录导出或用断点续跑（Resume）节点续接'
    ),
    'run.progress_file': '分批导出：{file}（{rows} 行，共 {parts} 个分批文件）',
    'run.live_export': '实时导出：{file}（每处理完一批刷新一次，运行结束后保留）',
    'run.live_export_failed': '实时导出写入失败：{err}',
    'run.cookieExpired': (
        '登录态疑似失效：{platform} 的抓取被挡回登录页（COOKIE 可能过期）。'
        '已采集的数据全部保留——请到 设置→Cookie 更新后，用断点续跑从上次中断处继续'
    ),
    'run.cookieExpiredOk': '提示：{platform} 在目标达成后才遇到登录墙，本次数据完整，无需续跑',
    # Only for a comment node whose links came from several platforms and whose own
    # platform field is empty — the message must name what walled, and a hand-written
    # list of platforms the user never crawled reads worse than no list at all.
    'run.cookieAnyPlatform': '所采集的平台',
    'run.forcedVisible': '「{label}」：{platform} 会拦截无头浏览器，本次已自动改用可见窗口运行',
    'run.forcedVisibleComment': (
        '「{platform}」的评论区要真的滚动才能取全（或该站点拒绝无头浏览器），这个链接的评论改用可见窗口采集'
    ),
    'run.platformQueued': (
        '{platform} 正在被另一条工作流采集，本轮改为排队：{n} 秒后开始，'
        '避免同一账号在同一秒内发出两次搜索而被弹到登录页'
    ),
    'run.serialForced': (
        '{platform} 的多条采集强制排队串行执行：同一账号并行翻页必被弹回登录页，'
        '这个平台的串行由站点决定，与错峰设置无关'
    ),
    'run.platformStaggered': (
        '{platform} 与上一条同平台采集错开 {n} 秒后发车：这次没有排队，两条仍可能同时跑，'
        '只是避开同一账号一秒内发出两次搜索'
    ),
    'run.platformGateTimeout': '{platform} 等待采集时段超时（{n} 秒）：可能有浏览器窗口没有关闭',
    'run.queueAbandoned': '{platform} 的排队等待已取消（本次运行已停止）',
    'run.wallRetry': ('{platform} 在第一条数据之前就被弹到登录页，这更像同一账号被两次并发搜索撞了：{n} 秒后重试一次'),
    'crawl.profile_wait': '已排队 {seconds} 秒：这个 profile 同时只能开一个浏览器，{dir}',
    'run.profileOff': '本次执行不使用浏览器 Profile：每次都是全新设备（为让同平台的工作流真并行），Cookie 快照照常导入',
    'crawl.profile_stuck': (
        '等待 profile 释放超时（{seconds} 秒）：{dir} —— 可能有浏览器没被关闭，请在进程面板结束残留的 Chrome 后重试'
    ),
    'crawl.profile_gave_up': '本次运行已停止：不再等待该 profile（{dir}），这次采集就此让路',
    'run.notCrawlable': (
        '「{label}」所在的平台（{platform}）目前只能保存登录 Cookie，还没有采集实现，'
        '因此不能作为数据源运行——请改用已支持的平台，或等该平台的抓取落地'
    ),
    'run.partial_down': '节点 {nid} 中断：已把 {n} 行已完成的结果交给下游',
    'run.failed_down': '节点 {nid} 失败且没有可用数据，下游按空表继续',
    'run.skipped_empty': '节点 {nid} 跳过：上游没有数据',
    'run.finished': '运行结束（{done}/{total} 个节点完成）',
    # Fragments appended to the line above, only when they are true: a run whose
    # numbers are all clean reads as one clean sentence rather than a table of
    # zeroes, while a run that starved or lost a node cannot be mistaken for one.
    'run.finished.skipped': '，{n} 个跳过',
    'run.finished.failed': '，{n} 个失败',
    'run.rejected': '未运行：工作流有 {n} 处问题，见上方提示',
    'resume.no_run': '续跑节点：没有选择运行记录，也没找到可续跑的记录',
    'resume.empty': '续跑节点：运行 {rid} 中「{nid}」没有可读取的数据行',
    'resume.unpicked': '未指定节点',
    'resume.loaded': '续跑节点：载入运行 {rid} 中节点 {nid} 的 {n} 行',
    'api.runNotFound': '找不到运行记录：{rid}',
    'api.exportNotFound': '导出文件不存在（或不允许下载）：{name}',
    # ── 一键报告（自包含 HTML） ───────────────────────────────
    'report.generated': '生成时间',
    'report.default_title': '{name} · 运行报告',
    'report.summary': '本次运行共 {nodes} 个节点，产出 {rows} 行数据，其中 {tables} 个节点有表格。',
    'report.charts': '图表',
    'report.run_facts': '运行信息',
    'report.tables': '数据表',
    'report.conclusion': '结论',
    'report.no_charts': '这些数据还不足以出图。',
    'report.chart_failed': '图表生成失败：{err}',
    'report.chartsFailed': '报告中的图表生成失败，正文与表格照常输出',
    'report.no_rows': '这个节点没有产出任何行。',
    'report.more_rows': '以上为前 {shown} 行，共 {total} 行；完整数据请用导出节点另存 CSV。',
    'report.row_count': '{n} 行 · {cols} 列',
    'report.fact.workflow': '工作流',
    'report.fact.run': '运行编号',
    'report.fact.status': '状态',
    'report.fact.started': '开始',
    'report.fact.finished': '结束',
    'api.reportNoData': '没有可写入报告的数据：请先运行一次工作流，或选择一条运行记录',
    # ── 运行队列 ──────────────────────────────────────────────
    'api.queued': '已排队：当前运行结束后自动开始（第 {at} 位）',
    'api.queueFull': '排队已满（最多 {n} 个），请等当前运行结束或先取消几个',
    'run.queued': '已排队（第 {at} 位）：{name}',
    'run.queuedUnnamed': '未命名工作流',
    'run.queue_started': '队列接续：{name} 开始运行（{rid}）',
    'run.queue_waited': '队列接续失败（已有运行在跑），{name} 重新排队',
    'run.queue_broken': '队列里的 {name} 无法启动，已跳过并继续下一个：{err}',
    'run.queueStartFailed': '排队的运行无法启动',
    'history.cleared': '执行历史已清空',
    'api.workflowShapeInvalid': '工作流内容无法理解：需要带 nodes 列表的对象',
    'api.resumeMissing': '无法继续：运行记录 {rid} 已被清理，继续会变成一次全新的从零采集，请改用「重新运行」',
    'api.historyNoRunId': '没有指定运行 ID，未删除任何执行历史',
    'run.store_unavailable': '本次运行无法开始：运行记录库打不开（磁盘满、文件损坏或被占用），未产生任何记录',
    'run.reportSaved': '报告已生成：{name}（{size} 字节）',
    'run.reportFailed': '报告生成失败：{err}',
    'run.reportConclusionFailed': '结论生成失败，报告已省略结论：{err}',
    # ── 自动清理（housekeeping） ──────────────────────────────
    'housekeeping.done': (
        '自动清理：删除 {runs} 条过期运行记录、{files} 个孤立文件（另回收 {cache} 条模型缓存、{seen} 条去重记录）'
    ),
    'housekeeping.runStoreFailed': '运行记录自动清理失败（不影响本次运行）',
    'housekeeping.datasetStoreFailed': '孤立文件自动清理失败（不影响本次运行）',
}

_EN = {
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] Executing node: {nid} ({ntype})',
    'wf.node_failed': '[{wf}] Node {nid} failed: {err}',
    'wf.unnamed': 'Unnamed workflow {i}',
    'wf.node_completed': '[{wf}] Node {nid} completed ({done}/{total})',
    'wf.multi_input': 'Node {nid} has {n} incoming connections — the first (from {up}) is the primary input',
    'wf.validation_error': 'Validation error: {err}',
    'wf.found': 'Found {n} workflow(s)',
    'wf.starting': 'Starting workflow "{name}"',
    'wf.component_indexed': '{name} (component {i} of {n})',
    # No 'wf.completed' / 'wf.all_completed' here either: see the zh block.
    # One line per failure, and it says where the detail is: the log handler
    # forwards every logger call to the console, so the pair of messages this
    # replaced printed the same sentence twice.
    'wf.exec_exception': 'Execution failed — the traceback is in the server log',
    'wf.wf_exception': 'Workflow "{wf}" failed — the traceback is in the server log',
    # Stated as the reason only: the executor prints these as the node's own
    # failure (「Node X failed: …」), so a "Tokenize failed:" prefix inside them
    # repeats the wrapper, and the pair used to print the same sentence twice —
    # once here with no node named, once attributed.
    'wf.analysis_step': '[Analysis] {op}: {before} -> {after} rows',
    'wf.analysis_step_removed': ' (-{removed})',
    'wf.analysis_step_nochange': ' (no change)',
    'wf.tokenize_no_column': 'no text column is configured for tokenizing',
    'wf.tokenize_no_input': 'no upstream data — connect a data source or an upload node',
    'wf.tokenize_no_col': 'column "{col}" not found in {cols}',
    'wf.tokenize_done': '[Tokenize] {mode} segmented {col} -> {n} rows',
    'wf.visualize_no_input': 'no upstream data — connect a data source or an upload node',
    'wf.visualize_done': '[Visualize] Rendered {chart} chart ({engine}) from {n} rows',
    'wf.browser_opened': 'Browser opened for {platform} login ({url}); waiting {n}s for the user to log in',
    'wf.cookies_generated': 'Cookies generated for {platform} ({n} cookies)',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API key is missing',
    'llm.no_model': 'OpenRouter model name is missing',
    'llm.ollama_pkg_missing': 'ollama package unavailable: {err}',
    'llm.ollama_empty': 'Ollama returned empty content',
    'llm.ollama_fail_attempt': 'Ollama call failed (attempt {i}/{n}): {err}',
    'llm.ollama_exception': 'Ollama call error (attempt {i}/{n}): {err}',
    'llm.ollama_failed': 'Ollama ({model}) call failed: {err}',
    'llm.no_ollama_model': 'No Ollama model set (AI → Model — hit Refresh to list what the daemon has)',
    'llm.ollama_unreachable': 'Cannot reach the Ollama server at {host} — is ollama running? {err}',
    'llm.ollama_client_failed': 'Could not create the Ollama client for {host}: {err}',
    'llm.ollama_model_missing': 'Ollama has no local model "{model}" — pick a pulled one in the panel ({err})',
    'llm.ollama_http': 'Ollama rejected the request ({code}): {err}',
    'llm.net_error': 'Network error: {err}',
    'llm.or_net_exception': 'OpenRouter network error (attempt {i}/{n}): {err}',
    'llm.or_bad_format': 'OpenRouter response malformed: {err}',
    'llm.or_empty': 'OpenRouter returned empty content',
    'llm.or_401': 'OpenRouter: invalid API key (401) — check the key',
    'llm.or_402': 'OpenRouter: out of credit (402) — free models need none, pick a :free model',
    'llm.or_404': 'OpenRouter: model not found (404) — "{model}", pick another one',
    'llm.or_429': 'OpenRouter: rate limited (429) — free models share a quota, lower the concurrency',
    'llm.or_429_wait': 'OpenRouter 429 rate limit (attempt {i}/{n}), waiting {wait}s',
    'llm.or_5xx': 'OpenRouter server error ({code})',
    'llm.or_5xx_attempt': 'OpenRouter {code} (attempt {i}/{n})',
    'llm.or_http_fail': 'OpenRouter request failed ({code}): {body}',
    'llm.or_failed': 'OpenRouter call failed',
    'llm.checkpoint_loaded': 'Checkpoint: loaded {n} finished rows ({file})',
    'llm.cancelled': 'Stopped manually — completed rows are saved; re-run resumes from the checkpoint',
    'llm.parse_failed': '[{label}] Row {i}/{total}: output could not be parsed ({f} in a row)',
    'llm.row_exception': '[{label}] Row processing error: {err}',
    'llm.row_done': '[{label}] row {done}/{total} done',
    'llm.progress': '[{label}] Progress {done}/{total} (saved)',
    'llm.circuit_break': '{f} rows failed in a row — network down / invalid key / model unavailable. '
    'This node is aborted. {done}/{total} rows are finished and saved; re-running resumes from '
    'the checkpoint and only refills the rest.',
    'llm.node_done': '[{label}] Node finished {done}/{total} rows',
    'llm.missing_column': (
        'DataFrame is missing the required column "{col}" — the {label} node failed; check its text-column setting'
    ),
    'llm.no_rows': '[{label}] Nothing to process (column "{col}" is empty).',
    'llm.start': '[{label}] {total} rows queued via {transport} (one request per row — longer text costs more tokens)',
    'llm.aborted': '[{label}] {done} finished rows are saved',
    'llm.stopped': '[{label}] stopped; finished rows are saved',
    'llm.unfinished': '[{label}] {n} rows not processed (marked {mark}). Re-running this node resumes from '
    'the checkpoint and fills only those.',
    # ── upload node ───────────────────────────────────────────
    'upload.no_file': 'Upload node has no file yet — upload a CSV / JSON / TXT in its settings',
    'upload.stale': 'That uploaded dataset is gone (the server may have restarted) — upload the file again',
    'upload.loaded': 'Loaded uploaded file {name}: {n} rows',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': 'Clean',
    'label.emotion': 'Emotion',
    'label.tendency': 'Tendency',
    'label.ner': 'Entities',
    'ner.dropped': 'NER: dropped {n} model answer(s) that do not appear in the source text (nothing is guessed)',
    # ── node type labels (console fallbacks; mirror frontend app.js) ──
    'node.name': 'Workflow Name',
    'node.source': 'Data Source',
    'node.upload': 'Upload File',
    'node.process': 'Process',
    'node.analysis': 'Analysis',
    'node.visualize': 'Visualize',
    'node.tokenize': 'Tokenize',
    'node.output': 'Output',
    'node.resume': 'Resume Run',
    'node.comment': 'Comments',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': 'Searching Zhihu for "{kw}", target {n} results',
    'crawl.zhihu.authorStart': '[Zhihu] collecting answers and articles of "{author}", target {n} rows',
    'crawl.zhihu.authorEmpty': '[Zhihu] no author given (a profile link, or the id after /people/): {author}',
    'crawl.zhihu.authorTabEmpty': (
        '[Zhihu] the "{tab}" tab of "{author}" holds nothing (this kind was never published), skipped'
    ),
    'crawl.zhihu.authorTabDone': '[Zhihu] tab "{tab}" finished, {n} rows so far (stopped because: {reason})',
    'crawl.zhihu.fallbackSearch': (
        'Deep-linked search rendered an empty shell; resubmitting the keyword through the search box'
    ),
    'crawl.zhihu.emptyOrBlocked': (
        'Zhihu search returned nothing (risk control, login wall, or dead page): '
        'turn off headless mode in the run settings, or retry later; collected data is safe'
    ),
    'crawl.cookiesSeeded': 'Cookies seeded: {host} accepted {n}/{total}',
    'crawl.loginWall': 'Login wall: {platform} redirected {where} to a login page',
    'crawl.riskBlocked': 'Risk control: {platform} answered {where} with a security check instead of content',
    'crawl.promptDismissed': '{label}: dismissed the first-run dialog by pressing "{button}"',
    'crawl.promptUnmatched': (
        '{label}: the first-run dialog matched no known button (the page offers: {buttons}),'
        ' this run may wait for it to clear on its own'
    ),
    'crawl.zhihu.url': 'Search URL: {url}',
    'crawl.zhihu.loaded': 'Search page loaded, scrolling for more content...',
    'crawl.zhihu.processed': 'Processed result {i}, valid so far: {n}',
    'crawl.zhihu.skipped': 'Result {i} has no usable content, skipped',
    'crawl.zhihu.process_error': 'Error processing result {i}: {err}',
    'crawl.zhihu.finished': 'Search done: {n} valid results (target {total})',
    'crawl.zhihu.scrolling': 'Scroll #{i}, waiting for content...',
    'crawl.zhihu.no_more': 'Reached "no more content", stopping (after {i} scrolls)',
    'crawl.zhihu.scroll_round': 'Scroll #{i} done, {n} cards so far (target: {total})',
    'crawl.zhihu.target_reached': 'Target of {n} reached, stopping scroll',
    'crawl.zhihu.stuck': '{n} scrolls loaded nothing new, stopping',
    'crawl.zhihu.no_growth': 'Card count did not grow ({n}/3), scrolling once more to confirm...',
    'crawl.zhihu.confirmed': 'Still {n} cards after the second check — content fully loaded',
    'crawl.zhihu.phase_done': 'Scroll phase done, {n} cards in total',
    'crawl.zhihu.excerpt_only': (
        'Bodies left collapsed: every 正文 is a search-page excerpt (tick "Expand full text" on the data source node)'
    ),
    'crawl.zhihu.bodies_short': '{n} answer(s) did not expand; their 正文 is still a search-page excerpt',
    'crawl.zhihu.expand_stopped': (
        '{n} expansions in a row answered nothing; keeping search-page excerpts for the rest of this crawl'
    ),
    # ── crawlers: weibo ───────────────────────────────────────
    'crawl.weibo.keyword': 'Keyword: {kw}',
    'crawl.weibo.range': 'Time range: {start} to {end}',
    'crawl.weibo.links': 'Built {n} search links (one per hour)',
    'crawl.weibo.keyword_plain': 'Keyword: {kw} (no time range, single search link)',
    'crawl.weibo.processing': 'Processing search link {i}/{total}',
    'crawl.weibo.url': 'URL: {url}',
    'crawl.weibo.link_done': 'Link {i} done, {n} rows collected',
    'crawl.weibo.accumulated': 'Total collected so far: {n}',
    'crawl.weibo.visiting': 'Visiting search link: {url}',
    'crawl.weibo.no_result': 'No results in this time window, skipping',
    'crawl.weibo.waiting': 'Waiting for the page to load...',
    'crawl.weibo.page_loaded': 'Page loaded',
    'crawl.weibo.total_pages': 'Detected {n} pages in total',
    'crawl.weibo.page_crawling': '  Crawling page {i}/{total}...',
    'crawl.weibo.page_empty': '  Page {i} has no usable cards, skipping',
    'crawl.weibo.page_done': '  Page {i} done: {n} rows, {total} accumulated',
    'crawl.weibo.link_error': 'Error processing search link: {err}',
    'crawl.weibo.page_timeout': '    Page load timed out, possibly empty',
    'crawl.weibo.max_page': 'Max page number: {n}',
    'crawl.weibo.pages_fail': 'Could not determine page count: {err}',
    'crawl.weibo.page_cards': '    Found {n} cards on this page',
    'crawl.weibo.card_error': '    Card {i}: error while processing, skipped',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': 'No URLs provided, returning empty results.',
    # ── resume and dedupe (crawler side) ────────────────────────
    'crawl.resume_have': 'Resuming: {n} item(s) already collected, continuing instead of starting over',
    'crawl.resume_urls': 'Resuming: reusing the {n} link(s) of the last attempt, no re-paging',
    'crawl.sink_failed': 'Incremental save failed (this row is still in the results, but may not be stored): {err}',
    'crawl.wechat.duplicate': 'Skipping a duplicate article link: {url}',
    'crawl.xhs.note_dup': 'Skipping a duplicate note: {url}',
    'crawl.zhihu.duplicate': 'Skipping duplicate answer #{i}',
    'ds.too_many_rows': 'the file has {n} rows, over the dataset limit of {limit} — it cannot be stored',
    'crawl.wechat.batch_start': 'Starting batch scrape of {n} WeChat article(s)',
    'crawl.wechat.processing': 'Scraping article {i} / {total}',
    'crawl.wechat.url': 'URL: {url}',
    'crawl.wechat.success': 'Article {i}/{total} scraped: "{title}" ({author})',
    'crawl.wechat.failed': 'Article {i}/{total} failed: no body was retrieved',
    'crawl.wechat.wait': 'Waiting 1 s before the next article',
    'crawl.wechat.batch_done': 'Batch scrape complete: {n} / {total} succeeded',
    'crawl.wechat.navigating': 'Navigating to article URL',
    'crawl.wechat.wait_title': 'Waiting for article title (#activity-name) to load',
    'crawl.wechat.loaded': 'Article page loaded successfully',
    'crawl.wechat.timeout': 'Page load timed out for: {url}',
    'crawl.wechat.scroll': 'Scrolling to bottom to trigger lazy loading',
    'crawl.wechat.scroll_done': 'Scroll complete',
    'crawl.wechat.extracting': 'Extracting article fields',
    'crawl.wechat.title': 'Title: {title}',
    'crawl.wechat.author': 'Author (official account): {author}',
    'crawl.wechat.pub_time': 'Publish time: {time}',
    'crawl.wechat.content_len': 'Content length: {n} characters',
    'crawl.wechat.preview': 'Content preview: {preview}',
    'crawl.wechat.no_content': 'Content element not found after retry.',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[XHS search] Searching for "{kw}", target {n} notes',
    'crawl.xhs.url': '[XHS search] Opened search URL: {url}',
    'crawl.xhs.page_ready': '[XHS search] Initial results page loaded',
    'crawl.xhs.page_timeout': '[XHS search] Initial content timed out — may be no results, still scrolling',
    'crawl.xhs.links': '[XHS search] Collected {n} note links',
    'crawl.xhs.note_ok': '[XHS search] Extracted: {title}...',
    'crawl.xhs.note_error': '[XHS search] Error processing note: {err}',
    'crawl.xhs.finished': '[XHS search] Done, {n} valid notes collected',
    'crawl.xhs.scroll_round': '[Collect links] Scroll #{i}',
    'crawl.xhs.cards': '[Collect links] Cards after scroll: {n}',
    'crawl.xhs.target_reached': '[Collect links] Target of {n} reached, stopping',
    'crawl.xhs.no_growth': '[Collect links] Card count did not grow, scrolling again...',
    'crawl.xhs.exhausted': '[Collect links] No more content on the page, stopping',
    'crawl.xhs.collect_done': '[Collect links] Done, {n} links collected',
    'crawl.xhs.detail_visit': '[Note detail] Opening detail page: {url}',
    'crawl.xhs.detail_ready': '[Note detail] Detail page loaded',
    'crawl.xhs.detail_timeout': '[Note detail] Detail page timed out',
    'crawl.xhs.content_len': '[Note detail] Content length: {n} characters',
    'crawl.xhs.author': '[Note detail] Author: {author}',
    'crawl.xhs.pub_time': '[Note detail] Publish time: {time}',
    'crawl.xhs.metrics': '[Note detail] Engagement - likes: {likes}, saves: {favs}, comments: {comments}',
    'crawl.xhs.comment_count': '[Note detail] Comments: {n}',
    'crawl.xhs.comment_skip': '[Comments] preview is 0, panel skipped (no wait)',
    'crawl.xhs.comment_start': '[Comments] Extracting up to {n} comments',
    'crawl.xhs.comment_found': '[Comments] Found {n} comment elements',
    'crawl.xhs.comment_error': '[Comments] Error extracting comment {i}: {err}',
    'crawl.xhs.comment_done': '[Comments] Extracted {n} comments',
    # ── analysis / services ───────────────────────────────────
    'export.done': 'Exported {n} rows to {path} ({fmt})',
    'analysis.type_convert_failed': 'Type conversion failed for column {col} -> {dtype}: {err}',
    'analysis.calc_failed': 'Column calc failed for {col} = {expr}: {err}',
    'analysis.bin_failed': 'Binning failed for {col}: {err}',
    'analysis.col_missing': 'Column "{col}" not found',
    'cluster.not_enough': 'Not enough valid rows for clustering (need >= 2)',
    'cluster.dbscan': 'DBSCAN found {n} clusters + {noise} noise points',
    'cluster.done': 'Clustering completed: {rows} rows into {clusters} clusters (silhouette={score:.3f})',
    'anomaly.no_numeric': 'No numeric columns available for anomaly detection',
    'anomaly.no_usable_columns': 'Anomaly detection: none of the columns you named holds numbers ({columns})',
    'anomaly.ignored_columns': 'Anomaly detection: skipped the non-numeric columns ({columns})',
    'anomaly.too_few': 'Too few rows ({n} < {min}) — anomaly detection cannot reach a conclusion',
    'anomaly.done': 'Anomaly detection: {n}/{total} rows flagged (contamination={c:.2f})',
    'corr.need_cols': 'Need at least 2 numeric columns for correlation analysis',
    'corr.no_usable_columns': 'Correlation: none of the columns you named holds numbers ({columns})',
    'corr.ignored_columns': 'Correlation: skipped the non-numeric columns ({columns})',
    'corr.done': 'Correlation analysis ({method}): {n} pairs found (min_abs={min_abs:.2f})',
    'ml.model_missing': 'Model {name} not trained and no saved model found — falling back to default',
    'ml.missing_col': 'DataFrame is missing the required column "{col}". Skipping analysis.',
    'ml.no_rows': 'Nothing to process (the target column is empty).',
    'ml.emotion_failed': 'ML emotion prediction failed: {err} — falling back to Neutral',
    'ml.tendency_failed': 'ML tendency prediction failed: {err} — falling back to Objective Statement',
    'ml.emotion_done': '[ML] Emotion classification done, {n} rows, mode: ML',
    'ml.tendency_done': '[ML] Tendency analysis done, {n} rows, mode: ML',
    'cookie.saved': 'Cookies saved for {platform}',
    'cookie.started': 'Login browser opened — finish the login in that window, then press Done',
    'cookie.jobCancelled': '{platform} login cancelled',
    'cookie.windowClosed': 'The login window was closed before cookies could be captured; start again',
    'cookie.noCookies': 'No cookies captured before the wait ended — retry if the login was unfinished',
    'cookie.droppedForeign': (
        'Ignored {n} cookie(s) that do not belong to {platform}: a login usually passes through a '
        'third-party site, and those cookies do not go into this platform’s file'
    ),
    'cookie.allForeign': (
        'Nothing was saved for {platform}: every cookie in that paste belongs to another site — paste the '
        'cookies of this platform itself'
    ),
    # ── cookie purposes and how to obtain them (shown in the panel) ──
    'cookie.zhihu.purpose': 'Unlocks Zhihu search plus answer and comment bodies; logged out, Zhihu often '
    'returns nothing but a login prompt.',
    'cookie.zhihu.steps': (
        '1. Press "Generate via Browser" and sign in to Zhihu in the Chrome window that opens (QR or phone)\n'
        '2. Browse one page and confirm your own avatar is in the top-right\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.weibo.purpose': 'Unlocks Weibo search (s.weibo.com) and the comment JSON API; logged out you are '
    'bounced back to the passport QR page.',
    'cookie.weibo.steps': (
        '1. Press "Generate via Browser" and sign in to Weibo in that window\n'
        '2. Search one keyword and confirm the post list renders\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.bilibili.purpose': 'Unlocks Bilibili search, video metadata and comments; logged out, search is '
    'collapsed and only the first few comments show.',
    'cookie.bilibili.steps': (
        '1. Press "Generate via Browser" and sign in to Bilibili in the Chrome window (QR or phone)\n'
        '2. Open any video and scroll to the comment area until the list renders\n'
        '3. Come back here and press "Done \u2014 I logged in"'
    ),
    'cookie.douyin.purpose': 'Unlocks Douyin web search, video captions and comments; logged out you usually '
    'get only the first screen and no comments.',
    'cookie.douyin.steps': (
        '1. Press "Generate via Browser" and sign in to Douyin web in that window (QR or phone)\n'
        '2. Open any video until the comment panel on the right renders\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: Douyin is quick to raise a slider captcha for automated browsers \u2014 finish it in that '
        'window before saving.'
    ),
    'crawl.dy.start': '[Douyin search] keyword "{kw}", target {n} rows (Douyin only answers a visible window)',
    'crawl.dy.target_reached': '[Douyin] target of {n} rows reached, stop',
    'crawl.dy.round': '[Douyin] screen {i}: {n} cards ({fresh} new, {done} collected)',
    'crawl.dy.processed': '[Douyin] stored video {i}, {n} valid rows so far',
    'crawl.dy.finished': '[Douyin search] done, {n} valid rows (target {total}, {rounds} screens walked)',
    'crawl.dy.authorStart': "[Douyin author] one creator's posts, target {n} (counters cost a page each)",
    'crawl.dy.authorEmpty': '[Douyin author] no author given (paste a douyin.com/user/… link or the sec_uid): {author}',
    'crawl.dy.authorNoWorks': '[Douyin author] the profile publishes 0 posts, so there is nothing to collect',
    'crawl.dy.authorDone': '[Douyin author] post list finished, {n} rows (the profile publishes {works})',
    'crawl.dy.authorDoneNoCount': '[Douyin author] post list finished, {n} rows (the profile published no count)',
    'crawl.dy.authorNoCards': (
        '[Douyin author] the profile never rendered its post grid, so nothing was collected. The page said: '
        '{page}; URL: {url}. The profile publishes {works} posts, so this is a blocked or broken page — '
        'not an author who posted nothing'
    ),
    'crawl.dy.authorNotMounted': (
        '[Douyin author] the profile rendered no post grid and published no post count, so nothing was collected. '
        'The page said: {page}; URL: {url}. Both defaults at once means blocked or broken'
    ),
    'crawl.dy.wall': (
        '[Douyin] the browser was parked on the captcha interstitial: Douyin web serves it to headless '
        'browsers and to bursty requests. Re-save the cookie through the Cookie panel (visible window) '
        'and retry this keyword a little later'
    ),
    'crawl.dy.detailEmpty': '[Douyin] video {i} rendered no detail data, row skipped',
    'crawl.dy.noCards': (
        '[Douyin] the result page never handed over a single video card, so nothing was collected. '
        'The page said: {page}; URL: {url}. Douyin fills the list with related videos even for a keyword '
        'that cannot exist, so zero cards means blocked or broken — never "this keyword found nothing"'
    ),
    'crawl.bili.start': '[Bilibili search] keyword "{kw}", target {n} results',
    'crawl.bili.url': '[Bilibili search] URL: {url}',
    'crawl.bili.page': '[Bilibili search] page {page}: {n} videos ({fresh} new, {done} collected)',
    'crawl.bili.empty_page': '[Bilibili search] page {page} has no video cards, stop paging',
    'crawl.bili.no_more': '[Bilibili search] two pages in a row held nothing new, list exhausted (page {page})',
    'crawl.bili.processed': '[Bilibili search] stored {i}, {n} valid rows so far',
    'crawl.bili.duplicate': '[Bilibili search] {i} already in this run, skipped',
    'crawl.bili.target_reached': '[Bilibili search] target of {n} rows reached, stop paging',
    'crawl.bili.authorStart': '[Bilibili] collecting uploads of UP {mid}, target {n} rows',
    'crawl.bili.hotStart': '[Bilibili] collecting the {board}, target {n} rows (items carry their own figures)',
    'crawl.bili.hotPage': '[Bilibili] board page {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.bili.hotDone': '[Bilibili] board finished, {n} rows (target {total})',
    'crawl.bili.boardPopular': 'popular feed',
    'crawl.bili.boardRanking': 'weekly ranking',
    'crawl.bili.authorEmpty': '[Bilibili] no UP given (a space.bilibili.com link or a numeric mid): {author}',
    'crawl.bili.authorNoVideos': '[Bilibili] the upload list of UP {mid} rendered no video (possibly none published)',
    'crawl.bili.authorDone': '[Bilibili] upload list finished, {n} rows (stopped because: {reason})',
    'crawl.bili.finished': '[Bilibili search] done, {n} valid rows (target {total})',
    'crawl.bili.blocked': (
        '[Bilibili] the endpoint refused to answer (code={code}): the cookie likely died or risk control '
        'kicked in — re-save the cookie in the Cookie panel, then resume this run'
    ),
    'crawl.platformNotCrawlable': 'This platform only supports storing a login cookie so far, not crawling '
    '({platform}) \u2014 use a supported platform, or wait for its crawler to land',
    'cookie.xiaohongshu.purpose': 'Unlocks Xiaohongshu search, note bodies and comments; logged out you hit the '
    'login wall and only the first screen shows.',
    'cookie.xiaohongshu.steps': (
        '1. Press "Generate via Browser" and sign in to Xiaohongshu in that window\n'
        '2. Open any note and confirm the comment area renders\n'
        '3. Come back here and press "Done — I logged in"'
    ),
    'cookie.twitter.purpose': 'Unlocks X (Twitter) search, user timelines, tweet bodies and replies; logged out '
    'those pages answer with a login wall.',
    'cookie.twitter.steps': (
        '1. Press "Generate via Browser" and sign in to x.com in the Chrome window (password or phone code)\n'
        '2. Open any tweet until the replies render — both auth_token and ct0 have to be present\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: X often asks a new device for one more verification code — finish it in that window before saving.'
    ),
    'cookie.instagram.purpose': 'Unlocks Instagram profiles, hashtag grids and comments; logged out the page shows '
    'a login wall and its endpoints refuse the request.',
    'cookie.instagram.steps': (
        '1. Press "Generate via Browser" and sign in to instagram.com in that window\n'
        '2. Open any post until the comment area renders\n'
        '3. Come back here and press "Done \u2014 I logged in"\n'
        'Note: if the login detours through Facebook, wait until Instagram is back before saving.'
    ),
    'cookie.youtube.purpose': 'Unlocks YouTube subscriptions, playlists, history and comments; public videos play '
    'without a login, but those pages are throttled or collapsed.',
    'cookie.youtube.steps': (
        '1. Press "Generate via Browser" and sign in to YouTube (a Google account) in the Chrome window\n'
        '2. Return to the youtube.com home page and check your avatar is showing\n'
        '3. Come back here and press "Done \u2014 I logged in" — the browser is pulled back to YouTube first, '
        'so the Google account\u2019s own cookies never land in this platform\u2019s file'
    ),
    'cookie.entryRejected': 'That link is not on a {platform} domain, so the platform login page was used instead '
    '(another site\u2019s cookies must never be stored in this platform\u2019s cookie file)',
    'cookie.verifying': 'Probing this platform with the stored cookie\u2026',
    'cookie.verifyFailed': 'Verification failed: {err}',
    'cookie.verify.ok': 'The stored {platform} cookie works',
    'cookie.verify.loginWall': '{platform} still redirects to a login page: log in again and save',
    'cookie.verify.noCookie': 'No {platform} cookie stored yet: log in and save first',
    'cookie.verify.checkedUrl': 'Verified against: {url}',
    # The pre-run check (cookie_preflight). Three conclusions, three next steps: merging
    # any pair would send the user off doing the wrong thing — re-logging in, or waiting.
    'cookie.pre.valid': 'The stored {platform} cookie works',
    'cookie.pre.expired': '{platform} rejected the stored cookie: the page bounced to a login page',
    'cookie.pre.unknown': '{platform} could not be checked (that is not a pass, and the run is not blocked)',
    'cookie.pre.noLogin': '{platform} is crawled without a login',
    'cookie.pre.notCrawlable': '{platform} can hold a cookie but cannot be crawled yet',
    'cookie.pre.notListed': 'Nothing here knows that platform, so nothing was checked: {platform}',
    'cookie.pre.busy': "{platform}'s browser is already held by something else",
    'cookie.pre.timeout': 'the check ran past {n} seconds',
    'cookie.pre.riskControl': 'the page answered with a captcha / risk control',
    'cookie.verify.unclear': '{platform} could not be verified: the page answered with a captcha or risk '
    'control, which says nothing about whether the cookie is valid',
    'cookie.delete.none': 'There is no saved {platform} cookie to delete',
    'cookie.delete.profileHolds': 'Note: {platform}\u2019s browser profile stays logged in — deleting this '
    'file does not sign that device out',
    'cookie.delete.failed': 'Could not delete the cookie file: {err}',
    'api.platformsRequired': 'platforms must be a list of platform names',
    'api.cookieBusy': 'A {platform} login window is already open — finish or cancel it first',
    'api.bodyNotObject': 'request body must be a JSON object',
    'api.paramInvalid': 'parameter {name} is invalid',
    'api.payloadTooLarge': 'request body exceeds the {limit} MB ceiling — split it up',
    'api.workflowNameRequired': 'a valid workflow name is required',
    'api.fieldTypeInvalid': 'field {name} has the wrong type',
    'api.stepsMustBeObjects': 'steps must be a list of objects, each with an "op" and optional "params"',
    'api.noCookieJob': 'No cookie login is currently active',
    'cookie.deleted': 'Cookies deleted for {platform}',
    'store.workflow_saved': 'Workflow saved: {path}',
    'store.dataset_saved': 'File stored: {name} ({rows} rows, id {did})',
    'store.datasets_bound': 'Workflow {wf} bound to {n} uploaded file(s)',
    'ds.corrupt': 'Dataset {did} could not be read (its records are damaged) — upload it again',
    'ds.purged': 'Removed {n} file(s) unused for {days} days and referenced by no workflow',
    'ds.purge_result': 'Removed {n} orphaned file(s), kept {kept} still in use',
    'ds.cleared': 'Emptied the file store: {n} file(s) removed',
    'ds.rebound': 'Re-attached dataset {name} ({did}) by file name — the workflow can run as-is',
    'ds.missing': 'An uploaded file this workflow refers to is no longer stored: {name}',
    'api.datasetMissing': 'No stored dataset with that id: {did}',
    'api.datasetNameInvalid': 'that name cannot label a dataset (nothing left after cleaning): {name}',
    'api.datasetInUse': 'saved workflows still read this file, and deleting it would leave them empty: {workflows}',
    'api.datasetTooBig': 'That file is too big to store: {err}',
    'history.recorded': 'Recorded {n} history metric(s) for "{wf}"',
    'history.run_deleted': 'Execution history: deleted {n} row(s) of run {rid}',
    'executor.task_failed': 'Task failed: {err}',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': 'Failed to record execution history (non-fatal)',
    'misc.save_workflow_failed': 'Failed to save workflow',
    'misc.i18nAudit': 'the message catalogue has a problem (harmless to run, please fix): {issue}',
    'misc.exportDeleteFailed': 'could not delete the exported file {name}: {err}',
    'misc.cookie_save_failed': 'Failed to save cookies',
    'misc.cookie_gen_failed': 'Failed to generate cookies',
    'misc.studio_source_failed': 'Merged studio load: source failed',
    'misc.source_probe_failed': 'Source probe failed',
    'misc.studio_saved': 'Chart studio saved {path} ({bytes} bytes)',
    'misc.browser_open_failed': 'Could not open browser: {err}',
    'misc.server_starting': 'Starting crawler workflow server on port {port}',
    'misc.visualize_failed': 'Chart rendering failed: {err}',
    'misc.export_failed': 'Writing the export file failed',
    # ── crawler internals (debug level) ───────────────────────
    'crawl.cookies_failed': '{platform}: could not load cookies ({err}) — the run may come back empty without a login',
    'crawl.xhs.untitled': 'untitled',
    'crawl.debug.title_missing': 'Title element not found',
    'crawl.debug.content_missing': 'Content element not found',
    'crawl.debug.author_missing': 'Author element not found',
    'crawl.debug.time_missing': 'Publish-time element not found',
    'crawl.debug.comments_missing': 'Comment area not loaded / not present',
    'crawl.debug.comment_item': 'comment #{i}: {author} - {text}...',
    'crawl.debug.card_skip': 'card {i}: skipped (no author)',
    'crawl.debug.card_author': 'card {i}: author="{v}"',
    'crawl.debug.card_time': 'card {i}: time="{v}"',
    'crawl.debug.card_len': 'card {i}: text length={v}',
    'crawl.debug.card_metrics': 'card {i}: reposts={f} comments={c} likes={l}',
    'crawl.debug.card_images': 'card {i}: images={n}',
    'crawl.debug.pager_missing': 'No pager button found — single page',
    'crawl.debug.content_retry': 'Content not extracted yet — retrying once',
    # ── argument validation / API errors (surfaced in toasts) ──
    'crawl.weibo.bad_date': 'Bad date format: {value} (expected YYYY-MM-DD)',
    'crawl.weibo.need_both_dates': 'Set both a start and an end date — a single one searches a different range',
    'crawl.weibo.bad_range': 'The end date ({end}) must be later than the start date ({start})',
    'chart.count': 'count',
    'ml.no_training_rows': 'No training data: every row has an empty text or label',
    'ml.need_two_labels': 'Training needs at least 2 distinct labels; this data only has: {label}',
    'cluster.no_features': 'Text could not be segmented (symbols only?) — clustering skipped: {err}',
    'engine.source_no_platform': 'Node {nid}: source node has no platform',
    'engine.source_unknown_platform': 'Node {nid}: {platform} has no crawler yet — pick a supported platform',
    'engine.source_unknown_mode': 'Node {nid}: {platform} has no such collection mode — pick one under Collect',
    'engine.source_missing': 'Node {nid}: the required field {field} is empty',
    'engine.source_link_mismatch': 'Node {nid}: {n} link(s) do not match the selected platform ({platform})',
    'field.keyword': 'keyword',
    'field.urls': 'article URLs',
    'field.author': 'creator',
    'engine.upload_no_file': 'Node {nid}: upload node has no file selected',
    'engine.comment_no_urls': 'Node {nid}: comment node has no article URLs yet',
    'comment.no_urls': 'comment node has no crawlable URLs (supported: {platforms})',
    'comment.unsupported': 'comment node ignored {n} unsupported link(s) (supported: {platforms})',
    'comment.noAdapter': '{platform} has no comment crawler, so this link cannot be handled: {url}',
    'comment.commentsClosed': 'this content has no open comment section (or none yet): {url}',
    'comment.ytNoPage': 'the YouTube page never loaded as a video page (login or interception?): {url}',
    'comment.xNoList': '[X comments] the post page rendered nothing at all (dead, deleted, or blocked link): {url}',
    # YouTube is crawled as JSON from inside its own page, so these lines talk
    # about rounds and answers rather than about scrolling a list.
    'crawl.yt.noContext': '[YouTube] the page exposed no innertube config (intercepted, or the DOM changed): {url}',
    'crawl.yt.callFailed': '[YouTube] the {endpoint} call failed',
    'crawl.yt.badAnswer': '[YouTube] {endpoint} answered {status}, not JSON',
    'crawl.yt.wall': '[YouTube] a human-verification page was served: {url}',
    'crawl.yt.searchStart': '[YouTube] keyword "{kw}", target {n} results',
    'crawl.yt.authorStart': '[YouTube] creator "{author}" uploads, target {n} results',
    'crawl.yt.authorEmpty': '[YouTube] no creator given (@handle, channel link or UC… id): {author}',
    'crawl.yt.authorNotFound': '[YouTube] that address is not a channel page, so no channel id: {author}',
    'crawl.yt.authorNoVideos': "[YouTube] this creator's video tab holds nothing: {author}",
    'crawl.yt.page': '[YouTube] round {page}: {n} items ({fresh} new, {done} collected)',
    'crawl.yt.noPage': '[YouTube] round {page} returned no items, stop paging',
    'crawl.yt.processed': '[YouTube] stored {i}: {title}',
    'crawl.yt.targetReached': '[YouTube] target of {n} rows reached, stop paging',
    'crawl.yt.drained': '[YouTube] the API stopped handing out a cursor, the list is exhausted',
    'crawl.yt.replay': '[YouTube] round {page} added nothing new, list treated as exhausted',
    'crawl.yt.noResults': '[YouTube] no public video matches "{kw}" (or this session is throttled)',
    'crawl.yt.finished': '[YouTube] collected {n} rows in this run',
    # X renders a virtualized timeline: the card count never grows while tweets
    # stream through it, so its log lines speak of rows kept, not cards on screen.
    'crawl.x.start': '[X] keyword "{kw}", target {n} posts (latest first)',
    'crawl.x.target_reached': '[X] target of {n} rows reached, stop scrolling',
    'crawl.x.authorStart': '[X] author "{author}" posts, target {n} posts',
    'crawl.x.authorEmpty': '[X] no author given (@handle or profile link): {author}',
    'crawl.x.wall': '[X] access was refused (login wall or 403): {url}',
    'crawl.x.loadSlow': '[X] the page did not finish loading in time; continuing with what rendered: {url}',
    'crawl.x.no_cards': '[X] no tweet rendered at all (blocked, too narrow, or an empty account): {url}',
    'crawl.x.finished': '[X] kept {n} posts (stopped because: {reason})',
    'comment.biliBadAnswer': 'bilibili comment endpoint returned no data (code={code}): {url}',
    'comment.dyNoId': 'the link carries no video id, so comments cannot be fetched: {url}',
    'comment.dyNoPanel': 'the comment panel never rendered (collapsed, or login required): {url}',
    'comment.dyNone': 'this video reports {n} comments but the list did not open: {url}',
    'comment.weiboShowFailed': '[weibo comments] the comment endpoint answered nothing (dead cookie, limited): {url}',
    'comment.zhihuNoPanels': '[zhihu comments] no comment panel on this answer (closed, or never loaded): {url}',
    'comment.prefix': '[comments]',
    'comment.platformMismatch': 'skipped {n} link(s) that do not match the selected platform ({platform})',
    'comment.allMismatched': 'every link conflicts with the selected platform ({platform}) — check the article URLs',
    'comment.article': 'comments: {url} added {n} ({status})',
    'comment.done': (
        'comment crawl finished: {urls} links (ok {ok}, blocked {blocked}, '
        'dead {dead}), {rows} comments, {files} file(s)'
    ),
    'comment.status.ok': 'ok',
    'comment.status.blocked': 'login/risk-control wall',
    'comment.status.dead': 'link unreadable',
    'engine.process_no_op': 'Node {nid}: process node has no operation',
    'engine.output_no_op': 'Node {nid}: output node has no operation',
    'engine.analysis_no_op': 'Node {nid}: analysis node has no operation/steps configured',
    'engine.cycle': 'the workflow contains a cycle; these nodes cannot be ordered: {nodes}',
    'engine.dangling_connection': 'a connection points at a node the canvas does not hold: {src} → {dst}',
    'engine.empty_canvas': 'the canvas holds no nodes, so there is no workflow to run',
    'engine.tokenize_no_column': 'Node {nid}: tokenize node is missing its text column',
    'engine.visualize_no_chart': 'Node {nid}: visualize node has no chart type',
    'engine.visualize_no_x': 'Node {nid}: visualize node is missing the x field',
    'engine.name_no_label': 'Node {nid}: the name node needs a workflow name',
    'engine.name_not_head': 'Node {nid}: the name node must lead — nothing may feed into it',
    'engine.name_no_downstream': 'Node {nid}: the name node must connect to a downstream node',
    'wf.unknown_process_op': 'unknown process operation "{op}"',
    'wf.join_no_right_table': 'A join needs two incoming connections (left table first, right table second)',
    'analysis.join_no_right': "Join failed: no right-hand table — connect it as this node's second input",
    'analysis.join_need_keys': 'Join failed: set both the left and the right key column',
    'analysis.join_missing_cols': 'Join failed — no such column: {cols}',
    'api.alreadyRunning': 'A workflow is already running — stop it or wait for it to finish',
    'api.needApiKey': 'The OpenRouter API key is missing (Settings → AI)',
    'api.needModel': 'No OpenRouter model selected (Settings → AI)',
    'api.needOllamaModel': 'No Ollama model selected (Settings → AI → Model; hit Refresh to list local ones)',
    'api.platformRequired': 'Platform is required',
    'api.cookiesRequired': 'Cookies data is required',
    'api.unsupportedPlatform': 'Unsupported platform: {platform}',
    'api.llmModelsFailed': 'Could not fetch the OpenRouter model list: {err}',
    'api.ollamaModelsFailed': 'Could not list local Ollama models at {host} (running? address right?): {err}',
    'api.parseFailed': 'Could not parse the file: {err}',
    'api.unsupportedUpload': 'unsupported file type: {name} (accepted: .csv .tsv .json .txt .xlsx .xls)',
    'api.columnMissing': 'No such column in the data: {column}',
    'api.needLabeledRows': 'At least 10 labelled rows are needed, this data has {n}',
    'api.noSourceTable': 'None of the selected nodes could supply a table',
    'api.badRequest': 'Malformed request: {what}',
    # ── runtime settings validation ───────────────────────────
    'set.driverMissing': 'Driver file does not exist: {path}',
    'set.driverEmpty': 'Driver path was empty — restored the default',
    'set.browserMissing': 'Browser executable does not exist: {path}',
    'set.badWindow': 'Window size must look like WIDTHxHEIGHT (e.g. 1920x1080) — restored the default {default}',
    'set.badNumber': '{setting} is not a number — restored the default {value}',
    'set.outOfRange': '{setting} is outside {lo}-{hi} — restored the default {value}',
    'set.badOllamaHost': 'The Ollama address must start with http:// or https:// — restored the default',
    'set.badFlag': '{setting} needs a true/false value — restored the default',
    'set.badProfileDir': 'The profile directory must be an absolute path (got: {value}) — restored the built-in one',
    'set.saveFailed': 'Settings could not be written to disk (still active for this session): {err}',
    # ── resumable runs ────────────────────────────────────────
    'run.row_limit': 'Node {nid} hit its {limit}-row safety cap — further rows are not stored',
    'run.interrupted_by_restart': 'Interrupted by a service restart',
    'run.promoted': '{n} unfinished run(s) from an earlier session marked resumable',
    'run.started': 'This run is checkpointed as {rid} — every row lands in the database as it is produced',
    'run.resume_from': 'Resuming the run interrupted at {at} — {rows} rows already stored',
    'run.restored': 'Node {nid} reuses its previous result ({n} rows) instead of running again',
    'run.resume_crawl': 'Node {nid} continues crawling from where it stopped ({have} rows already saved)',
    'run.recrawl': 'Re-crawl: released {n} dedupe records; this node will collect again',
    'run.dedupe_skipped': (
        'Incremental: {n} already-collected items were skipped (enable Recrawl on the source node to re-collect)'
    ),
    'run.dedupe_all_skipped': (
        'every item of this node was already collected — nothing new flows downstream; '
        'enable Recrawl on the source node to re-collect, or reach the stored rows through '
        'the run records / a Resume node'
    ),
    'run.progress_file': 'progress export: {file} ({rows} rows in {parts} part files)',
    'run.live_export': 'live export: {file} (rewritten after every batch; kept when the run ends)',
    'run.live_export_failed': 'live export write failed: {err}',
    'run.cookieExpired': (
        'login session looks expired: the {platform} crawl was bounced to a login page '
        '(the cookie may have gone stale). Everything collected so far is kept — refresh '
        'the cookie under Settings -> Cookie, then resume the run from its checkpoint'
    ),
    'run.cookieExpiredOk': (
        'note: {platform} hit the login wall only after the target was met — the data is complete, nothing to resume'
    ),
    'run.cookieAnyPlatform': 'the platform being crawled',
    'run.forcedVisible': '"{label}": {platform} blocks headless browsers, so this run was switched to a visible window',
    'run.forcedVisibleComment': (
        '"{platform}" comments must actually be scrolled to collect fully (or that site refuses '
        'headless browsers), so this link\u2019s comments use a visible window'
    ),
    'run.platformQueued': (
        '{platform} is being crawled by another workflow, so this one queued and starts in {n}s: two '
        'searches from one account in the same second are what gets bounced to the login page'
    ),
    'run.serialForced': (
        '{platform} crawls are forced to run one at a time: parallel paging on one account always draws the '
        "login wall, so this platform serializes by the site's rule, not by the 错峰 setting"
    ),
    'run.platformGateTimeout': (
        '{platform} waited {n}s for its turn to crawl and gave up: a browser window that never closed may be holding it'
    ),
    'run.platformStaggered': (
        '{platform} starts {n}s after the last same-platform crawl: this one queued behind nothing, so '
        'the two may still overlap — only their departures are kept apart, which is what stops one '
        'account issuing two searches in the same second'
    ),
    'run.queueAbandoned': 'the queue wait for {platform} was cancelled (this run stopped)',
    'run.wallRetry': (
        '{platform} was bounced to its login page before its first row, which reads as two concurrent '
        'searches from one account colliding: retrying once in {n}s'
    ),
    'crawl.profile_wait': 'queued {seconds} s: this profile runs one browser at a time — {dir}',
    'run.profileOff': (
        'this run uses no browser profile: every crawl is a brand-new device (so same-platform workflows '
        'really do run side by side), and the saved cookie snapshot is planted as usual'
    ),
    'crawl.profile_stuck': (
        'timed out waiting {seconds} s for the profile to free up: {dir} — a browser may have been left '
        'open; end the stray Chrome in the process panel and try again'
    ),
    'crawl.profile_gave_up': 'this run was stopped: no longer waiting for the profile ({dir}), this crawl stands down',
    'run.notCrawlable': (
        'the platform behind "{label}" ({platform}) can store a login cookie but has no crawler yet, so it cannot '
        'run as a data source — pick a supported platform, or wait for this one to land'
    ),
    'run.partial_down': 'Node {nid} interrupted — its {n} finished rows are handed downstream',
    'run.failed_down': 'Node {nid} failed with nothing usable — downstream sees an empty table',
    'run.skipped_empty': 'Node {nid} skipped: no data arrived from upstream',
    'run.finished': 'Run finished ({done}/{total} nodes)',
    'run.finished.skipped': ', {n} skipped',
    'run.finished.failed': ', {n} failed',
    'run.rejected': 'Nothing ran: the workflow has {n} problem(s), see the messages above',
    'resume.no_run': 'Resume node: no run selected, and no resumable run was found',
    'resume.empty': 'Resume node: "{nid}" of run {rid} has no stored rows',
    'resume.unpicked': 'no node picked',
    'resume.loaded': 'Resume node: loaded {n} rows from node {nid} of run {rid}',
    'api.runNotFound': 'No such run: {rid}',
    'api.exportNotFound': 'export file not found (or not downloadable): {name}',
    # ── one-click HTML report ───────────────────────────────────
    'report.generated': 'Generated',
    'report.default_title': '{name} · run report',
    'report.summary': 'This run had {nodes} node(s) and produced {rows} row(s); {tables} of them hold a table.',
    'report.charts': 'Charts',
    'report.run_facts': 'Run details',
    'report.tables': 'Tables',
    'report.conclusion': 'Conclusion',
    'report.no_charts': 'Nothing in these tables was chartable yet.',
    'report.chart_failed': 'Chart rendering failed: {err}',
    'report.chartsFailed': 'the report charts failed; its text and tables still came out',
    'report.no_rows': 'this node produced no rows',
    'report.more_rows': 'First {shown} of {total} rows shown; export the table as CSV for the rest.',
    'report.row_count': '{n} rows · {cols} columns',
    'report.fact.workflow': 'Workflow',
    'report.fact.run': 'Run id',
    'report.fact.status': 'Status',
    'report.fact.started': 'Started',
    'report.fact.finished': 'Finished',
    'api.reportNoData': 'nothing to report: run the workflow first, or pick a stored run',
    # ── run queue ─────────────────────────────────────────────
    'api.queued': 'Queued: it starts when the current run finishes (position {at})',
    'api.queueFull': 'the queue is full ({n} waiting) — wait for the current run, or cancel some',
    'run.queued': 'Queued (position {at}): {name}',
    'run.queuedUnnamed': 'an unnamed workflow',
    'run.queue_started': 'Queue: {name} started ({rid})',
    'run.queue_waited': 'Queue could not start {name} (a run is active), it waits again',
    'run.queue_broken': 'the queued request {name} could not start; skipped, the next one continues: {err}',
    'run.queueStartFailed': 'a queued run could not be started',
    'history.cleared': 'Execution history cleared',
    'api.workflowShapeInvalid': 'the workflow could not be read: an object with a nodes list is required',
    'api.resumeMissing': (
        'cannot continue: run {rid} has been purged, so it would re-crawl everything — press Run instead'
    ),
    'api.historyNoRunId': 'no run id given, so no execution history was deleted',
    'run.store_unavailable': 'this run could not begin: the run record store would not open (disk full, corrupt or '
    'locked file) — nothing was recorded',
    'run.reportSaved': 'Report written: {name} ({size} bytes)',
    'run.reportFailed': 'Report failed: {err}',
    'run.reportConclusionFailed': 'The conclusion could not be generated, so the report omits it: {err}',
    # ── housekeeping ──────────────────────────────────────────
    'housekeeping.done': (
        'Housekeeping: dropped {runs} expired run record(s) and {files} orphaned file(s) '
        '(plus {cache} cached model answer(s) and {seen} stale dedupe key(s))'
    ),
    'housekeeping.runStoreFailed': 'Automatic run-record cleanup failed (the run itself is unaffected)',
    'housekeeping.datasetStoreFailed': 'Automatic orphan-file cleanup failed (the run itself is unaffected)',
}

MESSAGES = {'zh': _ZH, 'en': _EN}


# ─── Runtime language ───────────────────────────────────────────


def normalize(value) -> str:
    """Map any accepted spelling ('zh-CN', 'en-US', 'ZH', None) onto a
    catalogue language, falling back to the default for anything unknown."""
    text = str(value or '').strip().lower().replace('_', '-')
    for lang in LANGS:
        if text == lang or text.startswith(lang + '-'):
            return lang
    return DEFAULT_LANG


def get_lang() -> str:
    """Thread-local language; defaults to zh for anything not driven by a
    request (startup messages, manual runs, tests)."""
    return getattr(_local, 'lang', None) or DEFAULT_LANG


def set_lang(value):
    """Pin the language for this thread. Workflow worker threads must call
    this themselves — thread-locals are not inherited from the starter."""
    _local.lang = normalize(value)
    return _local.lang


#: What a message carries in ``{platform}`` is a **storage key** — that is what the crawl
#: matrix, the cookie files, the browser profiles and the run records are all addressed by.
#: Printed as-is it put a bare ``zhihu`` into a Chinese console and into the pre-run dialog,
#: so the key is named in the language the message is already answering in. One rule here,
#: so every line that mentions a platform is translated — including lines written later.
#: The values are pinned equal to the frontend's ``platform.*`` catalogue by
#: ``test_frontend_contract.py::TestPlatformLabelParity``.
_PLATFORM_LABELS = {
    'zh': {
        'zhihu': '知乎',
        'weibo': '微博',
        'xiaohongshu': '小红书',
        'wechat': '微信',
        'bilibili': '哔哩哔哩',
        'douyin': '抖音',
        'twitter': 'X（推特）',
        'instagram': 'Instagram',
        'youtube': 'YouTube',
    },
    'en': {
        'zhihu': 'Zhihu',
        'weibo': 'Weibo',
        'xiaohongshu': 'Xiaohongshu',
        'wechat': 'WeChat',
        'bilibili': 'Bilibili',
        'douyin': 'Douyin',
        'twitter': 'X (Twitter)',
        'instagram': 'Instagram',
        'youtube': 'YouTube',
    },
}


def platform_label(key, lang: str | None = None) -> str:
    """The word a user reads for a platform key, or the key itself when it is not one.

    Domains (``weibo.com``) and free text pass through untouched: this names keys, it does
    not judge whether a string was meant to be one.
    """
    table = _PLATFORM_LABELS.get(lang or get_lang()) or {}
    return table.get(str(key), str(key))


def _name_platforms(params: dict) -> dict:
    """Localize ``platform`` / ``platforms`` placeholders on the way into a template.

    Callers hand this slot either one key, a list of them, or a string they joined
    themselves — all three are answered, because a half-translated list is the same bug
    with a comma in it. A value that is not made of platform keys (a domain, a free-text
    reason) is passed through untouched.
    """
    named = dict(params)
    for slot in ('platform', 'platforms'):
        value = named.get(slot)
        if isinstance(value, str):
            # Split on a list separator and nothing else. Splitting on whitespace or on
            # `/` looked harmless and was not: a refusal that names what it refused
            # (`../x`) came back mangled, and a sentence would have been re-joined with
            # 、. An unknown token is passed through whole, which is the safe answer for
            # every value that was never a platform key.
            named[slot] = '、'.join(
                platform_label(part.strip()) for part in re.split(r'[,、]', value.strip()) if part.strip()
            )
        elif isinstance(value, (list, tuple, set)):
            named[slot] = '、'.join(platform_label(item) for item in value)
    return named


def t(key: str, **params) -> str:
    """Render ``key`` in the current thread's language.

    Missing key -> the key itself (so gaps are visible in the console).
    Missing parameter -> the raw template, never a crash mid-crawl.
    """
    lang = get_lang()
    table = MESSAGES.get(lang) or {}
    template = table.get(key)
    if template is None:
        template = MESSAGES.get(DEFAULT_LANG, {}).get(key)
    if template is None:
        logger.debug(f'i18n: missing message key "{key}"')
        return key
    if not params:
        return template
    params = _name_platforms(params)
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.debug(f'i18n: bad params for "{key}": {params!r}')
        return template


def missing_keys() -> dict:
    """Catalogue gaps per language — used by the tests so a half-translated
    message cannot ship."""
    zh, en = set(_ZH), set(_EN)
    return {'en_only': sorted(en - zh), 'zh_only': sorted(zh - en)}


def audit() -> list[str]:
    """Self-check the catalogue; an empty list means it is healthy.

    Worth calling at startup: a leftover printf placeholder ('端口 %s') does
    not raise — ``str.format`` just fails and ``t()`` hands back the raw
    template, so the user sees a literal ``%s`` in the console and nothing
    points at the cause. This turns that into a warning that names the key.
    """
    problems = []
    for key in sorted(set(_ZH) | set(_EN)):
        for lang, table in MESSAGES.items():
            template = table.get(key)
            if template is None:
                problems.append(f'{key}: missing translation for {lang}')
                continue
            if _BAD_PLACEHOLDER.search(template):
                problems.append(f'{key} [{lang}]: printf-style placeholder in "{template}"')
    return problems
