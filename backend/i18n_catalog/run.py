"""The run itself: the claim, the queue, per-node console lines, resumes, the run record and
the saved canvas.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/i18n/test_i18n.py``).
"""

ZH = {
    'engine.accumulate_bad_identity': '节点 {nid}：未知的去重方式 {value}',
    'engine.accumulate_bad_parent': '节点 {nid}：累积数据集的上游 {up} 不是表格节点',
    'engine.accumulate_no_keys': '节点 {nid}：按列去重时必须填写去重列',
    'engine.accumulate_no_name': '节点 {nid}：累积数据集节点还没有填名字',
    'engine.accumulate_one_parent': '节点 {nid}：累积数据集节点必须恰好有一个上游',
    'engine.analysis_no_op': '节点 {nid}：分析节点没有配置操作或步骤',
    'engine.biblio_multi_input': '{nid} 有 {n} 个上游连接：文献计量只接受一个输入，请只保留一条连线',
    'engine.biblio_no_input': '{nid} 需要且只接受一个上游数据表（文献导入节点）',
    'engine.comment_no_urls': '节点 {nid}：评论节点还没有填写文章链接',
    'engine.compile_bad_parent': '节点 {nid}：编译节点只能接收可视化节点的 LaTeX，上游「{up}」不是可视化节点',
    'engine.compile_no_upstream': '节点 {nid}：编译节点没有上游连线（需要连接可视化节点）',
    'engine.compile_source_both_off': (
        '节点 {nid}：上游可视化「{up}」的 LaTeX 图与三线表复选框都没勾选，编译节点无内容可编'
    ),
    'engine.cycle': '工作流存在环，以下节点无法排序：{nodes}',
    # A wire whose end is not on the canvas is not a cycle. Reporting it as one
    # (with an empty node list, which is what the old code produced) sent users
    # hunting a loop that did not exist.
    'engine.dangling_connection': '连线指向画布上不存在的节点：{src} → {dst}',
    # An empty canvas is refused, never "completed": 0/0 nodes with a 已完成 toast
    # reads as a run that worked.
    'engine.empty_canvas': '画布上没有任何节点，没有可运行的工作流',
    'engine.name_no_downstream': '节点 {nid}：命名节点后面必须连接下游节点',
    'engine.name_no_label': '节点 {nid}：命名节点的工作流名称不能为空',
    'engine.name_not_head': '节点 {nid}：命名节点必须打头，不能有上游节点接入',
    'engine.output_needs_pdf': '节点 {nid}：上游是可视化/编译节点时，输出格式必须为 PDF',
    'engine.output_no_op': '节点 {nid}：输出节点没有选择操作',
    'engine.output_no_table': (
        '节点 {nid}：输出节点的上游都不产出表格（命名节点只是元数据，可视化节点产出的是图表配置）'
    ),
    'engine.output_no_upstream': '节点 {nid}：输出节点没有任何上游连线，没有可保存的表格',
    'engine.output_pdf_mixed': '节点 {nid}：PDF 输出不能与表格类上游混接（请只用可视化或编译节点作上游）',
    'engine.output_pdf_only_pdfable': '节点 {nid}：PDF 输出的上游必须是可视化节点或编译节点',
    'engine.output_pdf_two_sources': '节点 {nid}：PDF 输出不能同时接可视化节点与编译节点（二选一）',
    'engine.process_no_op': '节点 {nid}：处理节点没有选择操作',
    'engine.source_bad_backend': '节点 {nid}：采集方式「{backend}」不存在，请改用 Selenium 或 CatBus',
    'engine.source_bad_option': '节点 {nid}：「{field}」没有「{value}」这个选项，请在该节点的下拉里改选一个',
    'engine.source_catbus': '节点 {nid}：CatBus 引擎无法采集这一项：{detail}',
    'engine.source_feed_no_column': '节点 {nid}：已连接上游表格，但没有填写「{field}」要逐行读取的列名',
    'engine.source_feed_no_input': ('节点 {nid}：填写了上游列名，但该节点没有连接任何数据表（标注用的「名称」线不算）'),
    # Feeding a link mode from an upstream table column: the wire is allowed only where
    # the matrix declares a feed (Field.fed_by), and every mismatch is refused BY NAME —
    # a wired-but-unfed crawl would silently re-crawl the pasted list the user thinks
    # they replaced, and a fed crawl with no wire would read a table that is not there.
    'engine.source_feed_no_mode': (
        '节点 {nid}：这种采集内容不接受上游表格，逐行喂送只支持「链接列表」类表单，请断开这条连线或改选采集内容'
    ),
    'engine.source_link_mismatch': '节点 {nid}：{n} 个链接与所选平台（{platform}）不符',
    'engine.source_missing': '节点 {nid}：必填项「{field}」还没有填写',
    'engine.source_needs_machine': '节点 {nid}：这台机器跑不了这种采集（{reason}），请换采集内容或在能跑的机器上运行',
    'engine.source_no_cookie_account': (
        '节点 {nid}：{platform} 的账号「{account}」没有可用的 Cookie——请先到 Cookie 面板为该账号保存一份，'
        '或在该节点改用已有 Cookie 的账号（不会借用别的账号登录，也不会静默少采）'
    ),
    'engine.source_no_platform': '节点 {nid}：数据源节点没有选择平台',
    'engine.source_unknown_mode': '节点 {nid}：{platform} 没有这种采集内容，请在该节点的「采集内容」里改选一种',
    'engine.source_unknown_platform': '节点 {nid}：{platform} 还没有可用的采集实现，请改用已支持的平台',
    'engine.tokenize_no_column': '节点 {nid}：分词节点缺少文本列',
    'engine.unknown_node_type': '节点 {nid}：未知的节点类型「{type}」，工作流引擎无法执行它',
    'engine.upload_no_file': '节点 {nid}：上传节点还没有选择文件',
    'engine.visualize_no_chart': '节点 {nid}：可视化节点没有选择图表类型',
    'engine.visualize_no_x': '节点 {nid}：可视化节点缺少 X 字段',
    'engine.watermarkRecrawl': '节点 {nid}：跨运行水位与「重新采集」不能同时开启',
    'engine.watermarkUnsupported': '节点 {nid}：跨运行水位只支持哔哩哔哩作者投稿',
    'executor.task_failed': '任务失败：{err}',
    'housekeeping.datasetStoreFailed': '孤立文件自动清理失败（不影响本次运行）',
    # ── 自动清理（housekeeping） ──────────────────────────────
    'housekeeping.done': (
        '自动清理：删除 {runs} 条过期运行记录、{files} 个孤立文件（另回收 {cache} 条模型缓存、{seen} 条去重记录）'
    ),
    'housekeeping.runStoreFailed': '运行记录自动清理失败（不影响本次运行）',
    'latex.done': '已生成 LaTeX 图：{file}',
    'latex.failed': 'LaTeX 生成失败：{reason}',
    'latex.table_done': '已生成 LaTeX 三线表：{file}',
    'node.accumulate': '累积数据集',
    'node.analysis': '分析',
    'node.biblio': '文献计量',
    'node.comment': '评论采集',
    'node.compile': '编译',
    # ── node type labels (console fallbacks; mirror frontend app.js) ──
    'node.name': '工作流命名',
    'node.output': '输出',
    'node.process': '处理',
    'node.resume': '断点续跑',
    'node.source': '数据源',
    'node.tokenize': '分词',
    'node.upload': '上传文件',
    'node.visualize': '可视化',
    'project.badEntry': '项目包内的文件路径不合法：{file}',
    'project.badFormat': '不是采析绘项目包',
    'project.badJson': '项目包内的 JSON 无法读取：{file}',
    'project.badManifest': '项目包清单缺少列表：{section}',
    'project.badVersion': '项目包版本不支持：{version}',
    'project.badZip': '项目包不是有效的 zip 文件',
    'project.checksum': '项目包文件校验失败：{file}',
    'project.datasetInvalid': '项目包里的数据集无法读取：{id}',
    'project.datasetMissing': '工作流引用的数据集不存在：{id}',
    'project.datasetRefMissing': '工作流引用的数据集不在项目包里：{id}',
    'project.datasetTooLarge': '数据集 {id} 超过 {max} 行',
    'project.entryMissing': '项目包缺少文件：{file}',
    'project.fileTooLarge': '项目包内的文件过大：{file}（上限 {mb} MB）',
    'project.lineageInvalid': '项目包里的累积数据集信息无法读取',
    'project.lineageMissing': '引用的累积数据集不存在，已跳过：{name}',
    'project.noFile': '请选择一个项目包文件',
    'project.noWorkflow': '请先保存一个工作流，再导出项目包',
    'project.noWorkflowInBundle': '项目包里没有工作流',
    'project.templateInvalid': '可复用模板无法导入：{name}',
    'project.templateMissing': '引用的可复用模板不存在，已跳过：{id}',
    'project.templateRefMissing': '工作流「{name}」引用的模板不在项目包里：{id}（实例自带的快照仍然可用）',
    'project.tooLarge': '项目包解压后超过 {mb} MB',
    'project.tooMany': '项目包里的 {section} 过多（上限 {max}）',
    'project.tooManyEntries': '项目包条目过多（上限 {max}）',
    'project.workflowInvalid': '项目包里的工作流无法读取：{name}',
    'project.workflowUnreadable': '工作流文件无法读取：{name}',
    'report.chart_failed': '图表生成失败：{err}',
    'report.charts': '图表',
    'report.chartsFailed': '报告中的图表生成失败，正文与表格照常输出',
    'report.conclusion': '结论',
    'report.default_title': '{name} · 运行报告',
    'report.fact.finished': '结束',
    'report.fact.run': '运行编号',
    'report.fact.started': '开始',
    'report.fact.status': '状态',
    'report.fact.workflow': '工作流',
    'report.figure_section': '图表',
    # ── 一键报告（自包含 HTML） ───────────────────────────────
    'report.generated': '生成时间',
    'report.latex_no_run': '找不到这次运行（{rid}），无法合成成稿。',
    'report.latex_no_sources': '这次运行没有登记任何 LaTeX 图源或三线表，无法合成成稿：'
    '请在可视化节点勾选「生成 LaTeX」后重跑。',
    'report.method_analysis': '{title}：分析步骤 {ops}。',
    'report.method_biblio': '{title}：以{entity}为分析单元。参数（本系统内部枚举名，与运行记录及导出表一致）：{body}。',
    'report.method_counts': '共 {figures} 张图、{tables} 张三线表；每张图与其表格来自同一次运行登记的同一份行表。',
    'report.method_fuse': '{title}：把多张上游表折叠为一份规范记录表（角色按候选列顺序尝试）。',
    'report.method_no_canvas': '本次运行没有可读取的已保存画布，因此下表只给出运行编号与时间窗，不给参数；'
    '需要方法段落请先保存画布再运行。',
    'report.method_provenance': '本稿由工作流「{workflow}」的一次运行自动合成，运行编号 {run_id}。',
    'report.method_section': '方法',
    'report.method_source': '{title}：采集 {platform} 的 {collect}，目标 {target} 条。',
    'report.method_unverified': '以下节点的参数无法与运行记录的指纹核对（画布已改动或文件已不在）：{names}。',
    'report.method_upload': '{title}：数据集 {name}。',
    'report.method_window': '运行区间：{started} 至 {finished}。',
    'report.missing_charts': '另有 {count} 个可视化节点没有登记 LaTeX 源，本稿不含它们的图与表：{names}。',
    'report.more_rows': '以上为前 {shown} 行，共 {total} 行；完整数据请用导出节点另存 CSV。',
    'report.no_charts': '这些数据还不足以出图。',
    'report.no_rows': '这个节点没有产出任何行。',
    'report.row_count': '{n} 行 · {cols} 列',
    'report.run_facts': '运行信息',
    'report.summary': '本次运行共 {nodes} 个节点，产出 {rows} 行数据，其中 {tables} 个节点有表格。',
    'report.table_continued': '（续）',
    'report.table_suffix': '（三线表）',
    'report.tables': '数据表',
    'resume.empty': '续跑节点：运行 {rid} 中「{nid}」没有可读取的数据行',
    'resume.loaded': '续跑节点：载入运行 {rid} 中节点 {nid} 的 {n} 行',
    'resume.no_run': '续跑节点：没有选择运行记录，也没找到可续跑的记录',
    'resume.unpicked': '未指定节点',
    'reusable.badConnection': '连线两端不是模板内的节点：{a} → {b}',
    'reusable.badConnections': '模板里的连线无法理解',
    'reusable.badId': '可复用模板 id 形状不对：{id}',
    'reusable.badInput': '输入槽指向一个不存在的节点：{id}',
    'reusable.badInputs': '模板的输入槽列表无法理解',
    'reusable.badNode': '模板里有无法理解的节点',
    'reusable.badNodeId': '节点 id 缺失或重复：{id}',
    'reusable.badNodeParams': '节点 {id} 的参数不是对象',
    'reusable.badNodeType': '节点 {id} 的类型不能放进可复用节点：{type}',
    'reusable.badOutput': '输出槽指向一个不存在的节点：{id}',
    'reusable.badOutputs': '模板的输出槽列表无法理解',
    'reusable.badTemplate': '可复用节点「{name}」的模板无法展开（节点类型或连线不被接受）',
    'reusable.corrupt': '可复用模板 {id} 的内容已损坏',
    'reusable.cycle': '模板里存在环，无法按顺序执行',
    'reusable.descriptionTooLong': '模板说明超过 {n} 个字符',
    'reusable.full': '可复用模板已达上限（{max} 个），请先删除旧模板',
    'reusable.invalid': '可复用节点模板的内容无法理解',
    'reusable.missing': '没有这个可复用模板：{id}',
    'reusable.missingInputs': '可复用节点「{name}」需要 {n} 个输入，当前只接了 {wired} 个',
    'reusable.nameRequired': '可复用节点需要一个名字',
    'reusable.nameTaken': '已有同名可复用模板「{name}」',
    'reusable.nameTooLong': '模板名称超过 {n} 个字符',
    'reusable.noNodes': '可复用节点里至少要有一个节点',
    'reusable.noTemplateForRun': '可复用节点「{name}」没有可运行的模板',
    'reusable.oneOutput': '可复用节点必须恰好有一个输出节点（现在有 {n} 个）',
    'reusable.outputHasNext': '输出节点 {id} 还有后续节点，请选择真正的末端节点',
    'reusable.tooManyInputs': '可复用节点「{name}」的外部连线比输入槽多',
    'reusable.tooManyNodes': '一个可复用节点最多包含 {n} 个节点',
    'run.browserReapFailed': (
        '停止超时后仍未终止这个浏览器进程（PID {pid}）：{err}——它的窗口配置目录会一直被占着，'
        '该平台下一次采集要等到锁超时'
    ),
    # Said out loud because the alternative is silence that reads as "closed", while the
    # user may be looking at the window that is still open.
    'run.browserStuck': (
        '警告：{platform} 的浏览器关不掉（读不到它的进程号），它可能仍然开着，并会占用该平台目录最多 {seconds} 秒'
    ),
    'run.claims_released': '重跑节点：已归还 {n} 条「已采集」认领（运行 {rid}），这些条目会重新采',
    # Two bulk deletions, each naming what it destroyed. The claims figure is not decoration:
    # 清空运行记录 also hands back the "已采集" ledger, so the next crawl really will re-fetch
    # what an earlier one collected — a user who reads 「清空了 3 条」 and then watches the same
    # workflow crawl twice as much needs this line to know why.
    'run.cleared': '已清空运行记录：{runs} 条，并交回 {claims} 条"已采集"认领（这些条目下次会重新爬）',
    # Named because a feed of ten dramas that opened six is not a completed comment crawl;
    # the rows the six yielded stay in the table (the user chose 保留), and these four are
    # what 继续 still owes.
    'run.commentsSkipped': (
        '{platform} 有 {n} 部剧没有采完（没能进入播放器，或播放流中途切到了别的剧）：{names}——'
        '其余剧的行已保留；点「继续」会回到第一部未采完的剧起重走'
        '（已入库的评论按 评论ID 去重，不会重复入库）'
    ),
    'run.compileFailed': 'LaTeX 编译失败：{err}',
    'run.compileSaved': 'PDF 已编译：{name}（{size} 字节）',
    # Only for a comment node whose links came from several platforms and whose own
    # platform field is empty — the message must name what walled, and a hand-written
    # list of platforms the user never crawled reads worse than no list at all.
    'run.cookieAnyPlatform': '所采集的平台',
    'run.cookieExpired': (
        '登录态疑似失效：{platform} 的抓取被挡回登录页（COOKIE 可能过期）。'
        '已采集的数据全部保留——请到 设置→Cookie 更新后，用断点续跑从上次中断处继续'
    ),
    'run.cookieExpiredOk': '提示：{platform} 在目标达成后才遇到登录墙，本次数据完整，无需续跑',
    'run.dedupe_all_skipped': (
        '本节点的结果此前已全部采集，本次没有新数据传给下游；'
        '要重抓请在采集节点开启「重新采集」，要用旧数据请从运行记录导出或用断点续跑（Resume）节点续接'
    ),
    'run.dedupe_skipped': '增量采集：{n} 条结果此前已采集，本次被跳过（如需重抓请在采集节点开启「重新采集」）',
    'run.failed_down': '节点 {nid} 失败且没有可用数据，下游按空表继续',
    'run.finished': '运行结束（{done}/{total} 个节点完成）',
    'run.finished.failed': '，{n} 个失败',
    # Fragments appended to the line above, only when they are true: a run whose
    # numbers are all clean reads as one clean sentence rather than a table of
    # zeroes, while a run that starved or lost a node cannot be mistaken for one.
    'run.finished.skipped': '，{n} 个跳过',
    'run.finished.stopped': '，{n} 个被停止',
    'run.heavy_result': '内存提示：节点「{nid}」产出 {n} 行，运行结束前每个节点的这份结果都留在内存里',
    'run.interrupted_by_dead_worker': '执行线程已不在，记录自动判定为中断',
    'run.interrupted_by_restart': '服务重启时被打断',
    'run.live_export': '实时导出：{file}（每处理完一批刷新一次，运行结束后保留）',
    'run.live_export_failed': '实时导出写入失败：{err}',
    'run.nodeStopped': '节点 {nid} 已按「停止」结束：本次保留 {n} 行',
    'run.notCrawlable': (
        '「{label}」所在的平台（{platform}）目前只能保存登录 Cookie，还没有采集实现，'
        '因此不能作为数据源运行——请改用已支持的平台，或等该平台的抓取落地'
    ),
    # A page that never arrived, said once with the one thing the crawler cannot know:
    # whether this machine can reach anything at all. ``{advice}`` is left empty when the
    # page already named its own cause, so the sentence must read in both shapes.
    'run.pagePending': '{page}{streak}{advice}',
    'run.pageStreak': '；这已是本机连续第 {n} 次没有拿到页面',
    'run.partial_down': '节点 {nid} 中断：已把 {n} 行已完成的结果交给下游',
    'run.platformGateTimeout': '{platform} 等待采集时段超时（{n} 秒）：可能有浏览器窗口没有关闭',
    'run.platformQueued': (
        '{platform} 正在被另一条工作流采集，本轮改为排队：{n} 秒后开始，'
        '避免同一账号在同一秒内发出两次搜索而被弹到登录页'
    ),
    'run.platformStaggered': (
        '{platform} 与上一条同平台采集错开 {n} 秒后发车：这次没有排队，两条仍可能同时跑，'
        '只是避开同一账号一秒内发出两次搜索'
    ),
    'run.profileOff': '本次执行不使用浏览器 Profile：每次都是全新设备（为让同平台的工作流真并行），Cookie 快照照常导入',
    'run.progress_file': '分批导出：{file}（{rows} 行，共 {parts} 个分批文件）',
    'run.promoted': '发现 {n} 条上次没跑完的记录，已标记为「可续跑」',
    'run.queueAbandoned': '{platform} 的排队等待已取消（本次运行已停止）',
    'run.queueLoadFailed': '重启读取待运行队列镜像失败（本轮从空队列开始）',
    'run.queueMirrorFailed': '写入待运行队列镜像失败（内存队列仍是权威，不受影响）',
    'run.queueStartFailed': '排队的运行无法启动',
    'run.queue_broken': '队列里的 {name} 无法启动，已跳过并继续下一个：{err}',
    'run.queue_restored': '重启后恢复了 {n} 个待运行任务',
    'run.queue_started': '队列接续：{name} 开始运行（{rid}）',
    'run.queue_waited': '队列接续失败（已有运行在跑），{name} 重新排队',
    'run.queued': '已排队（第 {at} 位）：{name}',
    'run.queuedUnnamed': '未命名工作流',
    'run.reconciled': '发现 {n} 条线程已结束却没写下结论的记录，已判定为「已中断」',
    'run.recordWriteFailed': '记录 {rid} 的结论没能写进数据库（{err}）：运行记录会在下次刷新时自动补上判定',
    'run.recrawl': '重新采集：已释放 {n} 条历史去重记录，本节点将重新抓取',
    'run.rejected': '未运行：工作流有 {n} 处问题，见上方提示',
    'run.reportConclusionFailed': '结论生成失败，报告已省略结论：{err}',
    'run.reportFailed': '报告生成失败：{err}',
    'run.reportLatexFailed': '论文成稿失败：{err}',
    'run.reportLatexSaved': '论文成稿已编译：{name}（{figures} 张图 / {tables} 张三线表）',
    'run.reportSaved': '报告已生成：{name}（{size} 字节）',
    'run.restored': '节点 {nid} 沿用上次结果（{n} 行），不再重跑',
    'run.resume_crawl': '节点 {nid} 从上次中断处继续抓取（已有 {have} 行）',
    'run.resume_from': '续跑模式：接着 {at} 那次往下跑，此前已保存 {rows} 行',
    # A 风控 refusal is the OPPOSITE advice from a dead cookie: the session may be fine and
    # re-running straight into it only deepens the block, so the console names 风控, says it
    # is not a login problem, and tells the user to wait (继续 later), never to re-save.
    'run.riskControlled': (
        '{platform} 被安全验证（风控）拦下，本次未能采满——这不是登录态失效，请勿立刻重跑（立即再撞只会加重风控）。'
        '已采集的数据全部保留；可先开启 设置→慢速采集，稍后用「继续」从断点补采'
    ),
    # ── 断点续跑（durable run state） ────────────────────────
    'run.row_limit': '节点 {nid} 已达到保存上限 {limit} 行，超出部分不再落库',
    'run.serialForced': (
        '{platform} 的多条采集强制排队串行执行：同一账号并行翻页必被弹回登录页，'
        '这个平台的串行由站点决定，与错峰设置无关'
    ),
    'run.skippedWorkflows': '本次跳过（已禁用，不参与运行）：{names}',
    'run.skipped_empty': '节点 {nid} 跳过：上游没有数据',
    'run.start_failed': '运行线程启动失败（{err}）：本次运行已放弃，队列继续处理下一个',
    'run.started': '本次运行已记账：{rid}（随时可中断，数据逐条落库）',
    'run.store_unavailable': '本次运行无法开始：运行记录库打不开（磁盘满、文件损坏或被占用），未产生任何记录',
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
    'run.wallRetry': ('{platform} 在第一条数据之前就被弹到登录页，这更像同一账号被两次并发搜索撞了：{n} 秒后重试一次'),
    'run.watermarkFirst': '跨运行水位：这是第一次运行，完成后保存边界',
    'run.watermarkLoaded': '跨运行水位：从上次完成的边界 {boundary} 开始，遇到它即停止',
    'run.watermarkNoNew': '已到上次的边界 {boundary}，本次没有更新的条目',
    'run.watermarkNoScope': '跨运行水位需要运行上下文里的节点指纹；直接调用执行器时不能启用',
    'run.watermarkSaved': '跨运行水位已更新：{boundary}（本次新采 {n} 条）',
    'run.watermarkUnsupported': '跨运行水位只支持哔哩哔哩作者投稿（当前平台/模式：{platform} / {mode}）',
    'upload.loaded': '已载入上传文件 {name}：{n} 行',
    # ── upload node ───────────────────────────────────────────
    'upload.no_file': '文件上传节点未选择文件，请在节点设置里上传 CSV / JSON / TXT',
    'upload.stale': '已上传的数据集失效（服务可能重启过），请重新上传文件',
    # The labelling step needs a model: without one the step refuses instead of leaving the
    # column blank and settling the node DONE on work that did not happen.
    'wf.analysis_llm_no_model': '「主题概括」需要模型，但这条运行没有配置模型（设置 → 模型 / 节点模型）',
    # These refusals are printed by the executor as the node's own failure
    # (「节点 X 执行失败：…」), so they state the reason only — a second
    # 「分词失败：」/「可视化失败：」 inside them repeats the wrapper, and the node
    # used to be logged twice: once here without a name, once attributed.
    'wf.analysis_step': '[分析] {op}：{before} → {after} 行',
    'wf.analysis_step_nochange': '（无变化）',
    'wf.analysis_step_removed': '（-{removed}）',
    'wf.analysis_steps_shape': '「steps」必须是步骤列表（每个一步一个对象），收到的是一个对象',
    'wf.browser_opened': '已打开浏览器用于 {platform} 登录（{url}），等待 {n} 秒完成登录…',
    'wf.compile_no_source': '编译节点没有可编译的 LaTeX 来源（上游可视化节点既未产出图也未产出表）',
    'wf.component_indexed': '{name}（第 {i}/{n} 条）',
    'wf.cookies_generated': '已生成 {platform} 的 Cookie（{n} 项）',
    # No 'wf.completed' / 'wf.all_completed': `run.finished` says how the run
    # ended and carries the node counts, so a second sentence could only disagree.
    # One line per failure, and it says where the detail is: the log handler
    # forwards every logger call to the console, so the pair of messages this
    # replaced printed the same sentence twice.
    'wf.exec_exception': '执行失败，完整堆栈见服务端日志',
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] 正在执行节点：{nid}（{ntype}）',
    'wf.found': '发现 {n} 条工作流',
    'wf.join_no_right_table': '合并表需要两条上游连线：第一条是左表，第二条是右表',
    'wf.merge_columns': (
        '节点 {nid} 合并上游表时列名不一致，对比「{up}」：多出 [{extra}]、缺少 [{missing}]。'
        '不做外连接合并——那会凭空补出空值，让文件看起来完整'
    ),
    'wf.merge_detail_sep': '、',
    'wf.merge_done': '节点 {nid} 合并 {tables} 张上游表 → {n} 行（{detail}）',
    'wf.merge_not_tabular': (
        '节点 {nid} 的上游「{up}」不产出表格（是图表配置或错误应答），无法合并——请断开这条连线，'
        '或改接一个产出表格的节点'
    ),
    'wf.merge_table_detail': '{name} {n} 行',
    'wf.multi_input': (
        '节点 {nid} 有 {n} 条上游连线：主输入取第一条（来自 {up}）；分析节点的连接用第二条当右表，'
        '输出节点则把全部上游合并成一张表'
    ),
    'wf.node_completed': '[{wf}] 节点 {nid} 完成（{done}/{total}）',
    'wf.node_failed': '[{wf}] 节点 {nid} 执行失败：{err}',
    'wf.starting': '开始执行工作流「{name}」',
    'wf.tokenize_done': '[分词] {mode} 已切分 {col} → {n} 行',
    'wf.tokenize_no_col': '列“{col}”不在 {cols} 中',
    'wf.tokenize_no_column': '未配置要分词的文本列',
    'wf.tokenize_no_input': '没有上游数据，请连接数据源或文件上传节点',
    'wf.unknown_process_op': '使用了未知操作「{op}」',
    'wf.unnamed': '未命名工作流{i}',
    'wf.validation_error': '校验错误：{err}',
    'wf.visualize_done': '[可视化] 已渲染 {chart} 图表（{engine}），共 {n} 行',
    'wf.visualize_no_input': '没有上游数据，请连接数据源或文件上传节点',
    'wf.wf_exception': '工作流「{wf}」执行失败，完整堆栈见服务端日志',
    'wfHistory.badStrategy': '未知的自动排布策略：{strategy}',
    'wfHistory.baselineRequired': '按历史基准排布需要先指定一个快照',
    'wfHistory.corrupt': '画布快照 {id} 的内容已损坏，无法恢复',
    'wfHistory.full': '画布历史已满（{max} 份），请先删除旧快照再保存',
    'wfHistory.invalid': '这份画布状态存不下来：需要带 nodes 列表的对象',
    'wfHistory.labelTooLong': '快照名称超过 {n} 个字符',
    'wfHistory.missing': '没有这个画布快照：{id}',
    'wfHistory.unserializable': '画布里含有无法序列化的内容，不能存为快照',
    'wfHistory.workflowNameTooLong': '工作流名称超过 {n} 个字符',
    'wfHistory.workflowRequired': '请先保存工作流，再设置布局基准',
}

