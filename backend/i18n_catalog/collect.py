"""What can be collected: the matrix of platforms × contents, the fields each mode needs, and
the second backend's verdicts.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/i18n/test_i18n.py``).
"""

ZH = {
    'catbus.columnDrift': 'CatBus 返回的列与能力清单不一致：缺少 {missing}，多出 {extra}',
    'catbus.finished': 'CatBus 采集结束：本次新增 {n} 条（目标 {want}）',
    'catbus.finishedOnce': 'CatBus 执行结束：{mode}，本次新增 {n} 条',
    'catbus.noCli': (
        '这台机器有 Node，但找不到 CatBus 的采析绘适配器（可用 CIXI_CATBUS_CLI 指定文件，'
        '或用 CATBUS_HOME 指定它的源码目录）'
    ),
    'catbus.noDetail': 'CatBus 后端不单独取详情（详情由适配器逐条补齐）：{url}',
    'catbus.noIdentity': '{platform} / {mode} 的 CatBus 适配没有声明身份列，跨运行水位无法界定边界，因此拒绝',
    # 第二采集后端 CatBus（services/ingest/catbus.py）：每一句都点名缺的是哪一样。
    # 一个读不到的答案不能变成空表，因为节点会在空表上判定完成。
    'catbus.noNode': '这台机器上没有 Node 运行时，CatBus 后端因此不可用（可用 CIXI_NODE_BIN 指定）',
    'catbus.noRunnableCell': 'CatBus 对这个平台没有任何可运行的读功能',
    'catbus.notInManifest': 'CatBus 的清单里没有 {platform} / {mode} 这一格，不能用它采',
    'catbus.oldNode': 'CatBus 不接受这个 Node：{node} 报告 {version}（需要 22.22.2／24.15.0／26.0.0 以上）',
    'catbus.paramUnsupported': (
        'CatBus 的 {platform} / {mode} 不接受这些采集条件：{params}。适配器会忽略它们，'
        '而一张看起来执行过条件的表比拒绝更糟——请改用 Selenium，或在设置里去掉这些条件'
    ),
    'catbus.pre.login': '{platform} 在 CatBus 里没有登录态',
    'catbus.probeFailed': 'CatBus 适配器没能给出能力清单：{detail}',
    'catbus.probeUnreadable': 'CatBus 适配器返回的不是能读的答案：{detail}',
    'catbus.refused': '{platform} / {mode} 通过 CatBus 采集失败：{detail}',
    'catbus.start': 'CatBus 开始采集：{mode}，目标 {n} 条',
    'catbus.startOnce': 'CatBus 开始执行：{mode}',
    'catbus.stopped': '{platform} / {mode} 已通过 CatBus 停止，已经落库的行保留',
    'catbus.targetReached': '目标 {n} 条已经在表里，CatBus 不再请求',
    'catbus.timeout': 'CatBus 超过 {seconds} 秒没有返回，进程已被终止',
    'catbus.warning': 'CatBus 报告：{text}',
    'catbus.watermarkHit': 'CatBus 采到水位线 {i}，更旧的条目不再入库',
    'catbus.watermarkNote': 'CatBus 没有偏移量：水位线只界定哪些行入库，更旧的条目仍会被请求一次',
    'comment.allMismatched': '所有链接都与所选平台（{platform}）不符，请检查文章链接',
    'comment.article': '评论：{url} 新增 {n} 条（{status}）',
    'comment.bad_date': '节点 {nid}：评论时间筛选的日期无法解析（请用 YYYY-MM-DD）',
    'comment.bad_range': '节点 {nid}：评论时间筛选的结束时间早于开始时间',
    'comment.biliBadAnswer': '哔哩哔哩评论接口未返回数据（code={code}）：{url}',
    'comment.biliShort': '[B站评论] 游标收到 {rows} 条，站点标注 {declared} 条（匿名深翻页被限流）：{url}',
    'comment.commentsClosed': '该内容未开放评论区（或未产生评论）：{url}',
    'comment.done': (
        '评论采集完成：{urls} 个链接（正常 {ok}、拦截 {blocked}、失效 {dead}），共 {rows} 条评论，输出 {files} 个文件'
    ),
    'comment.dyGone': '[抖音评论] 站点把这条链接换成了另一条视频（{shown}），这条按失效处理：{url}',
    'comment.dyNoId': '链接里没有视频 ID，无法抓评论：{url}',
    'comment.dyNoPanel': '评论区没有渲染出来（可能被折叠或需要登录）：{url}',
    'comment.dyNone': '该视频计有 {n} 条评论，页面未展开评论列表：{url}',
    'comment.dyShort': (
        '[抖音评论] {url}：站点写着 {declared} 条，本表 {rows} 条 + 子回复 {nested} 条（还差 {gap} 条未采到）'
        ' —— 本次收尾原因是「{reason}」，所以差额不是「这条视频就这么多」'
    ),
    'comment.need_both': '节点 {nid}：按评论时间筛选必须同时给出开始和结束时间（半个区间无法界定范围）',
    'comment.noAdapter': '{platform} 还没有评论抓取实现，该链接无法处理：{url}',
    # The supported list is generated from the comment router's own domain table,
    # because that table is what actually decides the answer — naming the platforms
    # in the sentence left two messages that kept claiming the old four long after
    # the fifth landed.
    'comment.no_urls': '评论节点没有可抓取的链接（支持：{platforms}）',
    'comment.platformMismatch': '已忽略 {n} 个与所选平台（{platform}）不符的链接',
    'comment.prefix': '[评论]',
    'comment.status.blocked': '被登录墙/风控拦截',
    'comment.status.dead': '链接不可读',
    'comment.status.ok': '正常',
    'comment.time_filtered': '节点 {nid}：按评论时间 {start} ~ {end} 筛选，保留 {kept} 条、丢弃 {dropped} 条',
    'comment.unsupported': '评论节点忽略了 {n} 个不支持的链接（仅支持：{platforms}）',
    # Named because a count of dropped 「links」 sends the user hunting for a typo in a URL,
    # when what the node actually lacks is the platform that declared it takes plain names.
    'comment.unsupportedNames': '其中 {n} 行不是链接而是名称：按名称喂入需节点先选定平台'
    '（红果短剧 的「评论」模式按剧名走播放器自己的榜单）',
    'comment.weiboFetchDied': (
        '[微博评论] 第 {page} 页评论接口取数失败，就此收尾：本次 {rows} 条'
        '（站点标注 {declared} 条，差额 {gap} 条未采到；游标停在失败的那一页，可继续）'
    ),
    'comment.weiboReplay': (
        '[微博评论] 第 {page} 页没有交出新的一条（游标仍在动）：按「站点在重复同一批」收工，本次 {rows} 条'
    ),
    'comment.weiboShort': (
        '[微博评论] 站点写着 {declared} 条，本表只有 {rows} 条（差 {gap} 条）'
        '—— 差额是楼中楼：这个接口在当前会话里不整批返回子评论，只有父行自带的那条预览已入表'
    ),
    'comment.weiboShowFailed': '[微博评论] 评论接口取不回来（Cookie 可能失效或被限流）：{url}',
    'comment.xNoList': '[X 评论] 这条推文页面没有渲染出任何内容（链接失效、被删或被拦截）：{url}',
    'comment.xhsPanelCapped': '[小红书评论] 滚满 {rounds} 轮仍未走完，按轮次上限收工（本次 {rows} 条）：{url}',
    'comment.ytNoPage': 'YouTube 页面没有加载成视频页（可能需要登录或被拦截）：{url}',
    'comment.zhihuNoAuthor': '[知乎评论] 本轮 {total} 条里有 {n} 条在自己的子树内没有作者链接（匿名或被折叠）',
    'comment.zhihuNoPanels': '[知乎评论] 这个回答页面上没有评论面板（可能已关闭或未加载）：{url}',
    'comment.zhihuPanelCapped': '[知乎评论] 滚满 {n} 轮（含展开子回复）仍未走完，按轮次上限收工（本次 {rows} 条）',
    'comment.zhihuPanelShort': '[知乎评论] 页面写着 {declared} 条，本次取到 {rows} 条（差额未采到）',
    'comment.zhihuRound': '[知乎评论] 第 {r} 轮新增 {n} 条（累计 {total}）',
    'source.BibTeX.missing': '字段随导出工具而异：缺作者的条目会被计入「跳过」并在控制台点名，不会被当成空记录',
    'source.BibTeX.purpose': 'LaTeX 工作流的通用格式，Zotero 与 WoS 都能导出 .bib。',
    'source.BibTeX.steps': '1. 在 Web of Science 的导出格式里选「BibTeX」，'
    '或在 Zotero 里右键条目 →「导出条目」→ 格式选 BibTeX\n2. 上传 .bib',
    'source.CNKI.missing': '无参考文献列表 ⇒ 共被引、文献耦合、引文突现做不了\n'
    '无被引次数 ⇒ 「总被引/H 指数」列不会出现，按被引筛选保持关闭',
    # ── 文献来源导出指引（services/biblio/sources.py） ──────────────
    # 每条只写「我们解析过的真实文件」能支持的话：缺什么就写缺什么，不猜站点还有别的按钮。
    'source.CNKI.purpose': '中文文献共现网络的入口：关键词、作者、机构、期刊都能建图。'
    '知网导出不含参考文献与被引次数，因此引文类分析会在运行前点名拒绝，而不是画空图。',
    'source.CNKI.steps': '1. 在知网按主题/关键词检索，需要时用年限与来源收窄\n'
    '2. 勾选结果条目，点「导出/参考文献」\n'
    '3. 在导出页选「RefWorks」，得到 CNKI-<时间>-RefWorks.txt\n'
    '4. 把这份 .txt 直接上传；同一页的 NoteExpress、EndNote 两个按钮本应用也认',
    'source.CSSCI.missing': '无【摘要】⇒ 聚类标签来源要选「关键词」；选「摘要」会按名拒绝\n'
    '无 DOI ⇒ 跨库合并只能按题名与作者匹配',
    'source.CSSCI.purpose': '中文社科文献的引文入口：CSSCI 导出带参考文献列表，所以共被引与文献耦合可用；'
    '它不带摘要与 DOI。',
    'source.CSSCI.steps': '1. 进入南京大学中国社会科学研究评价中心的检索页\n'
    '2. 按年/来源/关键词检索后导出文本，导出内容要含【参考文献】与【年代卷期】'
    '（每篇以【来源篇名】开头）\n'
    '3. 标签里带对齐空格（【关 键 词】、【期    刊】、【基    金】），'
    '年份卷期合并在【年代卷期】的 2021,(2):146-155 里，机构写成【机构名称】=[作者]单位.院系——'
    '本应用就按这套真实写法解析\n'
    '4. 上传该 .txt',
    'source.Dimensions.missing': '实测这份导出没有 References 列 ⇒ 共被引、文献耦合、引文突现做不了\n'
    '另两种导出（bibliometric mapping、reference manager）我们没有真实件，'
    '所以不声明能读——要引文网络请补 WoS/Scopus/CSSCI',
    'source.Dimensions.purpose': 'Dimensions 的 Publication 导出（Export full record → CSV）：被引次数、学科分类、'
    '基金与 MeSH 主题词都在，一份常有数百条。',
    'source.Dimensions.steps': '1. 在 Dimensions 检索\n'
    '2. 勾选结果 → Export → 选「Export full record」，File format 保持「CSV - Comma separated」\n'
    '3. 不要选「Export for bibliometric mapping」——那是给 VOSviewer/CiteSpace 的网络文件，'
    '本应用读的是记录表；也不要用「Export for reference manager → BibTeX」，'
    '那种文件能按 BibTeX 读，但被引次数、学科与基金都不在里面\n'
    '4. 一次最多 500 条（All items - max 500 items per download），超出就分批导出或勾'
    '「Send email when export is ready」——文件在 Export center 保留 30 天\n'
    '5. 上传 .csv——它的第一行是版权横幅而不是表头，导入会先跳过横幅再读列名',
    'source.EndNote.missing': '实测知网的 .enw 不含参考文献与被引次数',
    'source.EndNote.purpose': '知网的「EndNote 下载」按钮或 EndNote/Zotero 都能产出 .enw。',
    'source.EndNote.steps': '1. 知网导出页选「EndNote 下载」，或在文献管理软件里导出 .enw\n2. 上传 .enw',
    'source.Lens.missing': '实测这份导出的 References 列写的是 Lens 记录 ID（形如 002-341-399-981-03X），'
    '不是引文文本 ⇒ 共被引与文献耦合做不了，需要引文网络请用 WoS/Scopus/CSSCI\n'
    '没有任何作者单位或地址列 ⇒ 机构网络与国家网络做不了；'
    'Source Country 是期刊所在国，本应用不会把它当成作者所在国\n'
    '没有使用次数（usage）列 ⇒ 按使用次数筛选保持关闭',
    'source.Lens.purpose': 'Lens 的学术文献（Scholarly Works）CSV 导出：作者、来源刊、年份、学科、MeSH、'
    '关键词、摘要、DOI、被引次数与基金都在，一份可达上千条。',
    'source.Lens.steps': '1. 在 Lens 检索，并把集合切到 Scholarly Works——不要停在 Patents，'
    '专利导出会被点名拒绝\n'
    '2. 勾选记录 → Export → CSV，字段里保留 Title / Author/s / Publication Year / Source Title / '
    'Volume / Issue Number / Start Page / Keywords / MeSH Terms / Fields of Study / '
    'Citing Works Count / Funding / DOI / Abstract\n'
    '3. 上传 .csv（表头里必须有 Lens ID 与 Citing Works Count 或 Fields of Study，'
    '否则识别不出这是学术集合）',
    'source.NoteExpress.missing': '与 RefWorks 版同样没有参考文献与被引次数',
    'source.NoteExpress.purpose': '知网「NoteExpress 下载」按钮产出的 .net 文件，字段与 RefWorks 版一致。',
    'source.NoteExpress.steps': '1. 知网导出页选「NoteExpress 下载」\n2. 上传得到的 .net 文件',
    'source.PubMed.missing': '没有参考文献与被引次数 ⇒ 引文类分析不可用',
    'source.PubMed.purpose': 'PubMed 免机构授权，适合生物医学文献的关键词/作者/机构/国家共现网络。',
    'source.PubMed.steps': '1. 在 PubMed 检索\n'
    '2. 勾选记录 →「Save」→ Format 选「Text（Medline）」，Create File 后得到 .txt 或 .nbib\n'
    '3. 上传它；Format 选「CSV」得到的摘要文件也读，但它不含摘要与关键词，只适合当引用清单',
    'source.RIS.missing': '实测 WoS 的 RIS 导出不含被引次数，单位里也不含国家 ⇒ 按被引筛选与国家网络不可用',
    'source.RIS.purpose': '通用引文交换格式，多数数据库与文献管理软件都能导出 .ris。',
    'source.RIS.steps': '1. 在 Web of Science 里勾选记录 →「导出」→ 文件格式选「RIS File」\n'
    '2. 或在 Zotero 里右键条目 →「导出条目」→ 格式选 RIS\n3. 上传 .ris',
    'source.Scopus.missing': 'Scopus 站点导出不提供 Subject area 与 usage 列（不是漏勾）⇒ '
    '学科共现与按使用次数筛选不可用；'
    '英文界面的列名会随版本变化（Citation count / Cited by、Article number / Art. No.），'
    '两种写法都认',
    'source.Scopus.purpose': 'Scopus 的 CSV 下载：带参考文献、被引次数与作者单位，机构网络与国家网络都能建；'
    '中文界面导出的中文表头同样能读。',
    'source.Scopus.steps': '1. 在 Scopus 检索\n'
    '2. 勾选结果 →「下载」→ 格式选 CSV\n'
    '3. 字段里务必勾上 References（参考文献）、Affiliations（作者单位）与 Cited by（施引文献）'
    '——单位列决定机构网络与国家网络能不能建\n'
    '4. 上传 .csv——中文界面会得到 文献标题/来源出版物名称/施引文献/'
    '参考文献 等列名，本应用都认',
    'source.WoS.missing': 'Excel 的 Cited References 列不可用：站点在 Excel 导出里不提供这一列'
    '（实测 30 条整列为空，只写 Cited Reference Count 这个数字）⇒ 用 Excel 时引文网络与引文突现做不了；'
    '关键词（14/30）、学科、基金、使用次数在 Excel 里都可用。'
    '要引文分析请用「纯文本 + 全记录与引用的参考文献」（23/30 条带 CR）',
    'source.WoS.purpose': '英文文献的完整入口：参考文献、被引次数、使用次数、学科与国家都在这份导出里，'
    '共被引/耦合与国家级合作网络都能建。',
    'source.WoS.steps': '1. 在 Web of Science 核心合集检索\n'
    '2. 勾选记录 →「导出」，记录内容选到最完整的一档：「全记录与引用的参考文献」'
    '（Full Record and Cited References）\n'
    '3. 文件格式首选「纯文本文件」，得到带 CR/TC/UT 标签的 .txt\n'
    '4. 上传 .txt；Excel（.xls/.xlsx）、RIS、BibTeX 也认——注意 Excel 里**没有 Cited References 列**'
    '（站点不提供），引文分析要用纯文本',
    'source.feed_column_missing': '节点 {nid}：上游表格没有名为「{col}」的列',
    'source.feed_skipped': '上游喂送：跳过 {n} 个空单元格（没有可读的链接）',
}

