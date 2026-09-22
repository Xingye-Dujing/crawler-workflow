/* Main Application Entry */

/* Console i18n: every request carries the UI language as X-Lang, so the log
   lines the server streams into the console (crawl progress, LLM batches,
   errors) come back in the language being read. Patching fetch once covers
   every call site, including the ones added later. */
(function () {
    const nativeFetch = window.fetch.bind(window);
    window.fetch = function (input, init) {
        let lang = 'zh';
        try {
            lang = (typeof I18n !== 'undefined' && I18n.lang) || document.body.dataset.lang || 'zh';
        } catch (e) { /* keep the default */ }
        try {
            const opts = Object.assign({}, init || {});
            opts.headers = new Headers((init && init.headers) || (input instanceof Request ? input.headers : undefined) || undefined);
            if (!opts.headers.has('X-Lang')) opts.headers.set('X-Lang', lang);
            return nativeFetch(input, opts);
        } catch (e) {
            return nativeFetch(input, init);
        }
    };
})();

/* I18n - Internationalization */
const I18n = {
    lang: 'en',
    dict: {
        en: {
            'menu.file': 'File', 'menu.save': 'Save', 'menu.load': 'Load', 'menu.new': 'New',
            'menu.edit': 'Edit',
            'menu.view': 'View', 'btn.bg': 'BG',
            'menu.style': 'Style', 'style.bg': 'Background', 'style.radius': 'Radius',
            'btn.zoomin': 'Zoom+', 'btn.zoomout': 'Zoom-', 'btn.fit': 'Fit',
            'menu.run': 'Run', 'btn.execute': 'Execute', 'btn.running': 'Running...', 'btn.stop': 'Stop',

            'btn.parallel': 'Parallel', 'btn.headless': 'Headless',
            'menu.nodes': 'Nodes', 'btn.src': '+Src', 'btn.proc': '+Proc', 'btn.out': '+Out',
            'menu.lang': 'Lang', 'pin.title': 'Pin menu',
            'bg.void': 'Void', 'bg.grid': 'Grid', 'bg.dots': 'Dots',
            'bg.cross': 'Cross', 'bg.diagonal': 'Diagonal',
            'palette.header': 'Node Library',
            'palette.cat.workflow': 'Workflow',
            'palette.cat.inputs': 'Data Inputs',
            'palette.cat.process': 'Processing',
            'palette.cat.outputs': 'Outputs',
            'palette.source': 'Data Source', 'palette.upload': 'Upload File', 'palette.process': 'Process', 'palette.output': 'Output',
            'palette.resume': 'Resume Run', 'palette.name': 'Workflow Name',
            'node.source': 'Data Source', 'node.upload': 'Upload File', 'node.process': 'Process',
            'node.analysis': 'Analysis', 'node.visualize': 'Visualize', 'node.tokenize': 'Tokenize', 'node.output': 'Output',
            'node.resume': 'Resume Run', 'node.name': 'Workflow Name',
            'node.comment': 'Comments',
            /* Resumable runs: everything happens while nobody is watching, so
               the wording has to state what is already paid for. */
            'resume.continue': 'Continue', 'resume.restart': 'Start over', 'resume.dismissTitle': 'Dismiss',
            'resume.interrupted': 'Interrupted run found ({at})',
            'resume.detail': '{done}/{total} nodes done, {rows} rows saved — continue picks up from there',
            'resume.incomplete': '{rows} rows saved before it stopped',
            'resume.runSelect': 'Saved run', 'resume.nodeSelect': 'Node output',
            'resume.autoNode': 'Biggest table (auto)',
            'resume.limit': 'Row limit', 'resume.limitPlaceholder': '0 = all',
            'resume.refresh': 'Refresh list', 'resume.none': 'No saved run yet — run this workflow once',
            'resume.hint': 'Reads a node\'s stored rows from a previous run, with no need to crawl again',
            'toast.resumeStarted': 'Continuing the interrupted run',
            'toast.runDiscarded': 'Saved run discarded — starting fresh',
            'settings.file': 'File', 'settings.rows': 'rows',
            'stats.header': 'Statistics', 'stats.close': 'Close',
            'stats.emotion': 'Emotion', 'stats.tendency': 'Tendency',
            'settings.header': 'Node Settings', 'settings.close': 'Close',
            'status.ready': 'Ready', 'status.completed': 'Completed', 'status.running': 'Running...',
            'ctx.newSource': 'New Source Node', 'ctx.newUpload': 'New Upload Node',
            'ctx.newProcess': 'New Process Node',
            'ctx.newOutput': 'New Output Node', 'ctx.edit': 'Edit Node', 'ctx.rename': 'Rename Node',
            'ctx.renameHint': 'Double-click to rename',
            'ctx.copy': 'Copy Node', 'ctx.paste': 'Paste Node',
            'ctx.delete': 'Delete Node', 'ctx.clear': 'Clear All Connections',
            'btn.lang': 'EN',
            'btn.cookies': 'Cookies',
            'console.header': 'Console', 'console.clear': 'Clear', 'console.close': 'Close', 'console.popout': 'Pop', 'console.dock': 'Dock',
            'console.all': 'All',
            'processes.header': 'Processes', 'processes.close': 'Close',
            'processes.running': 'Running', 'processes.stopped': 'Stopped',
            'processes.threads': 'Threads', 'processes.crawlers': 'Crawlers',
            'processes.pool': 'Pool Active', 'processes.yes': 'Yes', 'processes.no': 'No',
            'processes.name': 'Name', 'processes.status': 'Status', 'processes.type': 'Type',
            'processes.daemon': 'Daemon', 'processes.alive': 'Alive', 'processes.kill': 'Kill',
            'cookies.header': 'Cookie Settings', 'cookies.platform': 'Platform',
            'cookies.paste': 'Paste Cookies JSON', 'cookies.save': 'Save Cookies',
            'cookies.generate': 'Generate via Browser', 'cookies.waitTime': 'Wait time (seconds) for login:',
            'cookie.opening': 'Opening browser for {platform} login (waiting {s}s)...',
            'cookie.generated': 'Cookies generated for {platform}',
            'cookie.failed': 'Failed: {err}',
            'cookie.unreachable': 'Cannot reach the server (it may be starting or reloading) — try again shortly',
            'cookies.doneBtn': 'Done — I logged in',
            'cookies.cancelBtn': 'Cancel login',
            'cookie.mustStay': 'Login in progress — press Done or Cancel first, this window must stay open',
            'cookie.waiting': '{platform} login window open — finish logging in, then press Done',
            'cookies.entryUrl': 'Login entry link (optional: empty opens the platform login page)',
            'cookies.verify': 'Verify cookie',
            'cookie.verifying': 'Probing the platform with the stored cookie…',
            'cookie.guideLoading': 'Loading the steps for this platform…',
            'cookie.entryRejected': 'That link is not on this platform’s domain — the platform login page was opened instead',
            'cookie.savedN': 'Saved {n} cookies for {platform}',
            'cookie.cancelledMsg': '{platform} login cancelled',
            'settings.recrawl': 'Re-crawl (ignore previously collected items)',
            'settings.recrawlHint': 'Off by default: items already collected by this node are skipped to save time and cost. Enable to wipe that ledger and collect again.',
            'cookie.invalidJson': 'Invalid JSON: {err}',
            'cookie.pasteFirst': 'Paste the cookies JSON first',
            'toast.nodeDeleted': 'Node deleted',
            'toast.connCreated': 'Connection created',
            'toast.connRemoved': 'Connection removed',
            'toast.connCleared': 'All connections cleared',
            'toast.nodeCopied': 'Node copied',
            'toast.nodePasted': 'Node pasted',
            'toast.newWorkflow': 'New workflow',
            'toast.workflowSaved': 'Workflow saved',
            'toast.workflowLoaded': 'Workflow loaded',
            'toast.workflowStarted': 'Workflow started',
            'toast.workflowCompleted': 'Workflow completed',
            'toast.pollFailed': 'Lost contact with the server — status refresh stopped',
            'toast.workflowStopped': 'Workflow stopped',
            'toast.noWorkflows': 'No saved workflows',
            'toast.saveFailed': 'Save failed',
            'toast.loadFailed': 'Load failed',
            'toast.executeFailed': 'Execute failed',
            'toast.stopFailed': 'Stop failed',
            'toast.cookiesSaved': 'Cookies saved',
            'toast.cookiesMissing': 'Cookies not configured for platform. Please set cookies first:',
            'dialog.workflowName': 'Workflow name:',
            'dialog.selectWorkflow': 'Enter workflow name to load:',
            'dialog.cancel': 'Cancel',
            'dialog.confirm': 'Confirm',
            'dialog.renameNode': 'Rename this node — the console will say its name instead of node-N:',
            'dialog.cookieConfirm': 'This run crawls live sites. Have the cookies gone a while without refresh? You can exit, update them under Settings → Cookie, and resume from the checkpoint — or run now.',
            'dialog.cookieGoOn': 'Run anyway',
            'dialog.cookieExit': 'Exit & refresh Cookie',
            'toast.cookieExpired': 'Login wall hit — the cookie likely expired mid-run. Collected data is saved: refresh it under Settings → Cookie, then resume this run.',
            'settings.nodeType': 'Node Type',
            'settings.platform': 'Platform',
            'settings.collect': 'Collect',
            'settings.collectPosts': 'Posts / articles',
            'settings.collectComments': 'Comments',
            'settings.keyword': 'Keyword',
            'settings.targetCount': 'Target Count',
            'settings.startTime': 'Start Time',
            'settings.endTime': 'End Time',
            'settings.operation': 'Operation',
            'settings.textColumn': 'Text Column',
            'settings.topic': 'Topic',
            'settings.filename': 'Filename',
            'settings.workflowName': 'Workflow name',
            'nodeType.source': 'Data Source',
            'nodeType.upload': 'Upload File',
            'nodeType.process': 'Process',
            'nodeType.analysis': 'Analysis',
            'nodeType.visualize': 'Visualize',
            'nodeType.tokenize': 'Tokenize',
            'nodeType.resume': 'Resume Run', 'nodeType.name': 'Workflow Name',
            'nodeType.output': 'Output',
            'nodeType.comment': 'Comments',
            'op.clean': 'Clean',
            'op.emotion': 'Emotion',
            'op.tendency': 'Tendency',
            'op.save_csv': 'Save CSV',
            'op.save': 'Save',
            'op.chart': 'Chart',
            'op.drop_null': 'Drop Null Rows',
            'op.fill_null': 'Fill Null Values',
            'op.drop_duplicates': 'Drop Duplicates',
            'op.filter_rows': 'Filter Rows',
            'op.select_columns': 'Select Columns',
            'op.rename_columns': 'Rename Column',
            'op.strip_whitespace': 'Strip Whitespace',
            'op.convert_type': 'Convert Type',
            'platform.zhihu': 'Zhihu',
            'platform.weibo': 'Weibo',
            'platform.xiaohongshu': 'Xiaohongshu',
            'platform.wechat': 'WeChat',
            'platform.bilibili': 'Bilibili',
            'platform.douyin': 'Douyin',
            'btn.analysis': '+Analysis',
            'btn.visualize': '+Chart',
            'btn.tokenize': '+Tokenize',
            'btn.uploadFile': 'Upload File',
            'btn.preview': 'Preview Chart',
            'palette.analysis': 'Analysis',
            'palette.visualize': 'Visualize',
            'palette.tokenize': 'Tokenize',
            'ctx.newAnalysis': 'New Analysis Node',
            'ctx.newVisualize': 'New Visualize Node',
            'ctx.newTokenize': 'New Tokenize Node',
            'chart.header': 'Chart Preview',
            'chart.bar': 'Bar', 'chart.line': 'Line', 'chart.pie': 'Pie',
            'chart.scatter': 'Scatter', 'chart.histogram': 'Histogram', 'chart.box': 'Box Plot',
            'chart.heatmap': 'Heatmap', 'chart.wordcloud': 'Word Cloud',
            'chart.sankey': 'Sankey Diagram', 'chart.map': 'Map (China)',
            'format.csv': 'CSV', 'format.json': 'JSON', 'format.excel': 'Excel (.xlsx)',
            'format.txt': 'Text (.txt)', 'format.html': 'HTML', 'format.markdown': 'Markdown',
            'settings.format': 'Format',
            'settings.columns': 'Columns',
            'settings.column': 'Column',
            'settings.value': 'Value',
            'settings.filterOp': 'Condition',
            'settings.renameFrom': 'Rename From',
            'settings.renameTo': 'Rename To',
            'settings.dtype': 'Target Type',
            'settings.tokenizeUpstream': 'From Tokenize (auto-configured)',
            'settings.tokenizeOutputLocked': 'Output mode locked to Word Frequency (required by downstream Visualize node)',
            'settings.chartType': 'Chart Type',
            'settings.engine': 'Render Engine',
            'settings.xField': 'X Field',
            'settings.yField': 'Y Field (optional)',
            'settings.agg': 'Aggregation',
            'settings.title': 'Chart Title',
            'settings.dataSource': 'Data Source',
            'dataSource.loaded': 'Loaded',
            'dataSource.none': 'No file uploaded yet',
            'dataSource.persisted': 'Stored in the database — still attached after a refresh or reopening this workflow',
            'toast.datasetsMissing': 'These Upload nodes need their file re-uploaded',
            'toast.datasetUploaded': 'Dataset uploaded',
            'toast.txtUploaded': 'Text file uploaded — ready for word cloud',
            'toast.uploadFailed': 'Upload failed',
            'toast.previewNeedsUpload': 'Upload a CSV/JSON file in this upload node first',
            'toast.previewNeedsInput': 'Connect an upstream node and run the workflow first',
            'toast.renderFailed': 'Chart render failed',
            'toast.previewFailed': 'Data preview failed',
            'toast.mapLoadFailed': 'Failed to load map data (check network access)',
            'settings.xFieldCat1': 'Category 1',
            'settings.yFieldCat2': 'Category 2',
            'settings.sourceField': 'Source Field',
            'settings.targetField': 'Target Field',
            'settings.textField': 'Text Field',
            'settings.regionField': 'Region Field',
            'settings.valueField': 'Value Field (optional)',
            'settings.tokenize': 'Tokenize free text (jieba word segmentation)',
            'settings.outputMode': 'Output Mode',
            'outputMode.word_freq': 'Word Frequency',
            'outputMode.words_only': 'Word List',
            'outputMode.csv_line': 'Space-separated Line',
            'settings.topN': 'Top-N words',
            'settings.topNPlaceholder': 'empty = all words',
            'settings.wordcloudStyle': 'Word Cloud Style',
            'wordcloudStyle.vibrant': 'Vibrant',
            'wordcloudStyle.monoBlue': 'Mono Blue',
            'wordcloudStyle.monoOrange': 'Mono Orange',
            'wordcloudStyle.pastel': 'Pastel',
            'wordcloudStyle.ocean': 'Ocean',
            'wordcloudStyle.sunset': 'Sunset',
            'wordcloudStyle.forest': 'Forest',
            'warn.echartsOnly': 'This chart type only renders with the ECharts engine',
            'hint.mapRegionNames': 'Region names should match Chinese province names (e.g. 广东省, 北京市)',
            'menu.data': 'Data',
            'btn.dashboard': 'Dashboard',
            'btn.history': 'History',
            'btn.studio': 'Chart Studio',
            'studio.title': 'CHART STUDIO',
            'studio.subtitle': 'ZENVIZ · WORKFLOW',
            'studio.source': 'Source',
            'studio.load': 'Load Data',
            'studio.saveBack': 'Export Image',
            'studio.close': 'Close',
            'studio.noNodes': 'No data-producing node on the canvas yet',
            'studio.pickSource': 'Pick a node to pull data from',
            'studio.loading': 'Loading dataset…',
            'studio.loaded': '{rows} rows · {cols} columns loaded into the studio',
            'studio.loadFailed': 'Failed to load dataset',
            'studio.noResult': 'No tabular data on the canvas yet — run the workflow once first',
            'studio.fallback': '"{a}" has no data yet — loaded "{b}" instead',
            'studio.saved': 'Image exported to {path}',
            'studio.saveFailed': 'Failed to export image',
            'studio.ready': 'Studio ready',
            'studio.booting': 'Starting studio…',
            'studio.noChart': 'Render a chart first, then export it',
            'studio.emptyData': 'That node has no tabular result yet — run the workflow first',
            /* Source picker: why a node cannot be chosen. Two forms — the short
               one fits inside the dropdown row, the long one is what the
               tooltip, toast and status line say. */
            'studio.src.none': 'No node can supply data yet — run the workflow first',
            'studio.src.rows': '{rows} rows',
            'studio.src.noUpstream': 'Nothing is connected upstream, so there is no table to read',
            'studio.src.noUpstreamShort': 'no upstream input',
            'studio.src.noResult': 'This node has not produced a result yet — run the workflow first',
            'studio.src.noResultShort': 'no data yet',
            'studio.src.staleDataset': 'That uploaded dataset is gone (the server restarted) — upload it again',
            'studio.src.staleDatasetShort': 'dataset expired',
            'studio.src.empty': 'This node produced an empty table',
            'studio.src.emptyShort': 'empty table',
            'studio.src.probeFailed': 'Could not check what this node holds',
            'studio.src.probeFailedShort': 'check failed',
            'studio.pickMulti': 'Pick one or more nodes',
            'studio.src.tip': '{rows} rows · {cols} columns: {names}',
            'studio.src.selection': '{n} nodes selected · {rows} rows in total',
            'studio.multiCount': '{n} nodes selected',
            'studio.merge': 'Combine',
            'studio.merge.rows': 'Place below',
            'studio.merge.side': 'Place to the right',
            'studio.loadedMerged': 'Merged {n} sources · {rows} rows · {cols} columns',
            'studio.mergedSkipped': '{n} source(s) unavailable',
            'studio.mergedName': '{n} nodes merged',
            'studio.menu.engine': 'Engine',
            'studio.menu.data': 'Data',
            'studio.menu.style': 'Style',
            'studio.menu.export': 'Export',
            'btn.previewData': 'Preview Data',
            'btn.prev': 'Prev',
            'btn.next': 'Next',
            'btn.refresh': 'Refresh',
            'dataPreview.header': 'Data Preview',
            'dataPreview.rows': 'Rows',
            'dataPreview.columns': 'Columns',
            'dashboard.header': 'Dashboard',
            'dashboard.empty': 'No Visualize nodes on the canvas yet — add one to see it here.',
            'dashboard.noData': 'No data yet — connect an upstream node and run the workflow, or set Data Source to Upload.',
            'history.header': 'Execution History',
            'history.allWorkflows': 'All workflows',
            'history.metric.emotion': 'Emotion',
            'history.metric.tendency': 'Tendency',
            'history.metric.rows': 'Row Count',
            'history.runId': 'Run ID',
            'history.workflowName': 'Workflow',
            'history.startedAt': 'Started At',
            'history.metricCount': 'Metrics',
            'history.empty': 'No execution history yet — run a workflow first.',
            'history.clearAll': 'Clear History',
            'history.confirmClear': 'This will permanently delete all recorded execution history. Continue?',
            'history.cleared': 'Execution history cleared',
            'settings.mode': 'Analysis Mode',
            'mode.llm': 'LLM (local Ollama / OpenRouter)',
            'mode.ml': 'Traditional ML (sklearn)',
            'btn.ai': 'AI',
            'ai.provider': 'Provider',
            'ai.provider.ollama': 'Local Ollama',
            'ai.provider.openrouter': 'OpenRouter API',
            'ai.model': 'Model',
            'ai.localModels': 'Local models',
            'ai.ollamaHost': 'Server address',
            'ai.ollamaHostNote': 'Edit the Ollama address in the Settings panel',
            'ai.freeModels': 'Free models',
            'ai.refreshModels': '— click Refresh to load —',
            'ai.refresh': 'Refresh',
            'ai.pickModel': 'Pick a model…',
            'ai.key': 'API Key',
            'ai.test': 'Test connection',
            'ai.testing': 'Testing…',
            'ai.batch': 'Save every N rows',
            'ai.maxChars': 'Truncate row at (chars)',
            'ai.hintTitle': 'How the AI is called',
            'ai.hint1':
                'One row = one message = one API call, processed line by line. ' +
                'Large tables are slow and burn a lot of tokens — the longer the ' +
                'text, the more tokens each row costs. Keep an eye on your data size.',
            'ai.hint2': 'Free models are completely enough — no need to pay. Try a small batch first, then scale up.',
            'ai.hint3':
                'Results are saved in batches: if something breaks or you stop midway, ' +
                'finished rows are kept, and re-running resumes from the checkpoint.',
            'ai.keyNote': 'The API key is stored only in this browser (localStorage) — never written to server files.',
            'ai.ollamaNote':
                'Ollama: the model name must be one the daemon already has (press Refresh to list them); ' +
                'the server address is edited in the Settings panel. The two providers keep separate models.',
            'toast.aiTestOk': 'AI connection OK ({ms} ms)',
            'toast.aiTestFail': 'AI connection failed',
            'toast.aiNeedKey': 'Please fill in the OpenRouter API Key first',
            'toast.aiNeedModel': 'Please pick an OpenRouter model first',
            'toast.aiNeedOllamaModel': 'Please set an Ollama model first (Refresh lists the local ones)',
            'toast.aiModelsLoaded': 'Loaded {n} models',
            'toast.ollamaNoModels': 'The Ollama daemon has no model pulled yet (run “ollama pull …”)',
            'toast.aiModelsFail': 'Failed to load model list',
            'btn.settings': 'Settings',
            'set.driver': 'Browser driver path',
            'set.binary': 'Browser binary path',
            'set.window': 'Window size',
            'set.pageLoad': 'Page load timeout (s)',
            'set.elementWait': 'Element wait timeout (s)',
            'set.ollamaHost': 'Ollama server address',
            'set.cookieConfirm': 'Confirm Cookie before run',
            'set.cookieConfirmInline': 'Ask every time a run contains a crawler node',
            'set.save': 'Save settings',
            'set.note':
                'Machine-local settings. Saved to data/settings.json on the server ' +
                'and applied from the next execution — no restart needed.',
            'toast.setSaved': 'Settings saved',
            'toast.setSavedWarn': 'Settings saved, with warnings:',
            'toast.setSaveFail': 'Failed to save settings',
            'toast.setNoChange': 'No changes to save',
            'op.keyword': 'Keyword Extraction',
            'op.cluster': 'Text Clustering',
            'op.ner': 'Named Entity Recognition',
            'op.anomaly': 'Anomaly Detection',
            'op.correlation': 'Correlation Analysis',
            'op.sort_rows': 'Sort Rows',
            'op.sample_rows': 'Sample Rows',
            'op.groupby_agg': 'Group By & Aggregate',
            'op.join_tables': 'Join Tables',
            'op.column_calc': 'Column Calculation',
            'op.bin_column': 'Bin Numeric Column',
            'settings.method': 'Method',
            'settings.topk': 'Top-K',
            'settings.merge': 'Merge results',
            'settings.clusterMethod': 'Clustering Method',
            'settings.nClusters': 'Number of Clusters',
            'settings.eps': 'Epsilon (DBSCAN)',
            'settings.minSamples': 'Min Samples (DBSCAN)',
            'settings.nerMethod': 'NER Method',
            'settings.contamination': 'Contamination',
            'settings.corrMethod': 'Correlation Method',
            'settings.minAbs': 'Min Absolute Correlation',
            'settings.ascending': 'Ascending',
            'settings.n': 'Sample Count (N)',
            'settings.frac': 'Sample Fraction',
            'settings.seed': 'Random Seed',
            'settings.groupCol': 'Group Column',
            'settings.aggCol': 'Aggregate Column',
            'settings.aggFunc': 'Aggregate Function',
            'settings.joinHow': 'Join Type',
            'settings.leftOn': 'Left Key',
            'settings.rightOn': 'Right Key',
            'settings.newCol': 'New Column Name',
            'settings.urls': 'Article URLs',
            'settings.urlsHint': 'One URL per line — WeChat crawls these articles',
            'settings.commentUrls': 'Article Links',
            'settings.commentUrlsHintPlat': 'One article link per line — must match the selected platform ({plat})',
            'settings.wechatLimitsNote': 'WeChat: comments / likes / forwards cannot be collected — see why',
            'settings.wechatLimitsBtn': 'Why not WeChat comments / likes / forwards?',
            'settings.wechatLimitsBody':
                'WeChat delivers the article body to anyone, but keeps 留言 (comments), 点赞数 (likes) and ' +
                '转发数 (forwards) — and usually 阅读数 too — behind a credential its server mints only for a ' +
                'recognised WeChat client session.\n\n' +
                'Measured against real articles in a real browser: the page sets show_comment=0 and carries no ' +
                'comment data at all, while the comment endpoint replies with an HTML page saying ' +
                '请在微信客户端打开链接. Changing the user agent, reshaping the URL or replaying the client’s own ' +
                'cookies does not change that answer, and this project will not impersonate the WeChat client to ' +
                'get around the site’s access control.\n\n' +
                'The decisive reason for not guessing: in a browser, “this article has no comments” and “this visit ' +
                'was not allowed to see them” look exactly the same. Returning an empty table would hand you ' +
                'plausible-looking data that is really a failure, so WeChat is limited to what it genuinely ' +
                'serves — the article text — and comments are offered for 知乎 / 微博 / 小红书 instead.',
            'settings.commentUrlsHintMixed': 'One link per line; Zhihu / Weibo / Xiaohongshu may be mixed — each link is routed by its own domain',
            'settings.commentLimit': 'Comments Limit',
            'settings.commentLimitHint': '0 = every comment',
            'settings.partSize': 'Part Size',
            'settings.partSizeHint': '0 = no part files, one merged file',
            'settings.sourcePartSizeHint': '0 = off. Above 0, every N crawled rows flush to a numbered part file you can open during the run; parts merge into one at the end.',
            'settings.liveExport': 'Live export (per batch)',
            'settings.liveExportHint': 'Rewrites a {node}.live file after every batch so you can watch results before the node finishes.',
            'settings.perArticleFile': 'One output file per article',
            'settings.keepParts': 'Keep part files after merge',
            'settings.commentHint': 'Crawling opens a visible browser window (Zhihu blocks headless mode); every part_size comments are written as a part file into the export directory.',
            'settings.joinHint': 'The right-hand table comes from this node\'s second incoming connection',
            'settings.expr': 'Expression',
            'settings.binNewCol': 'Binned Column Name',
            'settings.dropHow': 'Drop row when',
            'settings.dropHowAny': 'any selected column is empty',
            'settings.dropHowAll': 'every selected column is empty',
            'settings.fillMethod': 'Fill method',
            'settings.fillMethodValue': 'use the value above',
            'settings.binEdges': 'Bins (count, or edges like 0, 60, 80, 100)',
            'settings.binLabels': 'Bin labels (optional, one per interval)',
            'settings.trainModel': 'Train ML Model',
            'settings.trainFrom': 'Train from this dataset',
            'toast.modelTrained': 'ML model trained successfully',
            'toast.modelTrainFailed': 'ML model training failed',
            'canvas.undo': 'Undo',
            'canvas.redo': 'Redo',
            'canvas.fold': 'Fold Node',
            'canvas.unfold': 'Unfold Node',
            'canvas.autoLayout': 'Auto Layout',
            'status.nodes': 'Nodes: ', 'status.progress': 'Progress: {done}/{total}',
            'toast.layoutApplied': 'Layout applied',
            'summary.tokenizeTop': ' | Top-{n}',
            'settings.textColumnPlaceholder': 'e.g. content text field',
            'toast.mlUpstreamNeeded': 'Please connect an upstream node with labeled data first',
            'toast.languageChanged': 'Language: {lang}',
            'validate.empty': 'Workflow is empty',
            'validate.sourceKeyword': 'Source node "{title}": keyword cannot be empty',
            'validate.sourceDownstream': 'Source node "{title}": must connect to a downstream node',
            'validate.sourceUrls': 'Source node "{title}": WeChat needs at least one article URL',
            'validate.sourceCommentUrls': 'Source node "{title}": comments mode needs at least one article URL',
            'validate.sourceCommentPlat': 'Source node "{title}": {n} link(s) do not match the selected platform ({plat})',
            'validate.joinNeedsTwo': 'Analysis node "{title}": joining needs two input connections (left table, right table)',
            'validate.uploadFile': 'Upload node "{title}": no file uploaded yet',
            'validate.uploadDownstream': 'Upload node "{title}": must connect to a downstream node',
            'validate.nameEmpty': 'Name node "{title}": workflow name cannot be empty',
            'validate.nameMustLead': 'Name node "{title}": must be the first node — nothing should feed into it',
            'validate.nameDownstream': 'Name node "{title}": connect it to a downstream node',
            'name.hint': 'This name labels the run in the Execution History panel.',
            'name.unnamed': 'Untitled',
            'runsMgr.header': 'Run Records',
            'exportsMgr.header': 'Export Files',
            'exportsMgr.empty': 'No export files yet — run a workflow with an Output node',
            'exportsMgr.loadFailed': 'Could not read the export folder',
            'exportsMgr.summary': '{files} file(s), {size} in total',
            'exportsMgr.colName': 'File',
            'exportsMgr.colKind': 'Kind',
            'exportsMgr.colSize': 'Size',
            'exportsMgr.colModified': 'Modified',
            'exportsMgr.download': 'Download',
            'exportsMgr.remove': 'Delete',
            'exportsMgr.confirmRemove': 'Delete this export file? It cannot be undone.',
            'exportsMgr.removeDone': 'Export file deleted',
            'exportsMgr.removeFailed': 'Delete failed',
            'runsMgr.empty': 'No runs recorded yet',
            'runsMgr.colWorkflow': 'Workflow',
            'runsMgr.colStatus': 'Status',
            'runsMgr.colNodes': 'Nodes',
            'runsMgr.colRows': 'Rows',
            'runsMgr.colStarted': 'Started',
            'runsMgr.status.running': 'Running',
            'runsMgr.status.interrupted': 'Interrupted',
            'runsMgr.status.completed': 'Completed',
            'runsMgr.status.failed': 'Failed',
            'runsMgr.status.abandoned': 'Abandoned',
            'runsMgr.resume': 'Continue',
            'runsMgr.restart': 'Restart',
            'runsMgr.remove': 'Delete',
            'runsMgr.detail': 'Details',
            'runsMgr.detailNodes': 'Node breakdown',
            'runsMgr.confirmRestart': 'Discard this interrupted attempt and start over from scratch?',
            'runsMgr.confirmRemove': 'Delete this run and its kept rows?',
            'runsMgr.removeDone': 'Run deleted',
            'runsMgr.removeFailed': 'Delete failed',
            'runsMgr.busy': 'A run is already in progress',
            'runsMgr.noNodes': 'No node records',
            'runsMgr.node.pending': 'Pending',
            'runsMgr.node.running': 'Running',
            'runsMgr.node.done': 'Done',
            'runsMgr.node.partial': 'Partial',
            'runsMgr.node.failed': 'Failed',
            'runsMgr.node.skipped': 'Skipped',
            'runsMgr.node.restored': 'Restored',
            'validate.processInput': 'Process node "{title}": must have an input connection',
            'validate.processDownstream': 'Process node "{title}": must connect to a downstream node',
            'validate.analysisInput': 'Analysis node "{title}": must have an input connection',
            'validate.analysisDownstream': 'Analysis node "{title}": must connect to a downstream node',
            'validate.analysisOperation': 'Analysis node "{title}": operation must be selected',
            'validate.tokenizeInput': 'Tokenize node "{title}": must have an input connection (a source or upload node)',
            'validate.tokenizeColumn': 'Tokenize node "{title}": text column cannot be empty',
            'validate.visualizeInput': 'Visualize node "{title}": must have an input connection (a source or upload node)',
            'validate.visualizeChartType': 'Visualize node "{title}": chart type must be selected',
            'validate.visualizeXField': 'Visualize node "{title}": X field cannot be empty',
            'validate.outputInput': 'Output node "{title}": must have an input connection',
            'validate.outputFilename': 'Output node "{title}": filename cannot be empty',
            'validate.noTerminal': 'At least one Output (Save) or Visualize node is required',        },
        zh: {
            'menu.file': '文件', 'menu.save': '保存', 'menu.load': '打开', 'menu.new': '新建',
            'menu.edit': '编辑',
            'menu.view': '视图', 'btn.bg': '背景',
            'menu.style': '样式', 'style.bg': '背景', 'style.radius': '圆角',
            'btn.zoomin': '放大', 'btn.zoomout': '缩小', 'btn.fit': '适应',
            'menu.run': '运行', 'btn.execute': '执行', 'btn.running': '运行中...', 'btn.stop': '停止',
            'btn.parallel': '并行', 'btn.headless': '无头',

            'menu.nodes': '节点', 'btn.src': '+源', 'btn.proc': '+处理', 'btn.out': '+输出',
            'menu.lang': '语言', 'pin.title': '固定菜单栏',
            'bg.void': '无', 'bg.grid': '网格', 'bg.dots': '点阵',
            'bg.cross': '十字', 'bg.diagonal': '斜纹',
            'palette.header': '节点库',
            'palette.cat.workflow': '工作流',
            'palette.cat.inputs': '数据输入',
            'palette.cat.process': '数据处理',
            'palette.cat.outputs': '结果输出',
            'palette.source': '数据源', 'palette.upload': '上传文件', 'palette.process': '处理', 'palette.output': '输出',
            'palette.resume': '断点续跑', 'palette.name': '工作流命名',
            'node.source': '数据源', 'node.upload': '上传文件', 'node.process': '处理',
            'node.analysis': '分析', 'node.visualize': '可视化', 'node.tokenize': '分词', 'node.output': '输出',
            'node.resume': '断点续跑', 'node.name': '工作流命名',
            'node.comment': '评论采集',
            /* 断点续跑：提示要说清已经保留了什么，否则用户不知道「继续」会发生什么 */
            'resume.continue': '继续执行', 'resume.restart': '从头开始', 'resume.dismissTitle': '忽略',
            'resume.interrupted': '发现 {at} 那次未跑完的运行',
            'resume.detail': '已完成 {done}/{total} 个节点，保留了 {rows} 行数据 —— 继续执行从这里接着跑',
            'resume.incomplete': '中断前已保存 {rows} 行数据',
            'resume.runSelect': '选择运行记录', 'resume.nodeSelect': '选择节点输出',
            'resume.autoNode': '数据量最大的节点（自动）',
            'resume.limit': '读取行数上限', 'resume.limitPlaceholder': '0 表示全部',
            'resume.refresh': '刷新列表', 'resume.none': '还没有可续跑的记录，先跑一次完整流程',
            'resume.hint': '直接读取上次运行里某个节点已保存的数据，不需要重新爬取',
            'toast.resumeStarted': '正在从断点继续执行',
            'toast.runDiscarded': '已丢弃上次的记录，从头开始',
            'settings.file': '文件', 'settings.rows': '行',
            'stats.header': '统计', 'stats.close': '关闭',
            'stats.emotion': '情感', 'stats.tendency': '倾向',
            'settings.header': '节点设置', 'settings.close': '关闭',
            'status.ready': '就绪', 'status.completed': '已完成', 'status.running': '运行中...',
            'ctx.newSource': '新建数据源', 'ctx.newUpload': '新建上传文件',
            'ctx.newProcess': '新建处理',
            'ctx.newOutput': '新建输出', 'ctx.edit': '编辑节点', 'ctx.rename': '重命名节点',
            'ctx.renameHint': '双击重命名',
            'ctx.copy': '复制节点', 'ctx.paste': '粘贴节点',
            'ctx.delete': '删除节点', 'ctx.clear': '清除所有连线',
            'btn.lang': '中文',
            'btn.cookies': 'Cookies',
            'console.header': '控制台', 'console.clear': '清空', 'console.close': '关闭', 'console.popout': '弹出', 'console.dock': '收回',
            'console.all': '全部',
            'processes.header': '进程监控', 'processes.close': '关闭',
            'processes.running': '运行中', 'processes.stopped': '已停止',
            'processes.threads': '线程数', 'processes.crawlers': '爬虫数',
            'processes.pool': '线程池活跃', 'processes.yes': '是', 'processes.no': '否',
            'processes.name': '名称', 'processes.status': '状态', 'processes.type': '类型',
            'processes.daemon': '守护', 'processes.alive': '存活', 'processes.kill': '结束',
            'cookies.header': 'Cookie 设置', 'cookies.platform': '平台',
            'cookies.paste': '粘贴 Cookies JSON', 'cookies.save': '保存 Cookies',
            'cookies.generate': '浏览器生成', 'cookies.waitTime': '等待时间（秒）用于登录:',
            'cookie.opening': '正在打开浏览器进行 {platform} 登录（等待 {s} 秒）...',
            'cookie.generated': '已生成 {platform} 的 Cookies',
            'cookie.failed': '失败：{err}',
            'cookie.unreachable': '无法连接后台服务（可能正在启动或重启）——稍等片刻后重试',
            'cookies.doneBtn': '已完成登录',
            'cookies.cancelBtn': '取消登录',
            'cookie.mustStay': '登录进行中——请先点「已完成登录」或「取消登录」，此窗口需保持打开',
            'cookie.waiting': '{platform} 登录窗口已打开——完成登录后点「已完成登录」',
            'cookies.entryUrl': '登录入口链接（可留空：默认打开该平台登录页）',
            'cookies.verify': '验证 Cookie',
            'cookie.verifying': '正在用已保存的 Cookie 试探该平台…',
            'cookie.guideLoading': '正在载入该平台的获取步骤…',
            'cookie.entryRejected': '该链接不属于本平台的域名，已改用平台登录页打开',
            'cookie.savedN': '已为 {platform} 保存 {n} 条 Cookie',
            'cookie.cancelledMsg': '{platform} 登录已取消',
            'settings.recrawl': '重新采集（忽略此前已采集条目）',
            'settings.recrawlHint': '默认关闭：该节点此前已采集过的条目会被跳过以节省成本；勾选后清除去重账本并重新抓取。',
            'cookie.invalidJson': 'JSON 格式错误：{err}',
            'cookie.pasteFirst': '请先粘贴 Cookies JSON',
            'toast.nodeDeleted': '节点已删除',
            'toast.connCreated': '连线已创建',
            'toast.connRemoved': '连线已删除',
            'toast.connCleared': '所有连线已清除',
            'toast.nodeCopied': '节点已复制',
            'toast.nodePasted': '节点已粘贴',
            'toast.newWorkflow': '新建工作流',
            'toast.workflowSaved': '工作流已保存',
            'toast.workflowLoaded': '工作流已加载',
            'toast.workflowStarted': '工作流已启动',
            'toast.workflowCompleted': '工作流已完成',
            'toast.pollFailed': '与服务端失去连接，状态刷新已停止',
            'toast.workflowStopped': '工作流已停止',
            'toast.noWorkflows': '没有已保存的工作流',
            'toast.saveFailed': '保存失败',
            'toast.loadFailed': '加载失败',
            'toast.executeFailed': '执行失败',
            'toast.stopFailed': '停止失败',
            'toast.cookiesSaved': 'Cookies 已保存',
            'toast.cookiesMissing': '平台 Cookies 未配置，请先设置:',
            'dialog.workflowName': '工作流名称:',
            'dialog.selectWorkflow': '输入要加载的工作流名称:',
            'dialog.cancel': '取消',
            'dialog.confirm': '确认',
            'dialog.renameNode': '重命名此节点——控制台将显示它的名字而不是 node-N（留空恢复类型默认名）：',
            'dialog.cookieConfirm': '本次运行会真实爬取站点。COOKIE 是否已长时间未更新？可先退出，到「设置 → Cookie」更新后续跑；也可直接继续运行。',
            'dialog.cookieGoOn': '继续执行',
            'dialog.cookieExit': '退出更新 Cookie',
            'toast.cookieExpired': '检测到登录墙——COOKIE 可能已在爬取中途失效。已采集数据不会丢失：请到「设置 → Cookie」更新后断点续跑。',
            'settings.nodeType': '节点类型',
            'settings.platform': '平台',
            'settings.collect': '采集内容',
            'settings.collectPosts': '帖子 / 文章',
            'settings.collectComments': '评论',
            'settings.keyword': '关键词',
            'settings.targetCount': '目标数量',
            'settings.startTime': '开始时间',
            'settings.endTime': '结束时间',
            'settings.operation': '操作',
            'settings.textColumn': '文本列',
            'settings.topic': '主题',
            'settings.filename': '文件名',
            'settings.workflowName': '工作流名称',
            'nodeType.source': '数据源',
            'nodeType.upload': '上传文件',
            'nodeType.process': '处理',
            'nodeType.analysis': '分析',
            'nodeType.visualize': '可视化',
            'nodeType.tokenize': '分词',
            'nodeType.resume': '断点续跑', 'nodeType.name': '工作流命名',
            'nodeType.output': '输出',
            'nodeType.comment': '评论采集',
            'op.clean': '清洗',
            'op.emotion': '情感分析',
            'op.tendency': '倾向分析',
            'op.save_csv': '保存 CSV',
            'op.save': '保存',
            'op.chart': '图表',
            'op.drop_null': '删除空值行',
            'op.fill_null': '填充空值',
            'op.drop_duplicates': '去重',
            'op.filter_rows': '筛选行',
            'op.select_columns': '选择列',
            'op.rename_columns': '重命名列',
            'op.strip_whitespace': '去除空白',
            'op.convert_type': '类型转换',
            'platform.zhihu': '知乎',
            'platform.weibo': '微博',
            'platform.xiaohongshu': '小红书',
            'platform.wechat': '微信',
            'platform.bilibili': '哔哩哔哩',
            'platform.douyin': '抖音',
            'btn.analysis': '+分析',
            'btn.visualize': '+图表',
            'btn.tokenize': '+分词',
            'btn.uploadFile': '上传文件',
            'btn.preview': '预览图表',
            'palette.analysis': '分析',
            'palette.visualize': '可视化',
            'palette.tokenize': '分词',
            'ctx.newAnalysis': '新建分析节点',
            'ctx.newVisualize': '新建可视化节点',
            'ctx.newTokenize': '新建分词节点',
            'chart.header': '图表预览',
            'chart.bar': '柱状图', 'chart.line': '折线图', 'chart.pie': '饼图',
            'chart.scatter': '散点图', 'chart.histogram': '直方图', 'chart.box': '箱线图',
            'chart.heatmap': '热力图', 'chart.wordcloud': '词云',
            'chart.sankey': '桑基图', 'chart.map': '地图（中国）',
            'format.csv': 'CSV', 'format.json': 'JSON', 'format.excel': 'Excel (.xlsx)',
            'format.txt': '文本 (.txt)', 'format.html': 'HTML', 'format.markdown': 'Markdown',
            'settings.format': '格式',
            'settings.columns': '列',
            'settings.column': '列',
            'settings.value': '值',
            'settings.filterOp': '条件',
            'settings.renameFrom': '原列名',
            'settings.renameTo': '新列名',
            'settings.dtype': '目标类型',
            'settings.tokenizeUpstream': '来自分词节点（自动适配）',
            'settings.tokenizeOutputLocked': '输出模式已锁定（下游图表节点需要词频统计）',
            'settings.chartType': '图表类型',
            'settings.engine': '渲染引擎',
            'settings.xField': 'X 字段',
            'settings.yField': 'Y 字段（可选）',
            'settings.agg': '聚合方式',
            'settings.title': '图表标题',
            'settings.dataSource': '数据来源',
            'dataSource.loaded': '已加载',
            'dataSource.none': '尚未上传文件',
            'dataSource.persisted': '已存入数据库：刷新页面或重开工作流后依然带着这个文件',
            'toast.datasetsMissing': '这些上传节点需要重新上传文件',
            'toast.datasetUploaded': '数据集已上传',
            'toast.txtUploaded': '文本文件已上传，已自动配置词云',
            'toast.uploadFailed': '上传失败',
            'toast.previewNeedsUpload': '请先在该上传节点中上传 CSV 或 JSON 文件',
            'toast.previewNeedsInput': '请先连接上游节点，然后完整执行一次工作流',
            'toast.renderFailed': '图表渲染失败',
            'toast.previewFailed': '数据预览失败',
            'toast.mapLoadFailed': '地图数据加载失败（请检查网络连接）',
            'settings.xFieldCat1': '分类字段一',
            'settings.yFieldCat2': '分类字段二',
            'settings.sourceField': '来源字段',
            'settings.targetField': '目标字段',
            'settings.textField': '文本字段',
            'settings.regionField': '地区字段',
            'settings.valueField': '数值字段（可选）',
            'settings.tokenize': '对文本分词（jieba 中文分词）',
            'settings.outputMode': '输出模式',
            'outputMode.word_freq': '词频统计',
            'outputMode.words_only': '仅词列表',
            'outputMode.csv_line': '空格分隔一行',
            'settings.topN': '最大词数',
            'settings.topNPlaceholder': '留空=全部词',
            'settings.wordcloudStyle': '词云样式',
            'wordcloudStyle.vibrant': '缤纷',
            'wordcloudStyle.monoBlue': '蓝色系',
            'wordcloudStyle.monoOrange': '橙色系',
            'wordcloudStyle.pastel': '粉彩',
            'wordcloudStyle.ocean': '海洋',
            'wordcloudStyle.sunset': '日落',
            'wordcloudStyle.forest': '森林',
            'warn.echartsOnly': '该图表类型仅支持 ECharts 引擎渲染',
            'hint.mapRegionNames': '地区名称需与中国省份名一致（如 广东省、北京市）',
            'menu.data': '数据',
            'btn.dashboard': '看板',
            'btn.history': '历史',
            'btn.studio': '图表工坊',
            'studio.title': '图表工坊',
            'studio.subtitle': 'ZENVIZ · 工作流',
            'studio.source': '数据来源',
            'studio.load': '载入数据',
            'studio.saveBack': '导出为图片',
            'studio.close': '关闭',
            'studio.noNodes': '画布上还没有可产出数据的节点',
            'studio.pickSource': '请选择要取数的节点',
            'studio.loading': '正在载入数据集…',
            'studio.loaded': '已载入 {rows} 行 · {cols} 列',
            'studio.loadFailed': '数据集载入失败',
            'studio.noResult': '画布上还没有表数据，请先执行一次工作流',
            'studio.fallback': '「{a}」暂无数据，已改用「{b}」的数据',
            'studio.saved': '图片已导出到 {path}',
            'studio.saveFailed': '图片导出失败',
            'studio.ready': '工坊已就绪',
            'studio.booting': '正在启动工坊…',
            'studio.noChart': '请先渲染图表，再导出图片',
            'studio.emptyData': '该节点还没有表数据，请先运行工作流',
            'studio.src.none': '当前没有可用的数据源，请先完整执行一次工作流',
            'studio.src.rows': '{rows} 行',
            'studio.src.noUpstream': '该节点没有连接上游节点，读不到表数据',
            'studio.src.noUpstreamShort': '未连接上游',
            'studio.src.noResult': '该节点还没有产出结果，请先执行一次工作流',
            'studio.src.noResultShort': '尚无数据',
            'studio.src.staleDataset': '上传的数据集已失效（服务重启后清空），请重新上传',
            'studio.src.staleDatasetShort': '数据集已失效',
            'studio.src.empty': '该节点产出的是空表',
            'studio.src.emptyShort': '空表',
            'studio.src.probeFailed': '无法探测该节点的数据状态',
            'studio.src.probeFailedShort': '探测失败',
            'studio.pickMulti': '选择节点（可多选）',
            'studio.src.tip': '{rows} 行 · {cols} 列：{names}',
            'studio.src.selection': '已选 {n} 个节点 · 合计 {rows} 行',
            'studio.multiCount': '已选 {n} 个节点',
            'studio.merge': '拼接方式',
            'studio.merge.rows': '放到下方（追加行）',
            'studio.merge.side': '放到右侧（追加列）',
            'studio.loadedMerged': '已合并 {n} 个来源 · {rows} 行 · {cols} 列',
            'studio.mergedSkipped': '{n} 个来源不可用',
            'studio.mergedName': '{n} 个节点合并',
            'studio.menu.engine': '引擎',
            'studio.menu.data': '数据',
            'studio.menu.style': '样式',
            'studio.menu.export': '导出',
            'btn.previewData': '预览数据',
            'btn.prev': '上一页',
            'btn.next': '下一页',
            'btn.refresh': '刷新',
            'dataPreview.header': '数据预览',
            'dataPreview.rows': '行数',
            'dataPreview.columns': '列数',
            'dashboard.header': '仪表盘',
            'dashboard.empty': '画布上还没有可视化节点，添加一个即可在这里查看。',
            'dashboard.noData': '暂无数据——请连接上游节点并运行工作流，或将数据来源设为"上传文件"。',
            'history.header': '执行历史',
            'history.allWorkflows': '全部工作流',
            'history.metric.emotion': '情感',
            'history.metric.tendency': '倾向性',
            'history.metric.rows': '行数',
            'history.runId': '执行 ID',
            'history.workflowName': '工作流',
            'history.startedAt': '开始时间',
            'history.metricCount': '指标数',
            'history.empty': '暂无执行历史——请先运行一次工作流。',
            'history.clearAll': '清空历史',
            'history.confirmClear': '此操作将永久删除所有已记录的执行历史，确定继续吗？',
            'history.cleared': '执行历史已清空',
            'settings.mode': '分析模式',
            'mode.llm': '大模型（本地 Ollama / OpenRouter）',
            'mode.ml': '传统机器学习 (sklearn)',
            'btn.ai': 'AI',
            'ai.provider': '调用方式',
            'ai.provider.ollama': '本地 Ollama',
            'ai.provider.openrouter': 'OpenRouter API',
            'ai.model': '模型',
            'ai.localModels': '本地模型',
            'ai.ollamaHost': '服务地址',
            'ai.ollamaHostNote': 'Ollama 服务地址在「设置」面板修改',
            'ai.freeModels': '免费模型',
            'ai.refreshModels': '— 点「刷新」获取列表 —',
            'ai.refresh': '刷新',
            'ai.pickModel': '选择一个模型…',
            'ai.key': 'API Key',
            'ai.test': '测试连接',
            'ai.testing': '测试中…',
            'ai.batch': '每批保存条数',
            'ai.maxChars': '单行截断长度（字符）',
            'ai.hintTitle': '调用方式说明',
            'ai.hint1':
                '每条数据 = 一次询问（一条消息一次调用），逐行处理。数据多时比较耗时，' +
                '也比较耗 token——文本越长，每行消耗越多，请务必注意控制数据量。',
            'ai.hint2': '免费模型完全够用，不需要掏钱；建议先小批量试跑，确认效果后再放量。',
            'ai.hint3':
                '结果分批保存：中途出错或停止时，已得到的结果不会丢失；修复后重新执行会自动从断点续跑。',
            'ai.keyNote': 'API Key 仅保存在本浏览器 Local Storage，不会写入服务器文件。',
            'ai.ollamaNote':
                'Ollama：模型名必须是本地已拉取的名称（点「刷新」可读取）；服务地址在「设置」面板修改。' +
                '两种调用方式各自保存模型，互不影响。',
            'toast.aiTestOk': 'AI 连接正常（{ms} 毫秒）',
            'toast.aiTestFail': 'AI 连接失败',
            'toast.aiNeedKey': '请先填写 OpenRouter API Key',
            'toast.aiNeedModel': '请先选择 OpenRouter 模型',
            'toast.aiNeedOllamaModel': '请先设置 Ollama 模型（可点「刷新」读取本地模型）',
            'toast.aiModelsLoaded': '已加载 {n} 个模型',
            'toast.ollamaNoModels': '本地 Ollama 还没有拉取任何模型（请先执行 ollama pull）',
            'toast.aiModelsFail': '模型列表加载失败',
            'btn.settings': '设置',
            'set.driver': '浏览器驱动路径',
            'set.binary': '浏览器程序路径',
            'set.window': '窗口大小',
            'set.pageLoad': '页面加载超时(秒)',
            'set.elementWait': '元素等待超时(秒)',
            'set.ollamaHost': 'Ollama 服务地址',
            'set.cookieConfirm': '执行前确认 Cookie',
            'set.cookieConfirmInline': '每次含采集节点的运行前都弹确认框',
            'set.save': '保存设置',
            'set.note':
                '这些是本机相关设置。保存后写入服务器 ' +
                'data/settings.json，下次执行即生效，无需重启服务。',
            'toast.setSaved': '设置已保存',
            'toast.setSavedWarn': '设置已保存，但有问题：',
            'toast.setSaveFail': '设置保存失败',
            'toast.setNoChange': '没有需要保存的修改',
            'op.keyword': '关键词提取',
            'op.cluster': '文本聚类',
            'op.ner': '命名实体识别',
            'op.anomaly': '异常检测',
            'op.correlation': '相关性分析',
            'op.sort_rows': '排序行',
            'op.sample_rows': '采样行',
            'op.groupby_agg': '分组聚合',
            'op.join_tables': '表关联',
            'op.column_calc': '列计算',
            'op.bin_column': '数值分箱',
            'settings.method': '方法',
            'settings.topk': 'Top-K 数量',
            'settings.merge': '合并结果',
            'settings.clusterMethod': '聚类方法',
            'settings.nClusters': '聚类数',
            'settings.eps': 'Epsilon (DBSCAN)',
            'settings.minSamples': '最小样本数 (DBSCAN)',
            'settings.nerMethod': 'NER 方法',
            'settings.contamination': '异常比例',
            'settings.corrMethod': '相关方法',
            'settings.minAbs': '最小绝对相关系数',
            'settings.ascending': '升序',
            'settings.n': '采样数量 (N)',
            'settings.frac': '采样比例',
            'settings.seed': '随机种子',
            'settings.groupCol': '分组列',
            'settings.aggCol': '聚合列',
            'settings.aggFunc': '聚合函数',
            'settings.joinHow': '关联方式',
            'settings.leftOn': '左表键',
            'settings.rightOn': '右表键',
            'settings.newCol': '新列名',
            'settings.urls': '文章链接',
            'settings.urlsHint': '每行一个链接，微信按这些文章逐个抓取',
            'settings.commentUrls': '文章链接',
            'settings.commentUrlsHintPlat': '每行一个文章链接，须与所选平台（{plat}）一致',
            'settings.wechatLimitsNote': '微信：留言 / 点赞数 / 转发数 无法采集——点击查看原因',
            'settings.wechatLimitsBtn': '为什么微信不能采集评论、点赞、转发？',
            'settings.wechatLimitsBody':
                '微信把文章正文开放给任何人，但把「留言」「点赞数」「转发数」（多数情况下还有「阅读数」）' +
                '放在只发给微信客户端会话的凭证之后。\n\n' +
                '在真实浏览器里对真实文章的实测结果：页面 show_comment=0，HTML 里不含任何留言数据；' +
                '直接调用留言接口返回一段 HTML 验证页，内容是「请在微信客户端打开链接」。' +
                '更换 User-Agent、改写链接参数、甚至重放微信客户端自己的 Cookie，都改变不了这个结果；' +
                '本项目也不会伪装成微信客户端去绕过站点的访问控制。\n\n' +
                '更关键的原因是：在浏览器里，「这篇文章没有评论」与「这次访问不被允许查看」看起来完全一样。' +
                '如果返回一张空表，你拿到的就是一份看着正常、实则是失败的数据。' +
                '因此微信只采集它真正开放的内容（文章正文），评论采集请使用 知乎 / 微博 / 小红书。',
            'settings.commentUrlsHintMixed': '每行一个文章链接，可混合知乎 / 微博 / 小红书，每个链接按域名自动识别平台',
            'settings.commentLimit': '评论条数上限',
            'settings.commentLimitHint': '0 表示采集全部评论',
            'settings.partSize': '分片大小',
            'settings.partSizeHint': '0 表示不生成分片文件，仅输出合并后的单个文件',
            'settings.sourcePartSizeHint': '0 表示关闭。大于 0 时，每爬满 N 行写入一个带编号的分片文件，运行中即可打开查看，结束时合并为一个文件。',
            'settings.liveExport': '实时导出（按批）',
            'settings.liveExportHint': '每处理完一批就重写一次 {node}.live 文件，节点未跑完也能查看当前结果。',
            'settings.perArticleFile': '每篇文章单独输出文件',
            'settings.keepParts': '合并后保留分片文件',
            'settings.commentHint': '采集时会打开可见的浏览器窗口（知乎禁止无头模式）；每 part_size 条评论写入一个分片文件到导出目录。',
            'settings.joinHint': '右表取自本节点的第二条上游连线',
            'settings.expr': '表达式',
            'settings.binNewCol': '分箱列名',
            'settings.dropHow': '删行条件',
            'settings.dropHowAny': '所选列中任一为空即删',
            'settings.dropHowAll': '所选列全部为空才删',
            'settings.fillMethod': '填充方式',
            'settings.fillMethodValue': '用上面的值填充',
            'settings.binEdges': '分箱（整数=等宽箱数，或 0,60,80,100 指定边界）',
            'settings.binLabels': '箱标签（逗号分隔，可留空）',
            'settings.trainModel': '训练 ML 模型',
            'settings.trainFrom': '从此数据集训练',
            'toast.modelTrained': 'ML 模型训练成功',
            'toast.modelTrainFailed': 'ML 模型训练失败',
            'canvas.undo': '撤销',
            'canvas.redo': '重做',
            'canvas.fold': '折叠节点',
            'canvas.unfold': '展开节点',
            'canvas.autoLayout': '自动布局',
            'status.nodes': '节点数：', 'status.progress': '进度：{done}/{total}',
            'toast.layoutApplied': '已应用自动布局',
            'summary.tokenizeTop': ' | Top-{n}',
            'settings.textColumnPlaceholder': '例如：正文',
            'toast.mlUpstreamNeeded': '请先连接一个带标签数据的上游节点',
            'toast.languageChanged': '语言：{lang}',
            'validate.empty': '工作流为空',
            'validate.sourceKeyword': '数据源节点 "{title}"：关键词不能为空',
            'validate.sourceDownstream': '数据源节点 "{title}"：必须连接到下游节点',
            'validate.sourceUrls': '数据源节点 "{title}"：微信平台需要填写至少一个文章链接',
            'validate.sourceCommentUrls': '数据源节点 "{title}"：评论模式需要填写至少一个文章链接',
            'validate.sourceCommentPlat': '数据源节点 "{title}"：{n} 个链接与所选平台（{plat}）不符',
            'validate.joinNeedsTwo': '分析节点 "{title}"：合并表需要两条输入连线（左表、右表）',
            'validate.uploadFile': '上传节点 "{title}"：尚未上传文件',
            'validate.uploadDownstream': '上传节点 "{title}"：必须连接到下游节点',
            'validate.nameEmpty': '命名节点 "{title}"：工作流名称不能为空',
            'validate.nameMustLead': '命名节点 "{title}"：必须是开头节点，不能有上游接入',
            'validate.nameDownstream': '命名节点 "{title}"：请连接下游节点',
            'name.hint': '这个名字会作为分类显示在「历史」区域。',
            'name.unnamed': '未命名',
            'runsMgr.header': '运行记录',
            'exportsMgr.header': '导出产物',
            'exportsMgr.empty': '还没有导出文件——运行一个含输出节点的工作流',
            'exportsMgr.loadFailed': '读取导出目录失败',
            'exportsMgr.summary': '共 {files} 个文件，合计 {size}',
            'exportsMgr.colName': '文件名',
            'exportsMgr.colKind': '类型',
            'exportsMgr.colSize': '大小',
            'exportsMgr.colModified': '修改时间',
            'exportsMgr.download': '下载',
            'exportsMgr.remove': '删除',
            'exportsMgr.confirmRemove': '删除这个导出文件？删除后无法恢复。',
            'exportsMgr.removeDone': '导出文件已删除',
            'exportsMgr.removeFailed': '删除失败',
            'runsMgr.empty': '还没有运行记录',
            'runsMgr.colWorkflow': '工作流',
            'runsMgr.colStatus': '状态',
            'runsMgr.colNodes': '节点',
            'runsMgr.colRows': '行数',
            'runsMgr.colStarted': '开始时间',
            'runsMgr.status.running': '运行中',
            'runsMgr.status.interrupted': '已中断',
            'runsMgr.status.completed': '已完成',
            'runsMgr.status.failed': '失败',
            'runsMgr.status.abandoned': '已放弃',
            'runsMgr.resume': '继续',
            'runsMgr.restart': '重新开始',
            'runsMgr.remove': '删除',
            'runsMgr.detail': '详情',
            'runsMgr.detailNodes': '节点明细',
            'runsMgr.confirmRestart': '丢弃这次中断的尝试，从头重新运行？',
            'runsMgr.confirmRemove': '删除这条运行及其保留的数据行？',
            'runsMgr.removeDone': '运行已删除',
            'runsMgr.removeFailed': '删除失败',
            'runsMgr.busy': '已有运行正在进行',
            'runsMgr.noNodes': '没有节点记录',
            'runsMgr.node.pending': '等待',
            'runsMgr.node.running': '运行中',
            'runsMgr.node.done': '完成',
            'runsMgr.node.partial': '部分完成',
            'runsMgr.node.failed': '失败',
            'runsMgr.node.skipped': '已跳过',
            'runsMgr.node.restored': '已复用',
            'validate.processInput': '处理节点 "{title}"：必须有一个输入连接',
            'validate.processDownstream': '处理节点 "{title}"：必须连接到下游节点',
            'validate.analysisInput': '分析节点 "{title}"：必须有一个输入连接',
            'validate.analysisDownstream': '分析节点 "{title}"：必须连接到下游节点',
            'validate.analysisOperation': '分析节点 "{title}"：必须选择操作',
            'validate.tokenizeInput': '分词节点 "{title}"：必须有输入连接（数据源或上传节点）',
            'validate.tokenizeColumn': '分词节点 "{title}"：文本列不能为空',
            'validate.visualizeInput': '图表节点 "{title}"：必须有输入连接（数据源或上传节点）',
            'validate.visualizeChartType': '图表节点 "{title}"：必须选择图表类型',
            'validate.visualizeXField': '图表节点 "{title}"：X 字段不能为空',
            'validate.outputInput': '输出节点 "{title}"：必须有一个输入连接',
            'validate.outputFilename': '输出节点 "{title}"：文件名不能为空',
            'validate.noTerminal': '至少需要一个输出（保存）或可视化节点',        },
    },
    /* Keys no dictionary defines, in the order they were first asked for. A
       silent fallback is exactly how a raw "nodeType.upload" reached the screen
       once: warn on the first miss (and keep the list available as
       I18n.missing()) so a gap can never hide again. */
    _missing: new Set(),

    t(key) {
        const d = this.dict[this.lang] || this.dict.en;
        if (d[key] !== undefined) return d[key];
        /* Show the other language before showing the raw key — a missing
           translation should still read as a sentence ("Upload File"), not as
           an identifier ("palette.upload"). */
        const other = this.dict[this.lang === 'zh' ? 'en' : 'zh'] || {};
        if (!this._missing.has(key)) {
            this._missing.add(key);
            console.warn('[i18n] missing ' + this.lang + ' string: ' + key);
        }
        return other[key] !== undefined ? other[key] : key;
    },

    missing() {
        return Array.from(this._missing).sort();
    },
    apply() {
        this.lang = document.body.dataset.lang || 'en';
        document.querySelectorAll('[data-i18n]').forEach(el => {
            el.textContent = this.t(el.dataset.i18n);
        });
        document.querySelectorAll('[data-i18n-title]').forEach(el => {
            el.title = this.t(el.dataset.i18nTitle);
        });
        /* Menu labels and the open dropdown are rendered by TopMenu, not by
           data-i18n attributes, so they need an explicit refresh. */
        if (window.TopMenu) TopMenu.refresh();
        /* The studio bar re-hosts the embedded studio's nav, so its mirrored
           chips carry i18n labels too. */
        if (window.chartStudio) chartStudio.refreshMenus();
        /* Option text inside custom selects comes from the <option> nodes, so
           their trigger labels need re-reading once the locale changes. */
        if (window.CustomSelect) CustomSelect.refreshAll();
    },
};