EN = {
    'engine.accumulate_bad_identity': 'Node {nid}: unknown duplicate policy {value}',
    'engine.accumulate_bad_parent': 'Node {nid}: upstream {up} is not a table node',
    'engine.accumulate_no_keys': 'Node {nid}: the named-columns policy needs key columns',
    'engine.accumulate_no_name': 'Node {nid}: the cumulative dataset node has no name',
    'engine.accumulate_one_parent': 'Node {nid}: a cumulative dataset node needs exactly one upstream',
    'engine.analysis_no_op': 'Node {nid}: analysis node has no operation/steps configured',
    'engine.biblio_multi_input': (
        '{nid} has {n} upstream connections: bibliometrics accepts one input; keep a single wire'
    ),
    'engine.biblio_no_input': '{nid} needs exactly one upstream data table (an Upload node)',
    'engine.comment_no_urls': 'Node {nid}: comment node has no article URLs yet',
    'engine.compile_bad_parent': (
        'Node {nid}: the compile node only accepts a visualize node’s LaTeX; upstream "{up}" is not one'
    ),
    'engine.compile_no_upstream': 'Node {nid}: the compile node has no incoming connection (it needs a visualize node)',
    'engine.compile_source_both_off': (
        'Node {nid}: the upstream visualize "{up}" has neither the LaTeX figure nor the three-line table box checked, '
        'so there is nothing to compile'
    ),
    'engine.cycle': 'the workflow contains a cycle; these nodes cannot be ordered: {nodes}',
    'engine.dangling_connection': 'a connection points at a node the canvas does not hold: {src} → {dst}',
    'engine.empty_canvas': 'the canvas holds no nodes, so there is no workflow to run',
    'engine.name_no_downstream': 'Node {nid}: the name node must connect to a downstream node',
    'engine.name_no_label': 'Node {nid}: the name node needs a workflow name',
    'engine.name_not_head': 'Node {nid}: the name node must lead — nothing may feed into it',
    'engine.output_needs_pdf': (
        'Node {nid}: the upstream is a visualize/compile node, so the output format must be PDF'
    ),
    'engine.output_no_op': 'Node {nid}: output node has no operation',
    'engine.output_no_table': (
        "Node {nid}: none of the output node's upstreams produces a table "
        '(a name node is metadata, a visualize node answers a chart spec)'
    ),
    'engine.output_no_upstream': 'Node {nid}: output node has no incoming connection, so there is no table to save',
    'engine.output_pdf_mixed': (
        'Node {nid}: a PDF output cannot mix with tabular upstreams — '
        'use only a visualize or compile node as the source'
    ),
    'engine.output_pdf_only_pdfable': 'Node {nid}: a PDF output must be fed by a visualize or compile node',
    'engine.output_pdf_two_sources': (
        'Node {nid}: a PDF output cannot take both a visualize node and a compile node — pick one'
    ),
    'engine.process_no_op': 'Node {nid}: process node has no operation',
    'engine.source_bad_backend': 'Node {nid}: the crawl backend "{backend}" does not exist — pick Selenium or CatBus',
    'engine.source_bad_option': 'Node {nid}: {field} has no option "{value}" — pick one of the choices in that node',
    'engine.source_catbus': 'Node {nid}: the CatBus engine cannot crawl this cell: {detail}',
    'engine.source_feed_no_column': (
        'Node {nid}: an upstream table is wired in but no column was named for {field} to read row by row'
    ),
    'engine.source_feed_no_input': (
        'Node {nid}: a fed column is named but this node has no data input wired (a name-label wire does not count)'
    ),
    'engine.source_feed_no_mode': (
        'Node {nid}: this collection mode cannot be fed from an upstream table — '
        'only link-list forms take a fed column; disconnect the wire or pick another mode'
    ),
    'engine.source_link_mismatch': 'Node {nid}: {n} link(s) do not match the selected platform ({platform})',
    'engine.source_missing': 'Node {nid}: the required field {field} is empty',
    'engine.source_needs_machine': (
        'Node {nid}: this machine cannot run that collection mode ({reason}) — choose another mode or '
        'run the canvas on a machine that can'
    ),
    'engine.source_no_cookie_account': (
        'Node {nid}: no cookie for the {platform} account "{account}" — save one in the Cookie panel, '
        'or pick an account that has a login (this never borrows another account and never '
        'silently under-collects)'
    ),
    'engine.source_no_platform': 'Node {nid}: source node has no platform',
    'engine.source_unknown_mode': 'Node {nid}: {platform} has no such collection mode — pick one under Collect',
    'engine.source_unknown_platform': 'Node {nid}: {platform} has no crawler yet — pick a supported platform',
    'engine.tokenize_no_column': 'Node {nid}: tokenize node is missing its text column',
    'engine.unknown_node_type': 'Node {nid}: unknown node type "{type}", the workflow engine cannot execute it',
    'engine.upload_no_file': 'Node {nid}: upload node has no file selected',
    'engine.visualize_no_chart': 'Node {nid}: visualize node has no chart type',
    'engine.visualize_no_x': 'Node {nid}: visualize node is missing the x field',
    'engine.watermarkRecrawl': 'Node {nid}: cross-run watermark and re-crawl cannot both be on',
    'engine.watermarkUnsupported': 'Node {nid}: cross-run watermark supports only Bilibili author uploads',
    'executor.task_failed': 'Task failed: {err}',
    'housekeeping.datasetStoreFailed': 'Automatic orphan-file cleanup failed (the run itself is unaffected)',
    # ── housekeeping ──────────────────────────────────────────
    'housekeeping.done': (
        'Housekeeping: dropped {runs} expired run record(s) and {files} orphaned file(s) '
        '(plus {cache} cached model answer(s) and {seen} stale dedupe key(s))'
    ),
    'housekeeping.runStoreFailed': 'Automatic run-record cleanup failed (the run itself is unaffected)',
    'latex.done': 'LaTeX figure written: {file}',
    'latex.failed': 'LaTeX generation failed: {reason}',
    'latex.table_done': 'LaTeX three-line table written: {file}',
    'node.accumulate': 'Cumulative dataset',
    'node.analysis': 'Analysis',
    'node.biblio': 'Bibliometrics',
    'node.comment': 'Comments',
    'node.compile': 'Compile',
    # ── node type labels (console fallbacks; mirror frontend app.js) ──
    'node.name': 'Workflow Name',
    'node.output': 'Output',
    'node.process': 'Process',
    'node.resume': 'Resume Run',
    'node.source': 'Data Source',
    'node.tokenize': 'Tokenize',
    'node.upload': 'Upload File',
    'node.visualize': 'Visualize',
    'project.badEntry': 'The bundle contains a file path this importer does not accept: {file}',
    'project.badFormat': 'This is not a CaiXiHui project bundle',
    'project.badJson': 'A JSON file inside the bundle cannot be read: {file}',
    'project.badManifest': 'The bundle manifest is missing a list: {section}',
    'project.badVersion': 'Unsupported project bundle version: {version}',
    'project.badZip': 'The project bundle is not a valid zip file',
    'project.checksum': 'A bundle file failed its checksum: {file}',
    'project.datasetInvalid': 'A dataset inside the bundle cannot be read: {id}',
    'project.datasetMissing': 'A dataset the workflow reads does not exist: {id}',
    'project.datasetRefMissing': 'A dataset the workflow reads is not in the bundle: {id}',
    'project.datasetTooLarge': 'Dataset {id} exceeds {max} rows',
    'project.entryMissing': 'The bundle is missing a file: {file}',
    'project.fileTooLarge': 'A file inside the bundle is too large: {file} (limit {mb} MB)',
    'project.lineageInvalid': 'The bundle’s cumulative-dataset information cannot be read',
    'project.lineageMissing': 'A referenced cumulative dataset is missing and was skipped: {name}',
    'project.noFile': 'Choose a project bundle file first',
    'project.noWorkflow': 'Save a workflow before exporting a project bundle',
    'project.noWorkflowInBundle': 'The project bundle contains no workflow',
    'project.templateInvalid': 'A reusable template cannot be imported: {name}',
    'project.templateMissing': 'A referenced reusable template is missing and was skipped: {id}',
    'project.templateRefMissing': (
        'Workflow “{name}” references a template not in the bundle: {id} (its instance snapshot still works)'
    ),
    'project.tooLarge': 'The project bundle expands beyond {mb} MB',
    'project.tooMany': 'The bundle contains too many {section} (limit {max})',
    'project.tooManyEntries': 'The project bundle has too many entries (limit {max})',
    'project.workflowInvalid': 'A workflow inside the bundle cannot be read: {name}',
    'project.workflowUnreadable': 'The workflow file cannot be read: {name}',
    'report.chart_failed': 'Chart rendering failed: {err}',
    'report.charts': 'Charts',
    'report.chartsFailed': 'the report charts failed; its text and tables still came out',
    'report.conclusion': 'Conclusion',
    'report.default_title': '{name} · run report',
    'report.fact.finished': 'Finished',
    'report.fact.run': 'Run id',
    'report.fact.started': 'Started',
    'report.fact.status': 'Status',
    'report.fact.workflow': 'Workflow',
    'report.figure_section': 'Figures and tables',
    # ── one-click HTML report ───────────────────────────────────
    'report.generated': 'Generated',
    'report.latex_no_run': 'That run cannot be found ({rid}), so there is nothing to assemble.',
    'report.latex_no_sources': 'This run filed no LaTeX figure or table sources, so there is no document to build: '
    'tick "生成 LaTeX" on the visualize nodes and run it again.',
    'report.method_analysis': '{title}: analysis steps {ops}.',
    'report.method_biblio': "{title}: {entity} as the unit of analysis. Parameters (this system's own enum names, "
    'identical to the run record and the exported tables): {body}.',
    'report.method_counts': '{figures} figures and {tables} three-line tables; each figure and its table come from '
    'the same table of rows the run filed.',
    'report.method_fuse': '{title}: folded several upstream tables into one canonical record table (each role tried '
    'against its candidate columns in order).',
    'report.method_no_canvas': 'This run has no saved canvas to read, so the document gives the run id and the time '
    'window only, with no parameters; save the canvas and run it again for a method section.',
    'report.method_provenance': 'This document was assembled from one run of workflow "{workflow}", run id {run_id}.',
    'report.method_section': 'Method',
    'report.method_source': '{title}: collected {collect} from {platform}, target {target} items.',
    'report.method_unverified': "These nodes' parameters could not be checked against the fingerprints the run "
    'recorded (the canvas changed, or its file is gone): {names}.',
    'report.method_upload': '{title}: dataset {name}.',
    'report.method_window': 'Run window: {started} to {finished}.',
    'report.missing_charts': '{count} chart node(s) filed no LaTeX source, so this document holds no figure or '
    'table for them: {names}.',
    'report.more_rows': 'First {shown} of {total} rows shown; export the table as CSV for the rest.',
    'report.no_charts': 'Nothing in these tables was chartable yet.',
    'report.no_rows': 'this node produced no rows',
    'report.row_count': '{n} rows · {cols} columns',
    'report.run_facts': 'Run details',
    'report.summary': 'This run had {nodes} node(s) and produced {rows} row(s); {tables} of them hold a table.',
    'report.table_continued': ' (continued)',
    'report.table_suffix': ' (three-line table)',
    'report.tables': 'Tables',
    'resume.empty': 'Resume node: "{nid}" of run {rid} has no stored rows',
    'resume.loaded': 'Resume node: loaded {n} rows from node {nid} of run {rid}',
    'resume.no_run': 'Resume node: no run selected, and no resumable run was found',
    'resume.unpicked': 'no node picked',
    'reusable.badConnection': 'A wire does not join two template nodes: {a} → {b}',
    'reusable.badConnections': 'The template connections could not be read',
    'reusable.badId': 'The reusable template id is malformed: {id}',
    'reusable.badInput': 'An input slot names a node that is not in the template: {id}',
    'reusable.badInputs': 'The template input list could not be read',
    'reusable.badNode': 'The template contains a node this build cannot read',
    'reusable.badNodeId': 'A node id is missing or repeated: {id}',
    'reusable.badNodeParams': 'Node {id} params are not an object',
    'reusable.badNodeType': 'Node {id} has a type a reusable node cannot hold: {type}',
    'reusable.badOutput': 'An output slot names a node that is not in the template: {id}',
    'reusable.badOutputs': 'The template output list could not be read',
    'reusable.badTemplate': 'Reusable node “{name}” cannot be expanded (a node type or wire is not accepted)',
    'reusable.corrupt': 'Reusable template {id} is unreadable',
    'reusable.cycle': 'The template contains a cycle and cannot run in order',
    'reusable.descriptionTooLong': 'The template description is longer than {n} characters',
    'reusable.full': 'Reusable templates are full ({max}); delete old ones first',
    'reusable.invalid': 'The reusable template could not be read',
    'reusable.missing': 'No reusable template with that id: {id}',
    'reusable.missingInputs': 'Reusable node “{name}” needs {n} input(s), but only {wired} are wired',
    'reusable.nameRequired': 'A reusable node needs a name',
    'reusable.nameTaken': 'A reusable template named “{name}” already exists',
    'reusable.nameTooLong': 'The template name is longer than {n} characters',
    'reusable.noNodes': 'A reusable node needs at least one node',
    'reusable.noTemplateForRun': 'Reusable node “{name}” has no template to run',
    'reusable.oneOutput': 'A reusable node must have exactly one output node ({n} now)',
    'reusable.outputHasNext': 'Output node {id} still has a successor; choose the real terminal node',
    'reusable.tooManyInputs': 'Reusable node “{name}” has more incoming wires than input slots',
    'reusable.tooManyNodes': 'A reusable node can hold at most {n} nodes',
    'run.browserReapFailed': (
        'the browser process still did not die after the stop timeout (PID {pid}): {err} — its profile '
        'directory stays claimed, so the next crawl of that platform waits for the lock to time out'
    ),
    # Said out loud because the alternative is silence that reads as "closed", while the
    # user may be looking at the window that is still open.
    'run.browserStuck': (
        'warning: {platform}\u2019s browser could not be closed (no readable process id); it may still be '
        'open and holds that platform\u2019s directory for up to {seconds} seconds'
    ),
    'run.claims_released': (
        'Rerun: handed back {n} "already crawled" claim(s) for run {rid} — those items will be crawled again'
    ),
    'run.cleared': 'Run records cleared: {runs} removed, and {claims} "already crawled" claims handed back',
    'run.commentsSkipped': (
        '{platform}: {n} drama(s) were not harvested completely (never opened in the player, or the feed '
        'moved to another drama mid-walk): {names} — the other dramas’ rows are kept; Resume re-walks from '
        'the first incomplete one (comments already stored are deduped by 评论ID, so nothing double-stores)'
    ),
    'run.compileFailed': 'LaTeX compilation failed: {err}',
    'run.compileSaved': 'PDF compiled: {name} ({size} bytes)',
    'run.cookieAnyPlatform': 'the platform being crawled',
    'run.cookieExpired': (
        'login session looks expired: the {platform} crawl was bounced to a login page '
        '(the cookie may have gone stale). Everything collected so far is kept — refresh '
        'the cookie under Settings -> Cookie, then resume the run from its checkpoint'
    ),
    'run.cookieExpiredOk': (
        'note: {platform} hit the login wall only after the target was met — the data is complete, nothing to resume'
    ),
    'run.dedupe_all_skipped': (
        'every item of this node was already collected — nothing new flows downstream; '
        'enable Recrawl on the source node to re-collect, or reach the stored rows through '
        'the run records / a Resume node'
    ),
    'run.dedupe_skipped': (
        'Incremental: {n} already-collected items were skipped (enable Recrawl on the source node to re-collect)'
    ),
    'run.failed_down': 'Node {nid} failed with nothing usable — downstream sees an empty table',
    'run.finished': 'Run finished ({done}/{total} nodes)',
    'run.finished.failed': ', {n} failed',
    'run.finished.skipped': ', {n} skipped',
    'run.finished.stopped': ', {n} stopped',
    'run.heavy_result': (
        'Memory note: node "{nid}" produced {n} rows, and every node\'s rows are held in memory until the run ends'
    ),
    'run.interrupted_by_dead_worker': 'Its worker thread is gone, so the record was settled as interrupted',
    'run.interrupted_by_restart': 'Interrupted by a service restart',
    'run.live_export': 'live export: {file} (rewritten after every batch; kept when the run ends)',
    'run.live_export_failed': 'live export write failed: {err}',
    'run.nodeStopped': 'Node {nid} ended on Stop: {n} row(s) kept',
    'run.notCrawlable': (
        'the platform behind "{label}" ({platform}) can store a login cookie but has no crawler yet, so it cannot '
        'run as a data source — pick a supported platform, or wait for this one to land'
    ),
    # A page that never arrived, said once with the one thing the crawler cannot know:
    # whether this machine can reach anything at all. ``{advice}`` is empty when the page
    # already named its own cause, so the sentence has to read in both shapes.
    'run.pagePending': '{page}{streak}{advice}',
    'run.pageStreak': '; this is the {n}th page in a row this machine has not delivered',
    'run.partial_down': 'Node {nid} interrupted — its {n} finished rows are handed downstream',
    'run.platformGateTimeout': (
        '{platform} waited {n}s for its turn to crawl and gave up: a browser window that never closed may be holding it'
    ),
    'run.platformQueued': (
        '{platform} is being crawled by another workflow, so this one queued and starts in {n}s: two '
        'searches from one account in the same second are what gets bounced to the login page'
    ),
    'run.platformStaggered': (
        '{platform} starts {n}s after the last same-platform crawl: this one queued behind nothing, so '
        'the two may still overlap — only their departures are kept apart, which is what stops one '
        'account issuing two searches in the same second'
    ),
    'run.profileOff': (
        'this run uses no browser profile: every crawl is a brand-new device (so same-platform workflows '
        'really do run side by side), and the saved cookie snapshot is planted as usual'
    ),
    'run.progress_file': 'progress export: {file} ({rows} rows in {parts} part files)',
    'run.promoted': '{n} unfinished run(s) from an earlier session marked resumable',
    'run.queueAbandoned': 'the queue wait for {platform} was cancelled (this run stopped)',
    'run.queueLoadFailed': 'failed to load the persisted run queue at startup (starting from an empty queue)',
    'run.queueMirrorFailed': 'failed to mirror the waiting-run queue (the in-memory queue is still authoritative)',
    'run.queueStartFailed': 'a queued run could not be started',
    'run.queue_broken': 'the queued request {name} could not start; skipped, the next one continues: {err}',
    'run.queue_restored': 'Restored {n} waiting run(s) after a restart',
    'run.queue_started': 'Queue: {name} started ({rid})',
    'run.queue_waited': 'Queue could not start {name} (a run is active), it waits again',
    'run.queued': 'Queued (position {at}): {name}',
    'run.queuedUnnamed': 'an unnamed workflow',
    'run.reconciled': '{n} record(s) whose worker had already gone were settled as interrupted',
    'run.recordWriteFailed': (
        'Could not write the verdict for record {rid} ({err}): the run list settles it on the next refresh'
    ),
    'run.recrawl': 'Re-crawl: released {n} dedupe records; this node will collect again',
    'run.rejected': 'Nothing ran: the workflow has {n} problem(s), see the messages above',
    'run.reportConclusionFailed': 'The conclusion could not be generated, so the report omits it: {err}',
    'run.reportFailed': 'Report failed: {err}',
    'run.reportLatexFailed': 'Paper document failed: {err}',
    'run.reportLatexSaved': 'Paper document compiled: {name} ({figures} figures / {tables} tables)',
    'run.reportSaved': 'Report written: {name} ({size} bytes)',
    'run.restored': 'Node {nid} reuses its previous result ({n} rows) instead of running again',
    'run.resume_crawl': 'Node {nid} continues crawling from where it stopped ({have} rows already saved)',
    'run.resume_from': 'Resuming the run interrupted at {at} — {rows} rows already stored',
    # A 风控 refusal is the OPPOSITE advice from a dead cookie: the session may be fine and
    # re-running straight into it only deepens the block, so the console names risk control,
    # says it is not a login problem, and tells the user to wait (继续 later), never re-save.
    'run.riskControlled': (
        '{platform} was stopped by a security check (risk control) before the target was met — this is NOT an expired '
        'login, and re-running immediately only deepens the block. Everything collected so far is kept; you can enable '
        'Settings -> Gentle crawling, then use 继续 / Resume later to pick up from the checkpoint'
    ),
    # ── resumable runs ────────────────────────────────────────
    'run.row_limit': 'Node {nid} hit its {limit}-row safety cap — further rows are not stored',
    'run.serialForced': (
        '{platform} crawls are forced to run one at a time: parallel paging on one account always draws the '
        "login wall, so this platform serializes by the site's rule, not by the 错峰 setting"
    ),
    'run.skippedWorkflows': 'skipped this run (disabled, will not run): {names}',
    'run.skipped_empty': 'Node {nid} skipped: no data arrived from upstream',
    'run.start_failed': 'Could not start the run worker ({err}): this run is dropped and the queue moves to the next',
    'run.started': 'This run is checkpointed as {rid} — every row lands in the database as it is produced',
    'run.store_unavailable': 'this run could not begin: the run record store would not open (disk full, corrupt or '
    'locked file) — nothing was recorded',
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
    'run.wallRetry': (
        '{platform} was bounced to its login page before its first row, which reads as two concurrent '
        'searches from one account colliding: retrying once in {n}s'
    ),
    'run.watermarkFirst': 'Cross-run watermark: first run; the boundary is saved on success',
    'run.watermarkLoaded': (
        'Cross-run watermark: starting from the previous boundary {boundary}; stop when it is reached'
    ),
    'run.watermarkNoNew': 'Reached the previous boundary {boundary}; no newer items this run',
    'run.watermarkNoScope': (
        'A cross-run watermark needs the node fingerprint from a run context; a direct executor call cannot enable it'
    ),
    'run.watermarkSaved': 'Cross-run watermark updated: {boundary} ({n} new rows this run)',
    'run.watermarkUnsupported': (
        'Cross-run watermark supports only Bilibili author uploads (this platform/mode: {platform} / {mode})'
    ),
    'upload.loaded': 'Loaded uploaded file {name}: {n} rows',
    # ── upload node ───────────────────────────────────────────
    'upload.no_file': 'Upload node has no file yet — upload a CSV / JSON / TXT in its settings',
    'upload.stale': 'That uploaded dataset is gone (the server may have restarted) — upload the file again',
    'wf.analysis_llm_no_model': (
        'the 主题概括 step needs a model, and this run has none (Settings → model, or the node model box)'
    ),
    # Stated as the reason only: the executor prints these as the node's own
    # failure (「Node X failed: …」), so a "Tokenize failed:" prefix inside them
    # repeats the wrapper, and the pair used to print the same sentence twice —
    # once here with no node named, once attributed.
    'wf.analysis_step': '[Analysis] {op}: {before} -> {after} rows',
    'wf.analysis_step_nochange': ' (no change)',
    'wf.analysis_step_removed': ' (-{removed})',
    'wf.analysis_steps_shape': '"steps" must be a LIST of steps (one object each), and this is a single object',
    'wf.browser_opened': 'Browser opened for {platform} login ({url}); waiting {n}s for the user to log in',
    'wf.compile_no_source': (
        'The compile node has no LaTeX to compile (its upstream visualize produced neither a figure nor a table)'
    ),
    'wf.component_indexed': '{name} (component {i} of {n})',
    'wf.cookies_generated': 'Cookies generated for {platform} ({n} cookies)',
    # No 'wf.completed' / 'wf.all_completed' here either: see the zh block.
    # One line per failure, and it says where the detail is: the log handler
    # forwards every logger call to the console, so the pair of messages this
    # replaced printed the same sentence twice.
    'wf.exec_exception': 'Execution failed — the traceback is in the server log',
    # ── workflow ──────────────────────────────────────────────
    'wf.executing_node': '[{wf}] Executing node: {nid} ({ntype})',
    'wf.found': 'Found {n} workflow(s)',
    'wf.join_no_right_table': 'A join needs two incoming connections (left table first, right table second)',
    'wf.merge_columns': (
        'Node {nid}: the upstream tables have different columns, compared with "{up}": extra [{extra}], '
        'missing [{missing}]. Not merged as an outer join — that fabricates empty cells and the file looks complete'
    ),
    'wf.merge_detail_sep': ', ',
    'wf.merge_done': 'Node {nid} merged {tables} upstream tables → {n} rows ({detail})',
    'wf.merge_not_tabular': (
        'Node {nid}: upstream "{up}" produces no table (a chart spec or a refusal), so it cannot be merged — '
        'disconnect that wire or point it at a node that carries rows'
    ),
    'wf.merge_table_detail': '{name} {n} rows',
    'wf.multi_input': (
        'Node {nid} has {n} incoming connections — the first (from {up}) is the primary input; '
        'an analysis node uses the second as its right-hand table, and an output node merges them all into one'
    ),
    'wf.node_completed': '[{wf}] Node {nid} completed ({done}/{total})',
    'wf.node_failed': '[{wf}] Node {nid} failed: {err}',
    'wf.starting': 'Starting workflow "{name}"',
    'wf.tokenize_done': '[Tokenize] {mode} segmented {col} -> {n} rows',
    'wf.tokenize_no_col': 'column "{col}" not found in {cols}',
    'wf.tokenize_no_column': 'no text column is configured for tokenizing',
    'wf.tokenize_no_input': 'no upstream data — connect a data source or an upload node',
    'wf.unknown_process_op': 'unknown process operation "{op}"',
    'wf.unnamed': 'Unnamed workflow {i}',
    'wf.validation_error': 'Validation error: {err}',
    'wf.visualize_done': '[Visualize] Rendered {chart} chart ({engine}) from {n} rows',
    'wf.visualize_no_input': 'no upstream data — connect a data source or an upload node',
    'wf.wf_exception': 'Workflow "{wf}" failed — the traceback is in the server log',
    'wfHistory.badStrategy': 'Unknown auto-layout strategy: {strategy}',
    'wfHistory.baselineRequired': 'A baseline snapshot is required for baseline layout',
    'wfHistory.corrupt': 'Canvas snapshot {id} is unreadable and cannot be restored',
    'wfHistory.full': 'Canvas history is full ({max} snapshots) — delete older snapshots before saving another',
    'wfHistory.invalid': 'That canvas state cannot be stored: an object with a nodes list is required',
    'wfHistory.labelTooLong': 'The snapshot name is longer than {n} characters',
    'wfHistory.missing': 'No canvas snapshot with that id: {id}',
    'wfHistory.unserializable': 'The canvas contains something that cannot be serialized, so no snapshot was stored',
    'wfHistory.workflowNameTooLong': 'The workflow name is longer than {n} characters',
    'wfHistory.workflowRequired': 'Save the workflow before choosing a layout baseline',
}