EN = {
    'catbus.columnDrift': 'the columns CatBus returned do not match the manifest: missing {missing}, extra {extra}',
    'catbus.finished': 'CatBus finished: {n} new rows (target {want})',
    'catbus.finishedOnce': 'CatBus finished: {mode}, {n} new rows',
    'catbus.noCli': (
        'this machine has Node but no CatBus adapter for 采析绘 — point CIXI_CATBUS_CLI at the entry file, '
        'or CATBUS_HOME at a source checkout'
    ),
    'catbus.noDetail': 'this backend does not fetch a detail on its own (the adapter resolves each card): {url}',
    'catbus.noIdentity': (
        '{platform} / {mode} declares no identity column to CatBus, so the cross-run watermark has '
        'nothing to bound — refused'
    ),
    # The second crawl backend, CatBus (services/ingest/catbus.py). Every sentence names which part
    # is missing: an answer this side cannot read must never arrive as an empty table, because a node
    # settles DONE on an empty table.
    'catbus.noNode': 'this machine has no Node runtime, so the CatBus backend is unavailable (CIXI_NODE_BIN names one)',
    'catbus.noRunnableCell': 'CatBus has no runnable read function for this platform',
    'catbus.notInManifest': 'the CatBus manifest has no {platform} / {mode} entry, so it cannot crawl that cell',
    'catbus.oldNode': 'CatBus will not run on this Node: {node} reports {version} (needs 22.22.2 / 24.15.0 / 26.0.0)',
    'catbus.paramUnsupported': (
        'CatBus {platform} / {mode} does not accept these collection conditions: {params}. '
        'The adapter would ignore them, and a table that looks like the condition ran is worse than '
        'a refusal — switch to Selenium or remove those conditions'
    ),
    'catbus.pre.login': '{platform} has no logged-in CatBus account',
    'catbus.probeFailed': 'the CatBus adapter could not report its capability list: {detail}',
    'catbus.probeUnreadable': 'the CatBus adapter answered with something unreadable: {detail}',
    'catbus.refused': '{platform} / {mode} could not be crawled through CatBus: {detail}',
    'catbus.start': 'CatBus starts crawling: {mode}, target {n} rows',
    'catbus.startOnce': 'CatBus starts: {mode}',
    'catbus.stopped': '{platform} / {mode} was stopped through CatBus; the rows already stored are kept',
    'catbus.targetReached': 'the target of {n} rows is already in the table, so CatBus asks for nothing',
    'catbus.timeout': 'CatBus did not return within {seconds} seconds; the process was terminated',
    'catbus.warning': 'CatBus reported: {text}',
    'catbus.watermarkHit': 'CatBus reached the watermark {i}; the older rows are not filed',
    'catbus.watermarkNote': (
        'CatBus has no offset: the watermark bounds which rows are filed, while older items are still asked for'
    ),
    'comment.allMismatched': 'every link conflicts with the selected platform ({platform}) — check the article URLs',
    'comment.article': 'comments: {url} added {n} ({status})',
    'comment.bad_date': 'Node {nid}: the comment time range could not be parsed (use YYYY-MM-DD)',
    'comment.bad_range': 'Node {nid}: the comment time range ends before it starts',
    'comment.biliBadAnswer': 'bilibili comment endpoint returned no data (code={code}): {url}',
    'comment.biliShort': '[bilibili] cursor got {rows} of {declared} per the site (deep-page throttling): {url}',
    'comment.commentsClosed': 'this content has no open comment section (or none yet): {url}',
    'comment.done': (
        'comment crawl finished: {urls} links (ok {ok}, blocked {blocked}, '
        'dead {dead}), {rows} comments, {files} file(s)'
    ),
    'comment.dyGone': (
        '[douyin comments] the site answered this link with a different video ({shown}); '
        'this link counts as dead, not as a wall: {url}'
    ),
    'comment.dyNoId': 'the link carries no video id, so comments cannot be fetched: {url}',
    'comment.dyNoPanel': 'the comment panel never rendered (collapsed, or login required): {url}',
    'comment.dyNone': 'this video reports {n} comments but the list did not open: {url}',
    'comment.dyShort': (
        '[douyin comments] {url}: the page says {declared}, this table holds {rows} plus {nested} counted '
        'replies ({gap} still not collected) — this walk ended because: {reason}, so the gap is not a claim '
        'that the thread is that short'
    ),
    'comment.need_both': (
        'Node {nid}: filtering comments by time needs BOTH a start and an end (a half range cannot bound the window)'
    ),
    'comment.noAdapter': '{platform} has no comment crawler, so this link cannot be handled: {url}',
    'comment.no_urls': 'comment node has no crawlable URLs (supported: {platforms})',
    'comment.platformMismatch': 'skipped {n} link(s) that do not match the selected platform ({platform})',
    'comment.prefix': '[comments]',
    'comment.status.blocked': 'login/risk-control wall',
    'comment.status.dead': 'link unreadable',
    'comment.status.ok': 'ok',
    'comment.time_filtered': 'Node {nid}: filtered comments by time {start} ~ {end}: kept {kept}, dropped {dropped}',
    'comment.unsupported': 'comment node ignored {n} unsupported link(s) (supported: {platforms})',
    # Named because a count of dropped 「links」 sends the user hunting for a typo in a URL,
    # when what the node actually lacks is the platform that declared it takes plain names.
    'comment.unsupportedNames': (
        '{n} of them are names rather than links: feeding names needs the node to name its platform first '
        "(红果短剧's 评论 mode walks the player's own boards by title)"
    ),
    'comment.weiboFetchDied': (
        '[weibo comments] the comment request failed on page {page}, so the walk ended: {rows} rows kept'
        ' (the thread is labelled {declared}, {gap} of them unfetched; the cursor stayed on the page that'
        ' failed, so 继续 can pick it up)'
    ),
    'comment.weiboReplay': (
        '[weibo comments] page {page} added no new row while the cursor was still live: '
        'the walk calls the thread replayed and stops, at {rows} rows'
    ),
    'comment.weiboShort': (
        '[weibo comments] the page says {declared}, this table holds {rows} (a gap of {gap})'
        ' — the missing rows are nested replies: this endpoint does not return them as a list in the'
        ' current session, and only the one preview each parent row carries is in the table'
    ),
    'comment.weiboShowFailed': '[weibo comments] the comment endpoint answered nothing (dead cookie, limited): {url}',
    'comment.xNoList': '[X comments] the post page rendered nothing at all (dead, deleted, or blocked link): {url}',
    'comment.xhsPanelCapped': (
        '[xiaohongshu comments] stopped after {rounds} scroll rounds with the panel still growing; '
        'took {rows} rows: {url}'
    ),
    'comment.ytNoPage': 'the YouTube page never loaded as a video page (login or interception?): {url}',
    'comment.zhihuNoAuthor': (
        '[zhihu comments] {n} of {total} rows carry no author link inside their own subtree (anonymous or collapsed)'
    ),
    'comment.zhihuNoPanels': '[zhihu comments] no comment panel on this answer (closed, or never loaded): {url}',
    'comment.zhihuPanelCapped': (
        '[zhihu comments] stopped after {n} scroll rounds (reply threads opened) with the panel still '
        'growing; took {rows} rows'
    ),
    'comment.zhihuPanelShort': '[zhihu comments] the page says {declared} comments, {rows} were taken',
    'comment.zhihuRound': '[zhihu comments] round {r} added {n} rows ({total} so far)',
    'source.BibTeX.missing': 'Fields vary by tool: a record without an author is counted in the skipped total and '
    'named in the console, never stored as an empty row',
    'source.BibTeX.purpose': 'The format LaTeX workflows already use; Zotero and Web of Science both export .bib.',
    'source.BibTeX.steps': '1. Choose "BibTeX" in Web of Science’s export format list, or in Zotero: '
    'right-click items → Export Items → format BibTeX\n2. Upload the .bib',
    'source.CNKI.missing': 'No reference list ⇒ co-citation, bibliographic coupling and citation '
    'bursts are unavailable\n'
    'No times-cited ⇒ the 总被引/H指数 columns never appear and citation-count filters stay off',
    # ── Bibliographic source export guide (services/biblio/sources.py) ──
    # Every line is bounded by a file we actually parsed: what a source lacks is stated as
    # missing, and no button is named that we have not seen in a real export.
    'source.CNKI.purpose': 'The entry point for co-occurrence networks in Chinese literature: keywords, authors, '
    'institutions and journals all build. CNKI exports carry no reference list and no '
    'times-cited, so citation analyses refuse by name before running instead '
    'of drawing nothing.',
    'source.CNKI.steps': '1. Search CNKI by topic or keyword; narrow by year and source if needed\n'
    '2. Tick the records, then press Export / Bibliography\n'
    '3. Choose the RefWorks format on the export page and save CNKI-<timestamp>-RefWorks.txt\n'
    '4. Upload that .txt; the NoteExpress and EndNote buttons on the same page are read too',
    'source.CSSCI.missing': 'No 【摘要】⇒ pick 关键词 as the cluster-label source; choosing 摘要 refuses by name\n'
    'No DOI ⇒ cross-source matching can only use title and authors',
    'source.CSSCI.purpose': 'The citation entry point for Chinese social science: the CSSCI export carries a '
    'reference list, so co-citation and coupling work; it carries no abstract and no DOI.',
    'source.CSSCI.steps': '1. Open the search page of the CSSCI centre at Nanjing University\n'
    '2. Search by year, source or keyword and export the text, making sure the records include '
    '【参考文献】and【年代卷期】(one record per 【来源篇名】)\n'
    '3. The real file pads its tags (【关 键 词】, 【期    刊】, 【基    金】), merges year, '
    'issue and pages into 【年代卷期】2021,(2):146-155, and writes affiliations as '
    '【机构名称】=[author]institute.department — the importer parses exactly that shape\n'
    '4. Upload the .txt',
    'source.Dimensions.missing': 'Measured: this export carries no References column ⇒ co-citation, coupling and '
    'citation bursts are unavailable\n'
    'We have no real file for the other two exports (bibliometric mapping, reference manager), '
    'so we do not claim to read them — for a citation network add WoS/Scopus/CSSCI',
    'source.Dimensions.purpose': "Dimensions' full-record CSV export: times-cited, subject fields, funding and MeSH "
    'terms are present, and one export often holds hundreds of records.',
    'source.Dimensions.steps': '1. Search Dimensions\n'
    '2. Select results → Export → choose "Export full record", and leave File format on '
    '"CSV - Comma separated"\n'
    '3. Do not choose "Export for bibliometric mapping" — that writes a VOSviewer/CiteSpace '
    'network file, not the record table this app reads; and do not use "Export for reference '
    'manager → BibTeX", which is readable as BibTeX but drops times-cited, subject fields and '
    'funding\n'
    '4. One download holds at most 500 items ("All items - max 500 items per download"), so '
    'export in batches, or tick "Send email when export is ready" — the file stays in the '
    'Export center for 30 days\n'
    '5. Upload the .csv — its first row is a copyright banner, not the header, and the '
    'importer skips it before reading column names',
    'source.EndNote.missing': 'Measured: CNKI’s .enw carries no references and no times-cited',
    'source.EndNote.purpose': "The .enw that CNKI's EndNote button produces, or that EndNote/Zotero export.",
    'source.EndNote.steps': '1. Choose the EndNote download on CNKI’s export page, or export .enw from a manager\n'
    '2. Upload the .enw',
    'source.Lens.missing': 'Measured: the References column of this export is a list of Lens record ids '
    '(shaped like 002-341-399-981-03X), not citation text ⇒ co-citation and bibliographic coupling '
    'are unavailable; use WoS/Scopus/CSSCI for a citation network\n'
    'It has no affiliation or address column ⇒ institution and country networks cannot be built; '
    'Source Country names the journal’s country, and this app will not present it as the authors’\n'
    'No usage counts ⇒ the usage filter stays off',
    'source.Lens.purpose': "Lens' Scholarly Works CSV export: authors, source journal, year, subject fields, MeSH "
    'terms, keywords, abstracts, DOIs, times-cited and funding are all in it, and one export can '
    'hold over a thousand records.',
    'source.Lens.steps': '1. Search Lens and switch the collection to Scholarly Works — do not stay on Patents, '
    'whose export is refused by name\n'
    '2. Select records → Export → CSV, keeping Title / Author/s / Publication Year / Source Title '
    '/ Volume / Issue Number / Start Page / Keywords / MeSH Terms / Fields of Study / Citing Works '
    'Count / Funding / DOI / Abstract in the field list\n'
    '3. Upload the .csv (the header must contain Lens ID plus Citing Works Count or Fields of '
    'Study, otherwise the file cannot be told apart from the patent collection)',
    'source.NoteExpress.missing': 'Like the RefWorks export: no reference list, no times-cited',
    'source.NoteExpress.purpose': "The .net file behind CNKI's NoteExpress button; its fields match the RefWorks one.",
    'source.NoteExpress.steps': '1. Choose the NoteExpress download on CNKI’s export page\n'
    '2. Upload the resulting .net file',
    'source.PubMed.missing': 'No references and no times-cited ⇒ citation analyses are unavailable',
    'source.PubMed.purpose': 'PubMed needs no institutional access and suits keyword, author, institution and '
    'country co-occurrence in biomedicine.',
    'source.PubMed.steps': '1. Search PubMed\n'
    '2. Select records → Save → Format "Text (Medline)", then Create File to get the .txt or .nbib\n'
    '3. Upload it; the CSV summary is read too, but it has no abstract and no '
    'keywords, so it works as a citation list rather than an analysis source',
    'source.RIS.missing': 'Measured: WoS’ RIS export carries no times-cited and no country in the affiliation ⇒ '
    'count filtering and the country network are unavailable',
    'source.RIS.purpose': 'A general citation-exchange format: most databases and reference managers export .ris.',
    'source.RIS.steps': '1. In Web of Science: select records → Export → file format "RIS File"\n'
    '2. Or in Zotero: right-click items → Export Items → format RIS\n'
    '3. Upload the .ris',
    'source.Scopus.missing': 'The Scopus site offers neither a Subject area nor a usage column in this export '
    '(it is not a field you forgot to tick) ⇒ subject co-occurrence and the usage filter are unavailable; the '
    'English column names move between versions (Citation count / Cited by, Article number / '
    'Art. No.) and both spellings are accepted',
    'source.Scopus.purpose': "Scopus' CSV download: references, times-cited and author affiliations are in it, so "
    'institution and country networks build, and the Chinese interface’s Chinese column headers '
    'are recognised too.',
    'source.Scopus.steps': '1. Search Scopus\n'
    '2. Select results → Download → format CSV\n'
    '3. Tick References, Affiliations and Cited by in the field list — the affiliation column '
    'decides whether institution and country networks can be built at all\n'
    '4. Upload the .csv (a Chinese-interface file arrives with 文献标题/来源出版物名称/'
    '施引文献/参考文献 columns, which the reader also accepts)',
    'source.WoS.missing': 'The Cited References field is unavailable in Excel: the site does not offer that column in '
    'the Excel download (measured: all thirty rows empty, only the Cited Reference Count number) ⇒ '
    'with Excel alone there is no citation network and no citation burst; keywords (14/30), '
    'categories, funding and usage ARE usable from Excel. For citation analysis use "Plain Text with '
    'Full Record and Cited References" (23/30 rows carry CR)',
    'source.WoS.purpose': 'The complete English-language entry point: this export carries references, times-cited, '
    'usage counts, research areas and countries, so co-citation, coupling and country '
    'collaboration networks all work.',
    'source.WoS.steps': '1. Search the Web of Science Core Collection\n'
    '2. Select records → Export, and choose the fullest record option: '
    '"Full Record and Cited References"\n'
    '3. Prefer "Plain Text" as the file format — that is the .txt carrying the CR/TC/UT tags\n'
    '4. Upload the .txt; Excel (.xls/.xlsx), RIS and BibTeX are read too — note that Excel carries '
    'no Cited References column (the site does not offer one), so citation work needs the plain text',
    'source.feed_column_missing': 'Node {nid}: the upstream table has no column named {col}',
    'source.feed_skipped': 'upstream feed: skipped {n} empty cell(s) (no link to read)',
}
