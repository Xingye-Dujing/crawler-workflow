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
import threading

logger = logging.getLogger(__name__)

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
    'wf.executing_node': '[WF{i}] 正在执行节点：{nid}（{ntype}）',
    'wf.node_failed': '[WF{i}] 节点 {nid} 执行失败：{err}',
    'wf.partial_kept': '[WF{i}] 已保留该节点已完成的部分结果；修复问题后重新执行可从断点续跑。',
    'wf.node_completed': '[WF{i}] 节点 {nid} 完成（{done}/{total}）',
    'wf.validation_error': '校验错误：{err}',
    'wf.found': '发现 {n} 条工作流：{c} 个连通子图',
    'wf.starting': '--- 开始执行工作流 {i}/{n} ---',
    'wf.completed': '工作流执行完成',
    'wf.wf_failed': '工作流 {i} 执行失败',
    'wf.all_completed': '全部工作流执行完成',
    'wf.exec_failed': '执行失败，详见服务端日志',
    'wf.exec_exception': '执行失败',
    'wf.wf_exception': '工作流 {i} 执行失败',
    'wf.save_failed': '保存失败：{err}',
    'wf.data_saved': '数据已保存至 {path}（{fmt}）',
    'wf.analysis_failed': '分析失败：{err}',
    'wf.analysis_step': '[分析] {op}：{before} → {after} 行（-{removed}）',
    'wf.tokenize_no_column': '分词失败：未配置 text_column',
    'wf.tokenize_failed': '分词失败：{err}',
    'wf.tokenize_no_col': '分词失败：列“{col}”不在 {cols} 中',
    'wf.tokenize_done': '[分词] {mode} 已切分 {col} → {n} 行',
    'wf.visualize_failed': '可视化失败：{err}',
    'wf.visualize_done': '[可视化] 已渲染 {chart} 图表（{engine}），共 {n} 行',
    'wf.browser_opened': '已打开浏览器用于 {platform} 登录，等待 {n} 秒完成登录…',
    'wf.cookies_generated': '已生成 {platform} 的 Cookie（{n} 项）',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API Key 未填写',
    'llm.no_model': 'OpenRouter 模型名未填写',
    'llm.ollama_pkg_missing': 'ollama 包不可用：{err}',
    'llm.ollama_empty': 'Ollama 返回了空内容',
    'llm.ollama_fail_attempt': 'Ollama 调用失败（尝试 {i}/{n}）：{err}',
    'llm.ollama_exception': 'Ollama 调用异常（尝试 {i}/{n}）：{err}',
    'llm.ollama_failed': 'Ollama（{model}）调用失败：{err}',
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
    'llm.progress': '[{label}] 进度 {done}/{total}（已保存）',
    'llm.circuit_break': '连续 {f} 行调用失败——疑似网络断开 / Key 失效 / 模型不可用，本节点已中止。'
    '已完成 {done}/{total} 行并全部保存，恢复后重新执行会自动从断点续跑。',
    'llm.node_done': '[{label}] 节点完成 {done}/{total} 行',
    'llm.missing_column': 'DataFrame 缺少必需的列“{col}”。跳过 {label}。',
    'llm.no_rows': '[{label}] 没有需要处理的行（“{col}”列为空）。',
    'llm.start': '[{label}] 共 {total} 行待处理，调用方式：{transport}（每条数据一次询问，文本越长越耗 token）',
    'llm.aborted': '[{label}] 中止：{err}（已完成 {done} 行的结果已保存）',
    'llm.stopped': '[{label}] 已停止：{err}（已完成行已保存）',
    'llm.unfinished': '[{label}] {n} 行未处理（标记为 {mark}）。重新执行同一节点将从断点续跑，只补这些行。',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': '清洗',
    'label.emotion': '情感分析',
    'label.tendency': '倾向性分析',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': '开始搜索知乎关键词: "{kw}"，目标获取 {n} 条结果',
    'crawl.zhihu.url': '搜索URL: {url}',
    'crawl.zhihu.loaded': '搜索页面已加载，开始滚动加载更多内容...',
    'crawl.zhihu.cards': '滚动加载完成，共获取到 {n} 个卡片元素',
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
    'crawl.weibo.page_visit': '    访问分页: {url}',
    'crawl.weibo.page_timeout': '    页面加载超时，可能无内容',
    'crawl.weibo.max_page': '最大页码: {n}',
    'crawl.weibo.pages_fail': '获取总页数失败: {err}',
    'crawl.weibo.page_cards': '    本页共发现 {n} 个卡片',
    'crawl.weibo.card_error': '    卡片 {i}: 处理出错，已跳过',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': '未提供 URL，返回空结果。',
    'crawl.wechat.batch_start': '开始批量抓取 {n} 篇微信公众号文章',
    'crawl.wechat.processing': '--- 正在处理第 {i} / {total} 篇文章 ---',
    'crawl.wechat.url': 'URL: {url}',
    'crawl.wechat.success': '>>> 成功 [{i}/{total}]: "{title}" 作者 "{author}" | 阅读={reads} 点赞={likes} 打赏={rewards}',
    'crawl.wechat.failed': '>>> 失败 [{i}/{total}]: 该文章抓取失败',
    'crawl.wechat.wait': '等待 1 秒后继续下一篇...',
    'crawl.wechat.batch_done': '批量抓取完成：{n} / {total} 篇成功',
    'crawl.wechat.navigating': '正在打开文章链接...',
    'crawl.wechat.wait_title': '等待文章标题 (#activity-name) 加载...',
    'crawl.wechat.loaded': '文章页面加载成功。',
    'crawl.wechat.timeout': '页面加载超时: {url}',
    'crawl.wechat.scroll': '滚动到底部以触发懒加载...',
    'crawl.wechat.scroll_done': '滚动完成。',
    'crawl.wechat.extracting': '正在提取文章字段...',
    'crawl.wechat.title': '  标题: {title}',
    'crawl.wechat.author': '  作者（公众号）: {author}',
    'crawl.wechat.pub_time': '  发布时间: {time}',
    'crawl.wechat.content_len': '  正文长度: {n} 字',
    'crawl.wechat.reads': '  阅读数: {n}',
    'crawl.wechat.likes': '  点赞数: {n}',
    'crawl.wechat.rewards': '  打赏数: {n}',
    'crawl.wechat.preview': '  正文预览: {preview}',
    'crawl.wechat.no_content': '重试后仍未找到正文元素。',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[小红书搜索] 开始搜索关键词: "{kw}"，目标数量: {n}',
    'crawl.xhs.url': '[小红书搜索] 已访问搜索URL: {url}',
    'crawl.xhs.page_ready': '[小红书搜索] 初始搜索结果页加载完成',
    'crawl.xhs.page_timeout': '[小红书搜索] 初始内容加载超时，可能没有搜索结果，将继续尝试滚动',
    'crawl.xhs.links': '[小红书搜索] 共收集到 {n} 条笔记链接',
    'crawl.xhs.note_processing': '[小红书搜索] 正在处理第 {i}/{total} 条笔记: {url}',
    'crawl.xhs.note_ok': '[小红书搜索] 成功提取: {title}...',
    'crawl.xhs.note_fail': '[小红书搜索] 提取失败: {url}',
    'crawl.xhs.note_error': '[小红书搜索] 处理笔记时出错: {err}',
    'crawl.xhs.finished': '[小红书搜索] 搜索完成，共获取 {n} 条有效笔记数据',
    'crawl.xhs.collect_start': '[收集链接] 开始滚动收集笔记链接，目标: {n} 条',
    'crawl.xhs.scroll_round': '[收集链接] 第 {i}/{total} 次滚动',
    'crawl.xhs.no_more': '[收集链接] 检测到"没有更多了"，停止加载',
    'crawl.xhs.cards': '[收集链接] 滚动后卡片数量: {n}',
    'crawl.xhs.collected': '[收集链接] 当前已收集链接数: {n}',
    'crawl.xhs.target_reached': '[收集链接] 已达到目标数量 {n}，停止加载',
    'crawl.xhs.no_growth': '[收集链接] 卡片数量未增加，尝试再次滚动...',
    'crawl.xhs.exhausted': '[收集链接] 页面已无更多内容，停止加载',
    'crawl.xhs.collect_done': '[收集链接] 收集完成，共 {n} 条链接',
    'crawl.xhs.detail_visit': '[爬取详情] 正在访问详情页: {url}',
    'crawl.xhs.detail_ready': '[爬取详情] 详情页加载完成',
    'crawl.xhs.detail_timeout': '[爬取详情] 详情页加载超时',
    'crawl.xhs.title': '[爬取详情] 标题: {title}',
    'crawl.xhs.content_len': '[爬取详情] 正文长度: {n} 字',
    'crawl.xhs.author': '[爬取详情] 作者: {author}',
    'crawl.xhs.pub_time': '[爬取详情] 发布时间: {time}',
    'crawl.xhs.metrics': '[爬取详情] 互动数据 - 点赞: {likes}, 收藏: {favs}, 评论数: {comments}',
    'crawl.xhs.comment_count': '[爬取详情] 评论列表: {n} 条',
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
    'anomaly.too_few': '行数过少（{n}），异常检测结论不可靠',
    'anomaly.done': '异常检测：{n}/{total} 行被标记（contamination={c:.2f}）',
    'corr.need_cols': '相关性分析至少需要 2 个数值列',
    'corr.done': '相关性分析（{method}）：找到 {n} 对（min_abs={min_abs:.2f}）',
    'ml.model_missing': '模型 {name} 未训练且无已保存模型——回退为默认值',
    'ml.missing_col': 'DataFrame 缺少必需的列“{col}”。跳过分析。',
    'ml.no_rows': '没有需要处理的行（目标列为空）。',
    'ml.emotion_failed': 'ML 情感预测失败：{err}——回退为 Neutral',
    'ml.tendency_failed': 'ML 倾向性预测失败：{err}——回退为 Objective Statement',
    'ml.emotion_done': '[ML] 情感分类完成，共处理 {n} 行，模式: ML',
    'ml.tendency_done': '[ML] 倾向性分析完成，共处理 {n} 行，模式: ML',
    'cookie.saved': '已保存 {platform} 的 Cookie',
    'cookie.deleted': '已删除 {platform} 的 Cookie',
    'store.workflow_saved': '工作流已保存：{path}',
    'history.recorded': '已记录 {n} 条历史指标',
    'executor.task_failed': '任务失败：{err}',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': '记录执行历史失败（不影响流程）',
    'misc.save_workflow_failed': '保存工作流失败',
    'misc.cookie_save_failed': '保存 Cookie 失败',
    'misc.cookie_gen_failed': '生成 Cookie 失败',
    'misc.studio_source_failed': '图表工坊合并载入：来源读取失败',
    'misc.source_probe_failed': '数据源探测失败',
    'misc.studio_saved': '图表工坊已保存 %s（%d 字节）',
    'misc.browser_open_failed': '无法打开浏览器：%s',
    'misc.server_starting': '爬虫工作流服务启动，端口 %s',
}

