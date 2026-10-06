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
    'wf.multi_input': (
        '节点 {nid} 有 {n} 条上游连线：主输入取第一条（来自 {up}）；分析节点的连接用第二条当右表，'
        '输出节点则把全部上游合并成一张表'
    ),
    'wf.merge_not_tabular': (
        '节点 {nid} 的上游「{up}」不产出表格（是图表配置或错误应答），无法合并——请断开这条连线，'
        '或改接一个产出表格的节点'
    ),
    'wf.merge_columns': (
        '节点 {nid} 合并上游表时列名不一致，对比「{up}」：多出 [{extra}]、缺少 [{missing}]。'
        '不做外连接合并——那会凭空补出空值，让文件看起来完整'
    ),
    'wf.merge_done': '节点 {nid} 合并 {tables} 张上游表 → {n} 行（{detail}）',
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
    # The labelling step needs a model: without one the step refuses instead of leaving the
    # column blank and settling the node DONE on work that did not happen.
    'wf.analysis_llm_no_model': '「主题概括」需要模型，但这条运行没有配置模型（设置 → 模型 / 节点模型）',
    'wf.analysis_steps_shape': '「steps」必须是步骤列表（每个一步一个对象），收到的是一个对象',
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
    'label.sentiment': '情感极性',
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
    'crawl.redrive': '页面没落到站点（停在 {where}），重发一次导航',
    # Observation only — never a claim about what the crawl then did. This line is
    # written by ``check_login_wall``, which cannot know the caller's policy: weibo
    # and zhihu stop, while WeChat's batch skips that one article and carries on to
    # the next. Saying 「已停止本次抓取」 there told the user their batch had ended.
    # The stop, when it happens, is announced by the node refusing with
    # ``run.cookieExpired``, which also says what to do about it.
    'crawl.loginWall': '登录墙：{platform} 的 {where} 被重定向到登录页',
    'crawl.riskBlocked': '风控拦截：{platform} 的 {where} 返回了安全验证而非内容（会话未必失效，稍后重试）',
    # Neither of the two above: the browser wrote this page itself, so the site never saw
    # the request and the session is not the thing in question.
    'crawl.unreachable': '浏览器自己拒绝了这次访问：{platform} 的 {where}{detail}',
    'crawl.unreachableToken': '（{token}）',
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
    'crawl.zhihu.stuck': '连续 {n} 轮滚动既无新卡片、页面也不再变高，且未出现「没有更多了」，停止滚动',
    'crawl.zhihu.no_growth': '卡片数未增长 ({n}/3)，再次滚动确认...',
    'crawl.zhihu.phase_done': '滚动加载阶段完成，最终获取 {n} 个卡片',
    # One fact, one line: what the 正文 column actually holds. The search page only ever
    # carries an excerpt, so a crawl that did not expand has to say so once at the end.
    'crawl.zhihu.excerpt_only': '未展开正文：本次所有正文都是搜索页摘要（可在数据源节点勾选「展开全文」）',
    # 热榜: measured as one answer of 30 questions with every paging parameter ignored,
    # so the mode never promises more than the board holds.
    'crawl.zhihu.hotStart': '开始采集知乎热榜，目标 {n} 条',
    'crawl.zhihu.hotDone': '热榜采集结束：{n} 条（目标 {total} 条）',
    'crawl.zhihu.hotCapped': '热榜一共只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.zhihu.hotRefused': '知乎热榜接口没有给出榜单（返回 {answer}）',
    'crawl.zhihu.hotWall': '知乎热榜需要登录：当前 Cookie 被挡在登录页，无法读取榜单',
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
    'crawl.weibo.target_reached': '已达到目标数量 {n} 条，停止翻页',
    'crawl.weibo.authorStart': '开始采集作者 {uid} 的作品，目标 {n} 条',
    'crawl.weibo.authorDone': '作者作品采集结束：{n} 条（{reason}）',
    # 热搜: one answer is the whole board, so the three lines below are the only
    # things this mode can honestly say.
    'crawl.weibo.hotStart': '开始采集微博热搜，目标 {n} 条',
    'crawl.weibo.hotDone': '热搜采集结束：{n} 条（目标 {total} 条）',
    'crawl.weibo.hotCapped': '热搜榜本次只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.weibo.hotRefused': '微博热搜接口没有给出榜单（返回 {answer}）',
    # Said when the request was never issuable: the browser was left on a frame that is not weibo.com, so
    # the same-origin fetch had no host to ask. Blaming the endpoint there would convict it of an answer
    # it never gave.
    'crawl.weibo.hotNoHost': '微博热搜未采集：浏览器还停在「{where}」，没回到 weibo.com（访客引导未完成，'
    '页面内请求发不出去；这是到场帧的问题，不是接口拒绝）',
    'crawl.weibo.authorEmpty': '「{author}」不是微博作者地址：填 weibo.com/u/<UID> 主页链接或数字 UID',
    'crawl.weibo.authorWall': '微博把 UID {uid} 的主页弹回了登录页：这个会话进不去作者页',
    'crawl.weibo.authorMirror': (
        'UID {uid} 的答复第一行不属于该作者——接口给的是首页时间线而不是作者作品，拒绝张冠李戴'
    ),
    'crawl.weibo.authorRefused': (
        'mymblog 接口拒绝应答（状态 {status}，UID {uid}）：这是按会话的限流，Cookie 可能并未失效，请稍后再试'
    ),
    'crawl.weibo.authorNoPosts': 'UID {uid} 没有返回任何作品：这个账号可能确实没发过微博',
    'crawl.weibo.visiting': '访问搜索链接: {url}',
    'crawl.weibo.no_result': '该时间段无搜索结果，跳过',
    'crawl.weibo.waiting': '等待页面加载...',
    'crawl.weibo.page_loaded': '页面加载完成',
    'crawl.weibo.total_pages': '检测到总页数: {n}',
    'crawl.weibo.page_crawling': '  正在爬取第 {i}/{total} 页...',
    'crawl.weibo.page_empty': '  第 {i} 页无有效卡片，跳过',
    'crawl.weibo.page_done': '  第 {i} 页爬取完成，共 {n} 条，累计 {total} 条',
    'crawl.weibo.link_error': '处理搜索链接时出错: {err}',
    'crawl.weibo.page_timeout': (
        '    等了 {secs} 秒：这一页既没有给出卡片，也没有给出「无结果」牌（导航{settled}）'
        '—— 这一句只说代码看得见的东西，不能据此断定窗口里没有内容'
    ),
    'crawl.weibo.navSettled': '已完成',
    'crawl.weibo.navUnsettled': '未完成，那是慢网络而不是站点的拒绝',
    'crawl.weibo.page_gave_up': (
        '    这台浏览器已经有 {waits} 个搜索页一次内容都没交付：不再把整段预算花在新的窗口上'
        '（这是「取不到页面」，不是「这个窗口没有内容」）'
    ),
    'crawl.weibo.walk_done': '微博搜索收尾：{n} 条（目标 {target}，窗口走到第 {walked}/{total} 个，原因：{reason}）',
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
    'crawl.xhs.target_reached': '[收集链接] 已达到目标数量 {n}，停止加载',
    'crawl.xhs.collect_done': '[收集链接] 收集完成，共 {n} 条链接',
    'crawl.xhs.detail_visit': '[爬取详情] 正在访问详情页: {url}',
    'crawl.xhs.detail_ready': '[爬取详情] 详情页加载完成',
    'crawl.xhs.detail_timeout': '[爬取详情] 详情页加载超时',
    'crawl.xhs.deadNote': '[详情] 笔记被安全验证挡住（非会话失效），跳过：{url}',
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
    # 「文件名带时间范围」 asks the save node to print a window it cannot see: the crawl
    # states it, this node receives a table. Both answers name the reason instead of
    # inventing a range, because a file labelled with the wrong month is worse than one
    # that was never written.
    'export.window_none': '文件名要求带时间范围，但这条链路上没有任何采集节点声明开始/结束时间',
    'export.window_many': '文件名要求带时间范围，但这条链路上有 {n} 个不同的时间窗，一个文件说不清它装的是哪一段',
    'export.window_ignored': '节点 {nid}：结果文件照常生成，仅「文件名追加时间范围」被忽略——{reason}',
    'analysis.type_convert_failed': '列 {col} 转换为 {dtype} 失败：{err}',
    'analysis.calc_failed': '计算列 {col} = {expr} 失败：{err}',
    'analysis.bin_failed': '列 {col} 分箱失败：{err}',
    'analysis.col_missing': '未找到列“{col}”',
    'analysis.dedupe_similar': (
        '近重复去重：在「{column}」上按 SimHash 距离 ≤{distance} 判定，删除 {n} 行（每组保留首次出现的那行）'
    ),
    'analysis.dedupe_distance': '近重复去重支持的距离是 0–{max} 位，收到 {value}，已拒绝（不做全量两两比对）',
    'analysis.time_unparsed': (
        '「{col}」有 {n} 行不是可解析的时间（站点只给了相对标签，如「09月26日 21:00」），已留空而不是猜一个年份'
    ),
    'analysis.time_binned': '{col} 划分完成：{detail}',
    'analysis.time_bin_labels': '时间分段需要「边界数 = 阶段名数 + 1」，现在是 {edges} 个边界、{labels} 个名称',
    # A boundary PROPOSAL: this step rewrites no row and does not decide when the event
    # turned — that needs the dates the researcher knows (the notice, the apology, the
    # filing), which are not in the post counts.
    'analysis.stages_sparse': '这一列只有 {days} 天有记录，切不出阶段（至少需要 {least} 天）',
    'analysis.stages_ratio': '「峰倍率」至少要是 1（高于平常的一天才算峰），收到 {value}',
    'analysis.stages_no_peak': (
        '发文量曲线里找不到 {ratio} 倍于日常（中位数 {floor} 行/日）的转折峰，'
        '这一列撑不起阶段划分——曲线只有一段，就不要切成多段'
    ),
    'analysis.stages_folded': '曲线上的峰多于 {kept} 个，只保留最高的 {kept} 个（折掉了 {dropped} 个）',
    'analysis.stages_folded_windows': (
        '{n} 个窗口短于「最短窗口」{days} 天，已并入相邻较长的窗口（一天冲上来的不算一个阶段）'
    ),
    'analysis.stages_done': '阶段建议：{n} 个候选窗口、覆盖 {rows} 行（{span}）',
    'analysis.stages_edges': '建议边界 edges（左闭右开，末位是最后一天+1）：{edges}',
    'analysis.stages_labels': '建议阶段名 labels（与 edges 一一对应，仅占位，可改名）：{labels}',
    'analysis.stages_basis_first': '自曲线首日 {day} 起',
    'analysis.stages_basis_valley': '自谷底 {valley} 的次日起',
    'analysis.time_bin_edges': '时间分段里有无法解析成日期的边界：{edges}',
    'analysis.time_bin_order': '{op} 的边界必须按时间从早到晚排列',
    'analysis.topic_count': 'LDA 主题数至少要 2，收到 {value}（1 个主题只是"整段文本"）',
    'analysis.topic_rows': 'LDA 需要至少和主题数一样多的文本：主题 {topics} 个、有效文本 {rows} 行',
    'analysis.topic_features': 'LDA 无法从这一列抽到特征词（可能整列都是标点或停用词）：{err}',
    # 分阶段主题模型。每一句都点名是哪个阶段、哪个主题，因为「某个阶段没跑出来」在一堆
    # TopicⅠ-1 … TopicⅤ-4 里是查不出来的。
    'analysis.stage_order': (
        '「{col}」这一列已经看不出阶段先后（跨节点会退化成普通文本）。把「按时间划分阶段」与它放在同一条'
        '流水线，或填「阶段排序列」指向一个时间列'
    ),
    'analysis.stage_order_col': '「{op}」的「阶段排序列」在表里不存在：{col}',
    'analysis.stage_order_unparsed': '「{col}」里排不出这些阶段的先后（没有任何可解析的时间）：{stages}',
    'analysis.stage_order_unranked': (
        '「{col}」里没有这些阶段的序号（要的是数字：划分阶段 的阶段序号，或 分阶段 LDA 的 stage_order）：{stages}'
    ),
    'analysis.topic_stage_number': '每阶段主题数只能是整数，收到「{value}」',
    'analysis.topic_stage_counts': (
        '每阶段主题数要与阶段一一对应：{stages} 个阶段，收到 {counts}（只填一个数字表示各阶段同数）'
    ),
    'analysis.stage_blank': '「{col}」有 {n} 行没有阶段（时间戳没解析出来），它们不进任何主题模型',
    'analysis.topic_stage_empty': '阶段「{stage}」一行都没有，无法为它建模（先检查「{col}」的边界）',
    'analysis.topic_stage_rows': (
        '阶段「{stage}」只有 {rows} 篇可用文本，撑不起 {topics} 个主题（LDA 至少要有和主题数一样多的文本）'
    ),
    'analysis.topic_stage_features': '阶段「{stage}」抽不到特征词：{err}',
    'analysis.topic_stage_words': (
        '阶段「{stage}」的 {topic} 一个特征词都选不出来（没有文本归到这个主题，请调小该阶段的主题数）'
    ),
    'analysis.topic_stage_unused': '阶段「{stage}」的 {topic} 没有分到任何文本（doc_n=0），特征词改用该主题的词分布',
    'analysis.topic_stage_done': '阶段「{stage}」：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}',
    # 主题可视化（pyLDAvis 那两张图的数据面）。λ 是「按主题自身概率」还是「按相对全库的溢出」
    # 排序，同一模型会给出两份不同的词表，所以用了哪个值必须随表一起说出来。
    'analysis.topic_map_done': (
        '主题距离图：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}'
        '（气泡大小=主题占比，坐标=两主题词分布的 JS 散度经 MDS）'
    ),
    'analysis.topic_salience_done': (
        '主题显著词：{n} 个主题、{rows} 篇文本、共 {terms} 行，λ={value}（1=按主题内概率排序，0=按相对全库的溢出排序）'
    ),
    'analysis.topic_lambda': 'λ 要在 0 到 1 之间（0=只看相对溢出，1=只看主题内概率），收到 {value}',
    # 主题概括：一行一次模型调用，所以失败要说清是哪个主题，停手也要说清还剩几个没问。
    'analysis.label_no_llm': '「{op}」没有拿到模型客户端：只有画布上的运行才带模型',
    'analysis.label_too_many': '主题概括要逐主题问模型：{rows} 行超过了上限 {limit}，请先把主题表缩小',
    'analysis.label_no_words': '{topic} 的「{col}」是空的，没有特征词就没有可概括的东西',
    'analysis.label_failed': '{topic} 的主题概括失败：{err}',
    'analysis.label_empty': '{topic} 的主题概括是空的（模型只回了标点）',
    'analysis.label_cancelled': '已停止：还有 {n} 个主题没问模型，它们的概括标为未处理',
    'analysis.label_done': '主题概括：{n} 个主题已写出（模型 {model}）',
    'analysis.label_cached': '主题概括：新问模型 {asked} 次，重放缓存答案 {replayed} 次（同一张表重跑不再重复付费）',
    'analysis.label_prompt': (
        '你是舆情分析研究员。下面是某网络暴力事件在一个阶段里一个主题的特征词与代表文本。'
        '请用不超过 15 个汉字概括这个主题在说什么；只输出概括本身，不要解释、不要引号。\n'
        '阶段：{stage}\n主题编号：{topic}\n特征词：{words}\n代表文本：{samples}'
    ),
    'analysis.topic_done': (
        'LDA 主题模型：{n} 个主题、{rows} 篇文本，困惑度 {perplexity}（数值越低拟合越好，但过小意味着在记原文）'
    ),
    'analysis.evolution_done': (
        '情感演化：按「period」聚合出 {n} 个时段（{periods}），情感指数 =(积极−消极)/总数 ∈ [-1, 1]'
    ),
    # The intensity curve is only honest if the periods it could not score say so: a blank
    # in an exported table is invisible, and 0.5 would print as "measured, and neutral".
    'analysis.evolution_unscored': '「{col}」在时段「{periods}」里一行分数都没有，这些时段的情感强度留空',
    # ── 阶段之后的读数：主题生命周期、跨阶段流向、主题数扫描、共词 ──
    # Each refusal names the number it measured, so the fix is a choice with a figure in front
    # of it rather than a guess at what the step wanted.
    'analysis.timeline_stages': '主题生命周期至少要 2 个阶段才谈得上「先后」，现在只有 {stages} 个',
    'analysis.timeline_overlap': '「同主题词重合度」要在 0 到 1 之间，收到 {value}',
    'analysis.timeline_blank': '「{col}」有 {n} 行不属于任何阶段，它们不进生命周期',
    'analysis.timeline_size': '「{col}」里一个数值都没有，峰值无从测量（留空不等于峰为 0）',
    'analysis.timeline_partial': '「{col}」有 {n} 行不是数值，它们在峰值里按 0 计',
    'analysis.timeline_words': '阶段「{stage}」的 {topic} 在「{col}」里没有特征词，无法跨阶段追踪它',
    'analysis.timeline_done': (
        '主题生命周期：{topics} 个主题（{stages} 个阶段），{multi} 个跨多阶段、{secondary} 个判为次生舆情'
        '（词重合阈值 {value}）'
    ),
    'analysis.timeline_secondary': '次生舆情：{topic} 的阶段路径 {path}',
    'analysis.flow_stages': '主题流向至少要 2 个相邻阶段，现在只有 {stages} 个',
    'analysis.flow_similarity': '「流向相似度阈值」要在 0 到 1 之间，收到 {value}',
    'analysis.flow_weights': '{topic}（阶段「{stage}」）的「{col}」里没有可用的词权重，无法算分布差异',
    'analysis.flow_stage_empty': '阶段「{stage}」里没有主题行（先检查「{col}」）',
    'analysis.flow_no_edges': ('没有一条主题流向达到阈值 {value}：实测最相似的一对是 {best}，把阈值调到它以下再来'),
    'analysis.flow_done': '主题流向：{stages} 个阶段之间得到 {edges} 条边（阈值 {value}，实测最高 {best}）',
    'analysis.coherence_range': '主题数扫描的起点不能大于终点：{low} > {high}',
    'analysis.coherence_sampled': '主题数扫描只抽 {used} 篇文本（共 {total} 篇可用），换个样本数字会变',
    'analysis.coherence_capped': '文本只有 {rows} 篇，扫描的终点从 {high} 个主题降到 {rows} 个',
    'analysis.coherence_pairs': (
        '每主题取 {topn} 个词，但这些词没有一对出现在同一篇文本里（跳过 {pairs} 对）：一致性无法测量，只有困惑度可读'
    ),
    'analysis.coherence_best': (
        '主题数扫描（{low}…{high}）：一致性最高在 {coherence} 个主题，困惑度最低在 {perplexity} 个'
    ),
    'analysis.cooccur_topn': '共词网络的候选词上限是 {cap}（词数翻倍则边数翻四倍），收到 {value}',
    'analysis.cooccur_count': '共现次数阈值至少是 1，收到 {value}',
    'analysis.cooccur_words': '只选出 {found} 个候选词，凑不出一对共现（要求前 {topn} 个）',
    'analysis.cooccur_empty': ('没有一对词共现达到阈值 {floor}：{pairs} 对里最高只有 {top} 次，请降低阈值或放宽候选词'),
    'analysis.cooccur_done': '共词网络：{words} 个候选词、{docs} 篇文本，{pairs} 对里 {edges} 对达到阈值 {floor}',
    # ── 往前看：曲线外推与二次爆发预警 ──
    'analysis.forecast_horizon': '外推步数至少是 1，收到 {value}（0 步只是把最后一格再抄一遍）',
    'analysis.forecast_window': '移动平均的窗口至少 2 期才能平均，收到 {value}',
    'analysis.forecast_smooth': '平滑系数「{name}」要在 0 与 1 之间（不含两端），收到 {value}',
    'analysis.forecast_dates': '「{col}」不是能解析成日期的时段列（一个日期都没有）：阶段名没法外推',
    'analysis.forecast_rows': '外推至少要 {least} 期观测，这一列只有 {rows} 期同时给出时间与数值',
    'analysis.forecast_window_rows': '窗口 {window} 期至少要留一期来预测，这一列只有 {rows} 期',
    'analysis.forecast_duplicate': '「{col}」里有同一天出现两行：{days}（两行会被当成趋势的两步）',
    'analysis.forecast_uneven': '时段间隔不齐：{rows} 期里有 {steps} 步不是 {gap} 天，未来格按 {gap} 天间隔标注',
    'analysis.forecast_done': '{method} 外推：{rows} 期观测，往后 {horizon} 步，间隔 {gap} 天（末期 {last}）',
    'analysis.alert_streak': '连续期数至少是 1，收到 {value}',
    'analysis.alert_threshold': '「{name}」阈值必须大于 0，收到 {value}',
    'analysis.alert_floor': '热度保持倍率不能超过 1（那等于要求热度上涨才算爆发），收到 {value}',
    'analysis.alert_rows': '预警至少要比连续期数多一行：需要 {least} 行，只有 {rows} 行',
    'analysis.alert_skipped': '「{col}」有 {n} 行解析不出日期，它们不参与预警判断',
    'analysis.alert_reason': '连续 {streak} 期变化 {moves}；强度斜率 {intensity}；本期热度 {volume}（{held}）',
    'analysis.alert_none': (
        '未触发：幅度最大的是 {period}，连续 {streak} 期平均 |Δ| 未到 {swing}，强度斜率未到 {heating}'
    ),
    'analysis.alert_none_log': '预警检查了 {checked} 期：连续 {streak} 期、幅度阈值 {swing}，一条都没触发',
    'analysis.alert_fired': '二次爆发预警：{period} 触发 {signal}，数值 {value}',
    'clean.unknown_mode': '清洗节点没有名为「{mode}」的模式（可用：regex、llm）',
    'aggression.lexicon_done': (
        '网暴言论识别（词库）：{rows} 行中 {violent} 行含暴力言论，其中 {severe} 行为严重'
        '（漏报无法度量：词表之外的说法看不见）'
    ),
    'clean.regex_done': '正则清洗：保留 {kept} 行、判定删除 {dropped} 行（未做主题相关性判断，那需要 llm 模式）',
    # A cleaning step that this table cannot carry out. `{op}` and `{param}` stay the
    # storage names on purpose: they are what the caller of /api/analysis/run wrote,
    # and what the Settings panel stores in the node's JSON, so a person fixing a
    # hand-written pipeline can match them against the file they edited.
    'analysis.need_param': '「{op}」缺少「{param}」，请先填写',
    # A count the step reads as an integer. The panel cannot send junk here (the normalizer drops
    # an unreadable box to the default), but a hand-written workflow file and /api/analysis/run
    # both reach the service, where int('abc') would otherwise surface as an opaque node failure.
    'analysis.need_number': '「{op}」的「{param}」要是一个整数，收到「{value}」',
    'analysis.step_col_missing': '「{op}」：表里没有名为「{col}」的列',
    'analysis.step_cols_missing': '「{op}」：表里没有这些列：{cols}',
    'analysis.bad_option': '「{op}」的「{param}」没有「{value}」这个选项（可用：{allowed}）',
    'analysis.rename_blank': '「{op}」：这些列的新名字是空的，请填写：{cols}',
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
    # ── 情感极性（snownlp / bert / ml / llm）───────────────────────────
    # A row that fails to read stays blank, so the failure line has to say the count:
    # 「判断为中性」 and 「没判断出来」 are different statements about the text.
    'sentiment.scored': '情感极性（{mode}）：已判断 {n} 行',
    'sentiment.scored_failed': '情感极性：{n} 行读取失败，留空（不是中性）',
    'sentiment.snownlp_failed': 'SnowNLP 判断失败：{err}',
    'sentiment.bert_failed': 'BERT 判断失败：{err}',
    'sentiment.ml_failed': 'ML 情感极性预测失败：{err}——回退为 neutral',
    'sentiment.unknown_mode': '使用了未知的情感极性模式「{mode}」',
    'sentiment.bad_thresholds': '正向阈值 {pos} 不得低于负向阈值 {neg}，那样每一行都会同时满足两边',
    'sentiment.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'sentiment.bert_no_model': 'BERT 模式还需要在「模型」里填一个情感模型名（本地目录或仓库名），空着无法判断',
    'sentiment.bert_bad_label': 'BERT 模型回了一个不认识的标签「{label}」，无法归入正面/负面/中性',
    'sentiment.bert_loaded': 'BERT 情感模型已加载：{model}（运行在 {device} 上，逐批推理）',
    'emotion.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'emotion.bert_no_model': 'BERT 模式还需要在「模型」里填一个情绪分类模型名（本地目录或仓库名），空着无法判断',
    'emotion.bert_loaded': 'BERT 情绪模型已加载：{model}（运行在 {device} 上，逐批推理）',
    'emotion.bert_failed': 'BERT 情绪判断失败：{err}',
    'emotion.bert_bad_label': 'BERT 模型回了一个不认识的情绪标签「{label}」，无法归入这六类',
    'emotion.bert_done': '[BERT] 情绪分类完成，{n} 行，失败 {failed} 行',
    'tendency.bert_missing': 'BERT 模式需要本机安装 {need}——当前环境没有，也不会改用别的方法代替',
    'tendency.bert_no_model': 'BERT 模式还需要在「模型」里填一个倾向分类模型名（本地目录或仓库名），空着无法判断',
    'tendency.bert_loaded': 'BERT 倾向模型已加载：{model}（运行在 {device} 上，逐批推理）',
    'tendency.bert_failed': 'BERT 倾向判断失败：{err}',
    'tendency.bert_bad_label': 'BERT 模型回了一个不认识的倾向标签「{label}」，无法归入这六类',
    'tendency.bert_done': '[BERT] 倾向分类完成，{n} 行，失败 {failed} 行',
    'ml.tendency_failed': 'ML 倾向性预测失败：{err}——回退为 Objective Statement',
    'ml.emotion_done': '[ML] 情感分类完成，共处理 {n} 行，模式: ML',
    'ml.tendency_done': '[ML] 倾向性分析完成，共处理 {n} 行，模式: ML',
    'cookie.saved': '已保存 {platform} 的 Cookie',
    # 一个平台可以多份登录：那句保存的话必须说出是**哪一份**，否则控制台里「已保存 微博 的 Cookie」
    # 指的是哪一个账号无从判断（用户要的正是逐个 Cookie 管理）。{account} 由 CookieManager 先取好
    # 词（空白=默认账号、default2=默认账号2、自己起的名字原样），这里只负责成句。
    'cookie.savedAccount': '已保存 {platform} 的 Cookie（账号：{account}）',
    'cookies.accountDefault': '默认账号',
    'cookies.accountDefaultNumbered': '默认账号{n}',
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
    'cookie.weibo.purpose': '解锁微博搜索（s.weibo.com）与评论 JSON 接口；未登录会被跳回 passport 二维码页。'
    '微博只认一份一直在用的会话：同账号并行翻页、或另开一个浏览器重放同一份 Cookie，都会被弹回登录页。'
    '所以抓取请始终用同一个 Profile，也不要同时跑两条微博。',
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
    'crawl.dy.target_reached': '[抖音] 已达到目标数量 {n} 条，停止',
    'crawl.dy.round': '[抖音] 第 {i} 屏：{n} 张卡片（新 {fresh} 个，已收录 {done} 条）',
    'crawl.dy.noMore': (
        '[抖音] 列表自己写了「暂时没有更多了」：翻了 {screens} 屏，最后一屏 {cards} 张卡片，'
        '这一轮的供给就到这儿（不是滚动没生效）'
    ),
    'crawl.dy.processed': '[抖音] 已收录视频 {i}，当前有效数据: {n} 条',
    'crawl.dy.authorStart': '[抖音作者] 开始采集该作者的作品，目标 {n} 条（计数在同页遮罩里逐条点开取，不整页跳转）',
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
    'crawl.dy.detailWalled': (
        '[抖音] 视频 {i} 这一条被站点挡在「验证码中间页」（图文页在这台设备上就是这样，视频页不受影响）'
        '，已跳过该行：它不是「站点没内容」，也不是登录态失效'
    ),
    'crawl.dy.detailSwapped': (
        '[抖音] 要打开的是 {i}，浏览器却给了另一条视频 {shown}（站点自己换了内容）'
        ' —— 这一行不入库：宁可少一行，也不把别人的文案和计数挂在这个链接下'
    ),
    'crawl.dy.detailNoIdentity': (
        '[抖音] 视频 {i} 的详情页只渲染出计数条，作者与发布时间都没有，已跳过该行：'
        '一条说不出是谁、什么时候发的记录不是数据，只是把额度花在一个空行上'
    ),
    'crawl.dy.detailSlow': (
        '[抖音] 视频 {i} 的详情页在加载超时内没加载完，已跳过该行：这是网络或站点响应慢，稍后重试可能就拿到了'
    ),
    'crawl.dy.modalDeferred': (
        '[抖音] 有 {n} 条作品卡片的遮罩打不开、本轮跳过：这不是「没有更多了」，是读不到，稍后可重试'
    ),
    # The one refusal on this page that needs no waiting and no probing: the document is
    # the browser's own, and it says which address it refused.
    'crawl.dy.noPageRefused': '[抖音] 浏览器自己拒绝了这一页，因此不可能有卡片：{url}{detail}',
    'crawl.dy.hotStart': '[抖音热榜] 开始采集热榜，目标 {n} 条（榜单一次给全，不逐条打开）',
    'crawl.dy.hotTarget': '[抖音热榜] 已采集到目标 {n} 条，不再读取榜单',
    'crawl.dy.hotDone': '[抖音热榜] 榜单采集结束，共 {n} 条（目标 {total} 条）',
    'crawl.dy.hotCapped': '[抖音热榜] 榜单本次只有 {board} 条，已按实际条数收尾（榜单大小由网站决定）',
    'crawl.dy.hotWall': '[抖音热榜] 打开榜单页时被挡在「验证码中间页」，本次未采集：请先在 Cookie 面板登录并保存抖音',
    'crawl.dy.hotRefused': '[抖音热榜] 榜单接口没有给出榜单（返回 {answer}）',
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
    'crawl.bili.goneVideo': '[哔哩哔哩搜索] {i} 稿件不存在或已失效（{code}），跳过这一条',
    'crawl.bili.fetchEmpty': '[哔哩哔哩搜索] {i} 的稿件接口没有返回可读数据（非 JSON 或被 WAF 拦截），跳过这一条',
    'crawl.bili.rankingCapped': '[哔哩哔哩] {board}本次只有 {n} 条（目标 {total} 条）：榜单大小由站点决定',
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
    'cookie.pre.account': '（账号 {account}）',
    'cookie.pre.notListed': '这个平台谁都不认识，没有验证：{platform}',
    'cookie.pre.busy': '{platform} 的浏览器正被占用',
    'cookie.pre.timeout': '验证超时（{n} 秒）',
    'cookie.pre.riskControl': '页面回的是验证码/风控',
    'cookie.verify.unclear': '{platform} 的验证没有结论：页面回的是验证码/风控，与 Cookie 是否有效无关',
    # The page never came from the site at all, so nothing about the cookie was tested —
    # and 「可用」 here would be cached and reused by every later run.
    'cookie.verify.unreachable': '{platform} 无法验证：浏览器自己没能打开这个地址（本机网络或 DNS），未检验到 Cookie',
    'cookie.delete.none': '{platform} 没有已保存的 Cookie 可删除',
    'cookie.delete.profileHolds': '注意：{platform} 的浏览器 profile 仍是登录状态，删这个文件不会把它登出',
    # 保存即更新：粘贴成功的这一刻就把这份 Cookie 送进它自己的 profile，不再要用户按第二个按钮
    # （原来那个 /api/cookies/refresh-profile 与它的四句拒绝一起删掉了）。只有一种情况当场做不到——
    # 那个浏览器正被占用——而这句话必须说：「保存成功」与「这次没进到 profile」在粘贴框里长得一样。
    'cookie.plant.deferred': (
        '{platform} 的浏览器正被占用（可能有抓取在跑），这次没能更新进 profile；Cookie 已保存，下一次抓取会自动带上它'
    ),
    'cookie.refresh.failed': '更新 profile 登录态失败：打不开该平台的浏览器（{err}）',
    'cookie.refresh.done': '已把保存的 {platform} Cookie 更新进它的浏览器 profile（{n} 条）',
    # Measured: a cookie without an expiry is never written to the profile store, so it
    # dies with the window that was opened to plant it. The count is said because the
    # alternative is a promise the next restart will break.
    'cookie.refresh.sessionOnly': '其中 {n} 条没有有效期（会话 Cookie），关掉这个窗口后不会留在 profile 里',
    'cookie.delete.failed': '删除 Cookie 文件失败：{err}',
    'api.platformsRequired': 'platforms 字段必须是平台名列表',
    'api.cookieBusy': '已有 {platform} 的登录窗口打开中——请先完成或取消它',
    'api.bodyNotObject': '请求体必须是 JSON 对象',
    'api.paramInvalid': '参数 {name} 无效',
    'api.payloadTooLarge': '请求体超过上限 {limit} MB，请分割后重试',
    'api.workflowNameRequired': '缺少有效的工作流名称',
    'api.workflowMissing': '没有这个已保存的工作流：{name}',
    'api.workflowNameTaken': '已有同名工作流「{name}」，重命名会覆盖它，请换一个名字',
    'api.workflowNameSame': '新旧名字是同一个文件，没有可重命名的东西',
    'api.workflowRenamed': '工作流已重命名：{old} → {new}',
    'api.fieldTypeInvalid': '字段 {name} 类型不正确',
    'api.stepsMustBeObjects': 'steps 必须是对象列表，每项含 "op" 与可选 "params"',
    'api.noCookieJob': '当前没有进行中的登录窗口',
    'cookie.deleted': '已删除 {platform} 的 Cookie',
    'cookie.renamed': '已把 {platform} 的登录改名：{old} → {new}（Cookie 文件与浏览器目录一起搬）',
    'cookie.renamedFileOnly': '已把 {platform} 的登录改名：{old} → {new}（该账号还没开过浏览器，只动了文件）',
    'cookie.profileDeleted': '已删除 {platform} · {account} 的浏览器 Profile（该设备已登出；Cookie 文件不动）',
    'cookie.profileDelete.none': '{platform} · {account} 没有可删除的浏览器 Profile',
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
    # Chart display labels — the column tokens the tool emits and the category values it can
    # group by. These localize ONLY at render time (the stored column names are unchanged), so
    # a Chinese run prints 发帖量 while an English run prints Total; unknown values pass through.
    'chart.col.total': '发帖量',
    'chart.col.sentiment_index': '情感指数',
    'chart.col.sentiment': '情感',
    'chart.col.prevalence_pct': '主题占比(%)',
    'chart.col.doc_n': '主题文档数',
    'chart.col.feature_words': '特征词',
    'chart.col.topic': '主题',
    'chart.col.score': '得分',
    'chart.col.weights': '权重',
    'chart.col.period': '时期',
    'chart.col.intensity': '强度',
    'chart.col.term': '词语',
    'chart.col.overall_freq': '总体词频',
    'chart.col.within_freq': '主题内词频',
    'chart.col.sample_texts': '样本帖',
    'chart.value.positive': '正面',
    'chart.value.negative': '负面',
    'chart.value.neutral': '中性',
    'chart.series.topics': '主题',
    'chart.axis.pc1': '第一主坐标',
    'chart.axis.pc2': '第二主坐标',
    'chart.range.high': '高',
    'chart.range.low': '低',
    'ml.no_training_rows': '没有可用的训练数据：所有行的文本或标签都是空的',
    'ml.need_two_labels': '训练至少需要 2 个不同的标签，当前只有：{label}',
    'ml.bad_model_name': '模型名「{name}」不合法：必须是单个路径安全的组件，不含分隔符',
    'cluster.no_features': '文本无法分词（可能只有符号），已跳过聚类：{err}',
    'engine.source_no_platform': '节点 {nid}：数据源节点没有选择平台',
    'engine.source_unknown_platform': '节点 {nid}：{platform} 还没有可用的采集实现，请改用已支持的平台',
    'engine.source_unknown_mode': '节点 {nid}：{platform} 没有这种采集内容，请在该节点的「采集内容」里改选一种',
    'engine.source_missing': '节点 {nid}：必填项「{field}」还没有填写',
    'engine.source_bad_option': '节点 {nid}：「{field}」没有「{value}」这个选项，请在该节点的下拉里改选一个',
    'engine.source_no_cookie_account': (
        '节点 {nid}：{platform} 的账号「{account}」没有可用的 Cookie——请先到 Cookie 面板为该账号保存一份，'
        '或在该节点改用已有 Cookie 的账号（不会借用别的账号登录，也不会静默少采）'
    ),
    'engine.source_link_mismatch': '节点 {nid}：{n} 个链接与所选平台（{platform}）不符',
    # Feeding a link mode from an upstream table column: the wire is allowed only where
    # the matrix declares a feed (Field.fed_by), and every mismatch is refused BY NAME —
    # a wired-but-unfed crawl would silently re-crawl the pasted list the user thinks
    # they replaced, and a fed crawl with no wire would read a table that is not there.
    'engine.source_feed_no_mode': (
        '节点 {nid}：这种采集内容不接受上游表格，逐行喂送只支持「链接列表」类表单，请断开这条连线或改选采集内容'
    ),
    'engine.source_feed_no_column': '节点 {nid}：已连接上游表格，但没有填写「{field}」要逐行读取的列名',
    'engine.source_feed_no_input': ('节点 {nid}：填写了上游列名，但该节点没有连接任何数据表（标注用的「名称」线不算）'),
    'source.feed_column_missing': '节点 {nid}：上游表格没有名为「{col}」的列',
    'source.feed_skipped': '上游喂送：跳过 {n} 个空单元格（没有可读的链接）',
    'field.keyword': '关键词',
    'field.urls': '文章链接',
    'field.author': '作者',
    'field.board': '榜单',
    'field.account': '登录账号',
    'field.format': '格式',
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
    'crawl.yt.finished': '[YouTube] 本次共采集 {n} 条（目标 {total} 条）',
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
    'comment.biliShort': '[B站评论] 游标收到 {rows} 条，站点标注 {declared} 条（匿名深翻页被限流）：{url}',
    'comment.dyNoId': '链接里没有视频 ID，无法抓评论：{url}',
    'comment.dyNoPanel': '评论区没有渲染出来（可能被折叠或需要登录）：{url}',
    'comment.dyGone': '[抖音评论] 站点把这条链接换成了另一条视频（{shown}），这条按失效处理：{url}',
    'comment.dyNone': '该视频计有 {n} 条评论，页面未展开评论列表：{url}',
    'comment.dyShort': (
        '[抖音评论] {url}：站点写着 {declared} 条，本表 {rows} 条 + 子回复 {nested} 条（还差 {gap} 条未采到）'
        ' —— 本次收尾原因是「{reason}」，所以差额不是「这条视频就这么多」'
    ),
    'comment.weiboShowFailed': '[微博评论] 评论接口取不回来（Cookie 可能失效或被限流）：{url}',
    'comment.weiboReplay': (
        '[微博评论] 第 {page} 页没有交出新的一条（游标仍在动）：按「站点在重复同一批」收工，本次 {rows} 条'
    ),
    'comment.weiboShort': (
        '[微博评论] 站点写着 {declared} 条，本表只有 {rows} 条（差 {gap} 条）'
        '—— 差额是楼中楼：这个接口在当前会话里不整批返回子评论，只有父行自带的那条预览已入表'
    ),
    'comment.weiboFetchDied': (
        '[微博评论] 第 {page} 页评论接口取数失败，就此收尾：本次 {rows} 条'
        '（站点标注 {declared} 条，差额 {gap} 条未采到；游标停在失败的那一页，可继续）'
    ),
    'comment.zhihuNoPanels': '[知乎评论] 这个回答页面上没有评论面板（可能已关闭或未加载）：{url}',
    'comment.zhihuNoAuthor': '[知乎评论] 本轮 {total} 条里有 {n} 条在自己的子树内没有作者链接（匿名或被折叠）',
    'comment.zhihuPanelCapped': '[知乎评论] 滚满 {n} 轮（含展开子回复）仍未走完，按轮次上限收工（本次 {rows} 条）',
    'comment.zhihuRound': '[知乎评论] 第 {r} 轮新增 {n} 条（累计 {total}）',
    'comment.zhihuPanelShort': '[知乎评论] 页面写着 {declared} 条，本次取到 {rows} 条（差额未采到）',
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
    'engine.output_no_upstream': '节点 {nid}：输出节点没有任何上游连线，没有可保存的表格',
    'engine.output_no_table': (
        '节点 {nid}：输出节点的上游都不产出表格（命名节点只是元数据，可视化节点产出的是图表配置）'
    ),
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
    'api.needConfirm': '这个操作会动到全部记录，请把 confirm 显式设为 true 再来',
    # Two bulk deletions, each naming what it destroyed. The claims figure is not decoration:
    # 清空运行记录 also hands back the "已采集" ledger, so the next crawl really will re-fetch
    # what an earlier one collected — a user who reads 「清空了 3 条」 and then watches the same
    # workflow crawl twice as much needs this line to know why.
    'run.cleared': '已清空运行记录：{runs} 条，并交回 {claims} 条"已采集"认领（这些条目下次会重新爬）',
    'exports.cleared': '已清空导出目录：删除 {n} 个文件',
    'exports.clearBusy': '正在运行的那次会把分片文件写进导出目录，请先停止或等它跑完再清空',
    'lock.refuse': '这一项已被锁定，请先解锁再删除/清空它',
    'lock.badKey': '锁定请求缺少有效的面板或条目名',
    'api.needApiKey': 'OpenRouter API Key 未填写（设置 → AI）',
    'api.needModel': 'OpenRouter 模型未选择（设置 → AI）',
    'api.needOllamaModel': '未选择 Ollama 模型（设置 → AI → 模型，可点“刷新”读取本地模型）',
    'api.cloudNoLocalModel': (
        '这台服务器没有本地模型可连（「{provider}」需要宿主自己跑一个 Ollama 守护进程）：'
        '云端部署只支持 OpenRouter，请在「设置 → AI」里改选 OpenRouter 并填入模型与 API Key'
    ),
    'api.cloudNoLoginWindow': (
        '这台服务器没有可以登录的窗口：请在「Cookie」面板里粘贴 Cookies JSON 保存，'
        '系统会在保存时替该账号建好 Profile 并种进去'
    ),
    'api.platformRequired': '平台不能为空',
    'api.cookiesRequired': 'Cookies 数据不能为空',
    'api.unsupportedPlatform': '不支持的平台：{platform}',
    'api.badAccount': '账号名不合法：{account}（字母、数字、下划线或连字符，1-24 个；统一按小写保存）',
    'api.cookieRenameEmptyTarget': '新名字不能留空',
    'api.cookieRenameBadName': '新名字不合法：字母、数字、下划线或连字符，1-24 个（统一按小写保存）',
    'api.cookieRenameDefault': '默认账号不能改名：它的浏览器目录就是该平台目录本身，其它账号都装在里面',
    'api.cookieRenameSameName': '新旧名字一样，没有改任何东西',
    'api.cookieRenameNoSource': '这个账号没有已保存的登录，改不了名',
    'api.cookieRenameTaken': '这个名字已经有另一份登录了，换一个个别的名字',
    'api.cookieRenameBusy': '这个账号的浏览器正在被占用，请等当前采集结束后再改名',
    'api.cookieRenameFailed': '改名失败：{err}',
    'api.profileDeleteBadName': '账号名不合法，无法定位要删除的 Profile：{account}',
    'api.profileDeleteDefault': '默认账号没有可删除的浏览器 Profile：它的数据就是平台目录本身，其它账号都在里面',
    'api.profileDeleteBusy': '{platform} · {account} 的浏览器正在被占用，请等当前采集结束后再删除它的 Profile',
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
    'run.interrupted_by_dead_worker': '执行线程已不在，记录自动判定为中断',
    'run.promoted': '发现 {n} 条上次没跑完的记录，已标记为「可续跑」',
    'run.reconciled': '发现 {n} 条线程已结束却没写下结论的记录，已判定为「已中断」',
    'run.recordWriteFailed': '记录 {rid} 的结论没能写进数据库（{err}）：运行记录会在下次刷新时自动补上判定',
    'run.start_failed': '运行线程启动失败（{err}）：本次运行已放弃，队列继续处理下一个',
    'run.nodeStopped': '节点 {nid} 已按「停止」结束：本次保留 {n} 行',
    'run.finished.stopped': '，{n} 个被停止',
    'crawl.stopped': '收到「停止」，本次抓取到此为止',
    # Said by a session whose browser process was already reaped, so it must not claim a person did
    # anything: the same object answers a cookie window that was closed after its grace ran out.
    'crawl.driverDead': '这个浏览器进程已经关掉了，不再向它发送命令',
    'run.started': '本次运行已记账：{rid}（随时可中断，数据逐条落库）',
    'run.resume_from': '续跑模式：接着 {at} 那次往下跑，此前已保存 {rows} 行',
    'run.restored': '节点 {nid} 沿用上次结果（{n} 行），不再重跑',
    'run.resume_crawl': '节点 {nid} 从上次中断处继续抓取（已有 {have} 行）',
    'run.heavy_result': '内存提示：节点「{nid}」产出 {n} 行，运行结束前每个节点的这份结果都留在内存里',
    'comment.need_both': '节点 {nid}：按评论时间筛选必须同时给出开始和结束时间（半个区间无法界定范围）',
    'comment.bad_date': '节点 {nid}：评论时间筛选的日期无法解析（请用 YYYY-MM-DD）',
    'comment.bad_range': '节点 {nid}：评论时间筛选的结束时间早于开始时间',
    'comment.time_filtered': '节点 {nid}：按评论时间 {start} ~ {end} 筛选，保留 {kept} 条、丢弃 {dropped} 条',
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
    # A 风控 refusal is the OPPOSITE advice from a dead cookie: the session may be fine and
    # re-running straight into it only deepens the block, so the console names 风控, says it
    # is not a login problem, and tells the user to wait (继续 later), never to re-save.
    'run.riskControlled': (
        '{platform} 被安全验证（风控）拦下，本次未能采满——这不是登录态失效，请勿立刻重跑（立即再撞只会加重风控）。'
        '已采集的数据全部保留；可先开启 设置→慢速采集，稍后用「继续」从断点补采'
    ),
    # U1: a crawl that came back under its target WITHOUT naming a licensed end (the site
    # said it ran out, a wall, risk, or the user's 停止) is a real under-collect, not a
    # success — so it is refused BY NAME and kept resumable, never settled clean DONE.
    # The walk funnel rides on the line because "refused N of M" is what separates "the
    # site had no more" from "our scraper dropped what it got" (§6's silent-under-collect).
    'run.underTargetShort': (
        '{platform} 采到 {have}/{want} 条就停了，却没说站点自己到底了——这不是「采完了」。'
        '已保留 {have} 行，可点「继续」从断点补剩下的{walk}'
    ),
    # The funnel clause only when the crawler reported counts; a convicted short without
    # them omits it, rather than printing a fake measurement of zeros.
    'run.underTargetWalk': '（走查：扫 {scanned}、留 {kept}、拒 {refused}）',
    # Said out loud because the alternative is silence that reads as "closed", while the
    # user may be looking at the window that is still open.
    'run.browserStuck': (
        '警告：{platform} 的浏览器关不掉（读不到它的进程号），它可能仍然开着，并会占用该平台目录最多 {seconds} 秒'
    ),
    # A page that never arrived, said once with the one thing the crawler cannot know:
    # whether this machine can reach anything at all. ``{advice}`` is left empty when the
    # page already named its own cause, so the sentence must read in both shapes.
    'run.pagePending': '{page}{streak}{advice}',
    'run.pageStreak': '；这已是本机连续第 {n} 次没有拿到页面',
    'net.region': '。诊断：本机目前到不了该平台所在的那一侧网络（对照主机不通，另一端正常）——请换网络后重跑',
    'net.offline': '。诊断：本机当前连不上任何外网（两个对照主机都不通），请先恢复网络再跑',
    'net.blocked': '。诊断：本机出网正常，但该平台的主机连不上，可能是站点故障或本地拦截',
    'net.slow': '。诊断：两侧网络都能连通，因此没有依据判断这一页为什么没到；可以再跑一次，或按停止结束',
    'net.speed': '（实测下载约 {speed} kB/s）',
    # Only for a comment node whose links came from several platforms and whose own
    # platform field is empty — the message must name what walled, and a hand-written
    # list of platforms the user never crawled reads worse than no list at all.
    'run.cookieAnyPlatform': '所采集的平台',
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
    'run.skippedWorkflows': '本次跳过（已禁用，不参与运行）：{names}',
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
    'run.reportPdfSaved': 'PDF 已导出：{name}（{size} 字节）',
    'run.reportPdfFailed': 'PDF 导出失败：{err}',
    'api.reportPdfNotFound': '找不到可导出为 PDF 的报告：{name}',
    'api.reportPdfNoChrome': '找不到 Chrome 浏览器，无法导出 PDF（请在设置里指定浏览器路径）',
    'api.reportPdfFailed': 'PDF 导出失败：{err}',
    # ── 自动清理（housekeeping） ──────────────────────────────
    'housekeeping.done': (
        '自动清理：删除 {runs} 条过期运行记录、{files} 个孤立文件（另回收 {cache} 条模型缓存、{seen} 条去重记录）'
    ),
    'housekeeping.runStoreFailed': '运行记录自动清理失败（不影响本次运行）',
    'housekeeping.datasetStoreFailed': '孤立文件自动清理失败（不影响本次运行）',
    # Why a crawl walk stopped, said to the user (engine/feed.py and engine/pager.py return the
    # machine token; stop_reason_label() maps it to one of these).
    'crawl.stopReason.target': '达到目标条数',
    'crawl.stopReason.end': '已到列表末尾',
    'crawl.stopReason.no_new': '翻了几页都没有新条目',
    'crawl.stopReason.stuck': '连续滚动没有新内容出现',
    'crawl.stopReason.no_cards': '页面没有渲染出列表',
    'crawl.stopReason.empty_page': '某一页是空的',
    'crawl.stopReason.fetch_failed': '列表接口取数失败',
    'crawl.stopReason.stopped': '用户停止了运行',
    'crawl.stopReason.wall': '登录墙拦住了后面的窗口',
    'crawl.stopReason.risk': '站点风控拦住了后面的窗口（不是 Cookie 失效）',
    'crawl.stopReason.unreachable': '浏览器根本没取到页面（网络或域名不可达，站点从未见到这个会话）',
}

