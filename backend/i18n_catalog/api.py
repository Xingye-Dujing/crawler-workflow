"""HTTP answers: request coercions, refusals that name the bad part, exports, datasets and the
durable ledger.

Part of the zh/en message catalogue, merged by ``backend/i18n.py`` — the ``t()`` machinery,
the thread-local language and the audit live there, so this module is data with no imports.
Keys are sorted; the two tables in here must hold the same set (``tests/unit/i18n/test_i18n.py``).
"""

ZH = {
    'api.alreadyRunning': '已有工作流正在运行，请先停止或等它跑完',
    'api.foreignRun': '当前的运行属于另一个账号，不能查看或停止它',
    'api.badAccount': '账号名不合法：{account}（字母、数字、下划线或连字符，1-24 个；统一按小写保存）',
    'api.badRequest': '请求格式不对：{what}',
    'api.biblioDecode': '无法解码文件 {name}（已尝试 UTF-8 与 GB18030）',
    'api.biblioEmpty': '无法从 {format} 文件中解析出任何文献记录',
    'api.biblioLensPatent': '这是 Lens 的专利库导出（列里有 Jurisdiction、Inventors、Application Number），'
    '不是学术文献。文献计量网络按学术文献建模，把发明人与申请人当作者画出来只会得到一张错图；'
    '请在 Lens 里改选文献（非专利）集合后重新导出',
    'api.biblioNotRecognized': '无法把 {name} 识别为任何已支持的文献导出格式',
    'api.bodyNotObject': '请求体必须是 JSON 对象',
    'api.cloudNoLocalModel': (
        '这台服务器没有本地模型可连（「{provider}」需要宿主自己跑一个 Ollama 守护进程）：'
        '云端部署只支持 OpenRouter，请在「设置 → AI」里改选 OpenRouter 并填入模型与 API Key'
    ),
    'api.cloudNoLoginWindow': (
        '这台服务器没有可以登录的窗口：请在「Cookie」面板里粘贴 Cookies JSON 保存，'
        '系统会在保存时替该账号建好 Profile 并种进去'
    ),
    'api.columnMissing': '数据里没有这一列：{column}',
    'api.compilePdfFailed': 'LaTeX 编译为 PDF 失败：{err}',
    'api.compilePdfNoFont': 'LaTeX 找不到字体 {font}：{remedy}',
    'api.compilePdfNoPackage': 'LaTeX 缺宏包 {package}.sty：{remedy}',
    'api.cookieBusy': '已有 {platform} 的登录窗口打开中——请先完成或取消它',
    'api.cookieRenameBadName': '新名字不合法：字母、数字、下划线或连字符，1-24 个（统一按小写保存）',
    'api.cookieRenameBusy': '这个账号的浏览器正在被占用，请等当前采集结束后再改名',
    'api.cookieRenameDefault': '默认账号不能改名：它的浏览器目录就是该平台目录本身，其它账号都装在里面',
    'api.cookieRenameEmptyTarget': '新名字不能留空',
    'api.cookieRenameFailed': '改名失败：{err}',
    'api.cookieRenameNoSource': '这个账号没有已保存的登录，改不了名',
    'api.cookieRenameSameName': '新旧名字一样，没有改任何东西',
    'api.cookieRenameTaken': '这个名字已经有另一份登录了，换一个个别的名字',
    'api.cookiesRequired': 'Cookies 数据不能为空',
    'api.datasetInLineage': (
        '这份文件是累积数据集「{name}」的当前版本；删除会让累积历史断开（强制删除会同时重置该累积集）'
    ),
    'api.datasetInUse': '这些已保存的工作流仍在引用该文件，删除后它们会变成空数据源：{workflows}',
    'api.datasetMissing': '没有这个已保存的数据集：{did}',
    'api.datasetNameInvalid': '这个名称不能用作数据集名（去掉路径字符后为空）：{name}',
    'api.datasetTooBig': '文件太大没法存：{err}',
    'api.diffKeyMissing': '对比键「{name}」不是两份表都有的列，无法据此匹配行',
    'api.diffKeyNotUnique': '对比键「{name}」在某份表里有重复值，无法唯一对应每一行',
    'api.diffTwoSources': '对比需要两个数据源（"a" 与 "b"），每个是 dataset_id 或 node_id+workflow_name 或内联 data',
    'api.excelMultiSheet': '工作簿「{name}」有多个非空工作表（{sheets}），一次只能导入一张表，请先拆成单个表再上传',
    'api.exportNotFound': '导出文件不存在（或不允许下载）：{name}',
    'api.fieldTypeInvalid': '字段 {name} 类型不正确',
    'api.foreignOriginRefused': '本站只服务本机浏览器：这个请求来自「{origin}」，未鉴权又握着真实账号，故拒绝',
    'api.historyNoRunId': '没有指定运行 ID，未删除任何执行历史',
    'api.killDone': '线程「{name}」已结束',
    'api.killFailedGeneric': '结束线程失败',
    'api.killInvalidId': '无效的线程 ID',
    'api.killLiveWorker': '这是正在运行的采集线程，请点「停止」而不是强杀它',
    'api.killNoIdent': '没有给出线程 ID',
    'api.killNotAlive': '该线程已不存活',
    'api.killNotFound': '找不到该线程',
    'api.killProtected': '不能结束受保护的线程：{name}',
    'api.lineageMissing': '没有这个累积数据集：{name}',
    'api.llmModelsFailed': '获取 OpenRouter 模型列表失败：{err}',
    'api.needApiKey': 'OpenRouter API Key 未填写（设置 → AI）',
    'api.needConfirm': '这个操作会动到全部记录，请把 confirm 显式设为 true 再来',
    'api.needLabeledRows': '至少需要 10 行带标签的数据，当前只有 {n} 行',
    'api.needModel': 'OpenRouter 模型未选择（设置 → AI）',
    'api.needOllamaModel': '未选择 Ollama 模型（设置 → AI → 模型，可点“刷新”读取本地模型）',
    'api.noCookieJob': '当前没有进行中的登录窗口',
    'api.noSourceTable': '所选节点都没有可用的数据表',
    'api.ollamaModelsFailed': '读取本地 Ollama 模型列表失败：{host}（请确认 ollama 已启动、服务地址正确）：{err}',
    'api.paramInvalid': '参数 {name} 无效',
    'api.parseFailed': '文件解析失败：{err}',
    'api.payloadTooLarge': '请求体超过上限 {limit} MB，请分割后重试',
    'api.pdfMissingFile': 'PDF 生成被拒：台账记着 {name}，但导出目录里已找不到它（可能被清除）',
    'api.pdfNeedsName': 'PDF 生成被拒：请给出该图已登记的 LaTeX 文件名',
    'api.pdfUnregistered': 'PDF 生成被拒：{name} 不在运行台账里，本程序没写过这个文件，不交给 xelatex 编译',
    'api.pdfWrongKind': 'PDF 生成被拒：{kind} 不是 LaTeX 源文件，只有本程序登记的 .txt 图源可以编译',
    'api.platformRequired': '平台不能为空',
    'api.platformsRequired': 'platforms 字段必须是平台名列表',
    'api.profileDeleteBadName': '账号名不合法，无法定位要删除的 Profile：{account}',
    'api.profileDeleteBusy': '{platform} · {account} 的浏览器正在被占用，请等当前采集结束后再删除它的 Profile',
    'api.profileDeleteDefault': '默认账号没有可删除的浏览器 Profile：它的数据就是平台目录本身，其它账号都在里面',
    'api.queueFull': '排队已满（最多 {n} 个），请等当前运行结束或先取消几个',
    # ── 运行队列 ──────────────────────────────────────────────
    'api.queued': '已排队：当前运行结束后自动开始（第 {at} 位）',
    'api.reportNoData': '没有可写入报告的数据：请先运行一次工作流，或选择一条运行记录',
    'api.rerunBusy': '另一个运行仍在进行中：重跑会先删掉这部分已存结果，请等它跑完再重试',
    'api.rerunFingerprintMismatch': '画布与所选运行记录不是同一份工作流，无法复用其结果，请从运行详情重跑该节点',
    'api.rerunNoNode': '当前画布里没有节点「{node}」，无从重跑',
    'api.rerunNoRows': '节点「{node}」在上次运行里没有可用的完成结果，无从重跑',
    'api.rerunNoRun': '找不到这个工作流已保存的运行结果，无法从该节点重跑（请先运行一次）',
    'api.rerunRunLive': '该运行仍在进行中（或正在停止），不能重跑它的节点——请等它跑完或先停止它',
    'api.resumeMissing': '无法继续：运行记录 {rid} 已被清理，继续会变成一次全新的从零采集，请改用「重新运行」',
    'api.runLogTruncated': '（日志过长，仅下载前 {n} 行）',
    'api.runNotFound': '找不到运行记录：{rid}',
    'api.runSettingOption': '画布设置里的「{setting}」没有「{value}」这个取值（可用：{allowed}）',
    'api.stepsMustBeObjects': 'steps 必须是对象列表，每项含 "op" 与可选 "params"',
    'api.svgNotSvg': 'SVG 保存被拒：内容不是以 <svg 开头或缺少 xmlns 声明',
    'api.svgRefused': 'SVG 保存被拒：图中含有 {found}，这类标记可能带脚本或外部引用',
    'api.svgTooLarge': 'SVG 保存被拒：内容 {cap} 字节已是上限，这不像是画出来的图',
    'api.svgTruncated': 'SVG 保存被拒：文件没有以 </svg> 结束（可能被截断）',
    'api.unsupportedPlatform': '不支持的平台：{platform}',
    'api.unsupportedUpload': '不支持的文件类型：{name}（可用 .csv .tsv .json .txt .xlsx .xls）',
    'api.workflowMissing': '没有这个已保存的工作流：{name}',
    'api.workflowNameRequired': '缺少有效的工作流名称',
    'api.workflowNameSame': '新旧名字是同一个文件，没有可重命名的东西',
    'api.workflowNameTaken': '已有同名工作流「{name}」，重命名会覆盖它，请换一个名字',
    'api.workflowNodeNoId': (
        '画布上有一个节点没有 id，无法运行（id 是节点的存储键）——请重新拖入该节点，或修复工作流文件'
    ),
    'api.workflowRenamed': '工作流已重命名：{old} → {new}',
    'api.workflowShapeInvalid': '工作流内容无法理解：需要带 nodes 列表的对象',
    'auth.badCredentials': '账号或密码不正确',
    'auth.loginHint': '这台服务器上保存着采集登录态、数据集与运行记录，登录后才能访问。',
    'auth.loginNeedsSecretKey': (
        '启用登录后必须设置 SECRET_KEY（现在还是仓库里的默认值）：会话 Cookie 用它签名，'
        '密钥公开等于任何人都能伪造一个已登录的会话'
    ),
    'auth.loginTitle': '登录',
    'auth.password': '密码',
    'auth.required': '需要先登录',
    'auth.signIn': '登录',
    'auth.username': '账号',
    'compare.nodeMissing': '运行 {rid} 里没有节点 {node}',
    'compare.runMissing': '没有这次运行：{rid}',
    'compare.sameRun': '不能拿一次运行和它自己对比',
    'compare.tooManyRows': '节点 {node} 的数据超过 {max} 行，无法对比',
    'data.mergeColumns': '数据集「{name}」的列与第一份不一致：多出 {extra}；缺少 {missing}',
    'data.mergeMissing': '要合并的数据集不存在：{id}',
    'data.mergeNameRequired': '合并结果需要一个名字',
    'data.mergeNameTooLong': '合并结果的名字超过 {n} 个字符',
    'data.mergeNeedTwo': '合并至少需要两个数据集',
    'data.mergeTooLarge': '合并后共 {n} 行，超过上限 {max}',
    'ds.clearBusy': '正在运行的那次可能正在读取这些数据集，请先停止或等它跑完再清空',
    'ds.cleared': '已清空全部已保存文件：{n} 个',
    'ds.corrupt': '数据集 {did} 读不出来（记录已损坏），请重新上传',
    'ds.lineage_columns': '累积数据集「{name}」的列与已有版本不一致：多出 {extra}；缺少 {missing}',
    'ds.lineage_current_missing': '累积数据集「{name}」的当前版本 {id} 不存在',
    'ds.lineage_identity': '未知的去重方式：{value}（只能是整行或指定列）',
    'ds.lineage_key_missing': '去重列不在表中：{cols}',
    'ds.lineage_keys_required': '按列去重时必须填写去重列',
    'ds.lineage_missing_dataset': '导入累积数据集时找不到数据集 {id}',
    'ds.lineage_name_required': '累积数据集需要一个名字',
    'ds.lineage_too_large': '累积数据集「{name}」将达 {n} 行，超过上限 {max}',
    'ds.missing': '工作流引用的上传文件已不在库中：{name}',
    'ds.purge_result': '清理孤立文件 {n} 个，保留 {kept} 个仍在使用的文件',
    'ds.purged': '已清理 {days} 天未使用且无工作流引用的文件：{n} 个',
    'ds.rebound': '按文件名重新接上数据集 {name}（{did}）——工作流可以直接跑了',
    'ds.too_many_rows': '文件共 {n} 行，超过数据集上限 {limit} 行，无法保存',
    # ── analysis / services ───────────────────────────────────
    'export.done': '已导出 {n} 行至 {path}（{fmt}）',
    'export.parquet_engine_missing': '导出 Parquet 需要列式引擎 pyarrow，请先安装：pip install pyarrow',
    'export.window_ignored': '节点 {nid}：结果文件照常生成，仅「文件名追加时间范围」被忽略——{reason}',
    'export.window_many': '文件名要求带时间范围，但这条链路上有 {n} 个不同的时间窗，一个文件说不清它装的是哪一段',
    # 「文件名带时间范围」 asks the save node to print a window it cannot see: the crawl
    # states it, this node receives a table. Both answers name the reason instead of
    # inventing a range, because a file labelled with the wrong month is worse than one
    # that was never written.
    'export.window_none': '文件名要求带时间范围，但这条链路上没有任何采集节点声明开始/结束时间',
    'exports.clearBusy': '正在运行的那次会把分片文件写进导出目录，请先停止或等它跑完再清空',
    'exports.cleared': '已清空导出目录：删除 {n} 个文件',
    'exports.notAPart': '「{name}」不是分片文件（形如 名称.part000.csv），无法按名字清除它这一批',
    'history.cleared': '执行历史已清空',
    'history.recorded': '「{wf}」已记录 {n} 条历史指标',
    'history.run_deleted': '执行历史：删除运行 {rid} 的 {n} 条记录',
    'lock.badKey': '锁定请求缺少有效的面板或条目名',
    'lock.refuse': '这一项已被锁定，请先解锁再删除/清空它',
    'store.dataset_saved': '文件已持久化：{name}（{rows} 行，id {did}）',
    'store.datasets_bound': '工作流 {wf} 已绑定 {n} 个上传文件',
    'store.workflow_saved': '工作流已保存：{path}',
}

