"""The AI workspace's own words: providers, capabilities, refusals and agent states.

The browser catalogue carries the UI vocabulary in ``static/js/i18n/ai.js``; these entries are
what the server says when it refuses a provider, a capability, a skill or a plugin. Keeping the
two tables separate is deliberate: a provider name is echoed by the server in an API answer and
also rendered by the page, and a single missing key must be visible in both places.
"""

ZH = {
    'trace.intro': (
        '这里记录节点向模型发出的每一条提示与回答。你可以在本对话里修改内容；'
        '确认后可从该节点继续重跑。Token 数为估算，不是账单数字。'
    ),
    'trace.opened': '已为节点 {node} 打开可见追踪对话：{id}',
    'trace.finished': '节点 {node} 已完成（{rows} 行）。如不满意，可在本对话里继续调整，再确认重跑。',
    'trace.streamingPrefix': '（本次调用估算：提示 {prompt} 字 ≈ {ptokens} token，回答生成中… 非账单数字）\n',
    'trace.usageNote': (
        '（本次调用估算：提示 {prompt} 字 ≈ {ptokens} token，回答 {answer} 字 ≈ {atokens} token；非账单数字）\n'
    ),
    'trace.sampleInput': '输入样本',
    'trace.sampleOutput': '输出样本',
    'trace.resultDefault': '节点已完成；如不满意，请继续在对话里修改，再确认重跑。',
    'trace.unavailable': '追踪对话不可用，节点照常执行：{err}',
    'trace.writeFailed': '写入追踪对话失败，节点照常执行：{err}',
    'trace.finishFailed': '收尾追踪对话失败，节点结果不受影响：{err}',
    'ai.traceNoResult': '这条追踪还没有已定稿的节点结果，先让节点跑完再套用',
    'ai.provider.deepseek': 'DeepSeek 直连',
    'ai.provider.opencode_go': 'OpenCode Go',
    'ai.provider.openrouter': 'OpenRouter',
    'ai.provider.ollama': '本地 Ollama',
    'ai.providerNote.deepseek': (
        '正式 API：深度思考、联网搜索、读链接、安全审核与会话标题。'
        '联网搜索与抓页的服务端工具调用免费，仅按模型 Token 计费。'
    ),
    'ai.providerNote.opencode_go': 'OpenCode Go 套餐通道，面向编码代理流量；通用分析对话可能被限流。',
    'ai.providerNote.openrouter': '现有 OpenAI 兼容通道；免费模型可用，但没有服务端联网与文件能力。',
    'ai.providerNote.ollama': '本机守护进程；云端模式无法使用。',
    'ai.runtime.desktop': '桌面版',
    'ai.runtime.local_web': '本地网页版',
    'ai.runtime.cloud': '云端网页版',
    # Artifact change previews: the server describes what an apply would do, by named source.
    'ai.preview.title': '变更预览',
    'ai.preview.add': '新增',
    'ai.preview.change': '覆盖',
    'ai.preview.keep': '保持',
    'ai.preview.nodeSummary': '将把 {n} 个节点带入画布（勾选后应用）',
    'ai.preview.memory': '写入长期记忆：{text}',
    'ai.preview.memoryItem': '一条记忆',
    'ai.preview.chars': '{n} 字',
    'ai.preview.monitor': '布防监控：监听 {events}',
    'ai.preview.monitorItem': '一条监控规则',
    'ai.preview.monitorNote': '监控不会自行消耗 Token；触发时只把事件事实交给模型。',
    'ai.preview.chart': '渲染图表：{type} · 数据集 {dataset}',
    'ai.preview.chartItem': '一张图表',
    'ai.preview.noColumns': '未指定列名',
    'ai.preview.mergeNote': '未勾选的节点保持原样；指向未勾选节点的连线会被丢弃。',
    'ai.preview.button': '预览变更',
    'ai.preview.apply': '应用所选',
    'ai.preview.none': '请至少勾选一项',
    'ai.preview.unknown': '工件类型 {kind_name} 没有可预览的变更',
    'ai.preview.refused': '草稿未通过校验：{detail}',
    'ai.unknownProvider': '未知的 AI 供应商：{provider}',
    'ai.unauthorized': '供应商拒绝了凭据（401/403）；检查 API Key 是否有效。',
    'ai.quota': '供应商账户余额不足（402）。',
    'ai.modelMissing': '供应商没有这个模型（404）：{detail}',
    'ai.rateLimit': '供应商限流（429）；稍后重试或换一个模型。',
    'ai.badRequest': '供应商拒绝了请求（400）：{detail}',
    'ai.server': '供应商服务端错误：{detail}',
    'ai.http': '供应商返回 HTTP {status}：{detail}',
    'ai.network': '连接供应商失败：{detail}',
    'ai.badResponse': '供应商返回了无法解析的数据：{detail}',
    'ai.workflowDraftInvalid': '工作流草稿无法载入：{detail}',
    'ai.workflowSaveFailed': '工作流无法保存到本账号的 workflows 目录：{detail}',
    'ai.auditLog': 'AI 操作审计：{action} {name}（账号 {account}，会话 {conversation}）',
    'ai.workflowNotFound': '找不到工作流“{name}”。',
    'ai.workflowNameTaken': '已有同名工作流“{name}”；没有覆盖。',
    'ai.workflowRunFailed': '启动工作流“{name}”失败：{detail}',
    'ai.workflowStopFailed': '停止当前运行失败：{detail}',
    'ai.exportNotFound': '导出目录里找不到“{name}”。',
    'ai.exportSaveFailed': '导出文件无法写入本账号的导出目录：{detail}',
    'ai.memoryDraftRefused': '记忆提案需要一段非空的 text，且不超过 {limit} 字；请改短后重新提议。',
    'ai.datasetTooBig': '数据超过单表上限，未导入：{detail}',
    'ai.workspaceCloud': '云端模式没有用户本机文件系统，工作文件夹、导入和命令都不可用。',
    'ai.approvalDenied': '你拒绝了这次操作，它没有被执行。',
    'ai.rerunArgs': '重跑需要 run_id、workflow_name 和 node_id 三个参数。',
    'ai.rerunNoWorkflow': '找不到这次运行对应的已保存工作流：{name}。它可能从未保存，或文件已被删除、改名。',
    'ai.rerunUnsaved': '这条运行没有对应的已保存工作流，无法从文件重跑；请先保存画布。',
    'ai.rerunCanvasChanged': (
        '已保存的画布与这条运行的记录不一致（文件或画布改过了），不能在这条运行上重跑；'
        '请用“继续”运行当前画布，或打开当时的工作流。'
    ),
    'ai.rerunNoNode': '这条运行里没有这个节点：{node}',
    'ai.rerunNoRun': '找不到可重跑的运行记录。',
    'ai.rerunRunLive': '这条运行还在进行中，不能重跑它的节点；先停止或等它结束。',
    'ai.rerunNoRows': '该节点没有可重跑的结果：{node}',
    'ai.rerunStarted': '已开始重跑节点 {node}',
    'ai.workspaceNotFound': '找不到这个文件夹：{path}',
    'ai.workspaceNotFile': '这不是一个文件：{path}',
    'ai.workspaceUnreadable': '无法读取 {path}：{detail}',
    'ai.workspaceUnsupported': '不支持把这个文件导入为数据集：{name}',
    'ai.workspaceParseFailed': '无法解析 {name}：{detail}',
    'ai.workspaceMultiSheet': '“{name}”有多个工作表（{sheets}），请指明要哪一个，或先另存为单表。',
    'ai.workspace.pickTitle': '选择 AI 工作文件夹',
    'ai.pickUnavailable': (
        '这台机器没有可用的系统文件夹窗口（Windows 用 PowerShell，macOS 用 osascript，'
        'Linux 用 zenity 或 kdialog）。请在上方列表里逐层选择。'
    ),
    'ai.pickTimeout': '系统文件夹窗口超过 {seconds} 秒没有返回，已放弃；需要的话再点一次。',
    'ai.localCloud': '云端模式没有本机模型守护进程，{provider} 不可用；请改用 DeepSeek、OpenCode Go 或 OpenRouter。',
    'ai.noKey': '这个供应商需要 API Key，先在 AI 设置里填写。',
    'ai.toolFailed': '工具执行失败：{detail}',
    'ai.artifact': '产物',
    'ai.monitorEvent': '监控事件“{event}”不存在；可用：run.started、node.finished、run.finished、run.log。',
    'ai.monitorStatus': '监控状态“{status}”不存在；可用：done、restored、partial、failed、skipped。',
    'ai.monitorOutcome': '运行结果“{outcome}”不存在；可用：completed、failed、interrupted。',
    'ai.monitorNeedle': '监控 run.log 必须给出 console_contains 关键字，否则每一行都会触发。',
    'ai.monitorRows': '监控的行数/次数阈值必须是整数。',
    'ai.pythonCloud': '共享云主机不允许执行用户 Python；请在本机网页版或桌面版使用 Python 扩展。',
    'ai.pythonDisabled': '先在设置里开启“允许 AI 执行 Python”。',
    'ai.pythonMissing': '没有检测到可用的 Python 3 解释器；请在设置里指定路径，或允许下载。',
    'ai.pythonSpawnFailed': '无法启动 Python：{detail}',
    'ai.pythonUnknown': '找不到脚本：{script}',
    'ai.pythonBadId': '脚本 id 只能是小写字母、数字、下划线，且以字母开头：{script}',
    'ai.pythonBuiltin': '内置脚本不能覆盖；请先 Fork 成自己的脚本。',
    'ai.pythonForkExists': '目标脚本已存在；换一个 id，或明确要求覆盖：{script}',
    'ai.pythonNoName': '脚本需要名称：{script}',
    'ai.pythonNoCode': '脚本需要代码：{script}',
    'ai.pythonTooLarge': '脚本超过 {kb} KB 上限：{script}',
    'ai.pythonArgs': '节点参数必须是 JSON 对象：{script}',
    'ai.pythonBadNumber': '节点参数 {field} 必须是正整数：{value}',
    'ai.pythonTimeout': '脚本运行超过 {seconds} 秒，已终止。',
    'ai.pythonFailed': '脚本退出码 {code}：{detail}',
    'ai.pythonOutput': '脚本“{label}”第 {line} 行输出不是 JSON 对象。',
    'ai.pythonNoOutput': '脚本“{script}”没有写输出文件；零行也必须创建 CIXI_OUTPUT。',
    'ai.pythonPath': '脚本工作区路径不合法：{path}',
    'ai.pythonFileLarge': '文件超过 {kb} KB：{path}',
    'ai.pythonInstallWindows': '只有 Windows 桌面版提供自动下载；其他系统请先安装 Python 3。',
    'ai.pythonInstallUrl': '下载地址不可用：{url}',
    'ai.pythonInstallSize': '下载内容超过 {mb} MB 上限，已中止。',
    'ai.pythonInstallChecksum': '下载的 Python 包校验失败，已中止；请稍后重试。',
    'ai.pythonOutputTruncated': '…（输出已截断）',
    'ai.skillUnavailable': '技能“{skill}”需要“{capability}”，而 {provider} 不提供它。',
    'ai.skillCodeLocal': '技能“{skill}”需要读取仓库源码，只在本地网页版（源码运行）可用；桌面版与云端不提供。',
    'ai.skillLocalOnly': '技能“{skill}”需要本机环境（本地 CLI 与运行时），云端不提供。',
    'ai.skillPythonLocal': '技能“{skill}”需要 Python 扩展：请在本机网页版/桌面版开启“允许 AI 执行 Python”。',
    'ai.skillUnknown': '未知技能：{skill}',
    'ai.skillBadTool': '技能“{skill}”引用了不存在的工具：{tool}',
    'ai.skillBadContext': '技能“{skill}”引用了不存在的上下文来源：{source}',
    'ai.toolRefused': '工具“{tool}”被拒绝：{reason}',
    'ai.chartSpecRefused': '图表方案无法渲染：{reason}',
    'ai.cancelled': '已停止生成。',
    'ai.attachEmpty': '文件“{name}”是空的，没有可读内容。',
    'ai.attachConvert': '旧版 {format} 文件无法直接读取文字；请另存为 .docx/.pptx 或 PDF 后再上传。',
    'ai.attachTableTooBig': '表格“{name}”有 {mb} MB，超过本地解析上限 {limit} MB；请先拆小或改用数据集上传。',
    'ai.attachUnreadable': '文件“{name}”读不出文字（可能已损坏或格式不受支持）。',
    'ai.attachNoText': '文件“{name}”里没有可提取的文字（可能是扫描版 PDF）；请先转成可复制文字的 PDF。',
    'ai.attachLocked': '这个 PDF 有密码保护，无法提取文字。',
    'ai.imageTooLarge': '图片“{name}”压缩后仍有 {mb} MB，超过 {limit} MB 的内联上限。',
    'ai.searchQuery': '搜索词必须是 1～128 个字符。',
    'ai.fetchUrl': '抓取地址必须是带 host 的 HTTP/HTTPS URL，且不能带用户名或密码。',
    'ai.fetchBlocked': 'Fetch 被安全策略拒绝。',
    'ai.fetchNotFound': 'Fetch 没有取得可用的网页正文。',
    'ai.codeCloudRefused': '源码检索只在本地/桌面可用；云端模式不可读取服务端源码。',
    'ai.datasetAccessNeeded': (
        '读取数据集 {dataset} 的多行内容需要先征得同意：调用 request_dataset_access 申请；'
        'dataset_peek 仍可免费看 5 行预览。'
    ),
    'ai.datasetGrantExhausted': (
        '本会话对数据集 {dataset} 的读取授权已用完（已读 {rows_read} / {max_rows} 行）；'
        '需要更多请再次调用 request_dataset_access。'
    ),
    'ai.datasetEmpty': '这个数据集没有行可读。',
}