_EN = {
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] Executing node: {nid} ({ntype})',
    'wf.node_failed': '[{wf}] Node {nid} failed: {err}',
    'wf.unnamed': 'Unnamed workflow {i}',
    'wf.node_completed': '[{wf}] Node {nid} completed ({done}/{total})',
    'wf.multi_input': (
        'Node {nid} has {n} incoming connections — the first (from {up}) is the primary input; '
        'an analysis node uses the second as its right-hand table, and an output node merges them all into one'
    ),
    'wf.merge_not_tabular': (
        'Node {nid}: upstream "{up}" produces no table (a chart spec or a refusal), so it cannot be merged — '
        'disconnect that wire or point it at a node that carries rows'
    ),
    'wf.merge_columns': (
        'Node {nid}: the upstream tables have different columns, compared with "{up}": extra [{extra}], '
        'missing [{missing}]. Not merged as an outer join — that fabricates empty cells and the file looks complete'
    ),
    'wf.merge_done': 'Node {nid} merged {tables} upstream tables → {n} rows ({detail})',
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
    'wf.analysis_steps_shape': '"steps" must be a LIST of steps (one object each), and this is a single object',
    'wf.analysis_llm_no_model': (
        'the 主题概括 step needs a model, and this run has none (Settings → model, or the node model box)'
    ),
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
    'label.sentiment': 'Sentiment polarity',
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
    'crawl.redrive': 'page did not reach the site (parked on {where}), re-driving once',
    'crawl.loginWall': 'Login wall: {platform} redirected {where} to a login page',
    'crawl.riskBlocked': 'Risk control: {platform} answered {where} with a security check instead of content',
    # Neither of the two above: the browser wrote this page itself, so the site never saw
    # the request and the session is not the thing in question.
    'crawl.unreachable': 'The browser refused this visit itself: {platform} at {where}{detail}',
    'crawl.unreachableToken': ' ({token})',
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
    'crawl.zhihu.stuck': (
        '{n} rounds with no new cards and no taller page, and no "no more content" marker seen — stopping the scroll'
    ),
    'crawl.zhihu.no_growth': 'Card count did not grow ({n}/3), scrolling once more to confirm...',
    'crawl.zhihu.phase_done': 'Scroll phase done, {n} cards in total',
    'crawl.zhihu.excerpt_only': (
        'Bodies left collapsed: every 正文 is a search-page excerpt (tick "Expand full text" on the data source node)'
    ),
    'crawl.zhihu.bodies_short': '{n} answer(s) did not expand; their 正文 is still a search-page excerpt',
    'crawl.zhihu.hotStart': 'Collecting the zhihu hot board, target {n}',
    'crawl.zhihu.hotDone': 'Hot board finished: {n} rows (target {total})',
    'crawl.zhihu.hotCapped': (
        'The board holds {board} questions in total, so the walk stopped there (the site sets the board size)'
    ),
    'crawl.zhihu.hotRefused': 'The zhihu hot-list endpoint gave no board (answered {answer})',
    'crawl.zhihu.hotWall': 'The zhihu hot board needs a login: the current cookie was held at the sign-in page',
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
    'crawl.weibo.target_reached': 'Reached the target of {n} rows, stopping the walk',
    'crawl.weibo.authorStart': 'Collecting author {uid}\u2019s posts, target {n}',
    'crawl.weibo.authorDone': 'Author walk finished: {n} rows ({reason})',
    'crawl.weibo.hotStart': 'Collecting the weibo hot search board, target {n}',
    'crawl.weibo.hotDone': 'Hot board finished: {n} rows (target {total})',
    'crawl.weibo.hotCapped': (
        'The hot board held only {board} rows this time, so the walk stopped there (the site sets the board size)'
    ),
    'crawl.weibo.hotRefused': 'The weibo hot-search endpoint gave no board (answered {answer})',
    # Said when the request was never issuable: the browser sat on a frame that is not weibo.com, so the
    # same-origin fetch had no host to ask. Blaming the endpoint there convicts it of an answer it never gave.
    'crawl.weibo.hotNoHost': 'weibo hot board not collected: the browser was still on 「{where}」 and never '
    'came back to weibo.com (the visitor bootstrap did not finish, so the in-page '
    'request had no host — an arrival-frame fact, not an endpoint refusal)',
    'crawl.weibo.authorEmpty': (
        '"{author}" is not a weibo author address: give a weibo.com/u/<UID> profile link or the numeric UID'
    ),
    'crawl.weibo.authorWall': (
        'weibo bounced UID {uid}\u2019s profile back to a login page: this session cannot reach the author page'
    ),
    'crawl.weibo.authorMirror': (
        'the first row returned for UID {uid} is not theirs \u2014 the endpoint answered the '
        'home timeline, not this author\u2019s posts; refusing to file it as theirs'
    ),
    'crawl.weibo.authorRefused': (
        'the mymblog endpoint refused (status {status}, UID {uid}): this is a per-session '
        'throttle, the cookie may be fine \u2014 try again later'
    ),
    'crawl.weibo.authorNoPosts': 'UID {uid} returned no posts: this account may genuinely have none',
    'crawl.weibo.visiting': 'Visiting search link: {url}',
    'crawl.weibo.no_result': 'No results in this time window, skipping',
    'crawl.weibo.waiting': 'Waiting for the page to load...',
    'crawl.weibo.page_loaded': 'Page loaded',
    'crawl.weibo.total_pages': 'Detected {n} pages in total',
    'crawl.weibo.page_crawling': '  Crawling page {i}/{total}...',
    'crawl.weibo.page_empty': '  Page {i} has no usable cards, skipping',
    'crawl.weibo.page_done': '  Page {i} done: {n} rows, {total} accumulated',
    'crawl.weibo.link_error': 'Error processing search link: {err}',
    'crawl.weibo.page_timeout': (
        '    Waited {secs}s: this page gave neither a card nor the "no result" plate (navigation {settled})'
        ' — that is all this line can say; it does not mean the window holds nothing'
    ),
    'crawl.weibo.navSettled': 'settled',
    'crawl.weibo.navUnsettled': 'did not settle, which is a slow network, not a refusal',
    'crawl.weibo.page_gave_up': (
        '    This browser has already watched {waits} search pages deliver nothing: the budget is'
        ' not being spent on another window (that is "no page fetched", not "this window is empty")'
    ),
    'crawl.weibo.walk_done': (
        'Weibo search walk closed: {n} rows (target {target}, window {walked} of {total} reached, reason: {reason})'
    ),
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
    'crawl.xhs.target_reached': '[Collect links] Target of {n} reached, stopping',
    'crawl.xhs.collect_done': '[Collect links] Done, {n} links collected',
    'crawl.xhs.detail_visit': '[Note detail] Opening detail page: {url}',
    'crawl.xhs.detail_ready': '[Note detail] Detail page loaded',
    'crawl.xhs.detail_timeout': '[Note detail] Detail page timed out',
    'crawl.xhs.deadNote': '[Detail] note blocked by 安全验证 (session is fine) — skipped: {url}',
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
    'export.window_none': 'the filename wants a time range, but no crawl here set a start/end time',
    'export.window_many': 'the filename wants a time range, but this path has {n} of them',
    'export.window_ignored': (
        'Node {nid}: the file is written as normal and only "append the crawled time range" was ignored — {reason}'
    ),
    'analysis.type_convert_failed': 'Type conversion failed for column {col} -> {dtype}: {err}',
    'analysis.calc_failed': 'Column calc failed for {col} = {expr}: {err}',
    'analysis.bin_failed': 'Binning failed for {col}: {err}',
    'analysis.col_missing': 'Column "{col}" not found',
    'analysis.dedupe_similar': (
        'Near-duplicate dedupe: SimHash distance ≤{distance} on "{column}", dropped {n} rows (first of each group kept)'
    ),
    'analysis.dedupe_distance': (
        'near-duplicate dedupe supports a distance of 0–{max} bits, got {value}: '
        'a larger one is refused rather than answered with an all-pairs scan'
    ),
    'analysis.time_unparsed': (
        '"{col}" has {n} rows that are not a parseable time (the site only gave a relative label such as '
        '"09月26日 21:00"); they are left empty rather than guessed into a year'
    ),
    'analysis.time_binned': '{col} split done: {detail}',
    'analysis.time_bin_labels': (
        'time binning needs one more boundary than there are phase names: {edges} boundaries and {labels} names'
    ),
    'analysis.time_bin_edges': 'time binning got a boundary that is not a date: {edges}',
    'analysis.time_bin_order': '{op} boundaries must run from earliest to latest',
    # A boundary PROPOSAL: this step rewrites no row and does not decide when an event
    # turned, because that needs the dates the researcher knows (the notice, the apology,
    # the filing) and not the post counts.
    'analysis.stages_sparse': (
        'only {days} days carry records in this column, which cannot be cut into phases ({least} needed)'
    ),
    'analysis.stages_ratio': 'the peak ratio has to be at least 1 (a peak is a day above the usual), got {value}',
    'analysis.stages_no_peak': (
        'the post-count curve has no turning peak {ratio}× above the usual day (median {floor} rows/day): '
        'one stretch of a curve must not be cut into several phases'
    ),
    'analysis.stages_folded': (
        'the curve holds more than {kept} peaks; the tallest {kept} were kept ({dropped} folded away)'
    ),
    'analysis.stages_folded_windows': (
        '{n} window(s) were shorter than the {days}-day minimum and joined their larger neighbour '
        '(a single tall day is not a phase)'
    ),
    'analysis.stages_done': 'phase proposal: {n} candidate windows covering {rows} rows ({span})',
    'analysis.stages_edges': 'suggested edges, left-closed/right-open, the last one is the final day + 1: {edges}',
    'analysis.stages_labels': 'suggested labels, one per window (placeholders — rename them): {labels}',
    'analysis.stages_basis_first': "opens on the curve's first day {day}",
    'analysis.stages_basis_valley': 'opens the day after the valley on {valley}',
    'analysis.topic_count': 'LDA needs at least 2 topics, got {value} (one topic is just "the whole text")',
    'analysis.topic_rows': 'LDA needs at least as many texts as topics: {topics} topics, {rows} usable rows',
    'analysis.topic_features': 'LDA could find no features in this column (punctuation or stopwords only?): {err}',
    # Staged topic modelling. Every one of these names WHICH stage and WHICH topic, because
    # "one phase produced nothing" is undiagnosable once the table holds TopicⅠ-1 … TopicⅤ-4.
    'analysis.stage_order': (
        '"{col}" no longer says which phase came first (a column that crosses a node boundary '
        'is rebuilt from records and loses its order). Keep 按时间划分阶段 in the same pipeline, '
        'or name a 阶段排序列 that holds a time'
    ),
    'analysis.stage_order_col': '{op}: the stage-order column "{col}" is not in this table',
    'analysis.stage_order_unparsed': 'no phase order can be read for {stages}: "{col}" holds no parsable time there',
    'analysis.stage_order_unranked': 'no phase order can be read for {stages}: "{col}" holds no number there',
    'analysis.topic_stage_number': 'topics per stage must be a whole number, got "{value}"',
    'analysis.topic_stage_counts': (
        '{stages} stages need one topic count each, got {counts} (a single number means the same for every stage)'
    ),
    'analysis.stage_blank': (
        '{n} rows have no "{col}" value (their timestamp did not parse), so they join no topic model'
    ),
    'analysis.topic_stage_empty': (
        'phase "{stage}" holds no rows at all, so nothing can be modelled (check the boundaries in "{col}")'
    ),
    'analysis.topic_stage_rows': (
        'phase "{stage}" has only {rows} usable texts, which cannot carry {topics} topics '
        '(LDA needs at least as many texts as topics)'
    ),
    'analysis.topic_stage_features': 'phase "{stage}" yielded no feature words: {err}',
    'analysis.topic_stage_words': (
        'nothing could be selected as a feature word for {topic} in phase "{stage}" — no text was assigned to it, '
        "so lower that stage's topic count"
    ),
    'analysis.topic_stage_unused': (
        'no text was assigned to {topic} in phase "{stage}" (doc_n=0), '
        'so its feature words come from the topic distribution'
    ),
    'analysis.topic_stage_done': 'phase "{stage}": {n} topics over {rows} texts, perplexity {perplexity}',
    'analysis.topic_map_done': (
        'intertopic map: {n} topics over {rows} texts, perplexity {perplexity} '
        '(bubble size = topic share; coordinates = MDS of the Jensen-Shannon distance between word distributions)'
    ),
    'analysis.topic_salience_done': (
        'salient terms: {terms} rows for {n} topics over {rows} texts, λ={value} '
        '(1 ranks by probability within the topic, 0 by over-representation against the corpus)'
    ),
    'analysis.topic_lambda': (
        'λ must sit between 0 and 1 (0 = over-representation only, 1 = within-topic probability only), got {value}'
    ),
    'analysis.label_no_llm': '{op} was handed no model client: only a canvas run carries one',
    'analysis.label_too_many': (
        'the labelling step asks the model once per topic: {rows} rows is over the limit of {limit}, '
        'so filter the topic table first'
    ),
    'analysis.label_no_words': '{topic} has an empty "{col}", and there is nothing to summarise without feature words',
    'analysis.label_failed': 'the summary for {topic} failed: {err}',
    'analysis.label_empty': 'the summary for {topic} came back empty (the model answered with punctuation only)',
    'analysis.label_cancelled': 'stopped: {n} topics were never asked, and their summaries are marked 未处理',
    'analysis.label_done': 'topic summaries: {n} written (model {model})',
    'analysis.label_cached': (
        'topic summaries: {asked} new questions to the model, {replayed} answers replayed from the '
        'cache (re-running the same table no longer pays twice)'
    ),
    'analysis.label_prompt': (
        'You are a public-opinion researcher. Below are the feature words and sample posts of one topic '
        'inside one phase of a cyberbullying event. Summarise what this topic is about in at most six words; '
        'output the phrase alone, no explanation, no quotes.\n'
        'Phase: {stage}\nTopic: {topic}\nFeature words: {words}\nSample posts: {samples}'
    ),
    'analysis.topic_done': (
        'LDA topic model: {n} topics over {rows} texts, perplexity {perplexity} '
        '(lower fits better, but far too low means it is memorising the corpus)'
    ),
    'analysis.evolution_done': (
        'Sentiment evolution: {n} periods from "period" ({periods}); index = (positive − negative) / total ∈ [-1, 1]'
    ),
    'analysis.evolution_unscored': (
        'no rows of "{col}" carry a score in {periods}, so the sentiment intensity is left empty there'
    ),
    # ── Reads taken after the phases: lifecycles, flow, a topic-count sweep, co-occurrence ──
    'analysis.timeline_stages': (
        'a lifecycle needs at least 2 phases to say "before" and "after", this table has {stages}'
    ),
    'analysis.timeline_overlap': 'the same-topic word overlap has to be between 0 and 1, got {value}',
    'analysis.timeline_blank': '{n} rows of "{col}" belong to no phase, so they join no lifecycle',
    'analysis.timeline_size': '"{col}" holds no number at all, so a peak cannot be measured (blank is not a peak of 0)',
    'analysis.timeline_partial': '{n} rows of "{col}" are not numbers and count as 0 when finding the peak',
    'analysis.timeline_words': '{topic} of phase "{stage}" has no feature words in "{col}", so it cannot be followed',
    'analysis.timeline_done': (
        'topic lifecycles: {topics} subjects over {stages} phases, {multi} spanning more than one phase '
        'and {secondary} flagged as a secondary flare-up (word-overlap threshold {value})'
    ),
    'analysis.timeline_secondary': 'secondary flare-up: {topic} runs {path}',
    'analysis.flow_stages': 'topic flow needs at least 2 adjacent phases, this table has {stages}',
    'analysis.flow_similarity': 'the flow similarity threshold has to be between 0 and 1, got {value}',
    'analysis.flow_weights': (
        '{topic} (phase "{stage}") has no usable word weights in "{col}", so no divergence can be computed'
    ),
    'analysis.flow_stage_empty': 'phase "{stage}" holds no topic rows (check "{col}" first)',
    'analysis.flow_no_edges': (
        'no topic pair reached the similarity threshold {value}: the closest measured pair was {best}, '
        'so lower the threshold below it'
    ),
    'analysis.flow_done': 'topic flow: {edges} edges between {stages} phases (threshold {value}, best measured {best})',
    'analysis.coherence_range': 'the topic-count sweep cannot start above where it ends: {low} > {high}',
    'analysis.coherence_sampled': (
        'the sweep fits {used} sampled texts out of {total} available; a different sample moves the numbers'
    ),
    'analysis.coherence_capped': (
        'only {rows} texts are available, so the sweep stops at {rows} topics instead of {high}'
    ),
    'analysis.coherence_pairs': (
        'no pair of the {topn} top words of any topic appears in one text ({pairs} pairs skipped): '
        'coherence is unmeasurable here, only perplexity is readable'
    ),
    'analysis.coherence_best': (
        'topic-count sweep ({low}…{high}): best coherence at {coherence} topics, lowest perplexity at {perplexity}'
    ),
    'analysis.cooccur_topn': (
        'a co-occurrence network caps its candidate words at {cap} (doubling the words '
        'quadruples the edges), got {value}'
    ),
    'analysis.cooccur_count': 'the co-occurrence count threshold has to be at least 1, got {value}',
    'analysis.cooccur_words': (
        'only {found} candidate words were available, which cannot form a pair (asked for the top {topn})'
    ),
    'analysis.cooccur_empty': (
        'no word pair reached the count threshold {floor}: the busiest of {pairs} pairs appeared {top} times, '
        'so lower the threshold or widen the candidates'
    ),
    'analysis.cooccur_done': (
        'co-occurrence network: {words} candidate words over {docs} texts, {edges} of {pairs} pairs at or above {floor}'
    ),
    # ── Looking forward: extrapolating the curve, and the flare-up warning ──
    'analysis.forecast_horizon': 'the horizon has to be at least 1 step, got {value} (0 just copies the last cell)',
    'analysis.forecast_window': 'a moving average needs 2 periods to average, got {value}',
    'analysis.forecast_smooth': 'the smoothing factor "{name}" has to be strictly between 0 and 1, got {value}',
    'analysis.forecast_dates': '"{col}" is not a period column of dates: a phase NAME cannot be extrapolated',
    'analysis.forecast_rows': (
        'extrapolating needs at least {least} observed periods, this column gives {rows} with both a date and a number'
    ),
    'analysis.forecast_window_rows': (
        'a window of {window} still needs one period left to forecast, this column has {rows}'
    ),
    'analysis.forecast_duplicate': '"{col}" has two rows for the same day: {days} (they read as two steps of a trend)',
    'analysis.forecast_uneven': (
        'the periods are not evenly spaced: {steps} of {rows} gaps are not {gap} days, '
        'so future rows are labelled {gap} days apart'
    ),
    'analysis.forecast_done': (
        '{method} forecast: {rows} observed periods, {horizon} steps ahead, {gap}-day spacing (last {last})'
    ),
    'analysis.alert_streak': 'the streak has to be at least 1 period, got {value}',
    'analysis.alert_threshold': 'the "{name}" threshold has to be above 0, got {value}',
    'analysis.alert_floor': 'the volume-hold ratio cannot exceed 1 (that asks for growth), got {value}',
    'analysis.alert_rows': 'the warning needs one row more than the streak: asked for {least}, this table has {rows}',
    'analysis.alert_skipped': '{n} rows of "{col}" parse to no date, so they join no warning check',
    'analysis.alert_reason': (
        'moves over the last {streak} periods {moves}; intensity slope {intensity}; volume {volume} ({held})'
    ),
    'analysis.alert_none': (
        'nothing fired: the largest swing was {period}, and {streak} consecutive moves stayed under {swing} '
        'while the intensity slope stayed under {heating}'
    ),
    'analysis.alert_none_log': 'warning checked {checked} periods (streak {streak}, swing {swing}) and fired on none',
    'analysis.alert_fired': 'flare-up warning: {period} fired {signal} at {value}',
    'clean.unknown_mode': 'the clean node has no mode named "{mode}" (available: regex, llm)',
    'aggression.lexicon_done': (
        'cyberbullying scan (word list): {violent} of {rows} rows carry violent speech, {severe} severe '
        '(misses cannot be measured here — wording outside the list is invisible)'
    ),
    'clean.regex_done': (
        'Regex clean: kept {kept} rows, marked {dropped} for deletion '
        '(topic relevance is not judged here — that needs the llm mode)'
    ),
    'analysis.need_param': '{op} needs {param}, which is empty',
    'analysis.need_number': '{op}: "{param}" has to be a whole number, got "{value}"',
    'analysis.step_col_missing': '{op}: no column named "{col}" in this table',
    'analysis.step_cols_missing': '{op}: these columns are not in this table: {cols}',
    'analysis.bad_option': '{op} has no "{param}" option "{value}" (available: {allowed})',
    'analysis.rename_blank': '{op}: these columns have no new name — set one for: {cols}',
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
    'sentiment.scored': 'Sentiment polarity ({mode}): judged {n} rows',
    'sentiment.scored_failed': 'Sentiment polarity: {n} rows could not be read and are left blank (not neutral)',
    'sentiment.snownlp_failed': 'SnowNLP failed: {err}',
    'sentiment.bert_failed': 'BERT failed: {err}',
    'sentiment.ml_failed': 'ML sentiment polarity prediction failed: {err} — falling back to neutral',
    'sentiment.unknown_mode': 'unknown sentiment polarity mode "{mode}"',
    'sentiment.bad_thresholds': 'the positive threshold {pos} cannot sit below the negative threshold {neg}',
    'sentiment.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'sentiment.bert_no_model': 'BERT mode needs a sentiment model named; empty means nothing can be judged',
    'sentiment.bert_bad_label': 'the BERT model answered an unrecognised label "{label}"',
    'sentiment.bert_loaded': 'BERT sentiment model loaded: {model} (running on {device}, in batches)',
    'emotion.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'emotion.bert_no_model': 'BERT mode needs an emotion model named; empty means nothing can be judged',
    'emotion.bert_loaded': 'BERT emotion model loaded: {model} (running on {device}, in batches)',
    'emotion.bert_failed': 'BERT emotion failed: {err}',
    'emotion.bert_bad_label': 'the BERT model answered an unrecognised emotion label "{label}"',
    'emotion.bert_done': '[BERT] emotion classification done, {n} rows, {failed} failed',
    'tendency.bert_missing': 'BERT mode needs {need} installed here — it is not, and nothing else will run instead',
    'tendency.bert_no_model': 'BERT mode needs a tendency model named; empty means nothing can be judged',
    'tendency.bert_loaded': 'BERT tendency model loaded: {model} (running on {device}, in batches)',
    'tendency.bert_failed': 'BERT tendency failed: {err}',
    'tendency.bert_bad_label': 'the BERT model answered an unrecognised tendency label "{label}"',
    'tendency.bert_done': '[BERT] tendency classification done, {n} rows, {failed} failed',
    'ml.tendency_failed': 'ML tendency prediction failed: {err} — falling back to Objective Statement',
    'ml.emotion_done': '[ML] Emotion classification done, {n} rows, mode: ML',
    'ml.tendency_done': '[ML] Tendency analysis done, {n} rows, mode: ML',
    'cookie.saved': 'Cookies saved for {platform}',
    # {account} is already a word by the time it reaches here (blank → "default account",
    # default2 → "default account 2", a typed label verbatim), so the sentence never prints a key.
    'cookie.savedAccount': 'Cookies saved for {platform} (account: {account})',
    'cookies.accountDefault': 'default account',
    'cookies.accountDefaultNumbered': 'default account {n}',
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
    'bounced back to the passport QR page. Weibo accepts one live session per account: paging in parallel, '
    'or replaying the same cookie from a second browser, is answered with the login page — so always crawl '
    'from the same profile, and never run two Weibo crawls at once.',
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
    'crawl.dy.target_reached': '[Douyin] target of {n} rows reached, stop',
    'crawl.dy.round': '[Douyin] screen {i}: {n} cards ({fresh} new, {done} collected)',
    'crawl.dy.noMore': (
        '[Douyin] the list wrote its own "no more for now": {screens} screens read, last screen held '
        '{cards} cards — that is the supply for this order, not a scroll that failed'
    ),
    'crawl.dy.processed': '[Douyin] stored video {i}, {n} valid rows so far',
    'crawl.dy.authorStart': "[Douyin author] one creator's posts, target {n} (counters read from the in-page overlay)",
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
    'crawl.dy.detailWalled': (
        '[Douyin] video {i} was answered with the captcha interstitial (image-text posts are refused for this '
        'device; video pages are not) — row skipped: the site did not run out of content and the session is not dead'
    ),
    'crawl.dy.detailSwapped': (
        '[Douyin] asked for video {i} but the browser served a different one, {shown} (the site swapped the content)'
        " — row not stored: one row short beats somebody else's caption and counters filed under this link"
    ),
    'crawl.dy.detailNoIdentity': (
        '[Douyin] video {i} rendered only its counter bar — no author and no publish time, row skipped: '
        'a record that cannot say whose it is or when it was posted is not data, just budget spent on a blank row'
    ),
    'crawl.dy.detailSlow': (
        '[Douyin] video {i} did not finish loading inside the page-load timeout, row skipped: that is the '
        'network or the site being slow, a retry may well get it'
    ),
    'crawl.dy.modalDeferred': (
        '[Douyin] the overlay would not open for {n} works cards, skipped this round: that is unreadable, '
        'not the site running out — retry later'
    ),
    # The one refusal on this page that needs no waiting and no probing: the document is
    # the browser's own, and it says which address it refused.
    'crawl.dy.noPageRefused': '[Douyin] the browser refused this page itself, so there can be no cards: {url}{detail}',
    'crawl.dy.hotStart': '[Douyin hot board] collecting the board, target {n} (one answer, no per-row page)',
    'crawl.dy.hotTarget': '[Douyin hot board] the target of {n} rows is already stored, the board is not read again',
    'crawl.dy.hotDone': '[Douyin hot board] finished with {n} rows (target {total})',
    'crawl.dy.hotCapped': (
        '[Douyin hot board] the board held {board} rows this time, so the run ended there '
        '(the site decides how large a board is)'
    ),
    'crawl.dy.hotWall': (
        '[Douyin hot board] the board page was parked on the captcha interstitial, so nothing was collected: '
        'save the douyin cookie through the Cookie panel first'
    ),
    'crawl.dy.hotRefused': '[Douyin hot board] the board endpoint gave no board (answered {answer})',
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
    'crawl.bili.goneVideo': '[Bilibili search] {i} is withdrawn or unavailable ({code}), skipped',
    'crawl.bili.fetchEmpty': '[Bilibili search] {i} returned no readable data (non-JSON or WAF-blocked), skipped',
    'crawl.bili.rankingCapped': "[Bilibili] the {board} had only {n} rows (target {total}): its size is the site's",
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
    'cookie.pre.account': ' (account {account})',
    'cookie.pre.notListed': 'Nothing here knows that platform, so nothing was checked: {platform}',
    'cookie.pre.busy': "{platform}'s browser is already held by something else",
    'cookie.pre.timeout': 'the check ran past {n} seconds',
    'cookie.pre.riskControl': 'the page answered with a captcha / risk control',
    'cookie.verify.unclear': '{platform} could not be verified: the page answered with a captcha or risk '
    'control, which says nothing about whether the cookie is valid',
    # The page never came from the site at all, so nothing about the cookie was tested —
    # and 「可用」 here would be cached and reused by every later run.
    'cookie.verify.unreachable': '{platform} could not be verified: the browser never opened this address '
    '(this machine\u2019s network or DNS), so the cookie was not tested',
    'cookie.delete.none': 'There is no saved {platform} cookie to delete',
    'cookie.delete.profileHolds': 'Note: {platform}\u2019s browser profile stays logged in — deleting this '
    'file does not sign that device out',
    # Saving IS the update now: the paste plants itself into that account's profile, and the
    # /api/cookies/refresh-profile route with its four refusal sentences went away with the
    # button. One case cannot be done on the spot — that browser is held — and it has to say so,
    # because 「saved」 and 「saved but not in the profile」 look identical from a paste box.
    'cookie.plant.deferred': (
        "{platform}'s browser is held by something else (a crawl may be running), so this cookie "
        'could not be planted into its profile yet — it is saved, and the next crawl will bring it in'
    ),
    'cookie.refresh.failed': 'Could not update the profile session: this platform\u2019s browser did not open ({err})',
    'cookie.refresh.done': 'Saved {platform} cookies were planted into its browser profile ({n} entries)',
    # Measured: a cookie without an expiry is never written to the profile store, so it
    # dies with the window that was opened to plant it.
    'cookie.refresh.sessionOnly': 'Note: {n} of them carry no expiry, so they live only in that window and are not '
    'kept by the profile once it closes',
    'cookie.delete.failed': 'Could not delete the cookie file: {err}',
    'api.platformsRequired': 'platforms must be a list of platform names',
    'api.cookieBusy': 'A {platform} login window is already open — finish or cancel it first',
    'api.bodyNotObject': 'request body must be a JSON object',
    'api.paramInvalid': 'parameter {name} is invalid',
    'api.payloadTooLarge': 'request body exceeds the {limit} MB ceiling — split it up',
    'api.workflowNameRequired': 'a valid workflow name is required',
    'api.workflowMissing': 'No saved workflow by that name: {name}',
    'api.workflowNameTaken': 'A workflow named “{name}” already exists — renaming would overwrite it, pick another',
    'api.workflowNameSame': 'The old and new names are the same file, so there is nothing to rename',
    'api.workflowRenamed': 'Workflow renamed: {old} → {new}',
    'api.fieldTypeInvalid': 'field {name} has the wrong type',
    'api.stepsMustBeObjects': 'steps must be a list of objects, each with an "op" and optional "params"',
    'api.noCookieJob': 'No cookie login is currently active',
    'cookie.deleted': 'Cookies deleted for {platform}',
    'cookie.renamed': (
        'Renamed the {platform} login “{old}” to “{new}” (its cookie file and its own browser directory moved together)'
    ),
    'cookie.renamedFileOnly': (
        'Renamed the {platform} login “{old}” to “{new}” — that account has never opened a '
        'browser of its own, so only the cookie file moved'
    ),
    'cookie.profileDeleted': (
        'Deleted the browser profile for {platform} · {account} — that device is signed out; '
        'the saved cookie file is untouched'
    ),
    'cookie.profileDelete.none': 'There is no browser profile to delete for {platform} · {account}',
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
    'chart.col.total': 'Total',
    'chart.col.sentiment_index': 'Sentiment index',
    'chart.col.sentiment': 'Sentiment',
    'chart.col.prevalence_pct': 'Prevalence (%)',
    'chart.col.doc_n': 'Topic docs',
    'chart.col.feature_words': 'Feature words',
    'chart.col.topic': 'Topic',
    'chart.col.score': 'Score',
    'chart.col.weights': 'Weight',
    'chart.col.period': 'Period',
    'chart.col.intensity': 'Intensity',
    'chart.col.term': 'Term',
    'chart.col.overall_freq': 'Overall frequency',
    'chart.col.within_freq': 'Within-topic frequency',
    'chart.col.sample_texts': 'Sample posts',
    'chart.value.positive': 'Positive',
    'chart.value.negative': 'Negative',
    'chart.value.neutral': 'Neutral',
    'chart.series.topics': 'Topics',
    'chart.axis.pc1': 'PC1',
    'chart.axis.pc2': 'PC2',
    'chart.range.high': 'High',
    'chart.range.low': 'Low',
    'ml.no_training_rows': 'No training data: every row has an empty text or label',
    'ml.need_two_labels': 'Training needs at least 2 distinct labels; this data only has: {label}',
    'ml.bad_model_name': 'Model name "{name}" is invalid: must be one path-safe component, no separators',
    'cluster.no_features': 'Text could not be segmented (symbols only?) — clustering skipped: {err}',
    'engine.source_no_platform': 'Node {nid}: source node has no platform',
    'engine.source_unknown_platform': 'Node {nid}: {platform} has no crawler yet — pick a supported platform',
    'engine.source_unknown_mode': 'Node {nid}: {platform} has no such collection mode — pick one under Collect',
    'engine.source_missing': 'Node {nid}: the required field {field} is empty',
    'engine.source_bad_option': 'Node {nid}: {field} has no option "{value}" — pick one of the choices in that node',
    'engine.source_no_cookie_account': (
        'Node {nid}: no cookie for the {platform} account "{account}" — save one in the Cookie panel, '
        'or pick an account that has a login (this never borrows another account and never '
        'silently under-collects)'
    ),
    'engine.source_link_mismatch': 'Node {nid}: {n} link(s) do not match the selected platform ({platform})',
    'engine.source_feed_no_mode': (
        'Node {nid}: this collection mode cannot be fed from an upstream table — '
        'only link-list forms take a fed column; disconnect the wire or pick another mode'
    ),
    'engine.source_feed_no_column': (
        'Node {nid}: an upstream table is wired in but no column was named for {field} to read row by row'
    ),
    'engine.source_feed_no_input': (
        'Node {nid}: a fed column is named but this node has no data input wired (a name-label wire does not count)'
    ),
    'source.feed_column_missing': 'Node {nid}: the upstream table has no column named {col}',
    'source.feed_skipped': 'upstream feed: skipped {n} empty cell(s) (no link to read)',
    'field.keyword': 'keyword',
    'field.urls': 'article URLs',
    'field.author': 'creator',
    'field.board': 'board',
    'field.account': 'account',
    'field.format': 'format',
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
    'crawl.yt.finished': '[YouTube] collected {n} rows (target {total})',
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
    'comment.biliShort': '[bilibili] cursor got {rows} of {declared} per the site (deep-page throttling): {url}',
    'comment.dyNoId': 'the link carries no video id, so comments cannot be fetched: {url}',
    'comment.dyNoPanel': 'the comment panel never rendered (collapsed, or login required): {url}',
    'comment.dyGone': (
        '[douyin comments] the site answered this link with a different video ({shown}); '
        'this link counts as dead, not as a wall: {url}'
    ),
    'comment.dyNone': 'this video reports {n} comments but the list did not open: {url}',
    'comment.dyShort': (
        '[douyin comments] {url}: the page says {declared}, this table holds {rows} plus {nested} counted '
        'replies ({gap} still not collected) — this walk ended because: {reason}, so the gap is not a claim '
        'that the thread is that short'
    ),
    'comment.weiboShowFailed': '[weibo comments] the comment endpoint answered nothing (dead cookie, limited): {url}',
    'comment.weiboReplay': (
        '[weibo comments] page {page} added no new row while the cursor was still live: '
        'the walk calls the thread replayed and stops, at {rows} rows'
    ),
    'comment.weiboShort': (
        '[weibo comments] the page says {declared}, this table holds {rows} (a gap of {gap})'
        ' — the missing rows are nested replies: this endpoint does not return them as a list in the'
        ' current session, and only the one preview each parent row carries is in the table'
    ),
    'comment.weiboFetchDied': (
        '[weibo comments] the comment request failed on page {page}, so the walk ended: {rows} rows kept'
        ' (the thread is labelled {declared}, {gap} of them unfetched; the cursor stayed on the page that'
        ' failed, so 继续 can pick it up)'
    ),
    'comment.zhihuNoPanels': '[zhihu comments] no comment panel on this answer (closed, or never loaded): {url}',
    'comment.zhihuNoAuthor': (
        '[zhihu comments] {n} of {total} rows carry no author link inside their own subtree (anonymous or collapsed)'
    ),
    'comment.zhihuPanelCapped': (
        '[zhihu comments] stopped after {n} scroll rounds (reply threads opened) with the panel still '
        'growing; took {rows} rows'
    ),
    'comment.zhihuRound': '[zhihu comments] round {r} added {n} rows ({total} so far)',
    'comment.zhihuPanelShort': '[zhihu comments] the page says {declared} comments, {rows} were taken',
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
    'engine.output_no_upstream': 'Node {nid}: output node has no incoming connection, so there is no table to save',
    'engine.output_no_table': (
        "Node {nid}: none of the output node's upstreams produces a table "
        '(a name node is metadata, a visualize node answers a chart spec)'
    ),
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
    'api.needConfirm': 'This acts on every record — send confirm=true explicitly to do it',
    'run.cleared': 'Run records cleared: {runs} removed, and {claims} "already crawled" claims handed back',
    'exports.cleared': 'Export folder cleared: {n} file(s) removed',
    'exports.clearBusy': 'A live run is writing part files into the export folder — stop it or wait before clearing',
    'lock.refuse': 'This item is locked — unlock it before deleting or clearing',
    'lock.badKey': 'The lock request is missing a valid panel or entry name',
    'api.needApiKey': 'The OpenRouter API key is missing (Settings → AI)',
    'api.needModel': 'No OpenRouter model selected (Settings → AI)',
    'api.needOllamaModel': 'No Ollama model selected (Settings → AI → Model; hit Refresh to list local ones)',
    'api.cloudNoLocalModel': (
        'This server has no local model to talk to ("{provider}" wants an Ollama daemon on its own '
        'host): a cloud deployment only supports OpenRouter — pick OpenRouter under Settings → AI and '
        'fill in the model and API key'
    ),
    'api.cloudNoLoginWindow': (
        'This server has no window to log into: paste the Cookies JSON into the Cookie panel and save, '
        "which builds that account's profile and plants the session into it"
    ),
    'api.platformRequired': 'Platform is required',
    'api.cookiesRequired': 'Cookies data is required',
    'api.unsupportedPlatform': 'Unsupported platform: {platform}',
    'api.badAccount': (
        'Invalid account name: {account} (letters, digits, _ and -, 1-24 of them; case does not '
        'make a second account — names are stored lowercase)'
    ),
    'api.cookieRenameEmptyTarget': 'The new name cannot be blank',
    'api.cookieRenameBadName': (
        'Invalid new name: letters, digits, _ and -, 1-24 of them (case does not make a second '
        'account — names are stored lowercase)'
    ),
    'api.cookieRenameDefault': (
        'The default account cannot be renamed: its browser directory IS the platform’s '
        'directory, with every other account inside it'
    ),
    'api.cookieRenameSameName': 'The old and new names are the same, so nothing was renamed',
    'api.cookieRenameNoSource': 'That account has no saved login to rename',
    'api.cookieRenameTaken': 'Another login already uses that name — pick a different one',
    'api.cookieRenameBusy': 'That account’s browser is in use; rename it after the current crawl ends',
    'api.cookieRenameFailed': 'Renaming failed: {err}',
    'api.profileDeleteBadName': (
        'Invalid account name: {account} (the default account has no separate profile directory to delete; '
        'letters, digits, underscore or hyphen, 1-24, stored lowercase)'
    ),
    'api.profileDeleteDefault': (
        'The default account has no browser profile to delete — its browser data IS the platform directory, '
        'and every other account is nested inside it'
    ),
    'api.profileDeleteBusy': (
        '{platform} · {account}’s browser is in use — wait for the running crawl to finish before deleting its profile'
    ),
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
    'run.interrupted_by_dead_worker': 'Its worker thread is gone, so the record was settled as interrupted',
    'run.promoted': '{n} unfinished run(s) from an earlier session marked resumable',
    'run.reconciled': '{n} record(s) whose worker had already gone were settled as interrupted',
    'run.recordWriteFailed': (
        'Could not write the verdict for record {rid} ({err}): the run list settles it on the next refresh'
    ),
    'run.start_failed': 'Could not start the run worker ({err}): this run is dropped and the queue moves to the next',
    'run.nodeStopped': 'Node {nid} ended on Stop: {n} row(s) kept',
    'run.finished.stopped': ', {n} stopped',
    'crawl.stopped': 'Stop received — this crawl ends here',
    # Said by a session whose browser process was already reaped, so it must not claim a person did
    # anything: the same object answers a cookie window that was closed after its grace ran out.
    'crawl.driverDead': 'This browser process is already closed, so no further commands are sent to it',
    'run.started': 'This run is checkpointed as {rid} — every row lands in the database as it is produced',
    'run.resume_from': 'Resuming the run interrupted at {at} — {rows} rows already stored',
    'run.restored': 'Node {nid} reuses its previous result ({n} rows) instead of running again',
    'run.resume_crawl': 'Node {nid} continues crawling from where it stopped ({have} rows already saved)',
    'run.heavy_result': (
        'Memory note: node "{nid}" produced {n} rows, and every node\'s rows are held in memory until the run ends'
    ),
    'comment.need_both': (
        'Node {nid}: filtering comments by time needs BOTH a start and an end (a half range cannot bound the window)'
    ),
    'comment.bad_date': 'Node {nid}: the comment time range could not be parsed (use YYYY-MM-DD)',
    'comment.bad_range': 'Node {nid}: the comment time range ends before it starts',
    'comment.time_filtered': 'Node {nid}: filtered comments by time {start} ~ {end}: kept {kept}, dropped {dropped}',
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
    # A 风控 refusal is the OPPOSITE advice from a dead cookie: the session may be fine and
    # re-running straight into it only deepens the block, so the console names risk control,
    # says it is not a login problem, and tells the user to wait (继续 later), never re-save.
    'run.riskControlled': (
        '{platform} was stopped by a security check (risk control) before the target was met — this is NOT an expired '
        'login, and re-running immediately only deepens the block. Everything collected so far is kept; you can enable '
        'Settings -> Gentle crawling, then use 继续 / Resume later to pick up from the checkpoint'
    ),
    # U1: a crawl under its target that named no licensed end (site ran out / wall / risk /
    # the user's Stop) is a real under-collect, refused by name and left resumable — never
    # settled clean DONE. The walk funnel rides along because "refused N of M" is what tells
    # "the site had no more" from "our scraper dropped what it got" (§6 silent-under-collect).
    'run.underTargetShort': (
        '{platform} stopped at {have}/{want} rows without the site saying it ran out — that is not "finished". '
        '{have} rows are kept; press Continue to pick up the rest from the cursor{walk}'
    ),
    # The funnel clause only when the crawler reported counts; a convicted short without them
    # omits it rather than printing a fake measurement of zeros.
    'run.underTargetWalk': ' (walk: scanned {scanned}, kept {kept}, refused {refused})',
    # Said out loud because the alternative is silence that reads as "closed", while the
    # user may be looking at the window that is still open.
    'run.browserStuck': (
        'warning: {platform}\u2019s browser could not be closed (no readable process id); it may still be '
        'open and holds that platform\u2019s directory for up to {seconds} seconds'
    ),
    # A page that never arrived, said once with the one thing the crawler cannot know:
    # whether this machine can reach anything at all. ``{advice}`` is empty when the page
    # already named its own cause, so the sentence has to read in both shapes.
    'run.pagePending': '{page}{streak}{advice}',
    'run.pageStreak': '; this is the {n}th page in a row this machine has not delivered',
    'net.region': (
        '. Diagnosis: this machine cannot reach the side of the internet that platform lives on (the control host '
        'for it fails while the other answers) — switch network and run it again'
    ),
    'net.offline': (
        '. Diagnosis: this machine has no outbound connection at all right now (both control hosts fail), '
        'so restore the network before running again'
    ),
    'net.blocked': (
        '. Diagnosis: this machine routes normally but the platform host itself does not answer, '
        'which is a site outage or a local interception rather than a slow page'
    ),
    'net.slow': (
        '. Diagnosis: both sides connect, so there is no evidence for why this page did not arrive; '
        'run it again, or press Stop to end the run'
    ),
    'net.speed': ' (measured about {speed} kB/s)',
    'run.cookieAnyPlatform': 'the platform being crawled',
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
    'run.skippedWorkflows': 'skipped this run (disabled, will not run): {names}',
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
    'run.reportPdfSaved': 'PDF exported: {name} ({size} bytes)',
    'run.reportPdfFailed': 'PDF export failed: {err}',
    'api.reportPdfNotFound': 'No report to export as PDF: {name}',
    'api.reportPdfNoChrome': 'Chrome was not found, so the PDF cannot be exported (set a browser path in Settings)',
    'api.reportPdfFailed': 'PDF export failed: {err}',
    # ── housekeeping ──────────────────────────────────────────
    'housekeeping.done': (
        'Housekeeping: dropped {runs} expired run record(s) and {files} orphaned file(s) '
        '(plus {cache} cached model answer(s) and {seen} stale dedupe key(s))'
    ),
    'housekeeping.runStoreFailed': 'Automatic run-record cleanup failed (the run itself is unaffected)',
    'housekeeping.datasetStoreFailed': 'Automatic orphan-file cleanup failed (the run itself is unaffected)',
    'crawl.stopReason.target': 'reached the target count',
    'crawl.stopReason.end': 'reached the end of the list',
    'crawl.stopReason.no_new': 'no new rows after paging',
    'crawl.stopReason.stuck': 'scrolling produced nothing new',
    'crawl.stopReason.no_cards': 'the page rendered no list',
    'crawl.stopReason.empty_page': 'a page came back empty',
    'crawl.stopReason.fetch_failed': 'the list request failed',
    'crawl.stopReason.stopped': 'the run was stopped',
    'crawl.stopReason.wall': 'a login wall stopped the walk',
    'crawl.stopReason.risk': "the site's risk control stopped the walk (not a dead cookie)",
    'crawl.stopReason.unreachable': 'the browser never fetched a page at all (network or DNS),'
    ' so the site never saw this session',
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
    # The enumeration comma is language-specific: '、' reads right in Chinese and wrong
    # in English ("Zhihu、Weibo"). Pick the joiner by the reader's language.
    sep = '、' if get_lang() == 'zh' else ', '
    for slot in ('platform', 'platforms'):
        value = named.get(slot)
        if isinstance(value, str):
            # Split on a list separator and nothing else. Splitting on whitespace or on
            # `/` looked harmless and was not: a refusal that names what it refused
            # (`../x`) came back mangled, and a sentence would have been re-joined with
            # 、. An unknown token is passed through whole, which is the safe answer for
            # every value that was never a platform key.
            named[slot] = sep.join(
                platform_label(part.strip()) for part in re.split(r'[,、]', value.strip()) if part.strip()
            )
        elif isinstance(value, (list, tuple, set)):
            named[slot] = sep.join(platform_label(item) for item in value)
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


