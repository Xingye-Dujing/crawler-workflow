"""Words for the environment matrix and the component manager.

Every reason is a key with parameters, never a sentence assembled in a probe: the installer, the
CLI report and the browser panel all render the same fact in the language of whoever is looking.
"""

ZH = {
    'env.capAnalysis': '上传 / 分析 / 报告',
    'env.capBert': '微调 BERT 分析',
    'env.capBrowser': '网页采集（Selenium）',
    'env.capCatbus': 'CatBus 采集',
    'env.capCore': '主程序',
    'env.capFont': '中文图表',
    'env.capLlmCloud': '云端 LLM（OpenRouter）',
    'env.capLlmLocal': '本机 LLM（Ollama）',
    'env.capPdf': 'PDF / 论文编译',
    'env.analysisOk': '不依赖外部程序',
    'env.bertNoModels': 'BERT 运行时在，但没有可用的微调模型；相关节点会降级到 ml/snownlp 并打印',
    'env.bertOk': '可用模型：{models}',
    'env.bertRuntimeMissing': '缺少 onnxruntime，打包版应自带；这不是用户需要安装的组件',
    'env.browserAndDriverMissing': '没有找到 Chrome，也没有找到匹配的 chromedriver',
    'env.browserMissing': '没有找到 Chrome；可以安装便携版或使用本机已装的 Chrome',
    'env.browserConfiguredMissing': '设置里的浏览器路径不存在：{path}；改正它，或清空让程序自己找 Chrome',
    'env.browserOk': 'Chrome 与 chromedriver 已就绪',
    'env.catbusOk': 'Node {node}，适配器 {entry}',
    'env.catbusUnknown': '无法核对 CatBus（探测本身失败）',
    'env.cloudUnknown': '需要 API Key，未在此处核对',
    'env.coreOk': '应用已启动',
    'env.driverMismatch': 'Chrome {chrome_major} 与 chromedriver {driver_major} 大版本不一致',
    'env.driverAutoDownload': '没有配置 chromedriver；首次采集会由 Selenium 自动下载匹配版本（需要网络）',
    'env.driverConfiguredMissing': '设置里的驱动路径不存在：{path}',
    'env.driverUnverified': '找到 Chrome 与 chromedriver，但读不出版本，无法核对是否成对',
    'env.fontMissing': '没有中文字体；汉字会画成方框（不影响运行，但会写进论文）',
    'env.fontOk': '使用字体 {family}',
    'env.ollamaMissing': '连不上 {host}；可以安装本机 Ollama，或改用云端 API',
    'env.ollamaNoModel': 'Ollama 在运行，但还没有拉取任何模型',
    'env.ollamaOk': '已拉取模型：{models}',
    'env.ollamaUnreadable': 'Ollama 有响应，但模型列表读不出来：{err}',
    'env.xelatexMissing': '没有找到 xelatex；只影响 PDF / 论文编译',
    'env.xelatexOk': '使用 {path}',
    'env.sourceTitle': '组件来源',
    'env.sourceBundled': '安装器安装的（默认）',
    'env.sourceSystem': '本机已安装的',
    'env.sourceHint': (
        '安装器安装的：只查安装器的组件目录，缺了直接报错，不会退回本机；本机已安装的：只查本机。重启采析绘后生效。'
    ),
    'env.sourceFailed': '切换组件来源失败：{err}',
    'env.sourceComponent': '安装器',
    'env.sourceSystemNow': '本机',
    'env.sourceSettings': '设置里指定',
    'env.sourceInstallerMissing': '安装器未装',
    'env.installerBrowserMissing': (
        '安装器没有安装 Chrome（当前组件来源是“安装器安装的”，不会改用本机的 Chrome）；'
        '请在“环境与组件”里安装，或把组件来源切到“本机已安装的”后重启'
    ),
    'env.installerDriverMissing': (
        '安装器没有安装 chromedriver（当前组件来源是“安装器安装的”，不会让 Selenium 另下一个）；'
        '请在“环境与组件”里安装，或把组件来源切到“本机已安装的”后重启'
    ),
    'components.catalogFailed': '组件清单读取失败：{err}',
    'components.installStarted': '正在安装 {component}；进度见任务状态',
    'components.jobMissing': '找不到这个安装任务',
    'components.removeFailed': '无法卸载 {component}：{err}',
    'env.remove': '卸载',
    'env.removeConfirm': '卸载 {id}？只会删除组件文件，用户数据不受影响。',
    'env.removed': '{id} 已卸载',
    'env.restartHint': '组件已装好；重启采析绘后，采集和运行会使用新组件。',
    'components.unknown': '没有这个组件：{component}（{err}）',
    'components.notDownloadable': '“{component}”只做检测，不由安装器下载；请按说明自行安装',
    'components.appNotSelfInstallable': '主程序更新请重新运行在线安装器：运行中的应用不能替换自己',
}

