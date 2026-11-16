"""The AI workspace's own words: providers, capabilities, refusals and agent states.

The browser catalogue carries the UI vocabulary in ``static/js/i18n/ai.js``; these entries are
what the server says when it refuses a provider, a capability, a skill or a plugin. Keeping the
two tables separate is deliberate: a provider name is echoed by the server in an API answer and
also rendered by the page, and a single missing key must be visible in both places.
"""

ZH = {
    'ai.provider.deepseek': 'DeepSeek 直连',
    'ai.provider.opencode_go': 'OpenCode Go',
    'ai.provider.openrouter': 'OpenRouter',
    'ai.provider.ollama': '本地 Ollama',
    'ai.providerNote.deepseek': '正式 API：深度思考、联网搜索、读链接、安全审核与会话标题。',
    'ai.providerNote.opencode_go': 'OpenCode Go 套餐通道，面向编码代理流量；通用分析对话可能被限流。',
    'ai.providerNote.openrouter': '现有 OpenAI 兼容通道；免费模型可用，但没有服务端联网与文件能力。',
    'ai.providerNote.ollama': '本机守护进程；云端模式无法使用。',
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
    'ai.localCloud': '云端模式没有本机模型守护进程，{provider} 不可用；请改用 DeepSeek、OpenCode Go 或 OpenRouter。',
    'ai.noKey': '这个供应商需要 API Key，先在 AI 设置里填写。',
    'ai.capabilityRefused': '{provider} 的 {model} 不支持“{capability}”；没有静默降级。',
    'ai.skillUnavailable': '技能“{skill}”需要“{capability}”，而 {provider} 不提供它。',
    'ai.skillCodeLocal': '技能“{skill}”需要读取源码：请在 AI 设置里开启并只在本地/桌面运行。',
    'ai.skillUnknown': '未知技能：{skill}',
    'ai.skillBadTool': '技能“{skill}”引用了不存在的工具：{tool}',
    'ai.skillBadContext': '技能“{skill}”引用了不存在的上下文来源：{source}',
    'ai.skillBadId': '技能 id 只能包含小写字母、数字、点、下划线和连字符：{skill}',
    'ai.skillNoPrompt': '技能必须有提示词：{skill}',
    'ai.skillExists': '内置技能不能被覆盖；请先 Fork 成自己的技能。',
    'ai.toolUnknown': '未知工具：{tool}',
    'ai.toolRefused': '工具“{tool}”被拒绝：{reason}',
    'ai.cancelled': '已停止生成。',
    'ai.streamFailed': 'AI 流式连接失败（{kind}）。',
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
    'ai.provider.deepseek': 'DeepSeek API',
    'ai.provider.opencode_go': 'OpenCode Go',
    'ai.provider.openrouter': 'OpenRouter',
    'ai.provider.ollama': 'Local Ollama',
    'ai.providerNote.deepseek': (
        'The full API: thinking, web search, link reading, safety review and conversation titles.'
    ),
    'ai.providerNote.opencode_go': (
        'The OpenCode Go plan, intended for coding-agent traffic; general analysis chat may be rate-limited.'
    ),
    'ai.providerNote.openrouter': (
        'The existing OpenAI-compatible route; free models work, but there is no server-side web or file capability.'
    ),
    'ai.providerNote.ollama': 'The local daemon; unavailable in cloud mode.',
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
    'ai.localCloud': (
        'A cloud host has no local model daemon, so {provider} is unavailable. Use DeepSeek, OpenCode Go or OpenRouter.'
    ),
    'ai.noKey': 'This provider needs an API key. Fill it in under AI settings first.',
    'ai.capabilityRefused': (
        '{provider} model {model} does not support “{capability}”; nothing was silently downgraded.'
    ),
    'ai.skillUnavailable': 'Skill “{skill}” needs “{capability}”, which {provider} does not offer.',
    'ai.skillCodeLocal': (
        'Skill “{skill}” needs local source access; enable it in AI settings and run on a local/desktop host.'
    ),
    'ai.skillUnknown': 'Unknown skill: {skill}',
    'ai.skillBadTool': 'Skill “{skill}” names a tool that does not exist: {tool}',
    'ai.skillBadContext': 'Skill “{skill}” names a context source that does not exist: {source}',
    'ai.skillBadId': 'A skill id may only contain lowercase letters, digits, dots, underscores and hyphens: {skill}',
    'ai.skillNoPrompt': 'A skill needs a prompt: {skill}',
    'ai.skillExists': 'A built-in skill cannot be overwritten; fork it into your own skill first.',
    'ai.toolUnknown': 'Unknown tool: {tool}',
    'ai.toolRefused': 'Tool “{tool}” was refused: {reason}',
    'ai.cancelled': 'Generation stopped.',
    'ai.streamFailed': 'The AI stream failed ({kind}).',
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