/* Run-time switches that used to live as `.toggle-on` classes on the old flat
   menu bar. They are real state now, because the buttons only exist while a
   dropdown is open — reading them back from the DOM is no longer possible. */
const RunState = {
    parallel: true,
    headless: true,
    running: false,

    set(key, value) {
        this[key] = !!value;
        Settings.save();           /* persist */
        if (window.TopMenu) TopMenu.refresh();  /* keep the open panel truthful */
    },

    /* Flip a boolean switch and re-sync the flat bar. */
    toggle(key) {
        this[key] = !this[key];
        Settings.save();
        if (window.TopMenu) TopMenu.refresh();
    },

    /* Execute / Stop reflect a run in progress. */
    setRunning(on) {
        this.running = !!on;
        if (window.TopMenu) TopMenu.refresh();
    },
};

const Settings = {
    _key: 'crawler_settings',
    defaults: {
        bg: 'bg-grid',
        parallel: true,
        headless: true,
        menuPinned: true,
        zoom: 1,
        lang: 'zh',
        radius: 2,
    },
    save() {
        const data = {
            bg: Array.from(document.body.classList).find(c => c.startsWith('bg-')) || 'bg-grid',
            parallel: RunState.parallel,
            headless: RunState.headless,
            menuPinned: document.getElementById('top-menu').classList.contains('pinned'),
            zoom: canvas.zoom,
            lang: document.body.dataset.lang || 'zh',
            radius: parseInt(getComputedStyle(document.documentElement).getPropertyValue('--radius'), 10) || 2,
        };
        localStorage.setItem(this._key, JSON.stringify(data));
    },
    load() {
        const raw = localStorage.getItem(this._key);
        const data = raw ? Object.assign({}, this.defaults, JSON.parse(raw)) : this.defaults;
        return data;
    },
    apply() {
        const s = this.load();
        /* Language — set first so I18n.t() uses the correct locale */
        document.body.dataset.lang = s.lang || 'zh';
        I18n.apply();
        /* Theme — the design system is light-only; no dark (black) surface exists. */
        document.body.classList.add('theme-light');
        /* Background */
        document.body.className = document.body.className.replace(/bg-\S+/g, '').trim();
        document.body.classList.add(s.bg);
        document.querySelectorAll('[data-bg]').forEach(el => {
            el.classList.toggle('active', el.dataset.bg === s.bg);
        });
        /* Run switches */
        RunState.parallel = s.parallel !== false;
        RunState.headless = s.headless !== false;
        /* Menu pin */
        document.getElementById('top-menu').classList.toggle('pinned', s.menuPinned);
        document.getElementById('pin-btn').classList.toggle('pinned', s.menuPinned);
        document.getElementById('pin-btn').setAttribute('aria-pressed', s.menuPinned ? 'true' : 'false');
        /* Corner radius — drive the single --radius token from saved value */
        const radius = (typeof s.radius === 'number') ? s.radius : 2;
        document.documentElement.style.setProperty('--radius', radius + 'px');
        const slider = document.getElementById('radius-slider');
        if (slider) slider.value = radius;
        const lbl = document.getElementById('radius-val');
        if (lbl) lbl.textContent = radius + 'px';
    },
};