EN = {
    'trace.intro': (
        'Every prompt and answer this node sends to the model appears here. '
        'You can edit the content and resume the run from the node after confirming. '
        'Token counts are estimates, not billed units.'
    ),
    'trace.opened': 'Opened a visible trace conversation for node {node}: {id}',
    'trace.finished': (
        'Node {node} finished ({rows} rows). If you want changes, keep talking here, then confirm and rerun.'
    ),
    'trace.streamingPrefix': '(Estimated: prompt {prompt} chars ~ {ptokens} tokens, answering... not billed)\n',
    'trace.usageNote': (
        '(Estimated: prompt {prompt} chars ~ {ptokens} tokens, answer {answer} chars ~ {atokens} tokens; not billed)\n'
    ),
    'trace.sampleInput': 'Input sample',
    'trace.sampleOutput': 'Output sample',
    'trace.resultDefault': 'Node finished; keep talking here to adjust it, then confirm and rerun.',
    'trace.unavailable': 'Trace conversation unavailable; the node runs as usual: {err}',
    'trace.writeFailed': 'Writing the trace failed; the node runs as usual: {err}',
    'trace.finishFailed': 'Closing the trace failed; the node result is unaffected: {err}',
    'ai.traceNoResult': 'This trace has no settled node result yet; let the node finish before applying one',
    'ai.provider.deepseek': 'DeepSeek API',
    'ai.provider.opencode_go': 'OpenCode Go',
    'ai.provider.openrouter': 'OpenRouter',
    'ai.provider.ollama': 'Local Ollama',
    'ai.providerNote.deepseek': (
        'The full API: thinking, web search, link reading, safety review and conversation titles. '
        'Server-side web search and fetch tool calls are free; only model tokens are billed.'
    ),
    'ai.providerNote.opencode_go': (
        'The OpenCode Go plan, intended for coding-agent traffic; general analysis chat may be rate-limited.'
    ),
    'ai.providerNote.openrouter': (
        'The existing OpenAI-compatible route; free models work, but there is no server-side web or file capability.'
    ),
    'ai.providerNote.ollama': 'The local daemon; unavailable in cloud mode.',
    'ai.runtime.desktop': 'Desktop app',
    'ai.runtime.local_web': 'Local web app',
    'ai.runtime.cloud': 'Cloud web app',
    # Artifact change previews: the server describes what an apply would do, by named source.
    'ai.preview.title': 'Changes to apply',
    'ai.preview.add': 'Add',
    'ai.preview.change': 'Overwrite',
    'ai.preview.keep': 'Keep',
    'ai.preview.nodeSummary': '{n} node(s) will be brought onto the canvas (select what to apply)',
    'ai.preview.memory': 'Store in long-term memory: {text}',
    'ai.preview.memoryItem': 'One memory',
    'ai.preview.chars': '{n} chars',
    'ai.preview.monitor': 'Arm a monitor for: {events}',
    'ai.preview.monitorItem': 'One monitor rule',
    'ai.preview.monitorNote': (
        'A monitor never spends a token on its own; a trigger only hands event facts to the model.'
    ),
    'ai.preview.chart': 'Render chart: {type} · dataset {dataset}',
    'ai.preview.chartItem': 'One chart',
    'ai.preview.noColumns': 'No columns named',
    'ai.preview.mergeNote': 'Unselected nodes stay as they are; connections to them are dropped.',
    'ai.preview.button': 'Preview changes',
    'ai.preview.apply': 'Apply selected',
    'ai.preview.none': 'Select at least one item',
    'ai.preview.unknown': 'Artifact kind {kind_name} has no preview',
    'ai.preview.refused': 'The draft failed validation: {detail}',
    'ai.unknownProvider': 'Unknown AI provider: {provider}',
    'ai.unauthorized': 'The provider rejected the credentials (401/403); check the API key.',
    'ai.quota': 'The provider account is out of quota (402).',
    'ai.modelMissing': 'The provider does not have that model (404): {detail}',
    'ai.rateLimit': 'The provider rate-limited the request (429); retry later or switch models.',
    'ai.badRequest': 'The provider rejected the request (400): {detail}',
    'ai.server': 'The provider failed on its side: {detail}',
    'ai.http': 'The provider answered HTTP {status}: {detail}',
    'ai.network': 'Could not reach the provider: {detail}',
    'ai.badResponse': 'The provider returned unreadable data: {detail}',
    'ai.workflowDraftInvalid': 'The workflow draft cannot be loaded: {detail}',
    'ai.workflowSaveFailed': 'The workflow could not be written to this account’s workflows folder: {detail}',
    'ai.auditLog': 'AI audit: {action} {name} (account {account}, conversation {conversation})',
    'ai.workflowNotFound': 'No saved workflow named “{name}”.',
    'ai.workflowNameTaken': 'A workflow named “{name}” already exists; nothing was overwritten.',
    'ai.workflowRunFailed': 'The workflow “{name}” could not start: {detail}',
    'ai.workflowStopFailed': 'The live run could not be stopped: {detail}',
    'ai.exportNotFound': 'No exported file named “{name}”.',
    'ai.exportSaveFailed': 'The export could not be written to this account’s export folder: {detail}',
    'ai.memoryDraftRefused': (
        'A memory proposal needs non-empty text of at most {limit} characters; shorten it and propose it again.'
    ),
    'ai.datasetTooBig': 'The table is above the single-table limit and was not imported: {detail}',
    'ai.workspaceCloud': (
        'A cloud host has no user filesystem, so the working folder, local imports and commands are unavailable.'
    ),
    'ai.approvalDenied': 'You denied this call; nothing ran.',
    'ai.rerunArgs': 'A rerun needs all three: run_id, workflow_name and node_id.',
    'ai.rerunNoWorkflow': (
        'No saved workflow matches this run: {name}. It may never have been saved, or the file was deleted or renamed.'
    ),
    'ai.rerunUnsaved': 'This run has no saved workflow to rerun from; save the canvas first.',
    'ai.rerunCanvasChanged': (
        'The saved canvas no longer matches this run (the file or the canvas changed), so it cannot be rerun '
        'there. Use 继续 on the current canvas, or open the workflow as it was.'
    ),
    'ai.rerunNoNode': 'This run has no such node: {node}',
    'ai.rerunNoRun': 'No rerunnable run record was found.',
    'ai.rerunRunLive': 'This run is still going, so its nodes cannot be rerun; stop it or wait for it to finish.',
    'ai.rerunNoRows': 'That node has no stored result to rerun: {node}',
    'ai.rerunStarted': 'Started rerunning node {node}',
    'ai.workspaceNotFound': 'No such folder: {path}',
    'ai.workspaceNotFile': 'That is not a file: {path}',
    'ai.workspaceUnreadable': 'Could not read {path}: {detail}',
    'ai.workspaceUnsupported': 'This file cannot be imported as a dataset: {name}',
    'ai.workspaceParseFailed': 'Could not parse {name}: {detail}',
    'ai.workspaceMultiSheet': '“{name}” has several sheets ({sheets}). Name the one to import, or save it as one.',
    'ai.workspace.pickTitle': 'Choose the AI working folder',
    'ai.pickUnavailable': (
        'This machine has no usable system folder window (PowerShell on Windows, osascript on macOS, '
        'zenity or kdialog on Linux). Walk the list above instead.'
    ),
    'ai.pickTimeout': 'The system folder window did not answer within {seconds} seconds; try again if you need it.',
    'ai.localCloud': (
        'A cloud host has no local model daemon, so {provider} is unavailable. Use DeepSeek, OpenCode Go or OpenRouter.'
    ),
    'ai.noKey': 'This provider needs an API key. Fill it in under AI settings first.',
    'ai.toolFailed': 'The tool failed: {detail}',
    'ai.artifact': 'Artifact',
    'ai.monitorEvent': 'Unknown monitor event “{event}”; use run.started, node.finished, run.finished or run.log.',
    'ai.monitorStatus': 'Unknown node status “{status}”; use done, restored, partial, failed or skipped.',
    'ai.monitorOutcome': 'Unknown run outcome “{outcome}”; use completed, failed or interrupted.',
    'ai.monitorNeedle': 'A run.log monitor needs console_contains; otherwise every line would trigger it.',
    'ai.monitorRows': 'A monitor row/trigger threshold must be an integer.',
    'ai.pythonCloud': 'A shared cloud host does not execute user Python; use the local web app or the desktop app.',
    'ai.pythonDisabled': 'Enable “Allow AI Python execution” in settings first.',
    'ai.pythonMissing': 'No usable Python 3 interpreter was found; set its path in settings or allow the download.',
    'ai.pythonSpawnFailed': 'Python could not be started: {detail}',
    'ai.pythonUnknown': 'No such script: {script}',
    'ai.pythonBadId': (
        'A script id may only contain lowercase letters, digits and underscores, starting with a letter: {script}'
    ),
    'ai.pythonBuiltin': 'A built-in script cannot be overwritten; fork it into your own script first.',
    'ai.pythonForkExists': 'That target script already exists; choose another id or ask to overwrite: {script}',
    'ai.pythonNoName': 'A script needs a name: {script}',
    'ai.pythonNoCode': 'A script needs code: {script}',
    'ai.pythonTooLarge': 'The script exceeds the {kb} KB limit: {script}',
    'ai.pythonArgs': 'The node parameters must be a JSON object: {script}',
    'ai.pythonBadNumber': 'Node parameter {field} must be a positive integer: {value}',
    'ai.pythonTimeout': 'The script ran longer than {seconds}s and was terminated.',
    'ai.pythonFailed': 'The script exited with code {code}: {detail}',
    'ai.pythonOutput': 'Script “{label}” wrote a non-object JSON line at {line}.',
    'ai.pythonNoOutput': 'Script “{script}” wrote no output file; zero rows still means creating CIXI_OUTPUT.',
    'ai.pythonPath': 'Illegal script workspace path: {path}',
    'ai.pythonFileLarge': 'The file exceeds {kb} KB: {path}',
    'ai.pythonInstallWindows': (
        'Only the Windows desktop app offers the automatic download; install Python 3 elsewhere.'
    ),
    'ai.pythonInstallUrl': 'The download URL is unavailable: {url}',
    'ai.pythonInstallSize': 'The download exceeded the {mb} MB limit and was stopped.',
    'ai.pythonInstallChecksum': 'The downloaded Python archive failed its checksum and was discarded; try again later.',
    'ai.pythonOutputTruncated': '… (output truncated)',
    'ai.skillUnavailable': 'Skill “{skill}” needs “{capability}”, which {provider} does not offer.',
    'ai.skillCodeLocal': (
        'Skill “{skill}” needs the repository source, which only the local web checkout provides; '
        'the desktop app and a cloud host do not offer it.'
    ),
    'ai.skillLocalOnly': (
        'Skill “{skill}” needs a local machine (a local CLI and runtime), which a cloud host does not offer.'
    ),
    'ai.skillPythonLocal': (
        'Skill “{skill}” needs the Python extension; enable “Allow AI Python execution” on a local web or desktop host.'
    ),
    'ai.skillUnknown': 'Unknown skill: {skill}',
    'ai.skillBadTool': 'Skill “{skill}” names a tool that does not exist: {tool}',
    'ai.skillBadContext': 'Skill “{skill}” names a context source that does not exist: {source}',
    'ai.toolRefused': 'Tool “{tool}” was refused: {reason}',
    'ai.chartSpecRefused': 'The chart spec cannot be rendered: {reason}',
    'ai.cancelled': 'Generation stopped.',
    'ai.attachEmpty': 'The file “{name}” is empty; there is nothing to read.',
    'ai.attachConvert': (
        'A legacy {format} file cannot be read as text; save it as .docx/.pptx or PDF and upload again.'
    ),
    'ai.attachTableTooBig': (
        'The table “{name}” is {mb} MB, over the {limit} MB local parsing limit; split it or upload it as a dataset.'
    ),
    'ai.attachUnreadable': 'The file “{name}” could not be read as text (it may be corrupt or unsupported).',
    'ai.attachNoText': (
        'The file “{name}” contains no extractable text (possibly a scanned PDF); convert it to a text PDF first.'
    ),
    'ai.attachLocked': 'This PDF is password-protected, so its text cannot be extracted.',
    'ai.imageTooLarge': 'The image “{name}” is still {mb} MB after compression, over the {limit} MB inline limit.',
    'ai.searchQuery': 'The search query must be 1–128 characters.',
    'ai.fetchUrl': 'The fetch URL must be an HTTP/HTTPS URL with a host and no credentials.',
    'ai.fetchBlocked': 'Fetch was refused by the safety policy.',
    'ai.fetchNotFound': 'Fetch found no usable page content.',
    'ai.codeCloudRefused': (
        'Source search is available on a local/desktop host only; cloud mode cannot read server source.'
    ),
    'ai.datasetAccessNeeded': (
        'Reading more than a preview of dataset {dataset} needs the user’s permission: call '
        'request_dataset_access first. dataset_peek still shows five rows for free.'
    ),
    'ai.datasetGrantExhausted': (
        'This conversation’s grant for dataset {dataset} is used up ({rows_read} of {max_rows} rows); '
        'call request_dataset_access again if more rows are needed.'
    ),
    'ai.datasetEmpty': 'This dataset has no rows to read.',
}
