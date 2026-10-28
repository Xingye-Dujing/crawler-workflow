"""Machine-local settings, field labels, dependency refusals, the LLM transport words and
the shared UI vocabulary.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/i18n/test_i18n.py``).
"""

ZH = {
    'deps.systemFont.darwin': 'macOS 自带苹方/宋体；若仍缺请装 Noto Sans CJK 后重启程序',
    'deps.systemFont.linux': '请安装中文字体（Debian/Ubuntu：apt-get install fonts-noto-cjk）后重启程序',
    # ── 「缺什么、在这台机器上怎么补」的按系统分支 ──────────────────────────
    # 一条补救说明在三套系统上说的是三件事：Windows 补字体功能、Linux 装发行包、macOS 用系统自带。
    # 键名由 core.machine.remedy_key 拼出，所以全清单（前缀 × 平台）由
    # tests/unit/foundation/test_missing_dependency_messages.py 从取值那头逐个查在不在。
    'deps.systemFont.win32': '请安装仿宋/黑体等中文字体（英文版 Windows 要在「可选功能」里补中文简体字体）后重启程序',
    'deps.texFont.darwin': '非 Windows 上纸质图改用 ctex 的 macnew 字体集（系统自带宋体/黑体）',
    'deps.texFont.linux': '非 Windows 上纸质图改用 ctex 自带的 fandol 中文字体集，需要 texlive-lang-chinese',
    'deps.texFont.win32': (
        '纸质图用 ctex + 仿宋（FangSong），需要系统装有该字体（英文版 Windows 要补「中文（简体）」字体功能）'
    ),
    'deps.texPackage.darwin': 'MacTeX 下用 sudo tlmgr install 该包，或在 TeX Live Utility 里安装',
    'deps.texPackage.linux': (
        '用发行版包装对应宏包（Debian/Ubuntu：apt-get install texlive-lang-chinese texlive-latex-extra），'
        '或 tlmgr install 该包'
    ),
    'deps.texPackage.win32': (
        '用 MiKTeX 控制台（或 miktex packages install）补上，或在 MiKTeX 设置里允许「联网自动安装缺失包」后重试'
    ),
    'deps.xelatex.darwin': '找不到 xelatex，无法编译 PDF：请安装 MacTeX（含 xelatex），或在「设置」里指定路径',
    'deps.xelatex.linux': (
        '找不到 xelatex，无法编译 PDF：请安装 TeX Live 的 xelatex'
        '（Debian/Ubuntu：apt-get install texlive-xetex），或在「设置」里指定路径'
    ),
    'deps.xelatex.win32': '找不到 xelatex，无法编译 PDF：请安装 MiKTeX，或在「设置」里指定编译程序路径',
    'field.account': '登录账号',
    'field.author': '作者',
    'field.backend': '采集方式',
    'field.board': '榜单',
    'field.catbusAccount': 'CatBus 账号',
    'field.catbusCommentId': '评论 ID',
    'field.catbusConversation': '会话 ID',
    'field.catbusFolder': '收藏夹',
    'field.catbusProduct': '商品',
    'field.catbusRoom': '直播间',
    'field.catbusSeries': '合集',
    'field.format': '格式',
    'field.keyword': '关键词',
    'field.urls': '文章链接',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': '清洗',
    'label.emotion': '情感分析',
    'label.ner': '实体识别',
    'label.sentiment': '情感极性',
    'label.tendency': '倾向性分析',
    # Neither line carries the failure text: the executor states it once, attributed
    # to the node. These two say only what that line cannot — what survived.
    'llm.aborted': '[{label}] 已完成 {done} 行，结果已保存',
    'llm.cancelled': '已手动停止——已完成的行均已保存，可修复后从断点续跑',
    'llm.checkpoint_loaded': '断点续跑：载入 {n} 行已完成结果（{file}）',
    'llm.circuit_break': '连续 {f} 行调用失败——疑似网络断开 / Key 失效 / 模型不可用，本节点已中止。'
    '已完成 {done}/{total} 行并全部保存，恢复后重新执行会自动从断点续跑。',
    'llm.missing_column': 'DataFrame 缺少必需的列“{col}”——{label} 节点失败，请检查文本列配置',
    'llm.net_error': '网络错误：{err}',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API Key 未填写',
    'llm.no_model': 'OpenRouter 模型名未填写',
    'llm.no_ollama_model': 'Ollama 模型名未填写（AI → 模型，可点“刷新”读取本地已拉取的模型）',
    'llm.no_rows': '[{label}] 没有需要处理的行（“{col}”列为空）。',
    'llm.node_done': '[{label}] 节点完成 {done}/{total} 行',
    'llm.ollama_client_failed': 'Ollama 客户端初始化失败（{host}）：{err}',
    'llm.ollama_empty': 'Ollama 返回了空内容',
    'llm.ollama_exception': 'Ollama 调用异常（尝试 {i}/{n}）：{err}',
    'llm.ollama_fail_attempt': 'Ollama 调用失败（尝试 {i}/{n}）：{err}',
    'llm.ollama_failed': 'Ollama（{model}）调用失败：{err}',
    'llm.ollama_http': 'Ollama 拒绝请求（{code}）：{err}',
    'llm.ollama_model_missing': 'Ollama 本地没有模型“{model}”——请在面板中改选一个已拉取的模型（{err}）',
    'llm.ollama_pkg_missing': 'ollama 包不可用：{err}',
    'llm.ollama_unreachable': '连不上 Ollama 服务 {host}——请确认 ollama 已启动、服务地址正确：{err}',
    'llm.or_401': 'OpenRouter：API Key 无效（401），请检查密钥',
    'llm.or_402': 'OpenRouter：余额不足（402）——免费模型不需要余额，请改选 :free 模型',
    'llm.or_404': 'OpenRouter：模型不存在（404）——"{model}"，请重新选择模型',
    'llm.or_429': 'OpenRouter：触发限流（429）——免费模型为共享额度，建议减小并发',
    'llm.or_429_wait': 'OpenRouter 429 限流（尝试 {i}/{n}），等待 {wait} 秒',
    'llm.or_5xx': 'OpenRouter 服务端错误（{code}）',
    'llm.or_5xx_attempt': 'OpenRouter {code}（尝试 {i}/{n}）',
    'llm.or_bad_format': 'OpenRouter 响应格式异常：{err}',
    'llm.or_empty': 'OpenRouter 返回了空内容',
    'llm.or_failed': 'OpenRouter 调用失败',
    'llm.or_http_fail': 'OpenRouter 请求失败（{code}）：{body}',
    'llm.or_net_exception': 'OpenRouter 网络异常（尝试 {i}/{n}）：{err}',
    'llm.parse_failed': '[{label}] 第 {i}/{total} 行输出解析失败（连续失败 {f}）',
    'llm.progress': '[{label}] 进度 {done}/{total}（已保存）',
    'llm.row_done': '[{label}] 第 {done}/{total} 行完成',
    'llm.row_exception': '[{label}] 行处理异常：{err}',
    'llm.start': '[{label}] 共 {total} 行待处理，调用方式：{transport}（每条数据一次询问，文本越长越耗 token）',
    'llm.stopped': '[{label}] 已停止，已完成行的结果已保存',
    'llm.unfinished': '[{label}] {n} 行未处理（标记为 {mark}）。重新执行同一节点将从断点续跑，只补这些行。',
    'misc.browserNotFound': '这台机器没有可接住地址的默认浏览器，请手动打开：{url}',
    'misc.browser_open_failed': '无法打开浏览器：{err}',
    'misc.chartPdfSaved': '图表 PDF 已生成：{name}（{bytes} 字节）',
    'misc.cloudNoBrowser': '云端模式不会尝试打开浏览器（服务器上没有浏览器可开）；请在自己机器上访问：{url}',
    'misc.consoleUtf8': ('本机的控制台编码 {streams} 写不出汉字，已改为 UTF-8（每个流只改一次，日志不会再因此丢行）'),
    'misc.cookie_gen_failed': '生成 Cookie 失败: {err}',
    'misc.cookie_save_failed': '保存 Cookie 失败: {err}',
    'misc.exportDeleteFailed': '无法删除导出文件 {name}：{err}',
    'misc.export_failed': '导出文件写入失败',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': '记录执行历史失败（不影响流程）',
    'misc.i18nAudit': '文本目录有问题（不影响运行，但请修复）：{issue}',
    'misc.save_workflow_failed': '保存工作流失败',
    'misc.server_starting': '爬虫工作流服务启动，端口 {port}',
    'misc.source_probe_failed': '数据源探测失败',
    'misc.studio_saved': '图表工坊已保存 {path}（{bytes} 字节）',
    'misc.studio_source_failed': '图表工坊合并载入：来源读取失败',
    'misc.visualize_failed': '图表渲染失败：{err}',
    'set.badFlag': '{setting} 需要 true/false 值，已恢复默认',
    'set.badNumber': '{setting} 不是数字，已恢复默认 {value}',
    'set.badOllamaHost': 'Ollama 地址需以 http:// 或 https:// 开头，已恢复默认',
    'set.badProfileDir': '浏览器 Profile 目录必须填绝对路径（收到：{value}），已恢复为内置目录',
    'set.badWindow': '窗口大小格式应为 宽x高（如 1920x1080），已恢复默认 {default}',
    'set.browserMissing': '浏览器程序不存在：{path}',
    # The two CatBus paths are accepted as either a file or a CatBus checkout directory, so the
    # warning says which of the two complaints it is, and names the setting the box belongs to.
    'set.catbusMissing': 'CatBus 组件（{tool}）在该位置不存在：{path}',
    'set.catbusNeedFile': '{tool} 要填可执行程序本身，不是它所在的目录：{path}',
    'set.driverEmpty': '驱动路径为空：将由 Selenium 自动取与当前 Chrome 匹配的驱动（首次需要联网）',
    # ── 运行时设置校验 ────────────────────────────────────────
    'set.driverMissing': '驱动文件不存在：{path}',
    'set.harvestMissing': '红果收割组件（{tool}）不是已存在的文件：{path}',
    'set.latexMissing': 'LaTeX 编译程序（xelatex）不存在：{path}',
    'set.outOfRange': '{setting} 超出范围 {lo}-{hi}，已恢复默认 {value}',
    'set.saveFailed': '设置未能写入磁盘（本次会话内仍生效）：{err}',
}