/* ── AI (LLM) settings — transport, model, key, batching ────────────────────
   The two transports keep *separate* settings blocks. They used to share one
   `model` field, so a local Ollama run inherited whatever OpenRouter id was
   left in the box (e.g. `nex-agi/nex-n2.5-pro:free`) and the daemon answered
   "unexpected keyword argument" long before it ever got to complain about the
   model. Ollama needs a tag the daemon has pulled; OpenRouter needs a catalog
   id plus a key. Nothing is shared, so switching provider no longer carries a
   stale value across.

   Everything lives in localStorage; the key never leaves the browser except
   inside the execute / test request bodies. workflow.execute() sends
   LLMSettings.payload() alongside the workflow. */
const LLMSettings = {
    _key: 'crawler_llm',
    defaults: {
        provider: 'ollama',   // 'ollama' | 'openrouter'
        ollama: {
            model: '',        // a tag pulled locally (see 刷新 / list_ollama_models)
        },
        openrouter: {
            model: '',        // required, a :free model id
            api_key: '',      // localStorage only, never written server-side
        },
        batch_size: 10,       // rows between checkpoint saves
        max_chars: 600,       // per-row truncation — long texts burn tokens
        workers: 3,           // openrouter only
    },

    load() {
        let raw = {};
        try {
            raw = JSON.parse(localStorage.getItem(this._key) || '{}');
        } catch (e) {
            raw = {};
        }
        const s = Object.assign({}, this.defaults, raw);
        /* Object.assign above replaces the nested blocks wholesale, so a stored
           block from an older build would drop its newer defaults. Merge both. */
        s.ollama = Object.assign({}, this.defaults.ollama, raw.ollama || {});
        s.openrouter = Object.assign({}, this.defaults.openrouter, raw.openrouter || {});
        /* Migration from the pre-split shape: the single flat `model`/`api_key`
           pair only ever appeared while OpenRouter was selected, so that is
           where it belongs. save() drops the flat keys, making this one-shot. */
        if (!s.openrouter.model && raw.model) s.openrouter.model = raw.model;
        if (!s.openrouter.api_key && raw.api_key) s.openrouter.api_key = raw.api_key;
        /* Anything but a known transport normalises to the local one, so a
           hand-edited localStorage entry cannot desync the panel and the
           backend (which treats every non-OpenRouter provider as Ollama). */
        if (s.provider !== 'openrouter') s.provider = 'ollama';
        return s;
    },

    save(patch) {
        const data = Object.assign(this.load(), patch || {});
        /* Written in the nested shape only: leaving the flat fields behind
           would let a stale OpenRouter id resurface after the user clears it. */
        delete data.model;
        delete data.api_key;
        localStorage.setItem(this._key, JSON.stringify(data));
        return data;
    },

    /* Patch one provider's block without touching the other's. */
    saveProvider(provider, patch) {
        const s = this.load();
        s[provider] = Object.assign({}, s[provider], patch);
        return this.save({ [provider]: s[provider] });
    },

    /* What the backend needs for a run: the *active* provider's model, never
       the other one's. The key is included — it travels with the request and
       is kept in memory server-side, never persisted. */
    payload() {
        const s = this.load();
        const active = s[s.provider] || {};
        return {
            provider: s.provider,
            model: active.model || '',
            api_key: s.provider === 'openrouter' ? active.api_key || '' : '',
            batch_size: s.batch_size,
            max_chars: s.max_chars,
            workers: s.workers,
        };
    },

    /* Mirror saved values into the panel inputs. */
    applyToPanel() {
        const s = this.load();
        const put = (id, value) => {
            const el = document.getElementById(id);
            if (el) el.value = value;
        };
        put('ai-provider', s.provider);
        put('ai-ollama-model', s.ollama.model || '');
        put('ai-model', s.openrouter.model || '');
        put('ai-key', s.openrouter.api_key || '');
        put('ai-batch', s.batch_size);
        put('ai-maxchars', s.max_chars);
        this.toggleProviderRows(s.provider);
        this.renderOllamaHost();
    },

    toggleProviderRows(provider) {
        document.querySelectorAll('.ai-only-ollama').forEach(el => {
            el.style.display = provider === 'ollama' ? '' : 'none';
        });
        document.querySelectorAll('.ai-only-openrouter').forEach(el => {
            el.style.display = provider === 'openrouter' ? '' : 'none';
        });
    },

    /* The placeholder should show the model the server considers the local
       default (Config.OLLAMA_MODEL) rather than a hardcoded copy of it that
       silently drifts when the environment variable changes. */
    async loadDefaults() {
        if (this._defaultsPulled) return;
        this._defaultsPulled = true;
        try {
            const cfg = await (await fetch('/api/config')).json();
            const input = document.getElementById('ai-ollama-model');
            if (input && cfg && cfg.ollama_model) input.placeholder = cfg.ollama_model;
        } catch (e) {
            /* Unreachable server: the built-in placeholder stands. */
        }
    },

    /* The daemon address is server-side (设置 → Ollama 服务地址). Show what is
       actually configured: "connection refused" is unreadable otherwise. */
    renderOllamaHost() {
        const el = document.getElementById('ai-ollama-host');
        if (!el) return;
        const values = (window.AppSettings && AppSettings._values) || {};
        el.textContent = values.ollama_host || 'http://localhost:11434';
    },
};