EN = {
    'api.alreadyRunning': 'A workflow is already running — stop it or wait for it to finish',
    'api.foreignRun': 'The current run belongs to another account; it cannot be inspected or stopped here',
    'api.badAccount': (
        'Invalid account name: {account} (letters, digits, _ and -, 1-24 of them; case does not '
        'make a second account — names are stored lowercase)'
    ),
    'api.badRequest': 'Malformed request: {what}',
    'api.biblioDecode': 'Could not decode {name} (tried UTF-8 and GB18030)',
    'api.biblioEmpty': 'No bibliographic records could be parsed from the {format} file',
    'api.biblioLensPatent': 'This is a Lens PATENT export (its columns include Jurisdiction, Inventors and Application '
    'Number), not scholarly records. The bibliometric network models publications, so drawing '
    'inventors and applicants as authors would only produce a wrong figure',
    'api.biblioNotRecognized': 'Could not recognize {name} as any supported bibliographic export',
    'api.bodyNotObject': 'request body must be a JSON object',
    'api.cloudNoLocalModel': (
        'This server has no local model to talk to ("{provider}" wants an Ollama daemon on its own '
        'host): a cloud deployment only supports OpenRouter — pick OpenRouter under Settings → AI and '
        'fill in the model and API key'
    ),
    'api.cloudNoLoginWindow': (
        'This server has no window to log into: paste the Cookies JSON into the Cookie panel and save, '
        "which builds that account's profile and plants the session into it"
    ),
    'api.columnMissing': 'No such column in the data: {column}',
    'api.compilePdfFailed': 'LaTeX to PDF compilation failed: {err}',
    'api.compilePdfNoFont': 'LaTeX cannot find the font {font}: {remedy}',
    'api.compilePdfNoPackage': 'LaTeX is missing the package {package}.sty: {remedy}',
    'api.cookieBusy': 'A {platform} login window is already open — finish or cancel it first',
    'api.cookieRenameBadName': (
        'Invalid new name: letters, digits, _ and -, 1-24 of them (case does not make a second '
        'account — names are stored lowercase)'
    ),
    'api.cookieRenameBusy': 'That account’s browser is in use; rename it after the current crawl ends',
    'api.cookieRenameDefault': (
        'The default account cannot be renamed: its browser directory IS the platform’s '
        'directory, with every other account inside it'
    ),
    'api.cookieRenameEmptyTarget': 'The new name cannot be blank',
    'api.cookieRenameFailed': 'Renaming failed: {err}',
    'api.cookieRenameNoSource': 'That account has no saved login to rename',
    'api.cookieRenameSameName': 'The old and new names are the same, so nothing was renamed',
    'api.cookieRenameTaken': 'Another login already uses that name — pick a different one',
    'api.cookiesRequired': 'Cookies data is required',
    'api.datasetInLineage': (
        'This file is the current version of cumulative dataset “{name}”; '
        'deleting it would break the history (force also resets that lineage)'
    ),
    'api.datasetInUse': 'saved workflows still read this file, and deleting it would leave them empty: {workflows}',
    'api.datasetMissing': 'No stored dataset with that id: {did}',
    'api.datasetNameInvalid': 'that name cannot label a dataset (nothing left after cleaning): {name}',
    'api.datasetTooBig': 'That file is too big to store: {err}',
    'api.diffKeyMissing': 'Compare key "{name}" is not a column in both tables, so rows cannot be matched by it',
    'api.diffKeyNotUnique': 'Compare key "{name}" has duplicate values, so it cannot identify rows uniquely',
    'api.diffTwoSources': 'Compare needs "a" and "b" (each a dataset_id, node_id+workflow_name, or inline data)',
    'api.excelMultiSheet': (
        'workbook "{name}" has several non-empty sheets ({sheets}); one upload imports one sheet — split it first'
    ),
    'api.exportNotFound': 'export file not found (or not downloadable): {name}',
    'api.fieldTypeInvalid': 'field {name} has the wrong type',
    'api.foreignOriginRefused': (
        'This server answers the local browser only: the request came from "{origin}" '
        'and is refused — the API is unauthenticated and holds real accounts'
    ),
    'api.historyNoRunId': 'no run id given, so no execution history was deleted',
    'api.killDone': 'thread "{name}" terminated',
    'api.killFailedGeneric': 'failed to kill thread',
    'api.killInvalidId': 'invalid thread ID',
    'api.killLiveWorker': 'this is a live crawl worker; use Stop rather than killing it',
    'api.killNoIdent': 'missing thread ident',
    'api.killNotAlive': 'thread is not alive',
    'api.killNotFound': 'thread not found',
    'api.killProtected': 'cannot kill protected thread: {name}',
    'api.lineageMissing': 'No cumulative dataset with that name: {name}',
    'api.llmModelsFailed': 'Could not fetch the OpenRouter model list: {err}',
    'api.needApiKey': 'The OpenRouter API key is missing (Settings → AI)',
    'api.needConfirm': 'This acts on every record — send confirm=true explicitly to do it',
    'api.needLabeledRows': 'At least 10 labelled rows are needed, this data has {n}',
    'api.needModel': 'No OpenRouter model selected (Settings → AI)',
    'api.needOllamaModel': 'No Ollama model selected (Settings → AI → Model; hit Refresh to list local ones)',
    'api.noCookieJob': 'No cookie login is currently active',
    'api.noSourceTable': 'None of the selected nodes could supply a table',
    'api.ollamaModelsFailed': 'Could not list local Ollama models at {host} (running? address right?): {err}',
    'api.paramInvalid': 'parameter {name} is invalid',
    'api.parseFailed': 'Could not parse the file: {err}',
    'api.payloadTooLarge': 'request body exceeds the {limit} MB ceiling — split it up',
    'api.pdfMissingFile': (
        'PDF refused: the ledger knows {name}, but the export folder no longer has it (it was cleared)'
    ),
    'api.pdfNeedsName': 'PDF refused: name the registered LaTeX source of this chart',
    'api.pdfUnregistered': (
        'PDF refused: {name} is not in the run ledger, so this program never wrote it and xelatex will not be handed it'
    ),
    'api.pdfWrongKind': 'PDF refused: {kind} is not a LaTeX source; only a .txt this program registered is compiled',
    'api.platformRequired': 'Platform is required',
    'api.platformsRequired': 'platforms must be a list of platform names',
    'api.profileDeleteBadName': (
        'Invalid account name: {account} (the default account has no separate profile directory to delete; '
        'letters, digits, underscore or hyphen, 1-24, stored lowercase)'
    ),
    'api.profileDeleteBusy': (
        '{platform} · {account}’s browser is in use — wait for the running crawl to finish before deleting its profile'
    ),
    'api.profileDeleteDefault': (
        'The default account has no browser profile to delete — its browser data IS the platform directory, '
        'and every other account is nested inside it'
    ),
    'api.queueFull': 'the queue is full ({n} waiting) — wait for the current run, or cancel some',
    # ── run queue ─────────────────────────────────────────────
    'api.queued': 'Queued: it starts when the current run finishes (position {at})',
    'api.reportNoData': 'nothing to report: run the workflow first, or pick a stored run',
    'api.rerunBusy': (
        "another run is still executing: a re-run deletes this subtree's saved rows first, "
        'so wait for it to finish before trying again'
    ),
    'api.rerunFingerprintMismatch': 'the canvas is not the same workflow as the chosen run, so its results cannot be '
    'reused safely — re-run the node from the run details',
    'api.rerunNoNode': 'node "{node}" is not on the current canvas, so it cannot be re-run',
    'api.rerunNoRows': 'node "{node}" has no completed result in the last run, so there is nothing to re-run from',
    'api.rerunNoRun': 'no saved run for this workflow was found; run it once before re-running a node',
    'api.rerunRunLive': (
        'this run is still executing (or stopping), so none of its nodes can be re-run — '
        'wait for it to finish or stop it first'
    ),
    'api.resumeMissing': (
        'cannot continue: run {rid} has been purged, so it would re-crawl everything — press Run instead'
    ),
    'api.runLogTruncated': '(log too long — downloaded the first {n} lines only)',
    'api.runNotFound': 'No such run: {rid}',
    'api.runSettingOption': 'The canvas setting "{setting}" has no value "{value}" (available: {allowed})',
    'api.stepsMustBeObjects': 'steps must be a list of objects, each with an "op" and optional "params"',
    'api.svgNotSvg': 'SVG refused: the content does not start with <svg or has no xmlns declaration',
    'api.svgRefused': 'SVG refused: the markup carries {found}, which can smuggle a script or an external reference',
    'api.svgTooLarge': 'SVG refused: {cap} bytes is the cap, and that is not a drawn chart',
    'api.svgTruncated': 'SVG refused: the file does not end with </svg> (it looks truncated)',
    'api.unsupportedPlatform': 'Unsupported platform: {platform}',
    'api.unsupportedUpload': 'unsupported file type: {name} (accepted: .csv .tsv .json .txt .xlsx .xls)',
    'api.workflowMissing': 'No saved workflow by that name: {name}',
    'api.workflowNameRequired': 'a valid workflow name is required',
    'api.workflowNameSame': 'The old and new names are the same file, so there is nothing to rename',
    'api.workflowNameTaken': 'A workflow named “{name}” already exists — renaming would overwrite it, pick another',
    'api.workflowNodeNoId': (
        'a node on the canvas has no id, so it cannot run (the id is a node storage key) — '
        're-add the node or repair the workflow file'
    ),
    'api.workflowRenamed': 'Workflow renamed: {old} → {new}',
    'api.workflowShapeInvalid': 'the workflow could not be read: an object with a nodes list is required',
    'auth.badCredentials': 'Wrong username or password',
    'auth.loginHint': 'This server keeps crawl sessions, datasets and run records — sign in to continue.',
    'auth.loginNeedsSecretKey': (
        'A login requires its own SECRET_KEY (this server is still using the repository default): the '
        'session cookie is signed with it, and a published key lets anyone mint a logged-in session'
    ),
    'auth.loginTitle': 'Sign in',
    'auth.password': 'Password',
    'auth.required': 'Sign in first',
    'auth.signIn': 'Sign in',
    'auth.username': 'Username',
    'compare.nodeMissing': 'Run {rid} has no node {node}',
    'compare.runMissing': 'No such run: {rid}',
    'compare.sameRun': 'A run cannot be compared with itself',
    'compare.tooManyRows': 'Node {node} has more than {max} rows, too many to compare',
    'data.mergeColumns': 'Dataset “{name}” does not match the first table: extra {extra}; missing {missing}',
    'data.mergeMissing': 'A dataset to merge does not exist: {id}',
    'data.mergeNameRequired': 'The merged dataset needs a name',
    'data.mergeNameTooLong': 'The merged dataset name is longer than {n} characters',
    'data.mergeNeedTwo': 'Merging needs at least two datasets',
    'data.mergeTooLarge': 'The merged table has {n} rows, over the limit of {max}',
    'ds.clearBusy': 'A live run may be reading these datasets — stop it or wait before clearing',
    'ds.cleared': 'Emptied the file store: {n} file(s) removed',
    'ds.corrupt': 'Dataset {did} could not be read (its records are damaged) — upload it again',
    'ds.lineage_columns': (
        'Cumulative dataset “{name}” does not match its current version: extra {extra}; missing {missing}'
    ),
    'ds.lineage_current_missing': 'The current version {id} of cumulative dataset “{name}” is missing',
    'ds.lineage_identity': 'Unknown duplicate policy: {value} (use whole row or named columns)',
    'ds.lineage_key_missing': 'Key column(s) not in the table: {cols}',
    'ds.lineage_keys_required': 'The named-columns policy needs at least one key column',
    'ds.lineage_missing_dataset': 'The dataset {id} for the cumulative import is missing',
    'ds.lineage_name_required': 'A cumulative dataset needs a name',
    'ds.lineage_too_large': 'Cumulative dataset “{name}” would reach {n} rows, over the limit of {max}',
    'ds.missing': 'An uploaded file this workflow refers to is no longer stored: {name}',
    'ds.purge_result': 'Removed {n} orphaned file(s), kept {kept} still in use',
    'ds.purged': 'Removed {n} file(s) unused for {days} days and referenced by no workflow',
    'ds.rebound': 'Re-attached dataset {name} ({did}) by file name — the workflow can run as-is',
    'ds.too_many_rows': 'the file has {n} rows, over the dataset limit of {limit} — it cannot be stored',
    # ── analysis / services ───────────────────────────────────
    'export.done': 'Exported {n} rows to {path} ({fmt})',
    'export.parquet_engine_missing': 'Parquet export needs the pyarrow engine — install it: pip install pyarrow',
    'export.window_ignored': (
        'Node {nid}: the file is written as normal and only "append the crawled time range" was ignored — {reason}'
    ),
    'export.window_many': 'the filename wants a time range, but this path has {n} of them',
    'export.window_none': 'the filename wants a time range, but no crawl here set a start/end time',
    'exports.clearBusy': 'A live run is writing part files into the export folder — stop it or wait before clearing',
    'exports.cleared': 'Export folder cleared: {n} file(s) removed',
    'exports.notAPart': '「{name}」 is not a shard file, so there is no batch to clear',
    'history.cleared': 'Execution history cleared',
    'history.recorded': 'Recorded {n} history metric(s) for "{wf}"',
    'history.run_deleted': 'Execution history: deleted {n} row(s) of run {rid}',
    'lock.badKey': 'The lock request is missing a valid panel or entry name',
    'lock.refuse': 'This item is locked — unlock it before deleting or clearing',
    'store.dataset_saved': 'File stored: {name} ({rows} rows, id {did})',
    'store.datasets_bound': 'Workflow {wf} bound to {n} uploaded file(s)',
    'store.workflow_saved': 'Workflow saved: {path}',
}