_EN = {
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[WF{i}] Executing node: {nid} ({ntype})',
    'wf.node_failed': '[WF{i}] Node {nid} failed: {err}',
    'wf.partial_kept': '[WF{i}] Partial results for this node are kept; re-running resumes from the checkpoint.',
    'wf.node_completed': '[WF{i}] Node {nid} completed ({done}/{total})',
    'wf.validation_error': 'Validation error: {err}',
    'wf.found': 'Found {n} workflow(s): {c} component(s)',
    'wf.starting': '--- Starting workflow {i}/{n} ---',
    'wf.completed': 'Workflow execution completed',
    'wf.wf_failed': 'Workflow {i} failed',
    'wf.all_completed': 'All workflows completed',
    'wf.exec_failed': 'Execution failed - see server logs',
    'wf.exec_exception': 'Execution failed',
    'wf.wf_exception': 'Workflow {i} failed',
    'wf.save_failed': 'Save failed: {err}',
    'wf.data_saved': 'Data saved to {path} ({fmt})',
    'wf.analysis_failed': 'Analysis failed: {err}',
    'wf.analysis_step': '[Analysis] {op}: {before} -> {after} rows (-{removed})',
    'wf.tokenize_no_column': 'Tokenize failed: text_column not configured',
    'wf.tokenize_failed': 'Tokenize failed: {err}',
    'wf.tokenize_no_col': 'Tokenize failed: column "{col}" not found in {cols}',
    'wf.tokenize_done': '[Tokenize] {mode} segmented {col} -> {n} rows',
    'wf.visualize_failed': 'Visualize failed: {err}',
    'wf.visualize_done': '[Visualize] Rendered {chart} chart ({engine}) from {n} rows',
    'wf.browser_opened': 'Browser opened for {platform} login. Waiting {n}s for user to log in...',
    'wf.cookies_generated': 'Cookies generated for {platform} ({n} cookies)',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API key is missing',
    'llm.no_model': 'OpenRouter model name is missing',
    'llm.ollama_pkg_missing': 'ollama package unavailable: {err}',
    'llm.ollama_empty': 'Ollama returned empty content',
    'llm.ollama_fail_attempt': 'Ollama call failed (attempt {i}/{n}): {err}',
    'llm.ollama_exception': 'Ollama call error (attempt {i}/{n}): {err}',
    'llm.ollama_failed': 'Ollama ({model}) call failed: {err}',
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
    'llm.progress': '[{label}] Progress {done}/{total} (saved)',
    'llm.circuit_break': '{f} rows failed in a row — network down / invalid key / model unavailable. '
    'This node is aborted. {done}/{total} rows are finished and saved; re-running resumes from '
    'the checkpoint and only refills the rest.',
    'llm.node_done': '[{label}] Node finished {done}/{total} rows',
    'llm.missing_column': 'DataFrame is missing the required column "{col}". Skipping {label}.',
    'llm.no_rows': '[{label}] Nothing to process (column "{col}" is empty).',
    'llm.start': '[{label}] {total} rows queued via {transport} (one request per row — longer text costs more tokens)',
    'llm.aborted': '[{label}] Aborted: {err} ({done} finished rows are saved)',
    'llm.stopped': '[{label}] Stopped: {err} (finished rows are saved)',
    'llm.unfinished': '[{label}] {n} rows not processed (marked {mark}). Re-running this node resumes from '
    'the checkpoint and fills only those.',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': 'Clean',
    'label.emotion': 'Emotion',
    'label.tendency': 'Tendency',
    # ── crawlers: zhihu ───────────────────────────────────────
    'crawl.zhihu.start': 'Searching Zhihu for "{kw}", target {n} results',
    'crawl.zhihu.url': 'Search URL: {url}',
    'crawl.zhihu.loaded': 'Search page loaded, scrolling for more content...',
    'crawl.zhihu.cards': 'Scrolling done, {n} card elements collected',
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
    'crawl.weibo.page_visit': '    Visiting page: {url}',
    'crawl.weibo.page_timeout': '    Page load timed out, possibly empty',
    'crawl.weibo.max_page': 'Max page number: {n}',
    'crawl.weibo.pages_fail': 'Could not determine page count: {err}',
    'crawl.weibo.page_cards': '    Found {n} cards on this page',
    'crawl.weibo.card_error': '    Card {i}: error while processing, skipped',
    # ── crawlers: wechat ──────────────────────────────────────
    'crawl.wechat.no_urls': 'No URLs provided, returning empty results.',
    'crawl.wechat.batch_start': 'Starting batch scrape of {n} WeChat article(s)',
    'crawl.wechat.processing': '--- Processing article {i} / {total} ---',
    'crawl.wechat.url': 'URL: {url}',
    'crawl.wechat.success': '>>> SUCCESS [{i}/{total}]: "{title}" by "{author}" | reads={reads} likes={likes} rewards={rewards}',
    'crawl.wechat.failed': '>>> FAILED [{i}/{total}]: Could not scrape article',
    'crawl.wechat.wait': 'Waiting 1 s before next article...',
    'crawl.wechat.batch_done': 'Batch scrape complete: {n} / {total} succeeded',
    'crawl.wechat.navigating': 'Navigating to article URL...',
    'crawl.wechat.wait_title': 'Waiting for article title (#activity-name) to load...',
    'crawl.wechat.loaded': 'Article page loaded successfully.',
    'crawl.wechat.timeout': 'Page load timed out for: {url}',
    'crawl.wechat.scroll': 'Scrolling to bottom to trigger lazy loading...',
    'crawl.wechat.scroll_done': 'Scroll complete.',
    'crawl.wechat.extracting': 'Extracting article fields...',
    'crawl.wechat.title': '  Title: {title}',
    'crawl.wechat.author': '  Author (official account): {author}',
    'crawl.wechat.pub_time': '  Publish time: {time}',
    'crawl.wechat.content_len': '  Content length: {n} characters',
    'crawl.wechat.reads': '  Read count: {n}',
    'crawl.wechat.likes': '  Like count: {n}',
    'crawl.wechat.rewards': '  Reward count: {n}',
    'crawl.wechat.preview': '  Content preview: {preview}',
    'crawl.wechat.no_content': 'Content element not found after retry.',
    # ── crawlers: xiaohongshu ─────────────────────────────────
    'crawl.xhs.start': '[XHS search] Searching for "{kw}", target {n} notes',
    'crawl.xhs.url': '[XHS search] Opened search URL: {url}',
    'crawl.xhs.page_ready': '[XHS search] Initial results page loaded',
    'crawl.xhs.page_timeout': '[XHS search] Initial content timed out — may be no results, still scrolling',
    'crawl.xhs.links': '[XHS search] Collected {n} note links',
    'crawl.xhs.note_processing': '[XHS search] Processing note {i}/{total}: {url}',
    'crawl.xhs.note_ok': '[XHS search] Extracted: {title}...',
    'crawl.xhs.note_fail': '[XHS search] Extraction failed: {url}',
    'crawl.xhs.note_error': '[XHS search] Error processing note: {err}',
    'crawl.xhs.finished': '[XHS search] Done, {n} valid notes collected',
    'crawl.xhs.collect_start': '[Collect links] Scrolling for note links, target {n}',
    'crawl.xhs.scroll_round': '[Collect links] Scroll {i}/{total}',
    'crawl.xhs.no_more': '[Collect links] Reached "no more content", stopping',
    'crawl.xhs.cards': '[Collect links] Cards after scroll: {n}',
    'crawl.xhs.collected': '[Collect links] Links collected so far: {n}',
    'crawl.xhs.target_reached': '[Collect links] Target of {n} reached, stopping',
    'crawl.xhs.no_growth': '[Collect links] Card count did not grow, scrolling again...',
    'crawl.xhs.exhausted': '[Collect links] No more content on the page, stopping',
    'crawl.xhs.collect_done': '[Collect links] Done, {n} links collected',
    'crawl.xhs.detail_visit': '[Note detail] Opening detail page: {url}',
    'crawl.xhs.detail_ready': '[Note detail] Detail page loaded',
    'crawl.xhs.detail_timeout': '[Note detail] Detail page timed out',
    'crawl.xhs.title': '[Note detail] Title: {title}',
    'crawl.xhs.content_len': '[Note detail] Content length: {n} characters',
    'crawl.xhs.author': '[Note detail] Author: {author}',
    'crawl.xhs.pub_time': '[Note detail] Publish time: {time}',
    'crawl.xhs.metrics': '[Note detail] Engagement - likes: {likes}, saves: {favs}, comments: {comments}',
    'crawl.xhs.comment_count': '[Note detail] Comments: {n}',
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
    'anomaly.too_few': 'Too few rows ({n}) for reliable anomaly detection',
    'anomaly.done': 'Anomaly detection: {n}/{total} rows flagged (contamination={c:.2f})',
    'corr.need_cols': 'Need at least 2 numeric columns for correlation analysis',
    'corr.done': 'Correlation analysis ({method}): {n} pairs found (min_abs={min_abs:.2f})',
    'ml.model_missing': 'Model {name} not trained and no saved model found — falling back to default',
    'ml.missing_col': 'DataFrame is missing the required column "{col}". Skipping analysis.',
    'ml.no_rows': 'Nothing to process (the target column is empty).',
    'ml.emotion_failed': 'ML emotion prediction failed: {err} — falling back to Neutral',
    'ml.tendency_failed': 'ML tendency prediction failed: {err} — falling back to Objective Statement',
    'ml.emotion_done': '[ML] Emotion classification done, {n} rows, mode: ML',
    'ml.tendency_done': '[ML] Tendency analysis done, {n} rows, mode: ML',
    'cookie.saved': 'Cookies saved for {platform}',
    'cookie.deleted': 'Cookies deleted for {platform}',
    'store.workflow_saved': 'Workflow saved: {path}',
    'history.recorded': 'Recorded {n} history metric(s)',
    'executor.task_failed': 'Task failed: {err}',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': 'Failed to record execution history (non-fatal)',
    'misc.save_workflow_failed': 'Failed to save workflow',
    'misc.cookie_save_failed': 'Failed to save cookies',
    'misc.cookie_gen_failed': 'Failed to generate cookies',
    'misc.studio_source_failed': 'Merged studio load: source failed',
    'misc.source_probe_failed': 'Source probe failed',
    'misc.studio_saved': 'Chart studio saved %s (%d bytes)',
    'misc.browser_open_failed': 'Could not open browser: %s',
    'misc.server_starting': 'Starting crawler workflow server on port %s',
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
        logger.debug('i18n: missing message key "%s"', key)
        return key
    if not params:
        return template
    try:
        return template.format(**params)
    except (KeyError, IndexError, ValueError):
        logger.debug('i18n: bad params for "%s": %r', key, params)
        return template


def missing_keys() -> dict:
    """Catalogue gaps per language — used by the tests so a half-translated
    message cannot ship."""
    zh, en = set(_ZH), set(_EN)
    return {'en_only': sorted(en - zh), 'zh_only': sorted(zh - en)}