/* menu.js loads before this file and guards with `window.LLMSettings` — a
   top-level const never lands on window, so without this export the panel
   opens showing every row instead of just the active provider's. */
window.LLMSettings = LLMSettings;

function onAIProviderChange(value) {
    const provider = value === 'openrouter' ? 'openrouter' : 'ollama';
    const s = LLMSettings.save({ provider });
    LLMSettings.toggleProviderRows(provider);
    if (provider === 'openrouter') {
        refreshAIModels();
    } else if (!s.ollama.model) {
        /* The tag must be one the daemon actually has, and listing it is cheap
           — so offer the list instead of making the user guess. */
        refreshOllamaModels();
    }
}

/* Ollama model — its own field, kept apart from the OpenRouter one. */
function onAIOllamaModelInput(value) {
    LLMSettings.saveProvider('ollama', { model: value.trim() });
}

function onAIModelInput(value) {
    LLMSettings.saveProvider('openrouter', { model: value.trim() });
}

function onAIKeyInput(value) {
    LLMSettings.saveProvider('openrouter', { api_key: value.trim() });
}

function onAINumberInput(field, value) {
    const limits = { batch_size: [1, 100], max_chars: [0, 20000] };
    const [lo, hi] = limits[field] || [0, 999999];
    let n = parseInt(value, 10);
    if (isNaN(n)) n = LLMSettings.load()[field];
    n = Math.max(lo, Math.min(hi, n));
    LLMSettings.save({ [field]: n });
}