EN = {
    'deps.systemFont.darwin': (
        'macOS ships PingFang/Songti; if one is missing, install Noto Sans CJK and restart the app'
    ),
    'deps.systemFont.linux': (
        'install a Chinese font (Debian/Ubuntu: apt-get install fonts-noto-cjk) and restart the app'
    ),
    'deps.systemFont.win32': (
        'install a Chinese font such as SimHei/FangSong (an English Windows needs the Simplified Chinese '
        'font feature under Settings > Optional features) and restart the app'
    ),
    'deps.texFont.darwin': "off Windows the paper figures use ctex's macnew font set (the system Songti/Heiti)",
    'deps.texFont.linux': (
        "off Windows the paper figures use ctex's own fandol CJK font set, which needs texlive-lang-chinese"
    ),
    'deps.texFont.win32': (
        'the paper figures use ctex with FangSong (仿宋), so the system needs that font (an English Windows '
        'needs the Simplified Chinese font feature installed)'
    ),
    'deps.texPackage.darwin': 'with MacTeX run sudo tlmgr install <package>, or install it in TeX Live Utility',
    'deps.texPackage.linux': (
        'install the matching distro package (Debian/Ubuntu: apt-get install texlive-lang-chinese '
        'texlive-latex-extra), or run tlmgr install <package>'
    ),
    'deps.texPackage.win32': (
        'install it with the MiKTeX console (or "miktex packages install"), or allow MiKTeX to fetch missing '
        'packages on the network and retry'
    ),
    'deps.xelatex.darwin': (
        'xelatex was not found, so the PDF cannot be compiled: install MacTeX (it ships xelatex), or set the '
        'compiler path in Settings'
    ),
    'deps.xelatex.linux': (
        'xelatex was not found, so the PDF cannot be compiled: install it with TeX Live (Debian/Ubuntu: '
        'apt-get install texlive-xetex), or set the compiler path in Settings'
    ),
    'deps.xelatex.win32': (
        'xelatex was not found, so the PDF cannot be compiled: install MiKTeX, or set the compiler path in Settings'
    ),
    'field.account': 'account',
    'field.author': 'creator',
    'field.backend': 'backend',
    'field.board': 'board',
    'field.catbusAccount': 'CatBus account',
    'field.catbusCommentId': 'comment ID',
    'field.catbusConversation': 'conversation ID',
    'field.catbusFolder': 'collection folder',
    'field.catbusProduct': 'product',
    'field.catbusRoom': 'live room',
    'field.catbusSeries': 'series',
    'field.format': 'format',
    'field.keyword': 'keyword',
    'field.urls': 'article URLs',
    # ── analyzer labels (console prefix) ──────────────────────
    'label.clean': 'Clean',
    'label.emotion': 'Emotion',
    'label.ner': 'Entities',
    'label.sentiment': 'Sentiment polarity',
    'label.tendency': 'Tendency',
    'llm.aborted': '[{label}] {done} finished rows are saved',
    'llm.cancelled': 'Stopped manually — completed rows are saved; re-run resumes from the checkpoint',
    'llm.checkpoint_loaded': 'Checkpoint: loaded {n} finished rows ({file})',
    'llm.circuit_break': '{f} rows failed in a row — network down / invalid key / model unavailable. '
    'This node is aborted. {done}/{total} rows are finished and saved; re-running resumes from '
    'the checkpoint and only refills the rest.',
    'llm.missing_column': (
        'DataFrame is missing the required column "{col}" — the {label} node failed; check its text-column setting'
    ),
    'llm.net_error': 'Network error: {err}',
    # ── LLM ───────────────────────────────────────────────────
    'llm.no_key': 'OpenRouter API key is missing',
    'llm.no_model': 'OpenRouter model name is missing',
    'llm.no_ollama_model': 'No Ollama model set (AI → Model — hit Refresh to list what the daemon has)',
    'llm.no_rows': '[{label}] Nothing to process (column "{col}" is empty).',
    'llm.node_done': '[{label}] Node finished {done}/{total} rows',
    'llm.ollama_client_failed': 'Could not create the Ollama client for {host}: {err}',
    'llm.ollama_empty': 'Ollama returned empty content',
    'llm.ollama_exception': 'Ollama call error (attempt {i}/{n}): {err}',
    'llm.ollama_fail_attempt': 'Ollama call failed (attempt {i}/{n}): {err}',
    'llm.ollama_failed': 'Ollama ({model}) call failed: {err}',
    'llm.ollama_http': 'Ollama rejected the request ({code}): {err}',
    'llm.ollama_model_missing': 'Ollama has no local model "{model}" — pick a pulled one in the panel ({err})',
    'llm.ollama_pkg_missing': 'ollama package unavailable: {err}',
    'llm.ollama_unreachable': 'Cannot reach the Ollama server at {host} — is ollama running? {err}',
    'llm.or_401': 'OpenRouter: invalid API key (401) — check the key',
    'llm.or_402': 'OpenRouter: out of credit (402) — free models need none, pick a :free model',
    'llm.or_404': 'OpenRouter: model not found (404) — "{model}", pick another one',
    'llm.or_429': 'OpenRouter: rate limited (429) — free models share a quota, lower the concurrency',
    'llm.or_429_wait': 'OpenRouter 429 rate limit (attempt {i}/{n}), waiting {wait}s',
    'llm.or_5xx': 'OpenRouter server error ({code})',
    'llm.or_5xx_attempt': 'OpenRouter {code} (attempt {i}/{n})',
    'llm.or_bad_format': 'OpenRouter response malformed: {err}',
    'llm.or_empty': 'OpenRouter returned empty content',
    'llm.or_failed': 'OpenRouter call failed',
    'llm.or_http_fail': 'OpenRouter request failed ({code}): {body}',
    'llm.or_net_exception': 'OpenRouter network error (attempt {i}/{n}): {err}',
    'llm.parse_failed': '[{label}] Row {i}/{total}: output could not be parsed ({f} in a row)',
    'llm.progress': '[{label}] Progress {done}/{total} (saved)',
    'llm.row_done': '[{label}] row {done}/{total} done',
    'llm.row_exception': '[{label}] Row processing error: {err}',
    'llm.start': '[{label}] {total} rows queued via {transport} (one request per row — longer text costs more tokens)',
    'llm.stopped': '[{label}] stopped; finished rows are saved',
    'llm.unfinished': '[{label}] {n} rows not processed (marked {mark}). Re-running this node resumes from '
    'the checkpoint and fills only those.',
    'misc.browserNotFound': 'This machine has no default browser to hand the address to — open it by hand: {url}',
    'misc.browser_open_failed': 'Could not open browser: {err}',
    'misc.chartPdfSaved': 'Chart PDF compiled: {name} ({bytes} bytes)',
    'misc.cloudNoBrowser': (
        'cloud mode does not try to open a browser (there is none on a server); reach this address from '
        'your own machine: {url}'
    ),
    'misc.consoleUtf8': (
        'the console encoding {streams} of this machine cannot write Han characters — switched to UTF-8 '
        '(each stream is changed once, so no log line is lost to it again)'
    ),
    'misc.cookie_gen_failed': 'Failed to generate cookies: {err}',
    'misc.cookie_save_failed': 'Failed to save cookies: {err}',
    'misc.exportDeleteFailed': 'could not delete the exported file {name}: {err}',
    'misc.export_failed': 'Writing the export file failed',
    # ── misc ──────────────────────────────────────────────────
    'misc.history_failed': 'Failed to record execution history (non-fatal)',
    'misc.i18nAudit': 'the message catalogue has a problem (harmless to run, please fix): {issue}',
    'misc.save_workflow_failed': 'Failed to save workflow',
    'misc.server_starting': 'Starting crawler workflow server on port {port}',
    'misc.source_probe_failed': 'Source probe failed',
    'misc.studio_saved': 'Chart studio saved {path} ({bytes} bytes)',
    'misc.studio_source_failed': 'Merged studio load: source failed',
    'misc.visualize_failed': 'Chart rendering failed: {err}',
    'set.badFlag': '{setting} needs a true/false value — restored the default',
    'set.badNumber': '{setting} is not a number — restored the default {value}',
    'set.badOllamaHost': 'The Ollama address must start with http:// or https:// — restored the default',
    'set.badProfileDir': 'The profile directory must be an absolute path (got: {value}) — restored the built-in one',
    'set.badWindow': 'Window size must look like WIDTHxHEIGHT (e.g. 1920x1080) — restored the default {default}',
    'set.browserMissing': 'Browser executable does not exist: {path}',
    'set.catbusMissing': 'The CatBus component ({tool}) does not exist at that location: {path}',
    'set.catbusNeedFile': '{tool} wants the executable itself, not the folder holding it: {path}',
    'set.driverEmpty': (
        'Driver path was empty — nothing is forced on it: Selenium fetches the driver matching the '
        'installed Chrome (the first time needs network)'
    ),
    # ── runtime settings validation ───────────────────────────
    'set.driverMissing': 'Driver file does not exist: {path}',
    'set.harvestMissing': 'Hongguo harvest component ({tool}) is not an existing file: {path}',
    'set.latexMissing': 'LaTeX compiler (xelatex) does not exist: {path}',
    'set.outOfRange': '{setting} is outside {lo}-{hi} — restored the default {value}',
    'set.saveFailed': 'Settings could not be written to disk (still active for this session): {err}',
}
