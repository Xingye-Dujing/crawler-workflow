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
    'ai.traceNotTrace': '这不是节点追踪对话，无法套用节点结果',
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
    'ai.attachTooLarge': (
        '“{name}”有 {mb} MB，超过一次对话可用的输入上限（{limit} MB）。'
        '大表格请导入为数据集后用 @ 引用（AI 只读前几行），或把文件拆小。'
    ),
    'ai.workflowDraftInvalid': '工作流草稿无法载入：{detail}',
    'ai.workflowSaveFailed': '工作流无法保存到本账号的 workflows 目录：{detail}',
    'ai.memoryDraftRefused': '记忆提案需要一段非空的 text，且不超过 {limit} 字；请改短后重新提议。',
    'ai.memoryTooLong': '一条记忆最多 {limit} 字；请精简后再保存。',
    'ai.memoryFull': '记忆已达上限（{limit} 条）；请先在“记忆”里删掉不再需要的内容。',
    'ai.exportUser': '用户',
    'ai.exportAssistant': '助手',
    'ai.exportTruncated': '这个会话超过 {limit} 条消息，导出的是最近 {limit} 条。',
    'ai.datasetTooBig': '数据超过单表上限，未导入：{detail}',
    'ai.workspaceCloud': '云端模式没有用户本机文件系统，工作文件夹、导入和命令都不可用。',
    'ai.approvalRequired': (
        '“{tool}”会改动本机或运行记录，但“自动同意 AI 的本机操作”是关闭的。'
        '先用 request_approval 提出这次调用的确切参数；用户同意后再原样重试那个工具。'
    ),
    'ai.approvalHeader': '需要你允许：{tool}',
    'ai.approvalQuestion': 'AI 想执行“{tool}”：{summary} 允许这次操作吗？',
    'ai.approvalOnce': '允许一次',
    'ai.approvalSession': '本次会话允许',
    'ai.approvalDeny': '拒绝',
    'ai.approvalOnceHint': '只为这一次、这份完全相同的参数放行。',
    'ai.approvalSessionHint': '在本次会话里，这份完全相同的参数不必再问。',
    'ai.approvalDenyHint': '不执行；AI 会说明它没有做这一步。',
    'ai.approvalNoArgs': (
        'request_approval 需要把将要执行的确切参数作为 JSON 对象写进 detail，例如把 command 写成 “python x.py”。'
    ),
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
    'ai.workspaceNoApp': '这个宿主没有本地安装目录，命令只能在已选择的工作文件夹里运行。',
    'ai.workspaceMissing': '还没有选择工作文件夹：请先在 AI 工作区顶部选择本地文件夹。',
    'ai.workspaceGone': '工作文件夹已不存在：{path}；请重新选择。',
    'ai.workspaceNotAbsolute': '工作文件夹必须是绝对路径：{path}',
    'ai.workspaceNotFound': '找不到这个文件夹：{path}',
    'ai.workspaceOutside': '路径只能留在工作文件夹内：{path}',
    'ai.workspaceFileMissing': '找不到这个文件：{path}',
    'ai.workspaceNotDir': '这不是一个文件夹：{path}',
    'ai.workspaceNotFile': '这不是一个文件：{path}',
    'ai.workspaceReadOnly': '这里是只读的：{path}',
    'ai.workspaceUnreadable': '无法读取 {path}：{detail}',
    'ai.workspaceUnsupported': '不支持把这个文件导入为数据集：{name}',
    'ai.workspaceParseFailed': '无法解析 {name}：{detail}',
    'ai.workspaceMultiSheet': '“{name}”有多个工作表（{sheets}），请指明要哪一个，或先另存为单表。',
    'ai.workspace.pickTitle': '选择 AI 工作文件夹',
    'ai.draftRefusedAgain': (
        '这份草稿和上次被拒绝的完全一样，问题没有变化，原样重发不可能通过。请按上面的问题修改草稿，'
        '或者用 ask_user_question 问用户缺的东西（数据集、平台/账号、关键词）。'
    ),
    'ai.repairCapReached': (
        '这类草稿在本轮已经被拒绝 {limit} 次，逐项试错没有收敛。请停止继续提交：'
        '要么依据已报告的问题重写整份草稿，要么用 ask_user_question 向用户要缺失的数据、平台/账号、关键词。'
    ),
    'ai.pickUnavailable': (
        '这台机器没有可用的系统文件夹窗口（Windows 用 PowerShell，macOS 用 osascript，'
        'Linux 用 zenity 或 kdialog）。请在上方列表里逐层选择。'
    ),
    'ai.pickTimeout': '系统文件夹窗口超过 {seconds} 秒没有返回，已放弃；需要的话再点一次。',
    'ai.cmdEmpty': '命令是空的。',
    'ai.cmdShellRefused': '这里不是 shell，不能使用管道/重定向/串联（{detail}）。一次只跑一个程序。',
    'ai.cmdUnparsable': '命令无法解析：{detail}',
    'ai.cmdCloud': '云端模式不能在服务器上执行本机命令。',
    'ai.cmdNotAllowed': '“{command}”不在允许执行的程序清单里。',
    'ai.cmdMissing': '找不到可执行程序：{command}',
    'ai.cmdTimeout': '命令超过 {seconds} 秒仍未结束，已终止。',
    'ai.localCloud': '云端模式没有本机模型守护进程，{provider} 不可用；请改用 DeepSeek、OpenCode Go 或 OpenRouter。',
    'ai.noKey': '这个供应商需要 API Key，先在 AI 设置里填写。',
    'ai.capabilityRefused': '{provider} 的 {model} 不支持“{capability}”；没有静默降级。',
    'ai.toolFailed': '工具执行失败：{detail}',
    'ai.questionTooMany': (
        '助手在一个卡片里提了超过 {limit} 个问题（上限 {limit}），已按名拒绝，不会静默丢掉后面的问题。'
    ),
    'ai.questionDuplicate': '两个问题的 id 都是“{question}”，答案会互相覆盖，卡片已按名拒绝。',
    'ai.questionBlank': '第 {index} 个问题没有文字，卡片会是一块空白，已按名拒绝。',
    'ai.toolUnanswered': (
        '这次工具调用没有执行完（会话被停止、刷新或服务中断），没有结果。请重新调用，或告诉我该怎么做。'
    ),
    'ai.toolBudgetHeader': '工具调用预算',
    'ai.toolBudgetQuestion': '本轮已经执行了 {rounds} 次工具调用，达到了当前上限。要继续吗？',
    'ai.toolBudgetContinue': '继续',
    'ai.toolBudgetContinueHint': '再给一组工具调用，继续读文件、跑命令或修复结果。',
    'ai.toolBudgetStop': '到此为止',
    'ai.toolBudgetStopHint': '不再调用工具，用已有结果总结并给出下一步。',
    'ai.budgetExceeded': '预算已用尽：{scope}已用 {spent} tokens，上限 {limit}。请到设置里调高上限后再发。',
    'ai.budgetScope.conversation': '本会话',
    'ai.budgetScope.day': '今日',
    'ai.tokenBudgetHeader': 'Token 预算',
    'ai.tokenBudgetQuestion': '{scope}已用 {spent} tokens，达到上限 {limit}。要继续生成吗？',
    'ai.stepAwaiting': '等待你的回答',
    'ai.stepTool': '调用 {tool}',
    'ai.artifact': '产物',
    'ai.untitled': '未命名会话',
    'ai.newConversation': '新会话',
    'ai.questionUnanswered': '用户没有回答问题，改发了新消息',
    'ai.questionPending': '这个会话还有一个待回答的问题；先回答它（或明确取消），再发新消息。',
    'ai.monitorEvent': '监控事件“{event}”不存在；可用：run.started、node.finished、run.finished、run.log。',
    'ai.monitorStatus': '监控状态“{status}”不存在；可用：done、restored、partial、failed、skipped。',
    'ai.monitorOutcome': '运行结果“{outcome}”不存在；可用：completed、failed、interrupted。',
    'ai.monitorNeedle': '监控 run.log 必须给出 console_contains 关键字，否则每一行都会触发。',
    'ai.monitorRows': '监控的行数/次数阈值必须是整数。',
    'ai.monitorMissing': '监控不存在或已结束：{monitor}',
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
    'ai.fileNotFound': '附件不存在或已删除：{file}',
    'ai.fileSaveFailed': '供应商已接收文件，但本地副本写入失败：{detail}',
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
    'ai.skillBadId': '技能 id 只能包含小写字母、数字、点、下划线和连字符：{skill}',
    'ai.skillNoPrompt': '技能必须有提示词：{skill}',
    'ai.skillExists': '内置技能不能被覆盖；请先 Fork 成自己的技能。',
    'ai.toolUnknown': '未知工具：{tool}',
    'ai.toolRefused': '工具“{tool}”被拒绝：{reason}',
    'ai.chartSpecRefused': '图表方案无法渲染：{reason}',
    'ai.toolArgumentsCut': (
        '工具“{tool}”的参数没有传完（通常是回答被输出长度上限截断），已拒绝执行，而不是拿空参数去跑。'
        '请把这一步拆小，或缩短要一次输出的内容。'
    ),
    'ai.cancelled': '已停止生成。',
    'ai.streamFailed': 'AI 流式连接失败（{kind}）。',
    'ai.fileUnsupported': '这个文件不能作为附件发送；请确认它属于当前会话，或换一个文件。',
    'ai.fileTooLarge': '文件超过 {mb} MB 上限。',
    'ai.attachEmpty': '文件“{name}”是空的，没有可读内容。',
    'ai.attachConvert': '旧版 {format} 文件无法直接读取文字；请另存为 .docx/.pptx 或 PDF 后再上传。',
    'ai.attachTableTooBig': '表格“{name}”有 {mb} MB，超过本地解析上限 {limit} MB；请先拆小或改用数据集上传。',
    'ai.attachUnreadable': '文件“{name}”读不出文字（可能已损坏或格式不受支持）。',
    'ai.attachNoText': '文件“{name}”里没有可提取的文字（可能是扫描版 PDF）；请先转成可复制文字的 PDF。',
    'ai.attachLocked': '这个 PDF 有密码保护，无法提取文字。',
    'ai.imageNeedsUpload': '图片“{name}”不属于 {provider} 的上传记录，无法直接发送；请在这个会话里重新上传一次。',
    'ai.imageTooLarge': '图片“{name}”压缩后仍有 {mb} MB，超过 {limit} MB 的内联上限。',
    'ai.searchQuery': '搜索词必须是 1～128 个字符。',
    'ai.fetchUrl': '抓取地址必须是带 host 的 HTTP/HTTPS URL，且不能带用户名或密码。',
    'ai.fetchBlocked': 'Fetch 被安全策略拒绝。',
    'ai.fetchNotFound': 'Fetch 没有取得可用的网页正文。',
    'ai.pluginCloudCode': '本地代码插件只在本地/桌面可用；云端模式按名字拒绝。',
    'ai.codeCloudRefused': '源码检索只在本地/桌面可用；云端模式不可读取服务端源码。',
    'ai.pluginBadManifest': '插件清单不合法：{reason}',
    'ai.pluginConflict': '插件 id 已被占用：{plugin}',
    'ai.pluginNotFound': '找不到插件：{plugin}',
    'ai.apiNoConversation': '找不到会话：{conversation}',
    'ai.apiNoQuestion': '找不到待回答的问题：{question}',
    'ai.apiNoMessage': '找不到消息：{message}',
    'ai.apiAlreadyAnswered': '这个问题已经回答过了。',
    'ai.apiNoText': '消息不能为空。',
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
    'ai.traceNotTrace': 'This is not a node trace conversation, so a node result cannot be applied here',
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
    'ai.attachTooLarge': (
        '“{name}” is {mb} MB, above what one conversation can carry ({limit} MB). '
        'Import a big table as a dataset and reference it with @ (the assistant reads only the first '
        'rows), or split the file.'
    ),
    'ai.workflowDraftInvalid': 'The workflow draft cannot be loaded: {detail}',
    'ai.workflowSaveFailed': 'The workflow could not be written to this account’s workflows folder: {detail}',
    'ai.memoryDraftRefused': (
        'A memory proposal needs non-empty text of at most {limit} characters; shorten it and propose it again.'
    ),
    'ai.memoryTooLong': 'One memory can hold at most {limit} characters; shorten it before saving.',
    'ai.memoryFull': 'The memory is full ({limit} entries); delete what you no longer need in Memory first.',
    'ai.exportUser': 'User',
    'ai.exportAssistant': 'Assistant',
    'ai.exportTruncated': 'This conversation has more than {limit} messages; the newest {limit} are exported.',
    'ai.datasetTooBig': 'The table is above the single-table limit and was not imported: {detail}',
    'ai.workspaceCloud': (
        'A cloud host has no user filesystem, so the working folder, local imports and commands are unavailable.'
    ),
    'ai.approvalRequired': (
        '“{tool}” changes the machine or the run records, but “Approve AI machine actions automatically” is off. '
        'Call request_approval with the exact arguments first; after the user allows it, retry the same tool call.'
    ),
    'ai.approvalHeader': 'Your permission is needed: {tool}',
    'ai.approvalQuestion': 'The assistant wants to run “{tool}”: {summary} Allow this call?',
    'ai.approvalOnce': 'Allow once',
    'ai.approvalSession': 'Allow for this session',
    'ai.approvalDeny': 'Deny',
    'ai.approvalOnceHint': 'Only this one call, with exactly these arguments.',
    'ai.approvalSessionHint': 'In this conversation, these exact arguments will not ask again.',
    'ai.approvalDenyHint': 'Nothing runs; the assistant will say the step was not done.',
    'ai.approvalNoArgs': (
        'request_approval needs the exact arguments you will pass as a JSON object in detail, '
        'for example the command “python x.py”.'
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
    'ai.workspaceNoApp': 'This host has no local install folder; a command needs a chosen working folder.',
    'ai.workspaceMissing': 'No working folder is chosen yet. Pick a local folder at the top of the AI workspace.',
    'ai.workspaceGone': 'The working folder no longer exists: {path}. Choose it again.',
    'ai.workspaceNotAbsolute': 'The working folder must be an absolute path: {path}',
    'ai.workspaceNotFound': 'No such folder: {path}',
    'ai.workspaceOutside': 'The path must stay inside the working folder: {path}',
    'ai.workspaceFileMissing': 'No such file: {path}',
    'ai.workspaceNotDir': 'That is not a folder: {path}',
    'ai.workspaceNotFile': 'That is not a file: {path}',
    'ai.workspaceReadOnly': 'This location is read-only: {path}',
    'ai.workspaceUnreadable': 'Could not read {path}: {detail}',
    'ai.workspaceUnsupported': 'This file cannot be imported as a dataset: {name}',
    'ai.workspaceParseFailed': 'Could not parse {name}: {detail}',
    'ai.workspaceMultiSheet': '“{name}” has several sheets ({sheets}). Name the one to import, or save it as one.',
    'ai.workspace.pickTitle': 'Choose the AI working folder',
    'ai.draftRefusedAgain': (
        'This is the SAME draft with the SAME problems, and nothing was changed. Do not send it again: '
        'change the draft to fix them, or use ask_user_question to get what is missing (a dataset, a '
        'platform/account, a keyword). A second identical attempt cannot succeed.'
    ),
    'ai.repairCapReached': (
        'This kind of draft has been refused {limit} times in this turn without converging. Stop '
        'resubmitting: either rewrite the whole draft using the problems already reported, or use '
        'ask_user_question to get the missing data, platform/account or keyword from the user.'
    ),
    'ai.pickUnavailable': (
        'This machine has no usable system folder window (PowerShell on Windows, osascript on macOS, '
        'zenity or kdialog on Linux). Walk the list above instead.'
    ),
    'ai.pickTimeout': 'The system folder window did not answer within {seconds} seconds; try again if you need it.',
    'ai.cmdEmpty': 'The command is empty.',
    'ai.cmdShellRefused': 'This is not a shell: no pipes, redirection or chaining ({detail}). One program at a time.',
    'ai.cmdUnparsable': 'The command could not be parsed: {detail}',
    'ai.cmdCloud': 'A cloud host cannot run commands on the user’s machine.',
    'ai.cmdNotAllowed': '“{command}” is not on the allowed program list.',
    'ai.cmdMissing': 'No such executable: {command}',
    'ai.cmdTimeout': 'The command did not finish within {seconds}s and was stopped.',
    'ai.localCloud': (
        'A cloud host has no local model daemon, so {provider} is unavailable. Use DeepSeek, OpenCode Go or OpenRouter.'
    ),
    'ai.noKey': 'This provider needs an API key. Fill it in under AI settings first.',
    'ai.capabilityRefused': (
        '{provider} model {model} does not support “{capability}”; nothing was silently downgraded.'
    ),
    'ai.toolFailed': 'The tool failed: {detail}',
    'ai.questionTooMany': (
        'The assistant asked more than {limit} questions in one card (the limit is {limit}); '
        'the card was refused instead of silently dropping the rest.'
    ),
    'ai.questionDuplicate': (
        'Two questions share the id “{question}”, so one answer would overwrite the other; the card was refused.'
    ),
    'ai.questionBlank': 'Question #{index} has no text, so the card would be an empty box; it was refused.',
    'ai.toolUnanswered': (
        'This tool call never finished (the turn was stopped, the page reloaded or the server '
        'restarted), so it has no result. Call it again, or tell me what to do instead.'
    ),
    'ai.toolBudgetHeader': 'Tool budget',
    'ai.toolBudgetQuestion': 'This turn has made {rounds} tool calls and reached the current budget. Continue?',
    'ai.toolBudgetContinue': 'Continue',
    'ai.toolBudgetContinueHint': 'Grant another round: keep reading files, running commands or fixing results.',
    'ai.toolBudgetStop': 'Stop here',
    'ai.toolBudgetStopHint': 'No more tools: summarise what you have and give the next step.',
    'ai.budgetExceeded': (
        'Budget spent: {scope} used {spent} of {limit} tokens. Raise the limit in settings to send more.'
    ),
    'ai.budgetScope.conversation': 'This conversation',
    'ai.budgetScope.day': 'Today',
    'ai.tokenBudgetHeader': 'Token budget',
    'ai.tokenBudgetQuestion': '{scope} used {spent} tokens and reached the {limit} cap. Continue generating?',
    'ai.stepAwaiting': 'Waiting for your answer',
    'ai.stepTool': 'Calling {tool}',
    'ai.artifact': 'Artifact',
    'ai.untitled': 'Untitled conversation',
    'ai.newConversation': 'New conversation',
    'ai.questionUnanswered': 'The user did not answer the question and sent a new message instead.',
    'ai.questionPending': (
        'This conversation still has an unanswered question; answer it (or cancel it explicitly) before sending.'
    ),
    'ai.monitorEvent': 'Unknown monitor event “{event}”; use run.started, node.finished, run.finished or run.log.',
    'ai.monitorStatus': 'Unknown node status “{status}”; use done, restored, partial, failed or skipped.',
    'ai.monitorOutcome': 'Unknown run outcome “{outcome}”; use completed, failed or interrupted.',
    'ai.monitorNeedle': 'A run.log monitor needs console_contains; otherwise every line would trigger it.',
    'ai.monitorRows': 'A monitor row/trigger threshold must be an integer.',
    'ai.monitorMissing': 'That monitor does not exist or has ended: {monitor}',
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
    'ai.fileNotFound': 'That attachment does not exist or was deleted: {file}',
    'ai.fileSaveFailed': 'The provider accepted the file, but the local copy could not be written: {detail}',
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
    'ai.skillBadId': 'A skill id may only contain lowercase letters, digits, dots, underscores and hyphens: {skill}',
    'ai.skillNoPrompt': 'A skill needs a prompt: {skill}',
    'ai.skillExists': 'A built-in skill cannot be overwritten; fork it into your own skill first.',
    'ai.toolUnknown': 'Unknown tool: {tool}',
    'ai.toolRefused': 'Tool “{tool}” was refused: {reason}',
    'ai.chartSpecRefused': 'The chart spec cannot be rendered: {reason}',
    'ai.toolArgumentsCut': (
        'The arguments for “{tool}” never arrived whole (usually an answer cut off by the output limit). '
        'The call was refused instead of being run with empty parameters.'
    ),
    'ai.cancelled': 'Generation stopped.',
    'ai.streamFailed': 'The AI stream failed ({kind}).',
    'ai.fileUnsupported': (
        'That file cannot be sent as an attachment; use one from this conversation or pick another file.'
    ),
    'ai.fileTooLarge': 'The file exceeds the {mb} MB limit.',
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
    'ai.imageNeedsUpload': (
        'The image “{name}” was not uploaded through {provider}, so it cannot be sent inline; upload it again here.'
    ),
    'ai.imageTooLarge': 'The image “{name}” is still {mb} MB after compression, over the {limit} MB inline limit.',
    'ai.searchQuery': 'The search query must be 1–128 characters.',
    'ai.fetchUrl': 'The fetch URL must be an HTTP/HTTPS URL with a host and no credentials.',
    'ai.fetchBlocked': 'Fetch was refused by the safety policy.',
    'ai.fetchNotFound': 'Fetch found no usable page content.',
    'ai.pluginCloudCode': 'Local code plugins run on a local/desktop host only; cloud mode refuses them by name.',
    'ai.codeCloudRefused': (
        'Source search is available on a local/desktop host only; cloud mode cannot read server source.'
    ),
    'ai.pluginBadManifest': 'Invalid plugin manifest: {reason}',
    'ai.pluginConflict': 'Plugin id is already taken: {plugin}',
    'ai.pluginNotFound': 'Plugin not found: {plugin}',
    'ai.apiNoConversation': 'Conversation not found: {conversation}',
    'ai.apiNoQuestion': 'No pending question found: {question}',
    'ai.apiNoMessage': 'Message not found: {message}',
    'ai.apiAlreadyAnswered': 'That question has already been answered.',
    'ai.apiNoText': 'The message cannot be empty.',
}