/* Fill a model <select> from a list of ids. The ids come from a remote
   catalog / local daemon and go straight into innerHTML, so they are escaped
   rather than trusted. */
function fillModelSelect(sel, ids, current, placeholderKey) {
    sel.innerHTML = '<option value="">' + I18n.t(placeholderKey) + '</option>' +
        ids.map(id =>
            '<option value="' + escapeHtml(id) + '"' + (id === current ? ' selected' : '') + '>' +
            escapeHtml(id) + '</option>'
        ).join('');
}

async function refreshAIModels() {
    const sel = document.getElementById('ai-models');
    const btn = document.getElementById('ai-refresh-btn');
    if (!sel) return;
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch('/api/llm/models');
        const result = await resp.json();
        if (result.ok && result.models.length) {
            fillModelSelect(sel, result.models, LLMSettings.load().openrouter.model, 'ai.pickModel');
            showToast(I18n.t('toast.aiModelsLoaded').replace('{n}', result.models.length));
        } else {
            showToast(I18n.t('toast.aiModelsFail') + ': ' + (result.error || ''));
        }
    } catch (e) {
        showToast(I18n.t('toast.aiModelsFail') + ': ' + e.message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

/* Local daemon tags — a different endpoint from the OpenRouter catalog because
   the two providers no longer share a model setting. */
async function refreshOllamaModels() {
    const sel = document.getElementById('ai-ollama-models');
    const btn = document.getElementById('ai-ollama-refresh-btn');
    if (!sel) return;
    if (btn) btn.disabled = true;
    try {
        const resp = await fetch('/api/llm/ollama/models');
        const result = await resp.json();
        if (result.ok && result.models.length) {
            fillModelSelect(sel, result.models, LLMSettings.load().ollama.model, 'ai.pickModel');
            /* Remembered so merely reopening the panel does not re-hit the
               daemon; 刷新 always re-reads. */
            sel.dataset.loaded = '1';
            showToast(I18n.t('toast.aiModelsLoaded').replace('{n}', result.models.length));
        } else if (result.ok) {
            /* Daemon answered but has nothing pulled — say that, don't fail. */
            showToast(I18n.t('toast.ollamaNoModels'));
        } else {
            showToast(I18n.t('toast.aiModelsFail') + ': ' + (result.error || ''));
        }
    } catch (e) {
        showToast(I18n.t('toast.aiModelsFail') + ': ' + e.message);
    } finally {
        if (btn) btn.disabled = false;
    }
}

function onAIModelPick(id) {
    if (!id) return;
    LLMSettings.saveProvider('openrouter', { model: id });
    const input = document.getElementById('ai-model');
    if (input) input.value = id;
}

function onAIOllamaModelPick(id) {
    if (!id) return;
    LLMSettings.saveProvider('ollama', { model: id });
    const input = document.getElementById('ai-ollama-model');
    if (input) input.value = id;
}

/* ── Machine-local settings (driver path, window, timeouts, Ollama host) ────
   These used to be hardcoded in config.py / crawlers/base.py. They live in
   data/settings.json on the server, edited through the 设置 panel; the draft
   only reaches the server on 保存设置, and warnings (e.g. driver file not
   found) come back in the response. */
const AppSettings = {
    _inputMap: {
        driver_path: 'set-driver',
        browser_binary: 'set-binary',
        window_size: 'set-window',
        page_load_timeout: 'set-pageload',
        element_timeout: 'set-elementwait',
        ollama_host: 'set-ollamahost',
        cookie_confirm_before_run: 'set-cookie-confirm',
    },
    _values: null,
    _draft: {},
    _pulled: false,

    async pull(force) {
        if (this._pulled && !force) return;
        try {
            const resp = await fetch('/api/settings');
            const result = await resp.json();
            if (result.ok) {
                this._values = result.settings || {};
                this._draft = {};
                this._pulled = true;
                this.applyToPanel();
            }
        } catch (e) {
            /* Panel just keeps whatever it has; save() reports failures. */
        }
    },

    applyToPanel() {
        const v = this._values || {};
        Object.keys(this._inputMap).forEach((key) => {
            const el = document.getElementById(this._inputMap[key]);
            if (!el) return;
            // A checkbox answers to .checked; writing .value would silently
            // do nothing and the panel would show a stale box.
            if (el.type === 'checkbox') el.checked = !!v[key];
            else el.value = v[key] !== undefined && v[key] !== null ? v[key] : '';
        });
        /* The AI panel shows the Ollama address read-only, and it is fetched
           asynchronously — mirror it now that the values have arrived. */
        if (window.LLMSettings) LLMSettings.renderOllamaHost();
    },

    async save() {
        if (!Object.keys(this._draft).length) {
            showToast(I18n.t('toast.setNoChange'));
            return;
        }
        const btn = document.getElementById('set-save-btn');
        if (btn) btn.disabled = true;
        try {
            const resp = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ settings: this._draft }),
            });
            const result = await resp.json();
            if (result.ok) {
                this._values = result.settings || {};
                this._draft = {};
                this.applyToPanel();
                const warns = result.warnings || [];
                if (warns.length) {
                    showToast(I18n.t('toast.setSavedWarn') + ' ' + warns.join('；'));
                } else {
                    showToast(I18n.t('toast.setSaved'));
                }
            } else {
                showToast(I18n.t('toast.setSaveFail') + ': ' + (result.error || ''));
            }
        } catch (e) {
            showToast(I18n.t('toast.setSaveFail') + ': ' + e.message);
        } finally {
            if (btn) btn.disabled = false;
        }
    },
};