#: Machine stop-tokens a crawl walk can end on (``engine/feed.py`` / ``engine/pager.py`` return
#: these). The engine stays language-free; a log line wraps the token here so the console reads a
#: reason, not a code word like ``stuck``. An unknown token falls through unchanged rather than
#: inventing a sentence, so a new engine reason is visible, never silently swallowed.
STOP_REASONS = {
    'target': 'crawl.stopReason.target',
    'end': 'crawl.stopReason.end',
    'no_new': 'crawl.stopReason.no_new',
    'stuck': 'crawl.stopReason.stuck',
    'no_cards': 'crawl.stopReason.no_cards',
    'empty_page': 'crawl.stopReason.empty_page',
    'fetch_failed': 'crawl.stopReason.fetch_failed',
    'stopped': 'crawl.stopReason.stopped',
    # Not an engine token: a walk over a *list of URLs* (weibo's hourly windows) ends on the wall
    # itself, not on one page's shape, and it must still read as a reason rather than as a code word.
    'wall': 'crawl.stopReason.wall',
    'risk': 'crawl.stopReason.risk',
    'unreachable': 'crawl.stopReason.unreachable',
}


def stop_reason_label(reason: str) -> str:
    """Render a crawl walk's stop token as a user-readable phrase in the current language."""
    key = STOP_REASONS.get(str(reason or '').strip())
    return t(key) if key else str(reason)


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