EN = {
    'env.capAnalysis': 'Upload / analysis / reports',
    'env.capBert': 'Fine-tuned BERT analysis',
    'env.capBrowser': 'Web crawling (Selenium)',
    'env.capCatbus': 'CatBus crawling',
    'env.capCore': 'Application',
    'env.capFont': 'Chinese charts',
    'env.capLlmCloud': 'Cloud LLM (OpenRouter)',
    'env.capLlmLocal': 'Local LLM (Ollama)',
    'env.capPdf': 'PDF / paper compile',
    'env.analysisOk': 'No external program needed',
    'env.bertNoModels': (
        'The BERT runtime is present but no fine-tuned model is; those nodes fall back to ml/snownlp and print it'
    ),
    'env.bertOk': 'Models available: {models}',
    'env.bertRuntimeMissing': (
        'onnxruntime is missing; the packaged build should carry it, so this is not a user component'
    ),
    'env.browserAndDriverMissing': 'No Chrome and no matching chromedriver were found',
    'env.browserMissing': 'No Chrome was found; install the portable copy or use the Chrome already on this machine',
    'env.browserConfiguredMissing': (
        'The browser path in settings does not exist: {path}. Correct it, or clear it so the app finds Chrome itself'
    ),
    'env.browserOk': 'Chrome and chromedriver are ready',
    'env.catbusOk': 'Node {node}, adapter {entry}',
    'env.catbusUnknown': 'CatBus could not be checked (the probe itself failed)',
    'env.cloudUnknown': 'Needs an API key; not checked here',
    'env.coreOk': 'The application is running',
    'env.driverMismatch': 'Chrome {chrome_major} and chromedriver {driver_major} are different major versions',
    'env.driverAutoDownload': (
        'No chromedriver is configured; the first crawl lets Selenium download a matching one (needs network)'
    ),
    'env.driverConfiguredMissing': 'The driver path in settings does not exist: {path}',
    'env.driverUnverified': (
        'Chrome and chromedriver were found but neither version could be read, so the pair is unverified'
    ),
    'env.fontMissing': 'No Chinese font; Han characters draw as boxes (the app runs, but a paper would show it)',
    'env.fontOk': 'Using {family}',
    'env.ollamaMissing': 'Cannot reach {host}; install local Ollama or use a cloud API',
    'env.ollamaNoModel': 'Ollama is running but has no pulled model',
    'env.ollamaOk': 'Models pulled: {models}',
    'env.ollamaUnreadable': 'Ollama answered but its model list could not be read: {err}',
    'env.xelatexMissing': 'xelatex was not found; only PDF / paper compilation is affected',
    'env.xelatexOk': 'Using {path}',
    'env.sourceTitle': 'Component source',
    'env.sourceBundled': 'Installed by the installer (default)',
    'env.sourceSystem': 'Already on this machine',
    'env.sourceHint': (
        'Installer copy: only the installer’s component folder is searched; a missing component is an '
        'error, never a fallback to this machine. Machine copy: only this machine is searched. '
        'Takes effect after restarting CaiXiHui.'
    ),
    'env.sourceFailed': 'Could not change the component source: {err}',
    'env.sourceComponent': 'installer',
    'env.sourceSystemNow': 'machine',
    'env.sourceSettings': 'from settings',
    'env.sourceInstallerMissing': 'not installed by the installer',
    'env.installerBrowserMissing': (
        'The installer did not install Chrome (the component source is “Installed by the installer”, so '
        'this machine’s Chrome is not used). Install it under Environment & components, or switch the '
        'source to “Already on this machine” and restart'
    ),
    'env.installerDriverMissing': (
        'The installer did not install chromedriver (the component source is “Installed by the installer”, '
        'so Selenium will not download one). Install it under Environment & components, or switch the '
        'source to “Already on this machine” and restart'
    ),
    'components.catalogFailed': 'The component catalogue could not be read: {err}',
    'components.installStarted': 'Installing {component}; the job status carries the progress',
    'components.jobMissing': 'That installation job does not exist',
    'components.removeFailed': 'Could not remove {component}: {err}',
    'env.remove': 'Uninstall',
    'env.removeConfirm': 'Uninstall {id}? Only the component files are deleted; user data is untouched.',
    'env.removed': '{id} uninstalled',
    'env.restartHint': 'Component installed; restart CaiXiHui so crawling and runs pick it up.',
    'components.unknown': 'No such component: {component} ({err})',
    'components.notDownloadable': '"{component}" is only detected, never downloaded; install it the documented way',
    'components.appNotSelfInstallable': (
        'To update the application, run the online installer again: a running app cannot replace itself'
    ),
}