function onSettingInput(field, value) {
    AppSettings._draft[field] = value;
}

async function saveAppSettings() {
    await AppSettings.save();
}

/* Same window export as LLMSettings — menu.js's 设置 panel guard needs it. */
window.AppSettings = AppSettings;


async function testAIConnection() {
    const btn = document.getElementById('ai-test-btn');
    const s = LLMSettings.load();
    /* Per-provider prerequisites — the same rules the backend enforces before
       a run, so the panel never promises a run it would refuse. */
    if (s.provider === 'openrouter') {
        if (!s.openrouter.api_key) { showToast(I18n.t('toast.aiNeedKey')); return; }
        if (!s.openrouter.model) { showToast(I18n.t('toast.aiNeedModel')); return; }
    } else if (!s.ollama.model) {
        showToast(I18n.t('toast.aiNeedOllamaModel'));
        return;
    }
    if (btn) { btn.disabled = true; btn.textContent = I18n.t('ai.testing'); }
    try {
        const resp = await fetch('/api/llm/test', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(LLMSettings.payload()),
        });
        const result = await resp.json();
        if (result.ok) {
            showToast(I18n.t('toast.aiTestOk').replace('{ms}', result.latency_ms) + ' [' + result.provider + ']');
        } else {
            showToast(I18n.t('toast.aiTestFail') + ': ' + (result.error || ''));
        }
    } catch (e) {
        showToast(I18n.t('toast.aiTestFail') + ': ' + e.message);
    } finally {
        if (btn) { btn.disabled = false; btn.textContent = I18n.t('ai.test'); }
    }
}

document.addEventListener('DOMContentLoaded', () => {
    Settings.apply();
    TopMenu.init();
    canvas.init();
    stats.init();
    /* Replace every OS-drawn candidate UI (select popups, datalist suggestions)
       with the themed equivalents. Runs last so it also catches anything the
       other modules rendered during init. */
    CustomSelect.init();

    /* Uploaded files are stored on the server, so the canvas restored from
       localStorage very likely still owns every file it referenced. Verify
       each one instead of clearing it — see dataNodes.reconcileDatasets. */
    dataNodes.reconcileDatasets();
    /* Sweep orphaned files (only ones no saved workflow points at go). */
    fetch('/api/data/clear', { method: 'POST' }).catch(() => { });

    /* Palette drag */
    document.querySelectorAll('.palette-item').forEach(item => {
        item.addEventListener('dragstart', (e) => {
            e.dataTransfer.setData('text/plain', item.dataset.type);
            e.dataTransfer.effectAllowed = 'copy';
        });
    });

    /* Auto-save every 30 seconds */
    setInterval(() => {
        canvas.saveState();
    }, 30000);

    console.log('Crawler Workflow initialized');

    /* An interrupted run may be waiting from before this page opened. */
    if (window.resumeBar) resumeBar.refresh();
});

/* Background selection is handled by setBg() in workflow.js, which the menu
   delegates to — no separate listener needed here. */

/* ── Panel Drag & Resize Utilities ── */

const _DS = {}; // shared drag state

function makeDraggable(el, handleSelector) {
    const handle = typeof handleSelector === 'string'
        ? el.querySelector(handleSelector) : handleSelector;
    if (!handle) return;

    handle.addEventListener('mousedown', (e) => {
        if (e.target.closest('button, select, input, textarea')) return;
        e.preventDefault();

        /* Convert to floating FIRST (while transform is still readable)
           THEN add panel-dragging to freeze inline styles */
        convertToFloating(el);
        el.classList.add('panel-dragging');

        const rect = el.getBoundingClientRect();
        _DS.el = el;
        _DS.offX = e.clientX - rect.left;
        _DS.offY = e.clientY - rect.top;
        _DS.isDragging = true;
        _DS.handle = handle;
        handle.style.cursor = 'grabbing';
    });
}

document.addEventListener('mousemove', (e) => {
    if (!_DS.isDragging || !_DS.el) return;
    _DS.el.style.setProperty('left', (e.clientX - _DS.offX) + 'px', 'important');
    _DS.el.style.setProperty('top', (e.clientY - _DS.offY) + 'px', 'important');
});

document.addEventListener('mouseup', () => {
    if (_DS.isDragging && _DS.el) {
        _DS.el.classList.remove('panel-dragging');
        if (_DS.handle) _DS.handle.style.cursor = '';
    }
    _DS.isDragging = false;
    _DS.el = null;
    _DS.handle = null;
});

function convertToFloating(el) {
    /* Use getComputedStyle to detect positioning from CSS classes
       (el.style only sees inline styles, not class-based rules) */
    const cs = getComputedStyle(el);
    const hasRight = cs.right && cs.right !== 'auto' && parseFloat(cs.right) !== 0;
    const hasTransform = cs.transform && cs.transform !== 'none';

    if (hasRight || hasTransform) {
        const rect = el.getBoundingClientRect();
        el.style.setProperty('left', rect.left + 'px', 'important');
        el.style.setProperty('top', rect.top + 'px', 'important');
        el.style.right = 'auto';
        el.style.setProperty('transform', 'none', 'important');
    }
}

function makeResizable(el, opts) {
    opts = opts || {};
    const minW = opts.minW || 250;
    const minH = opts.minH || 120;
    const maxW = opts.maxW || window.innerWidth - 40;
    const maxH = opts.maxH || window.innerHeight - 40;
    const onResize = opts.onResize;

    let handle = el.querySelector('.resize-handle');
    if (!handle) {
        handle = document.createElement('div');
        handle.className = 'resize-handle';
        el.appendChild(handle);
    }

    let rs = {};
    handle.addEventListener('mousedown', (e) => {
        e.stopPropagation();
        e.preventDefault();
        convertToFloating(el);
        rs.el = el;
        rs.startX = e.clientX;
        rs.startY = e.clientY;
        rs.startW = el.offsetWidth;
        rs.startH = el.offsetHeight;
        rs.minW = minW; rs.minH = minH; rs.maxW = maxW; rs.maxH = maxH;
        window._rs = rs;
        rs.active = true;
    });

    /* Single shared mousemove/mouseup for resize */
    if (!window._resizeInit) {
        window._resizeInit = true;
        document.addEventListener('mousemove', (e) => {
            const r = window._rs;
            if (!r || !r.active) return;
            const newW = Math.max(r.minW, Math.min(r.maxW, r.startW + (e.clientX - r.startX)));
            const newH = Math.max(r.minH, Math.min(r.maxH, r.startH + (e.clientY - r.startY)));
            r.el.style.setProperty('width', newW + 'px', 'important');
            r.el.style.setProperty('height', newH + 'px', 'important');
            if (r.onResize) r.onResize(newW, newH);
        });
        document.addEventListener('mouseup', () => {
            const r = window._rs;
            if (r) r.active = false;
        });
    }
    rs.onResize = onResize;
    window._rs = rs;
}

/* ── Console pop-out / dock ── */

function toggleConsolePopout() {
    const panel = document.getElementById('console-panel');
    const btn = document.getElementById('btn-console-popout');
    const wasOpen = panel.classList.contains('open');

    if (panel.classList.contains('popout')) {
        /* Dock back */
        panel.classList.remove('popout');
        panel.classList.remove('panel-dragging');
        panel.style.left = '';
        panel.style.top = '';
        panel.style.width = '';
        panel.style.height = '';
        panel.style.transform = '';
        btn.textContent = I18n.t('console.popout');
        /* Restore open state */
        if (wasOpen) panel.classList.add('open');
    } else {
        /* Pop out: ensure open, then switch to floating */
        panel.classList.add('open');
        panel.classList.add('popout');
        /* Remove the docked bottom position, let CSS take over */
        btn.textContent = I18n.t('console.dock');
        /* Make draggable + resizable on first pop */
        if (!panel.dataset._popInit) {
            panel.dataset._popInit = '1';
            makeDraggable(panel, '.console-header');
            makeResizable(panel, { minW: 350, minH: 150, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        }
        /* Add resize handle if not present */
        if (!panel.querySelector('.resize-handle')) {
            const rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }
    I18n.apply();
}

/* ── Console height resize (dock mode) ── */

(function initConsoleResize() {
    const handle = document.getElementById('console-resize-handle');
    if (!handle) return;
    let cs = {};

    handle.addEventListener('mousedown', (e) => {
        const panel = document.getElementById('console-panel');
        if (panel.classList.contains('popout')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('mousemove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('mouseup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
})();

/* ── Run-records panel height resize (dock mode) ── */

(function initRunsResize() {
    const handle = document.getElementById('runs-resize-handle');
    if (!handle) return;
    let cs = {};

    handle.addEventListener('mousedown', (e) => {
        const panel = document.getElementById('runs-panel');
        if (!panel.classList.contains('open')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('mousemove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('mouseup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
})();

/* ── Cookie dialog: close on outside click ──
   The platform dropdown is a CustomSelect: its menu is rendered into <body>,
   OUTSIDE the dialog's DOM. Clicking a row there must count as an interaction
   with the dialog, not as an outside click — same two guards as the
   node-settings panel below. */

document.addEventListener('mousedown', (e) => {
    const dialog = document.getElementById('cookie-dialog');
    if (!dialog.classList.contains('open')) return;
    if (e.target.closest('#cookie-dialog')) return;
    if (e.target.closest('[data-i18n="btn.cookies"]')) return;
    /* A dropdown row belongs to the dialog's own control — never "outside". */
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    if (window.CustomSelect && CustomSelect.ownsPopup(e.target, dialog)) return;
    closeCookieDialog();
});

/* Close node-settings on outside click.
   Several things must not count as "outside" even though they live outside the
   panel's own DOM — otherwise the editor closes on the user mid-edit:
   · the node this panel edits (header, body, ports);
   · that node's right-click submenu, and the full-screen layers the panel can
     launch (chart studio, data preview);
   · a control's own popup (dropdown rows, suggestion candidates), which
     custom-select renders into <body> rather than into the panel. */
document.addEventListener('mousedown', (e) => {
    const panel = document.getElementById('node-settings');
    if (!panel.classList.contains('open')) return;
    if (e.target.closest('#node-settings')) return;
    if (e.target.closest('.node-action-btn, [data-action="ctxEdit"]')) return;
    /* A dropdown row is always an interaction with a control, never an "outside"
       click. The studio's picker renders its rows into <body>, so the overlay
       test below cannot see them — and without this the panel would close
       underneath while the user ticks sources in the studio. */
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    const nodeId = canvas._settingsNodeId;
    if (nodeId && e.target.closest('#' + nodeId)) return;
    if (nodeId && e.target.closest('#context-menu') && canvas._contextNode === nodeId) return;
    if (e.target.closest('#studio-overlay, #data-preview-panel')) return;
    if (window.CustomSelect && CustomSelect.ownsPopup(e.target, panel)) return;
    closeSettings();
});

/* Close the dashboard (看板) and Execution History (执行历史) popups on an
   outside click. They are floating windows, not modal overlays — while one
   is open the canvas stays usable, so the user expects it to be gone once
   they click back into the workspace. What must NOT count as "outside":
   · either panel itself (headers, drag/resize handles — and working with
     one popup may never discard the other; they are sized to sit side by side);
   · CustomSelect option menus — the panel's own <select>s render their menus
     into <body>, so a click there is an inside choice, not a click-away;
   · the modal dialogs (generic confirm, cookie capture) — the history panel's
     own button can raise one, and discarding the panel underneath while the
     answer is pending would strand the dialog over an empty canvas. */
document.addEventListener('mousedown', (e) => {
    if (!e.target || !e.target.closest) return;
    if (e.target.closest('#dashboard-panel, #history-panel')) return;
    if (e.target.closest('.cselect-menu, .cand-menu')) return;
    if (e.target.closest('#dialog-overlay, #cookie-dialog')) return;
    ['dashboard-panel', 'history-panel'].forEach((id) => {
        const panel = document.getElementById(id);
        if (!panel || !panel.classList.contains('open')) return;
        if (window.CustomSelect && CustomSelect.ownsPopup(e.target, panel)) return;
        panel.classList.remove('open');
    });
});

/* ── Init draggable panels on first open ── */

/* Patch openCookieDialog to init drag+resize on first open */
const _origOpenCookie = window.openCookieDialog;
window.openCookieDialog = function () {
    _origOpenCookie();
    const dialog = document.getElementById('cookie-dialog');
    if (dialog.classList.contains('open') && !dialog.dataset._uiInit) {
        dialog.dataset._uiInit = '1';
        makeDraggable(dialog, '.settings-header');
        makeResizable(dialog, { minW: 300, minH: 250, maxW: 500, maxH: 500 });
    }
};

/* Patch openSettings to init drag+resize on first open */
const _origOpenSettings = window.openSettings;
window.openSettings = function (nodeId) {
    var panel = document.getElementById('node-settings');
    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.settings-header');
        makeResizable(panel, { minW: 280, minH: 200, maxW: 500, maxH: 800 });
    }
    _origOpenSettings(nodeId);
};

/* Init processes panel drag+resize */
(function initProcessesPanel() {
    const origToggle = window.toggleProcessesPanel;
    window.toggleProcessesPanel = function () {
        origToggle();
        var panel = document.getElementById('processes-panel');
        if (panel.classList.contains('open') && !panel.dataset._uiInit) {
            panel.dataset._uiInit = '1';
            makeDraggable(panel, '.console-header');
            makeResizable(panel, { minW: 300, minH: 150, maxW: 800, maxH: 500 });
        }
    };
})();
