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
            'menu.file': 'File', 'menu.save': 'Save', 'menu.load': 'Load', 'menu.new': 'New', 'menu.import': 'Import',
            'menu.edit': 'Edit',
            'menu.view': 'View',
            'menu.style': 'Style', 'style.bg': 'Background', 'style.radius': 'Radius',
            'btn.fit': 'Fit',
            'menu.run': 'Run', 'btn.execute': 'Execute', 'btn.queue': 'Queue this run', 'btn.stop': 'Stop',
            'btn.retry': 'Retry',

            'btn.parallel': 'Parallel', 'btn.headless': 'Headless',
            'menu.lang': 'Lang', 'pin.title': 'Pin menu',
            'bg.void': 'Void', 'bg.grid': 'Grid', 'bg.dots': 'Dots',
            'bg.cross': 'Cross', 'bg.diagonal': 'Diagonal',
            'palette.header': 'Node Library',
            'palette.collapse': 'Collapse', 'palette.expand': 'Expand',
            'palette.cat.workflow': 'Workflow',
            'palette.cat.inputs': 'Data Inputs',
            'palette.cat.process': 'Processing',
            'palette.cat.outputs': 'Outputs',
            'palette.source': 'Data Source', 'palette.upload': 'Upload File', 'palette.process': 'Process', 'palette.output': 'Output', 'palette.compile': 'Compile (PDF)',
            'palette.resume': 'Resume Run', 'palette.name': 'Workflow Name',
            'node.source': 'Data Source', 'node.upload': 'Upload File', 'node.process': 'Process',
            'node.analysis': 'Analysis', 'node.visualize': 'Visualize', 'node.tokenize': 'Tokenize', 'node.output': 'Output', 'node.compile': 'Compile', 'compile.summary': 'LaTeX → PDF',
            'node.resume': 'Resume Run', 'node.name': 'Workflow Name',
            'node.comment': 'Comments',
            /* Resumable runs: everything happens while nobody is watching, so
               the wording has to state what is already paid for. */
            'resume.continue': 'Continue', 'resume.restart': 'Start over', 'resume.dismissTitle': 'Dismiss',
            'resume.interrupted': 'Interrupted run found ({at})',
            'resume.detail': '{done}/{total} nodes done, {rows} rows saved — continue picks up from there',
            'resume.runSelect': 'Saved run', 'resume.nodeSelect': 'Node output',
            'resume.autoNode': 'Biggest table (auto)',
            'resume.limit': 'Row limit', 'resume.limitPlaceholder': '0 = all',
            'resume.refresh': 'Refresh list', 'resume.none': 'No saved run yet — run this workflow once',
            'resume.hint': 'Reads a node\'s stored rows from a previous run, with no need to crawl again',
            'toast.runDiscarded': 'Saved run discarded — starting fresh',
            'settings.file': 'File', 'settings.rows': 'rows',
            'stats.header': 'Statistics', 'stats.close': 'Close',
            'stats.emotion': 'Emotion', 'stats.tendency': 'Tendency',
            'settings.header': 'Node Settings', 'settings.close': 'Close',
            'outline.title': 'Outline', 'outline.collapse': 'Collapse', 'outline.expand': 'Expand',
            'outline.noNodes': 'No nodes yet',
            'status.ready': 'Ready', 'status.completed': 'Completed', 'status.running': 'Running...',
            'status.stopping': 'Stopping…',
            'ctx.newSource': 'New Source Node', 'ctx.newUpload': 'New Upload Node',
            'ctx.newProcess': 'New Process Node',
            'ctx.newOutput': 'New Output Node', 'ctx.newCompile': 'New Compile Node', 'ctx.edit': 'Edit Node', 'ctx.rename': 'Rename Node',
            'ctx.renameHint': 'Double-click to rename',
            'ctx.copy': 'Copy Node', 'ctx.paste': 'Paste Node',
            'ctx.disableNode': 'Disable this node', 'ctx.enableNode': 'Enable this node',
            'ctx.disableType': 'Disable all {type} nodes', 'ctx.enableType': 'Enable all {type} nodes',
            'node.badgeDisabled': 'Disabled', 'node.badgeNoInput': 'No live input',
            'ctx.delete': 'Delete Node', 'ctx.clear': 'Clear All Connections',
            'btn.cookies': 'Cookies',
            'console.header': 'Console', 'console.clear': 'Clear', 'console.close': 'Close', 'console.popout': 'Pop', 'console.dock': 'Dock',
            'console.all': 'All',
            'processes.header': 'Processes', 'processes.close': 'Close',
            'processes.running': 'Running', 'processes.stopped': 'Stopped',
            'processes.threads': 'Threads', 'processes.crawlers': 'Crawlers',
            'processes.pool': 'Pool Active', 'processes.yes': 'Yes', 'processes.no': 'No',
            'processes.name': 'Name', 'processes.status': 'Status', 'processes.type': 'Type',
            'processes.kill': 'Kill',
            'cookies.header': 'Cookie Settings', 'cookies.platform': 'Platform',
            'cookies.paste': 'Paste Cookies JSON', 'cookies.save': 'Save Cookies',
            'cookies.generate': 'Generate via Browser', 'cookies.waitTime': 'Wait time (seconds) for login:',
            'cookie.opening': 'Opening browser for {platform} login (waiting {s}s)...',
            'cookie.failed': 'Failed: {err}',
            'cookie.unreachable': 'Cannot reach the server (it may be starting or reloading) — try again shortly',
            'cookies.doneBtn': 'Done — I logged in',
            'cookies.cancelBtn': 'Cancel login',
            'cookie.mustStay': 'Login in progress — press Done or Cancel first, this window must stay open',
            'cookie.waiting': '{platform} login window open — finish logging in, then press Done',
            'cookies.entryUrl': 'Login entry link (optional: empty opens the platform login page)',
            'cookies.verify': 'Verify cookie',
            'cookies.delete': 'Delete saved Cookie',
            'cookies.deleteProfile': 'Delete saved Profile',
            'cookies.accountDefault': 'Default account',
            /* Sent as a labelKey by /api/cookies/status for a login this program named: the
               SECOND blank save is `default2` on disk. A key the server hands the browser and
               the browser cannot answer is a raw string on screen, which is why
               ``test_every_account_label_the_server_sends_has_a_word_in_both_languages`` walks them. */
            'cookies.accountDefaultNumbered': 'Default account {n}',
            'cookies.accountDefaultHint': 'This login is named default',
            'cookies.accountStatusHead': '{platform} · {account}',
            'cookies.accountStatusNone': 'no cookie saved for it yet',
            'cookies.accountStatusSaved': '{n} entries, saved {when}',
            'cookies.chosen': 'Selected login: {platform} · {account}',
            'cookies.listFailed': 'Could not read the saved logins (the server did not answer)',
            'cookies.manageTitle': 'Saved logins',
            'cookies.noneSaved': 'Nothing is saved yet — paste a Cookie and it appears here.',
            'cookies.unknownWhen': 'unknown',
            'cookies.renameOne': 'Rename',
            'cookies.renamePlaceholder': 'a new name for this login',
            'cookies.renameSame': 'That is already its name, so nothing was renamed',
            'cookies.renameDefaultRefused':
                'The default account cannot be renamed: its browser directory IS this platform’s directory, with every other account inside it',
            'cookies.colPlatform': 'Platform',
            'cookies.colAccount': 'Account',
            'cookies.colEntries': 'Entries',
            'cookies.colSavedAt': 'Saved',
            'cookies.colActions': 'Actions',
            'cookies.deleteOne': 'Delete',
            /* The first-entry notice on a cloud host. The headline is the first line of the
               body because this page's dialog has no title slot — inventing one for one
               dialog would be a second way to render a dialog. */
            'privacy.body':
                'This app is running on a server, not on your computer.\n' +
                'Stored on the server: the cookies you paste in, every table you upload or crawl, ' +
                'your workflow files and run records. Cookie VALUES are never sent back to a browser ' +
                "or shown on screen, but they live on this server's disk.\n" +
                'Stored only in this browser: your OpenRouter API key, the canvas draft and the ' +
                'interface settings. The key is used inside one request and never written to a ' +
                'server file.',
            'privacy.gotIt': 'Got it',
            'privacy.never': 'Stop showing this',
            'cookies.account': 'Account',
            'cookies.accountPlaceholder': 'default = the default login; type a new name to create one',
            'field.account': 'Account',
            'dialog.cookieDelete': 'Delete the Cookie file saved for {platform}? If this platform is crawled inside its own browser profile, its login lives in that profile: deleting this file does not sign the profile out, it only removes the snapshot a throwaway browser is planted from. The answer says which of the two applies to {platform}.',
            'dialog.cookieDeleteYes': 'Delete the file',
            'cookies.deleteProfileOne': 'Delete Profile',
            'cookies.profileDeleteDefaultRefused': 'The default account has no browser profile to delete — its data is the platform folder, and every other account is inside it',
            'dialog.profileDelete': 'Delete the browser profile for {platform} · {account}? This signs that device out and removes its on-disk browser data (the profile keeps its own session; the saved Cookie file is left untouched).',
            'dialog.profileDeleteYes': 'Delete the profile',
            'toast.profileDeleted': 'Browser profile deleted',
            'dialog.cookieRename': 'Rename the login “{account}” of {platform}? Its cookie file and its own browser directory move together.',
            'toast.cookieRenamed': 'Login renamed',
            'toast.cookieDeleted': 'Cookie file deleted for {platform}',
            /* No ``cookies.refreshExplain`` any more (user, 2026-09-28): a standing paragraph
               about how a profile relates to a cookie file is the implementation's history,
               not a choice the user makes. The setting row says the benefit instead. */
            'cookie.refreshHint':
                'That profile still holds an older cookie: it was busy when this one was saved, so the next '
                + 'crawl of this account brings the new one in on its own',
            'toast.cookieChecking': 'Checking the Cookie for {platforms} before the run…',
            'toast.cookieUncheckable': 'The Cookie check could not run for {platforms} — that is not a pass, and the run is starting anyway',
            'toast.cookieUnclear': 'Could not verify the Cookie for {platforms} (captcha, timeout or a profile already in use) — no answer is not a failure, so the run is not blocked',
            'dialog.cookieExpired': '{n} platform(s) refused the stored Cookie, so the run will not start: {platforms}',
            'dialog.cookieExpiredHint': 'Log in again under Settings → Cookie and save. There is deliberately no "run anyway" here: a crawl that starts at a login page comes back an hour later with an empty table and a half-built dataset.',
            'dialog.cookieGoUpdate': 'Open the Cookie panel',
            'cookie.verifying': 'Probing the platform with the stored cookie…',
            'cookie.guideLoading': 'Loading the steps for this platform…',
            'cookie.entryRejected': 'That link is not on this platform’s domain — the platform login page was opened instead',
            'cookie.savedN': 'Saved {n} cookies for {platform}',
            'cookie.savedYes': 'saved',
            'cookie.savedNo': 'none',
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
            'toast.workflowFileInvalid': 'That file is not a workflow — it holds no node list, so nothing was changed',
            'toast.workflowImported': 'Imported — the workflow is on the canvas now (not yet saved to the server)',
            'toast.workflowImportFailed': 'That file could not be read as JSON',
            'toast.workflowStarted': 'Workflow started',
            'toast.consoleReconnected': 'Reconnected to the run still going — its log is shown below',
            'toast.workflowEnded': 'Run ended — {done}/{total} nodes completed (continue is available)',
            'toast.queued': 'Queued — it starts when the current run finishes',
            'toast.workflowCompleted': 'Workflow completed',
            'toast.workflowRejected': 'Nothing ran — the workflow has problems listed in the console',
            'toast.pollFailed': 'Lost contact with the server — status refresh stopped',
            'toast.workflowStopped': 'Workflow stopped',
            'toast.stillSettling': 'Still stopping — the run record will settle on its own',
            'toast.stopping': 'Stopping — closing browsers and writing the record…',
            'toast.noWorkflows': 'No saved workflows',
            'toast.saveFailed': 'Save failed',
            'toast.loadFailed': 'Load failed',
            'toast.executeFailed': 'Execute failed',
            'toast.stopFailed': 'Stop failed',
            'toast.killFailed': 'Could not kill that process',
            'toast.cookiesSaved': 'Cookies saved',
            /* One press, one toast: the count is what tells the user the list below is
               everything that is wrong, not the one thing they will get to see. */
            'toast.problems': '{n} problems to fix before this run can start:',
            'dialog.workflowName': 'Workflow name:',
            'dialog.selectWorkflow': 'Enter workflow name to load:',
            'dialog.cancel': 'Cancel',
            'dialog.confirm': 'Confirm',
            'dialog.renameNode': 'Rename this node — the console will say its name instead of node-N:',
            /* Fan-in / fan-out wire consequences. One message per outcome the executor
               actually produces, so a wire is explained the moment it is drawn. Each
               names the node, and {count} appears only in the fan-out line — the parity
               guard requires the two languages to use a slot the same number of times. */
            'conn.fanin.name': '“{node}” is a workflow-name node — a run rejects any wire feeding into it; nothing may sit upstream of a name.',
            'conn.fanin.ignore': '“{node}” reads no upstream data at all — this wire does nothing when the workflow runs.',
            'conn.fanin.first': '“{node}” uses only the FIRST incoming table; every other upstream is silently ignored at run time.',
            'conn.fanin.source': '“{node}” (Source) uses at most one upstream: if this crawl can be fed it reads only the first parent that carries a table; if it cannot, a run rejects the wire.',
            'conn.fanin.analysis': '“{node}” joins only two tables — the first as the left, the second as the right; a third or later upstream is dropped, and non-join steps read only the first.',
            'conn.fanin.merge': '“{node}” (Output) merges EVERY incoming table into one file (rows stacked); if two tables have different columns the run is refused by name.',
            'conn.fanout': '“{node}” now feeds {count} downstream nodes. That is safe: each branch receives the same complete copy of its rows — nothing is split or overwritten.',
            'conn.help': 'See the README “Wiring branches” section for the full table.',
            'conn.undo': 'Undo this connection',
            'conn.keep': 'Keep it',
            'conn.dismiss': 'Do not warn me again this session',
            'toast.cookieExpired': 'Login wall hit — the cookie likely expired mid-run. Collected data is saved: refresh it under Settings → Cookie, then resume this run.',
            'settings.nodeType': 'Node Type',
            'settings.platform': 'Platform',
            'settings.collect': 'Collect',
            'settings.collectPosts': 'Posts / articles',
            'settings.collectVideos': 'Videos',
            'settings.collectComments': 'Comments',
            'settings.collectAuthor': "A creator's posts",
            'settings.collectHot': 'Hot list',
            'settings.hotBoard': 'Board',
            'settings.hotBoardPopular': 'Popular feed',
            'settings.hotBoardRanking': 'Weekly ranking',
            'settings.author': 'Creator',
            'settings.authorHint': 'An @handle or a link to that author — not a display name to search for (YouTube also accepts a UC… channel id)',
            'settings.authorHintZhihu': 'A profile link, or the id after /people/ — a Zhihu answer page carries no link to the author profile, so a display name cannot be resolved',
            'settings.authorHintBili': 'A space.bilibili.com link, or the numeric UID — the upload list is read from the page itself (its API needs a per-request signature), so the number is what addresses it',
            'settings.authorHintDouyin': 'A douyin.com/user/… profile link, or the sec_uid inside it — a display name addresses nobody, and the list is read off the profile grid',
            'settings.authorHintWeibo': 'A weibo.com/u/<UID> profile link, or the numeric UID — the posts are read from the author page\u2019s own endpoint, which cannot be addressed by a display name',
            'settings.withFacts': 'Fetch exact figures per row',
            'settings.withFactsHint': 'One extra request per row (~0.3 s) for likes, the full text and the real publish time. Off = keep the list figures.',
            'settings.fullBody': 'Expand full text',
            'settings.fullBodyHint': 'The result list carries an excerpt only (measured 35–109 characters per row). Each 回答 card gets one in-place 阅读全文 click (~0.3 s); column cards are never clicked — that one navigates away and detaches the rest of the list.',
            'settings.articleUrls': 'Article bodies',
            'settings.capFailed': 'The crawl list could not be read from the server, and the Data Source form is built from it.',
            'settings.capLoaded': 'Crawl list reloaded',
            'settings.capNoMode': 'This platform has no crawl mode yet, so it cannot run as a data source.',
            'settings.keyword': 'Keyword',
            'settings.targetCount': 'Target Count',
            'settings.startTime': 'Start Time',
            'settings.endTime': 'End Time',
            'settings.operation': 'Operation',
            'settings.unknownOption': '"{value}" - not a choice, pick one',
            'settings.textColumn': 'Text Column',
            'settings.topic': 'Topic',
            'settings.filename': 'Filename',
            'settings.filenameTimestamp': 'Append the run time to the filename (never overwrite)',
            'settings.filenameTimeRange': 'Append the crawled time range to the filename',
            'settings.workflowName': 'Workflow name',
            'settings.layoutOrder': 'Layout order',
            'settings.layoutOrderHint': 'Lower numbers stack higher on the canvas. Leave blank to keep creation order.',
            'nodeType.source': 'Data Source',
            'nodeType.upload': 'Upload File',
            'nodeType.process': 'Process',
            'nodeType.analysis': 'Analysis',
            'nodeType.visualize': 'Visualize',
            'nodeType.tokenize': 'Tokenize',
            'nodeType.resume': 'Resume Run', 'nodeType.name': 'Workflow Name',
            'nodeType.output': 'Output',
            'nodeType.compile': 'Compile',
            'nodeType.comment': 'Comments',
            /* The run-detail card falls back to this for a node type this build
               does not know — one stored by a newer version, or hand-edited in.
               A computed key never reaches the i18n audit, so the fallback has to
               exist here or the panel prints the raw key and logs a warning. */
            'nodeType.misc': 'Node',
            'op.clean': 'Clean',
            'op.emotion': 'Emotion',
            'op.sentiment': 'Sentiment polarity',
            'op.tendency': 'Tendency',
            'op.save_csv': 'Save CSV',
            'op.save': 'Save',
            'op.chart': 'Chart',
            'op.drop_null': 'Drop Null Rows',
            'op.fill_null': 'Fill Null Values',
            'op.drop_duplicates': 'Drop Duplicates',
            'op.dedupe_similar': 'Drop Near-Duplicates (SimHash)',
            'settings.dedupeMode': 'Match on',
            'settings.dedupeModeExact': 'Exact text',
            'settings.dedupeModeNormalized': 'Normalised text (links/@/topics/emoji ignored)',
            'settings.dedupeDistance': 'Bit distance',
            'settings.dedupeSimilarHint': 'SimHash compares what a comment is ABOUT, not its exact characters, so a repost with one word changed or a padded laugh collapses into the same group. The first row of each group is kept. 0 merges only identical fingerprints. Measured on Weibo comments: a one-word rewrite sits 5–18 bits apart and two unrelated comments 26–28, so 8 (the default) catches the clearly-identical rewrites and leaves the rest alone; raise it towards 15 for more recall at the cost of precision.',
            'op.extract_time': 'Extract calendar part',
            'op.bin_time': 'Split into phases',
            'op.suggest_stages': 'Suggest phase boundaries',
            'op.topic_model': 'Topic model (LDA)',
            'op.topic_by_stage': 'Topic model per phase (LDA)',
            'op.topic_label': 'Summarise each topic (LLM)',
            'op.topic_map': 'Intertopic distance map (data)',
            'op.topic_salience': 'Salient terms per topic (data)',
            'op.topic_timeline': 'Topic lifecycles (secondary flare-ups)',
            'op.topic_flow': 'Topic flow between phases',
            'op.topic_coherence': 'Topic-count sweep (coherence + perplexity)',
            'op.cooccur': 'Word co-occurrence edges',
            'op.forecast': 'Forecast the sentiment curve',
            'op.alert': 'Secondary-outbreak warning',
            'settings.forecastPeriodColumn': 'Period column (dates)',
            'settings.forecastValueColumn': 'Value column to extrapolate',
            'settings.forecastMethod': 'Method',
            'settings.forecastMethodMa': 'Moving average (flat)',
            'settings.forecastMethodHolt': 'Holt (level + trend)',
            'settings.forecastHorizon': 'Steps ahead',
            'settings.forecastWindow': 'Window (moving average)',
            'settings.forecastAlpha': 'α (level smoothing)',
            'settings.forecastBeta': 'β (trend smoothing)',
            'settings.forecastMinPeriods': 'Minimum observed periods',
            'settings.forecastHint': 'This extrapolates the SHAPE of the curve, not events: nothing here knows about a police notification. History keeps its actual plus the one-step-ahead value the model would have predicted (horizon 0); future rows carry predicted/lower/upper only. Holt widens its band with √horizon because a trend carried further really is less certain, while a moving average has no trend to widen, so its band stays flat rather than pretending otherwise. The period column has to parse to DATES — a phase name like 发酵期 cannot be extrapolated — and an uneven series is reported, with future labels stepped by the most common gap.',
            'settings.alertPeriodColumn': 'Period column (dates)',
            'settings.alertIndexColumn': 'Sentiment index column',
            'settings.alertIntensityColumn': 'Intensity column (blank = no 升温 signal)',
            'settings.alertVolumeColumn': 'Volume column (blank = no decay check)',
            'settings.alertStreak': 'Consecutive periods',
            'settings.alertSwing': 'Swing threshold |Δindex|',
            'settings.alertHeating': 'Intensity slope threshold',
            'settings.alertVolumeFloor': 'Volume hold ratio (0–1)',
            'settings.alertHint': '转向 fires when N consecutive steps each moved the index by at least the swing, all in one direction; 升温 fires when the intensity rose by at least the slope per step. Either is SUPPRESSED while the volume sits below the hold ratio, because a swing by a handful of leftover posters is not an outbreak. A suppressed candidate still gets a row saying so, and when nothing fires the table answers with one 未触发 row carrying the largest value measured — an empty table would read as "not checked".',
            'op.sentiment_evolution': 'Sentiment evolution curve',
            'settings.newColumn': 'New column',
            'settings.timePart': 'Which part',
            'settings.timePartDate': 'Day (YYYY-MM-DD)',
            'settings.timePartHour': 'Hour of day',
            'settings.timePartWeekday': 'Weekday',
            'settings.timePartMonth': 'Month',
            'settings.timePartYear': 'Year',
            'settings.phaseEdges': 'Boundaries (earliest first)',
            'settings.phaseLabels': 'Phase names',
            'settings.phaseOrderColumn': 'Phase-order column (blank = none)',
            'settings.phaseHint': 'Boundaries are left-closed, right-open: five phases need SIX dates, the last being the day after the final phase ends. Splitting on the calendar day means 23:59 on the day before a boundary stays in the earlier phase. Naming an order column adds the phase position as a NUMBER (first = 1) — the only form of the lifecycle order that survives a node boundary, because the ordered category degrades to plain strings there and Chinese names then sort by code point (二次爆发期 before 发酵期).',
            'settings.stagesMinDays': 'Shortest window (days)',
            'settings.stagesMaxWindows': 'At most N windows',
            'settings.stagesPeakRatio': 'Peak must be × this above a usual day',
            'settings.stagesHint': 'A PROPOSAL, nothing more: it reads the posts-per-day curve, marks its peaks and cuts between them at the valleys. No row is changed. The console prints the boundary list and the phase names, which paste straight into 按时间划分阶段 (bin_time). Bring the 官方通报 / 道歉 dates yourself — they are not in the counts.',
            'settings.nTopics': 'Number of topics',
            'settings.topicTopn': 'Words per topic',
            'settings.topicMaxFeatures': 'Vocabulary cap',
            'settings.topicHint': 'LDA via scikit-learn — no extra dependency. The output is one row per (topic, keyword), so a chart can group it by topic. The console prints each topic\'s words in order and the perplexity, which is how you choose the number of topics: try several and watch it fall.',
            'settings.stageColumn': 'Phase column',
            'settings.stageOrderColumn': 'Phase order comes from (time column)',
            'settings.stageTopicCounts': 'Topics per phase (one number, or one per phase)',
            'settings.topicSampleN': 'Sample posts per topic',
            'settings.topicWordSource': 'Feature words from',
            'settings.topicWordSourceTfidf': 'TF-IDF of the topic\'s posts',
            'settings.topicWordSourceLda': 'LDA topic-word weights',
            'settings.topicStageHint': 'This is 表 1: one row per (phase, topic), numbered TopicⅠ-1 … by the phase\'s place in the lifecycle. Fitting one LDA over the whole corpus instead cannot produce it — the pooled model spends its topics on the phases with the most posts. Leave 每阶段主题数 as a single number for the same count everywhere, or write one per phase (5,6,4,4,4). TF-IDF drops single-character words (捞), which LDA keeps: the two lists differ on purpose.',
            'settings.labelWordsColumn': 'Feature-word column',
            'settings.labelSamplesColumn': 'Sample-text column (optional)',
            'settings.labelSummaryColumn': 'Summary column to write',
            'settings.labelOnFail': 'If the model refuses',
            'settings.labelOnFailAbort': 'Fail the node (default)',
            'settings.labelOnFailBlank': 'Leave that cell empty',
            'settings.labelMaxTopics': 'Max topics to ask',
            'settings.topicLabelHint': 'One model call per topic row — 表 1 is 25 calls, so this step is capped. It answers in the run\'s own language and writes the phrase into 主题概括; the paper\'s authors wrote that column by reading the corpus, so treat this as this project\'s reading of the same words.',
            'settings.topicMapTopn': 'Words shown per bubble',
            'settings.topicMapHint': 'The left half of the pyLDAvis figure, as a TABLE: one row per topic with its map coordinates (PC1/PC2 from MDS of the Jensen-Shannon distance between topic word distributions), its share of the corpus and its top words. Feed it to the 主题距离图 chart. Overlapping bubbles mean the split was not in the text — that is the finding, not a rendering problem.',
            'settings.topicTermsTopn': 'Terms per topic',
            'settings.topicLambda': 'λ (relevance weighting)',
            'settings.topicSalienceHint': 'The right half of the figure, as a table: rank 1..N terms of each topic with BOTH counts — overall_freq (corpus-wide, the blue bar) and within_freq (what this topic alone produces, the red bar). λ decides the ranking: 1 = probability within the topic, 0 = over-representation against the corpus; the paper\'s figure has a slider for this and the number used is printed with the rows. Feed it to the 显著词图 chart after filtering to one topic.',
            'settings.timelineStageColumn': 'Phase column',
            'settings.timelineTopicColumn': 'Topic column (label only)',
            'settings.timelineWordsColumn': 'Feature-word column',
            'settings.timelineSizeColumn': 'Size column (for the peak)',
            'settings.timelineOrderColumn': 'Phase-order column',
            'settings.timelineOverlap': 'Same-topic word overlap (0–1)',
            'settings.timelineHint': 'One row per SUBJECT, not per topic number: a per-phase LDA renumbers every phase (TopicⅠ-1 is not TopicⅡ-1), so a subject is followed by how much its feature-word list overlaps, from its first phase to its peak and its last. 次生舆情 (is_secondary) needs both: the subject did not open the case, and it grew after it appeared. Feed the 阶段 column 按时间划分阶段 writes, or name a time column to order the phases by; without an order it refuses instead of sorting Chinese names by code point.',
            'settings.flowStageColumn': 'Phase column',
            'settings.flowTopicColumn': 'Topic column',
            'settings.flowWordsColumn': 'Feature-word column (shown on the edge)',
            'settings.flowWeightsColumn': 'Word-weight column (word:weight)',
            'settings.flowOrderColumn': 'Phase-order column',
            'settings.flowLabelColumn': 'Topic-name column (blank = TopicⅠ-1)',
            'settings.flowMinSimilarity': 'Minimum similarity (0–1)',
            'settings.flowHint': 'Adjacent phases only, compared by the Jensen-Shannon divergence of their WORD DISTRIBUTIONS (the word:weight cell), turned into similarity = 1/(1+d). Output is source/target/value, which is exactly what the 桑基图 node reads: x=source, y=target, value field=similarity. If nothing reaches the threshold it refuses and names the closest pair it measured — an empty flow table would look like "no carry-over", which is not what was checked.',
            'settings.coherenceMinTopics': 'Lowest topic count',
            'settings.coherenceMaxTopics': 'Highest topic count',
            'settings.coherenceMaxDocuments': 'Texts sampled (0 = all)',
            'settings.coherenceHint': 'Fits the model once per topic count and prints both numbers that argue about 设定主题个数: perplexity (falls as the model memorises rows) and coherence (do a topic\'s top words actually appear in the same posts). The coherence here is document-level NPMI — a fraction of the published C_v, not C_v itself, so it will not match a paper that used the full algorithm. The sample is fixed per table, so two runs give the same numbers.',
            'settings.cooccurTopn': 'Candidate words (max 120)',
            'settings.cooccurMinCount': 'Minimum co-occurrences',
            'settings.cooccurWindow': 'Window in tokens (0 = whole post)',
            'settings.cooccurHint': 'The 知识图谱 half of the paper: two words are linked because readers put them in the same post. Candidates are the corpus TF-IDF list (the same tokenizer and the same ≥2-character rule the keyword node uses), and the output source/target/value feeds the 关系图 or the 桑基图 node. topn is capped at 120 because the graph is complete over its candidates — 120 words is 7,140 pairs per post.',
            'settings.labelColumn': 'Sentiment column',
            'settings.labelPositive': 'Positive label',
            'settings.labelNeutral': 'Neutral label',
            'settings.labelNegative': 'Negative label',
            'settings.scoreColumn': 'Score column (intensity)',
            'settings.evolutionOrderColumn': 'Phase-order column (序号 or 时间)',
            'settings.evolutionHint': 'This is the evolution curve\'s data. The index is (positive − negative) / total, so +1 is a wholly positive period and −1 wholly negative; 0 means either everything was neutral or the two sides cancelled. Every period also gets volume_pct, its share of the corpus — the 舆情热度 half of the figure. Fill in a score column (the sentiment node\'s 0–1 score) to also get intensity = mean(|score − 0.5|) × 2, how hard the crowd pushed in either direction: plot it against volume_pct on a dual-axis line chart to read the paper\'s finding that 爆发期 and 二次爆发期 lean opposite ways. When you group by a PHASE column, name its order column too (the 阶段序号 划分阶段 writes): rows are otherwise sorted by period name, and 二次爆发期 sorts before 发酵期 by code point, which presents the lifecycle out of order.',
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
            'platform.twitter': 'X (Twitter)',
            'platform.instagram': 'Instagram',
            'platform.youtube': 'YouTube',
            'btn.uploadFile': 'Upload File',
            'btn.preview': 'Preview Chart',
            'palette.analysis': 'Analysis',
            'palette.visualize': 'Visualize',
            'palette.tokenize': 'Tokenize',
            'ctx.newAnalysis': 'New Analysis Node',
            'ctx.newVisualize': 'New Visualize Node',
            'ctx.newTokenize': 'New Tokenize Node',
            'chart.header': 'Chart Preview',
            'chart.saveImage': 'Save image',
            'chart.fullscreen': 'Fullscreen',
            'chart.saveNothing': 'Nothing to save yet — preview the chart (or run the node) first',
            'chart.copyLatex': 'Copy LaTeX', 'chart.downloadLatex': 'Download LaTeX (.txt)',
            'chart.copyTable': 'Copy table', 'chart.downloadTable': 'Download table (.txt)',
            'chart.copied': 'Copied to clipboard',
            'settings.emitLatex': 'Emit LaTeX figure (.txt)',
            'settings.emitLatexHint': 'Also writes a MiKTeX-compilable standalone figure source to the exports folder. On by default; untick to skip.',
            'settings.emitLatexTable': 'Emit LaTeX three-line table (booktabs)',
            'settings.compileHint': 'Compiles the LaTeX a connected visualize node emitted (figure and/or three-line table) into one PDF using the local MiKTeX. Connect it to an Output node and pick PDF to write the file; set the xelatex path under Settings.',
            'settings.outputPdfHint': 'This output is fed by a chart / compile node, so the only format is PDF — the LaTeX above is compiled to a file here.',
            'chart.bar': 'Bar', 'chart.line': 'Line', 'chart.dual_line': 'Dual-axis line', 'chart.stack_pct': '100% stacked share', 'chart.pie': 'Pie',
            'chart.topic_map': 'Intertopic map', 'chart.topic_terms': 'Salient terms',
            'chart.scatter': 'Scatter', 'chart.histogram': 'Histogram', 'chart.box': 'Box Plot',
            'chart.heatmap': 'Heatmap', 'chart.model_agreement': 'Model Agreement', 'chart.wordcloud': 'Word Cloud',
            'chart.sankey': 'Sankey Diagram', 'chart.network': 'Relationship Network', 'chart.map': 'Map (China)',
            'format.csv': 'CSV', 'format.json': 'JSON', 'format.excel': 'Excel (.xlsx)',
            'format.txt': 'Text (.txt)', 'format.html': 'HTML', 'format.markdown': 'Markdown', 'format.pdf': 'PDF (compiled LaTeX)',
            'settings.format': 'Format',
            'settings.columns': 'Columns',
            'settings.commentPreview': 'Comment preview per note',
            'settings.commentPreviewHint': 'How many comments each note row carries. 0 skips the comment panel (fastest).',
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
            'settings.y2Field': 'Y2 Field (right axis)',
            'settings.stackFields': 'Stacked Fields',
            'hint.stackFields': 'Comma-separated columns, each one segment of the bar. Every category is normalised to 100%, so pass the share columns a step wrote (e.g. 积极占比, 中性占比, 消极占比) or any counts that form one distribution.',
            'hint.bertModelsMulti': 'Two or more models selected: this node now outputs a per-row × per-model comparison table (it adds the 模型 and 原行 columns) for the comparison charts.',
            'hint.modelAgreement': 'Pairwise percent of the rows on which two models chose the SAME label. The upstream must be a multi-model comparison table (an analysis node with ≥2 models checked).',
            'settings.agg2': 'Aggregation (right axis)',
            'settings.labelField': 'Bubble label column',
            'hint.dualLine': 'Two scales, one axis: the left series is 舆情热度 (rows or volume_pct), the right one 情感强度. ECharts only — Matplotlib refuses this type by name.',
            'settings.title': 'Chart Title',
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
            'settings.chartAnnotations': 'Event markers (date=label; …)',
            'hint.annotations': 'One vertical dashed line per event, drawn AT THE X-AXIS LABEL you type, so 4/23 遗体打捞 and 5/19 通报 sit on the curve they explain. Separate events with ; and write date=label (= or : both work). The label has to be one of this axis\'s values exactly: a date formatted differently would draw nothing, so a name that is not on the axis is refused with the real labels listed instead of a figure that quietly lost its dates. 柱状图 / 折线图 / 双轴折线 only.',
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
            'chart.noRunData': 'No run data yet — execute the workflow once first.',
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
            'history.remove': 'Delete',
            'history.confirmRemove': 'Delete the recorded metrics of run {rid}? The rest of the history stays.',
            'history.removed': 'Run removed from execution history',
            'history.removeGone': 'That run was no longer in the history (cleaned up in the meantime)',
            'history.removeFailed': 'Delete failed',
            'settings.mode': 'Analysis Mode',
            'settings.nodeModel': 'Model (this node)',
            'settings.followGlobalModel': 'Follow global AI model',
            'mode.llm': 'LLM (local Ollama / OpenRouter)',
            // On a cloud host the first half of that name is a transport with no daemon
            // behind it, so the option says what will actually be called.
            'mode.llmCloud': 'LLM (OpenRouter)',
            'mode.ml': 'Traditional ML (sklearn)',
            'mode.snownlp': 'SnowNLP (traditional polarity, no model needed)',
            'mode.bert': 'BERT transformer (needs torch + a sentiment model)',
            'settings.posThreshold': 'Positive at or above',
            'settings.negThreshold': 'Negative at or below',
            'settings.sentimentThresholdHint': 'SnowNLP answers a 0–1 probability that the text is positive. Between the two figures the row is 中性; raise the band when a site writes neutrally, lower it when you want fewer neutral rows. The score column always keeps the raw figure.',
            'settings.bertModel': 'BERT model',
            'settings.bertModelsPick': 'Registered models (tick several to compare)',
            'settings.modelField': 'Model column',
            'settings.networkCenter': 'Centre node (optional)',
            'settings.networkCenterPlaceholder': 'a word already in the graph (blank = full graph)',
            'hint.networkCenter': 'Name one word and draw only its ego-network — that word and the words directly co-occurring with it — so a dense 关系图 becomes a single readable, exportable figure (no more info that only shows on hover). Blank renders the whole candidate graph.',
            'settings.agreementLabelField': 'Label column to compare',
            'settings.idField': 'Row-id column (aligns the same text across models)',
            'settings.batchSize': 'Batch size',
            'settings.bertModelHint': 'A local folder or a model name on this machine. Left empty, the node refuses to run rather than answering with a different model. The whole column is judged in batches, on the GPU when there is one.',
            'mode.regex': 'Rule-based regex (no model)',
            'settings.cleanRegexHint': 'Strips what a repost leaves behind: the //@ forward chain (only your own words survive), @mentions, #topic# markers, links and 网页链接 placeholders, 展开c, and [emoji] codes. Rows that were nothing but those become 删除. It does NOT judge whether a comment is about your topic — that is what the model mode is for. The original text column is kept, so nothing is lost.',
            'settings.methodCorpusIdf': 'TF-IDF on your own corpus',
            'settings.outputMergeHint': 'Several upstream wires merge into ONE table here, and that merged table is what flows onwards — so a chain of analyses can hang off this node. The upstreams must have the same column set; if they differ the node refuses and names the extra/missing columns rather than outer-joining them into a table full of empty cells.',
            'settings.allowPos': 'Word classes',
            'settings.allowPosHint': 'Comma-separated jieba word classes, e.g. n,vn,v,a — nouns, verbal nouns, verbs, adjectives. Empty keeps every word, which is what this node always did. Filtering is what removes 转发 / 哈哈 / 回复 from a Weibo keyword list.',
            'settings.entityTypes': 'Entity types',
            'settings.entityTypesPlaceholder': 'PERSON,ORG,LOC,DATE',
            'settings.entityTypesHint': 'Comma-separated; leave empty for all four',
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
            'set.latexBinary': 'MiKTeX compiler path',
            'set.window': 'Window size',
            'set.pageLoad': 'Page load timeout (s)',
            'set.elementWait': 'Element wait timeout (s)',
            'set.ollamaHost': 'Ollama server address',
            'set.cookiePreflight': 'Verify Cookie before run',
            'set.overseasAsk': 'Ask about the VPN for overseas platforms',
            'set.overseasAskInline': 'Before a run, ask whether the VPN is up when the canvas crawls an overseas platform',
            'dialog.overseasNetwork':
                'This run crawls overseas platforms: {overseas}.\nThey need the VPN — inside China they do not load '
                + 'at all, and the empty result that follows looks like a search that found nothing. '
                + 'Is your overseas connection up?',
            'dialog.overseasNetworkYes': 'It is up — run',
            'dialog.overseasNetworkNo': 'Not yet — do not run',
            'dialog.commentRegionNotice':
                'Some platforms/videos do not publish an IP region in their comments, so the 「评论地区」 column may '
                + 'come back blank. That is the site not having it, not a crawl error — continuing is normal.',
            'dialog.commentRegionOk': 'Got it — continue',
            'set.cookiePreflightInline': 'Ask each platform of this canvas whether its Cookie still works',
            'set.sameQueue': 'Fully queue same-platform crawls',
            'set.sameQueueInline': '真排队: one platform runs one crawl at a time, start to finish',
            'set.stagger': 'Same-platform start gap (seconds)',
            'set.useProfile': 'Persistent browser profile',
            'set.useProfileInline':
                'One browser directory per platform and account, so the site keeps seeing one continuing device — '
                + 'that is what weibo, xiaohongshu and douyin ask for, and it means the cookie you take is the '
                + 'session the crawl runs on. Off, every crawl starts as a brand-new device replaying a saved snapshot.',
            'set.maxVisible': 'Max browsers, windowed run',
            'set.maxHeadless': 'Max browsers, headless run',
            'set.clearConsole': 'Clear console before each run',
            'set.clearConsoleInline': 'A new run wipes the console immediately — every workflow tab and its retained history included',
            'set.gentleCrawl': 'Gentle crawling (fewer blocks)',
            'set.gentleCrawlInline': 'Slow only the crawl rhythm (a few more seconds between actions); it never touches the browser identity. Turn it on right after a 风控 / captcha — trade speed for backing off.',
            'set.adviceButton': 'Collection advice (profile / parallel / serial)',
            'advice.title': 'What each platform prefers',
            'advice.profile': 'Prefer a persistent profile (a throwaway/old-snapshot session is punished): ',
            'advice.live': 'Automation testing must reuse ONE real profile session (a copied login is a second device): ',
            'advice.serial': 'Serial-only — never parallel (one account paging two sessions hits the wall): ',
            'advice.parallel': 'Parallel recommended (two sessions measured to coexist): ',
            'advice.none': 'none',
            'advice.unavailable': 'The platform capability list is not loaded yet — retry it from the data-source panel',
            'lock.lock': 'Lock: keep this through clear/delete',
            'lock.unlock': 'Unlock: allow clearing/deleting this',
            'set.profileDir': 'Profile directory',
            'set.profileDirPlaceholder': 'empty = built-in data/chrome_profile/<platform>; or an absolute path',
            'set.profileStatus': 'Profiles by platform',
            'set.profileUnavailable': 'Profile state is unavailable (the server did not answer)',
            'set.profileSuggested': 'recommended here',
            'set.profileOff': 'profiles are switched off',
            'set.profileReady': 'in use — it keeps its own session',
            'set.profileWillImport': 'will import the saved cookie on first use',
            'set.profileNeedsLogin': 'not logged in yet — log in through the Cookie panel',
            'set.templateReady': 'New-device template: clean — every account made later is cloned from it',
            'set.templateMissing': 'New-device template: none yet — one blank browser will create it the first time an account needs it',
            'set.templateDirty': 'New-device template: it picked up a session — it is destroyed and rebuilt before any account uses it again',
            'dialog.profileOff': 'This workflow crawls {n} platform(s) where a throwaway browser is known to fail (their session rotates, or a replayed one is refused within minutes). Switch on Settings → Persistent browser profile and log into that profile once through the Cookie panel. Carrying that login into a second browser makes it a second device — measured, and the answer is the login page. You can also run anyway.',
            'dialog.profileGoOn': 'Run anyway',
            'dialog.profileSetup': 'Open settings first',
            'dialog.profileClash':
                'This parallel canvas crawls {n} platform(s) — {platforms} — from more than one workflow, '
                + 'and one browser profile can only hold one Chrome at a time. Choose what this run buys:\n'
                + '· Keep the profile — the site sees one continuous device (what weibo/xiaohongshu punish a '
                + 'throwaway browser for), but those crawls take turns, so parallelism is lost on them.\n'
                + '· Skip the profile this time — the workflows really crawl side by side, but each starts as '
                + 'a brand-new device on a planted cookie snapshot, which is the shape those sites refuse.',
            'dialog.profileClashUse': 'Keep the profile',
            'dialog.profileClashSkip': 'No profile this run',
            'dialog.serialWarn':
                '{platforms} crawls are forced to run one at a time: parallel paging on one account is always '
                + 'answered by the login wall (measured), so a second crawl on these platforms queues until the '
                + 'first finishes and parallelism buys nothing there. This is the site\'s rule, not a setting. '
                + 'Start the run anyway?',
            'dialog.serialWarnGo': 'Run anyway (they queue)',
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
            'op.aggression': 'Cyberbullying-speech Detection',
            'mode.lexicon': 'Word-list rules (no model)',
            'settings.aggressionHint': 'Judges how VIOLENT the speech is, not how negative: abuse, personal attack, privacy disclosure (人肉/开盒) and rumour framing, in three levels — none / mild / severe. Columns: aggression, aggression_score, aggression_hits (which pattern fired, so you can check the verdict rather than trust the number). The word-list mode is a RECALL device, not a classifier: an attack phrased in words the list does not hold is missed, and nothing here can measure that miss rate — the lists are in the repository so their limits are visible. Severe is weighted toward doxxing on purpose, because that is the step that turns online abuse into real-world harm. Combine with 分组聚合 on a phase column to get the paper\'s "violent speech per phase" curve.',
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
            'settings.groupOrderColumn': 'Order rows by this column (blank = by name)',
            'settings.joinHow': 'Join Type',
            'settings.leftOn': 'Left Key',
            'settings.rightOn': 'Right Key',
            'settings.newCol': 'New Column Name',
            'settings.urls': 'Article URLs',
            'settings.urlsHint': 'One URL per line — WeChat crawls these articles',
            'settings.commentUrls': 'Article Links',
            'settings.inputColumn': 'Upstream Column',
            'settings.inputColumnHint':
                'Name the wired table column to crawl one link per row; the box above is then ignored. Cells holding several links are split.',
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
            'settings.commentStart': 'Comment time filter — start (YYYY-MM-DD)',
            'settings.commentEnd': 'Comment time filter — end (YYYY-MM-DD)',
            'settings.commentTimeHint': 'Keeps only comments whose 评论时间 falls within [start, end]; leave both blank to keep every comment. Fill BOTH ends or neither.',
            'settings.commentLimit': 'Comments Limit',
            'settings.commentLimitHint': '0 = every comment',
            'settings.partSize': 'Part Size',
            'settings.partSizeHint': '0 = no part files, one merged file',
            'settings.sourcePartSizeHint': '0 = off. Above 0, every N crawled rows flush to a numbered part file you can open during the run; parts merge into one at the end.',
            'settings.liveExport': 'Live export (per batch)',
            'settings.liveExportHint': 'Rewrites this node\'s .live file after every batch so you can watch results before the node finishes.',
            'settings.perArticleFile': 'One output file per article',
            'settings.keepParts': 'Keep part files after merge',
            'settings.partTimestamp': 'Add this run\'s time to part filenames',
            'settings.partTimestampHint': 'Names the shards (and the file they merge into) after the moment this run started, so a second pass keeps the first one\'s files. A 续跑 of the same run keeps writing the same names.',
            'settings.commentHint': 'The comments load by scrolling the page. A windowed run scrolls visibly; a headless run opens no window and collects the same rows (#148). Every part_size comments are written as a part file into the export directory.',
            'settings.commentFetchHint': 'These comments are read from inside one loaded page, so a window would just sit there. A headless run opens no window and collects the same rows. Every part_size comments are written as a part file into the export directory.',
            'settings.fetchQuietNote': 'This mode loads a page once and reads the data from inside it: a visible window would just sit there showing nothing, so 无头 runs it just as well.',
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
            'summary.fedColumn': 'column "{col}"',
            'settings.textColumnPlaceholder': 'e.g. content text field',
            'toast.mlUpstreamNeeded': 'Please connect an upstream node with labeled data first',
            'toast.languageChanged': 'Language: {lang}',
            'boot.partial': '{steps} interface module(s) failed to start — the details are in the browser console',
            'stats.noChartLibrary': 'The chart library did not load (offline?), so these two pies are unavailable. Everything else works.',
            'validate.empty': 'Workflow is empty',
            'validate.sourceNoPlatform': 'Source node "{title}": no platform selected',
            'validate.sourceUnknownPlatform': 'Source node "{title}": this tool cannot crawl "{platform}"',
            'validate.sourceUnknownMode': 'Source node "{title}": "{platform}" offers no such collection mode',
            'validate.capUnavailable': 'Source node "{title}": the platform capability list has not loaded, so its required fields cannot be checked — retry it in the settings panel',
            'validate.sourceFieldMissing': 'Source node "{title}": {field} cannot be empty',
            'validate.sourceDownstream': 'Source node "{title}": must connect to a downstream node',
            'validate.sourceFeedNoMode':
                'Source node "{title}": this collection mode cannot be fed from an upstream table — disconnect the wire or pick another mode',
            'validate.sourceFeedNoColumn':
                'Source node "{title}": an upstream table is wired in — name the column to read row by row for {field}',
            'validate.sourceFeedNoInput':
                'Source node "{title}": a fed column is named but no data table is wired in',
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
            'runsMgr.queueHeader': 'Waiting to run ({n})',
            'runsMgr.queueCancel': 'Cancel',
            'runsMgr.queueCancelled': 'Removed from the queue',
            'runsMgr.queueGone': 'That run had already started or was removed',
            'runsMgr.queueCancelFailed': 'Could not reach the queue',
            'exportsMgr.header': 'Export Files',
            'exportsMgr.empty': 'No export files yet — run a workflow with an Output node',
            'exportsMgr.loadFailed': 'Could not read the export folder',
            'exportsMgr.summary': '{files} file(s), {size} in total',
            'exportsMgr.colName': 'File',
            'exportsMgr.colKind': 'Kind',
            'exportsMgr.colSize': 'Size',
            'exportsMgr.colModified': 'Modified',
            'exportsMgr.download': 'Download',
            'exportsMgr.view': 'Open report',
            'exportsMgr.report': 'Report',
            'exportsMgr.reportHint': 'One self-contained HTML file: every table this run produced, plus charts.',
            'exportsMgr.reportPlaceholder': 'Report title (empty = the workflow name)',
            'exportsMgr.reportGo': 'Create',
            'exportsMgr.reportAi': 'Create with AI conclusion',
            'exportsMgr.reportDone': 'Report created',
            'exportsMgr.reportFailed': 'Report failed',
            'exportsMgr.reportPdf': 'Create + PDF',
            'exportsMgr.reportPdfDone': 'PDF exported',
            'exportsMgr.reportPdfFailed': 'PDF export failed',
            'exportsMgr.reportTCharts': 'Include charts',
            'exportsMgr.reportTTables': 'Include data tables',
            'exportsMgr.reportTFacts': 'Include run details',
            'exportsMgr.reportRows': 'Max rows per table',
            'runsMgr.report': 'Report',
            'exportsMgr.remove': 'Delete',
            'exportsMgr.confirmRemove': 'Delete this export file? It cannot be undone.',
            'exportsMgr.clearAll': 'Clear all',
            'exportsMgr.confirmClearAll': 'Delete every file in the export folder? It cannot be undone. Refused while a run is writing part files there.',
            'exportsMgr.clearAllDone': 'Exports cleared: {n} file(s) removed',
            'exportsMgr.clearAllFailed': 'Could not clear the exports',
            'exportsMgr.smartClearRun': 'Clear a run',
            'exportsMgr.smartClearParts': 'Clear shards',
            'exportsMgr.pickRun': 'Choose which run’s files to clear (newest first):',
            'exportsMgr.runField': 'Run',
            'exportsMgr.next': 'Next',
            'exportsMgr.clearGo': 'Clear',
            'exportsMgr.confirmClearRun': 'Delete every file this run wrote ({n} in all)? Merged tables, charts and exports go too. This cannot be undone.',
            'exportsMgr.clearRunDone': 'Run cleared: {removed} removed, {skipped} kept (固定)',
            'exportsMgr.unnamedRun': '(unnamed run)',
            'exportsMgr.noLedger': 'No run has written export files yet',
            'exportsMgr.pickNode': 'Choose which source node’s shard files to clear (the merged file is kept):',
            'exportsMgr.nodeField': 'Source node',
            'exportsMgr.noParts': 'That run left no shard files to clear',
            'exportsMgr.clearPartsDone': 'Shards cleared: {removed} removed, {skipped} kept (固定)',
            'exportsMgr.clearFailed': 'Smart clear failed',
            'exportsMgr.removeDone': 'Export file deleted',
            'exportsMgr.removeFailed': 'Delete failed',
            'datasetMgr.header': 'Datasets',
            'datasetMgr.empty': 'No stored files yet — upload or paste some data',
            'datasetMgr.loading': 'Loading the dataset list…',
            'datasetMgr.loadFailed': 'Could not read the dataset list',
            'datasetMgr.colName': 'Name',
            'datasetMgr.colSource': 'Source',
            'datasetMgr.sourceUpload': 'Uploaded file',
            'datasetMgr.sourcePaste': 'Pasted text',
            'datasetMgr.sourceAnalysis': 'Cleaned result',
            'datasetMgr.colRows': 'Rows',
            'datasetMgr.colSize': 'Size',
            'datasetMgr.colUsedBy': 'Used by',
            'datasetMgr.rename': 'Rename',
            'datasetMgr.renamePrompt': 'New name for this dataset',
            'datasetMgr.renamePlaceholder': 'e.g. 三亚攻略-9月',
            'datasetMgr.renameDone': 'Dataset renamed',
            'datasetMgr.renameFailed': 'Rename failed',
            'datasetMgr.remove': 'Delete',
            'datasetMgr.confirmRemove': 'Delete dataset {name}? Saved workflows that read it would come up empty.',
            'datasetMgr.clearAll': 'Clear all',
            'datasetMgr.confirmClearAll': 'Delete every stored file? The per-row button protects a file a workflow points at; a wipe removes those too, and those nodes will find nothing next time.',
            'datasetMgr.clearAllDone': 'Datasets cleared: {n} file(s) removed',
            'datasetMgr.clearAllFailed': 'Could not clear the datasets',
            'datasetMgr.stillUsed': 'A saved workflow still reads this file — remove that node first',
            'datasetMgr.removeDone': 'Dataset deleted',
            'datasetMgr.removeFailed': 'Delete failed',
            'wfMgr.header': 'Workflows',
            'wfMgr.empty': 'Nothing saved yet — save the canvas first',
            'wfMgr.loading': 'Reading the saved workflows…',
            'wfMgr.loadFailed': 'Could not read the workflow list',
            'wfMgr.colName': 'Name',
            'wfMgr.colNodes': 'Nodes',
            'wfMgr.colModified': 'Modified',
            'wfMgr.current': 'open',
            'wfMgr.broken': 'unreadable',
            'wfMgr.open': 'Open',
            'wfMgr.confirmOpen': 'Open {name}? The canvas will be replaced by it.',
            'wfMgr.rename': 'Rename',
            'wfMgr.renamePrompt': 'New name for workflow {name}',
            'wfMgr.renamePlaceholder': 'e.g. 微博舆情-9月',
            'wfMgr.renameDone': 'Workflow renamed',
            'wfMgr.renameFailed': 'Rename failed',
            'wfMgr.remove': 'Delete',
            'wfMgr.confirmRemove': 'Delete workflow {name}? The recorded runs and datasets it produced are kept.',
            'wfMgr.removeDone': 'Workflow deleted',
            'wfMgr.removeFailed': 'Delete failed',
            'wfMgr.busy': 'A run is live — stop it before changing workflow files',
            'runsMgr.empty': 'No runs recorded yet',
            'runsMgr.colWorkflow': 'Workflow',
            'runsMgr.tagParallel': 'parallel ×{n}',
            'runsMgr.tagSerial': 'serial ×{n}',
            'runsMgr.tagHeadless': 'headless',
            'runsMgr.tagWindow': 'window',
            'runsMgr.skipped': 'skipped: {names}',
            'runsMgr.colStatus': 'Status',
            'runsMgr.colNodes': 'Nodes',
            'runsMgr.colRows': 'Rows',
            'runsMgr.colStarted': 'Started',
            'runsMgr.colDuration': 'Duration',
            'runsMgr.status.running': 'Running',
            'runsMgr.status.stopping': 'Stopping',
            'runsMgr.status.interrupted': 'Interrupted',
            'runsMgr.status.completed': 'Completed',
            'runsMgr.status.failed': 'Failed',
            'runsMgr.status.abandoned': 'Abandoned',
            'runsMgr.resume': 'Continue',
            'runsMgr.restart': 'Restart',
            'runsMgr.remove': 'Delete',
            'runsMgr.detail': 'Details',
            'runsMgr.detailNodes': 'Node breakdown',
            'runsMgr.groupDone': '{done}/{total} nodes',
            'runsMgr.confirmRestart': 'Discard this interrupted attempt and start over from scratch?',
            'runsMgr.confirmRemove': 'Delete this run and its kept rows?',
            'runsMgr.clearAll': 'Clear all',
            'runsMgr.clearAllDone': 'Run records cleared: {n} removed',
            'runsMgr.clearAllFailed': 'Could not clear the run records',
            'runsMgr.confirmClearAll': 'Delete every run and its kept rows? The run in progress is left alone. The already-collected ledger is released too, so a matching crawl really does fetch everything again.',
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
            'validate.visualizeAgreementLabel': 'Visualize node "{title}": the agreement label column cannot be empty',
            'validate.outputInput': 'Output node "{title}": must have an input connection',
            'validate.outputFilename': 'Output node "{title}": filename cannot be empty',
            'validate.compileInput': 'Compile node "{title}": connect a visualize node to it first — it compiles that node’s LaTeX.',
            'validate.compileBadParent': 'Compile node "{title}": its upstream must be a visualize node (only a chart carries LaTeX to compile).',
            'validate.compileSourceBothOff': 'Compile node "{title}": the connected visualize node has neither the LaTeX figure nor the three-line table box on, so there is nothing to compile.',
            'validate.outputPdfOnly': 'Output node "{title}": a PDF output must be fed by a visualize or compile node.',
            'validate.outputPdfMixed': 'Output node "{title}": a PDF output cannot also merge row tables — disconnect the table upstream or choose a table format.',
            'validate.outputPdfTwoSources': 'Output node "{title}": feed a PDF from either a visualize node or a compile node, not both.',
            'validate.outputNeedsPdf': 'Output node "{title}": its upstream is a chart/compile node, so the format must be PDF.',
            'validate.noTerminal': 'At least one Output (Save) or Visualize node is required',        },
        zh: {
            'menu.file': '文件', 'menu.save': '保存', 'menu.load': '打开', 'menu.new': '新建', 'menu.import': '导入',
            'menu.edit': '编辑',
            'menu.view': '视图',
            'menu.style': '样式', 'style.bg': '背景', 'style.radius': '圆角',
            'btn.fit': '适应',
            'menu.run': '运行', 'btn.execute': '执行', 'btn.queue': '排队运行', 'btn.stop': '停止',
            'btn.retry': '重试',
            'btn.parallel': '并行', 'btn.headless': '无头',

            'menu.lang': '语言', 'pin.title': '固定菜单栏',
            'bg.void': '无', 'bg.grid': '网格', 'bg.dots': '点阵',
            'bg.cross': '十字', 'bg.diagonal': '斜纹',
            'palette.header': '节点库',
            'palette.collapse': '收起', 'palette.expand': '展开',
            'palette.cat.workflow': '工作流',
            'palette.cat.inputs': '数据输入',
            'palette.cat.process': '数据处理',
            'palette.cat.outputs': '结果输出',
            'palette.source': '数据源', 'palette.upload': '上传文件', 'palette.process': '处理', 'palette.output': '输出', 'palette.compile': '编译 (PDF)',
            'palette.resume': '断点续跑', 'palette.name': '工作流命名',
            'node.source': '数据源', 'node.upload': '上传文件', 'node.process': '处理',
            'node.analysis': '分析', 'node.visualize': '可视化', 'node.tokenize': '分词', 'node.output': '输出', 'node.compile': '编译', 'compile.summary': 'LaTeX → PDF',
            'node.resume': '断点续跑', 'node.name': '工作流命名',
            'node.comment': '评论采集',
            /* 断点续跑：提示要说清已经保留了什么，否则用户不知道「继续」会发生什么 */
            'resume.continue': '继续执行', 'resume.restart': '从头开始', 'resume.dismissTitle': '忽略',
            'resume.interrupted': '发现 {at} 那次未跑完的运行',
            'resume.detail': '已完成 {done}/{total} 个节点，保留了 {rows} 行数据 —— 继续执行从这里接着跑',
            'resume.runSelect': '选择运行记录', 'resume.nodeSelect': '选择节点输出',
            'resume.autoNode': '数据量最大的节点（自动）',
            'resume.limit': '读取行数上限', 'resume.limitPlaceholder': '0 表示全部',
            'resume.refresh': '刷新列表', 'resume.none': '还没有可续跑的记录，先跑一次完整流程',
            'resume.hint': '直接读取上次运行里某个节点已保存的数据，不需要重新爬取',
            'toast.runDiscarded': '已丢弃上次的记录，从头开始',
            'settings.file': '文件', 'settings.rows': '行',
            'stats.header': '统计', 'stats.close': '关闭',
            'stats.emotion': '情感', 'stats.tendency': '倾向',
            'settings.header': '节点设置', 'settings.close': '关闭',
            'outline.title': '大纲', 'outline.collapse': '收起', 'outline.expand': '展开',
            'outline.noNodes': '还没有节点',
            'status.ready': '就绪', 'status.completed': '已完成', 'status.running': '运行中...',
            'status.stopping': '正在停止…',
            'ctx.newSource': '新建数据源', 'ctx.newUpload': '新建上传文件',
            'ctx.newProcess': '新建处理',
            'ctx.newOutput': '新建输出', 'ctx.newCompile': '新建编译', 'ctx.edit': '编辑节点', 'ctx.rename': '重命名节点',
            'ctx.renameHint': '双击重命名',
            'ctx.copy': '复制节点', 'ctx.paste': '粘贴节点',
            'ctx.disableNode': '禁用此节点', 'ctx.enableNode': '启用此节点',
            'ctx.disableType': '禁用所有「{type}」节点', 'ctx.enableType': '启用所有「{type}」节点',
            'node.badgeDisabled': '已禁用', 'node.badgeNoInput': '无有效输入',
            'ctx.delete': '删除节点', 'ctx.clear': '清除所有连线',
            'btn.cookies': 'Cookies',
            'console.header': '控制台', 'console.clear': '清空', 'console.close': '关闭', 'console.popout': '弹出', 'console.dock': '收回',
            'console.all': '全部',
            'processes.header': '进程监控', 'processes.close': '关闭',
            'processes.running': '运行中', 'processes.stopped': '已停止',
            'processes.threads': '线程数', 'processes.crawlers': '爬虫数',
            'processes.pool': '线程池活跃', 'processes.yes': '是', 'processes.no': '否',
            'processes.name': '名称', 'processes.status': '状态', 'processes.type': '类型',
            'processes.kill': '结束',
            'cookies.header': 'Cookie 设置', 'cookies.platform': '平台',
            'cookies.paste': '粘贴 Cookies JSON', 'cookies.save': '保存 Cookies',
            'cookies.generate': '浏览器生成', 'cookies.waitTime': '等待时间（秒）用于登录:',
            'cookie.opening': '正在打开浏览器进行 {platform} 登录（等待 {s} 秒）...',
            'cookie.failed': '失败：{err}',
            'cookie.unreachable': '无法连接后台服务（可能正在启动或重启）——稍等片刻后重试',
            'cookies.doneBtn': '已完成登录',
            'cookies.cancelBtn': '取消登录',
            'cookie.mustStay': '登录进行中——请先点「已完成登录」或「取消登录」，此窗口需保持打开',
            'cookie.waiting': '{platform} 登录窗口已打开——完成登录后点「已完成登录」',
            'cookies.entryUrl': '登录入口链接（可留空：默认打开该平台登录页）',
            'cookies.verify': '验证 Cookie',
            'cookies.delete': '删除已存 Cookie',
            'cookies.deleteProfile': '删除已存 Profile',
            'cookies.accountDefault': '默认账号',
            'cookies.accountDefaultNumbered': '默认账号{n}',
            'cookies.accountDefaultHint': '这个登录的名字就是 default',
            'cookies.accountStatusHead': '{platform} · {account}',
            'cookies.accountStatusNone': '这个账号还没有保存过 Cookie',
            'cookies.accountStatusSaved': '{n} 条，存于 {when}',
            'cookies.chosen': '已选择登录：{platform} · {account}',
            'cookies.listFailed': '读不到已保存的登录（服务未响应）',
            'cookies.manageTitle': '已保存的登录',
            'cookies.noneSaved': '还没有任何已保存的登录——粘贴一份 Cookie 后会出现在这里。',
            'cookies.unknownWhen': '时间未知',
            'cookies.renameOne': '重命名',
            'cookies.renamePlaceholder': '给这个登录起个新名字',
            'cookies.renameSame': '名字没变，所以什么都没改',
            'cookies.renameDefaultRefused': '默认账号不能改名：它的浏览器目录就是该平台目录本身，其它账号都装在里面',
            'cookies.colPlatform': '平台',
            'cookies.colAccount': '账号',
            'cookies.colEntries': '条数',
            'cookies.colSavedAt': '存于',
            'cookies.colActions': '操作',
            'cookies.deleteOne': '删除',
            'privacy.body':
                '这个应用跑在服务器上，不在你这台电脑里。\n'
                + '存在服务器上的：你粘贴进来的 Cookie、你上传或采集到的每一张表、你的工作流文件与运行记录。'
                + 'Cookie 的值永远不会发回浏览器、也不显示在任何界面上，但它们就放在这台服务器的磁盘里。\n'
                + '只存在你这个浏览器里的：OpenRouter API Key、画布草稿和界面设置。'
                + 'Key 只在一次请求里被用到，绝不写进服务器的文件。',
            'privacy.gotIt': '知道了',
            'privacy.never': '不再提醒',
            'cookies.account': '账号',
            'cookies.accountPlaceholder': 'default＝默认登录；输入一个新名字即另存一份',
            'field.account': '登录账号',
            'dialog.cookieDelete': '删除 {platform} 已保存的 Cookie 文件？如果该平台的抓取是在它自己的浏览器 profile 里跑的，登录态存在那个 profile 里：删这个文件不会把它登出，只是清掉「一次性浏览器」用来植入的快照。删除后的那一行会说明 {platform} 属于哪种情况。',
            'dialog.cookieDeleteYes': '删除文件',
            'cookies.deleteProfileOne': '删除 Profile',
            'cookies.profileDeleteDefaultRefused': '默认账号没有可删除的浏览器 Profile：它的数据就是该平台目录本身，其它账号都装在里面',
            'dialog.profileDelete': '删除 {platform} · {account} 的浏览器 Profile？这会把该设备登出、并清掉它在磁盘上的浏览器数据（Profile 自己持有会话；已保存的 Cookie 文件不动）。',
            'dialog.profileDeleteYes': '删除 Profile',
            'toast.profileDeleted': '已删除浏览器 Profile',
            'dialog.cookieRename': '把 {platform} 的登录「{account}」改名？它的 Cookie 文件与它自己的浏览器目录会一起搬过去。',
            'toast.cookieRenamed': '登录已改名',
            'toast.cookieDeleted': '已删除 {platform} 的 Cookie 文件',
            'cookie.refreshHint':
                '这个 profile 里还是旧的那份 Cookie：保存时它的浏览器正被占用，下一次抓取这个账号会自动带上新的',
            'toast.cookieChecking': '运行前先验证 {platforms} 的 Cookie…',
            'toast.cookieUncheckable': '{platforms} 的 Cookie 没能验证成功——这不是「有效」，本次仍然开始运行',
            'toast.cookieUnclear': '{platforms} 的 Cookie 无法核对（风控、超时或 profile 被占用）——这不算失效，所以不拦截本次运行',
            'dialog.cookieExpired': '{n} 个平台拒绝了已保存的 Cookie，本次不启动：{platforms}',
            'dialog.cookieExpiredHint': '请到「设置 → Cookie」重新登录并保存。这里刻意不留「我确定，照样跑」：从一个登录页开始的抓取，一小时后只会带回一张空表和一个半途的数据集。',
            'dialog.cookieGoUpdate': '打开 Cookie 面板',
            'cookie.verifying': '正在用已保存的 Cookie 试探该平台…',
            'cookie.guideLoading': '正在载入该平台的获取步骤…',
            'cookie.entryRejected': '该链接不属于本平台的域名，已改用平台登录页打开',
            'cookie.savedN': '已为 {platform} 保存 {n} 条 Cookie',
            'cookie.savedYes': '已存 Cookie',
            'cookie.savedNo': '未存',
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
            'toast.workflowFileInvalid': '这个文件不是工作流（没有节点列表），画布内容未做任何改动',
            'toast.workflowImported': '已导入——工作流已载入画布（尚未保存到服务器）',
            'toast.workflowImportFailed': '无法把该文件读成 JSON',
            'toast.workflowStarted': '工作流已启动',
            'toast.consoleReconnected': '已重新接上仍在进行的运行，下面是它的日志',
            'toast.workflowEnded': '运行结束——完成 {done}/{total} 个节点（可继续）',
            'toast.queued': '已排队——当前运行结束后自动开始',
            'toast.workflowCompleted': '工作流已完成',
            'toast.workflowRejected': '工作流未运行：定义有问题，详见控制台',
            'toast.pollFailed': '与服务端失去连接，状态刷新已停止',
            'toast.workflowStopped': '工作流已停止',
            'toast.stillSettling': '仍在停止中——运行记录会自行完成判定',
            'toast.stopping': '正在停止——关闭浏览器、写运行记录…',
            'toast.noWorkflows': '没有已保存的工作流',
            'toast.saveFailed': '保存失败',
            'toast.loadFailed': '加载失败',
            'toast.executeFailed': '执行失败',
            'toast.stopFailed': '停止失败',
            'toast.killFailed': '无法结束该进程',
            'toast.cookiesSaved': 'Cookies 已保存',
            'toast.problems': '本次运行前有 {n} 个问题需要处理:',
            'dialog.workflowName': '工作流名称:',
            'dialog.selectWorkflow': '输入要加载的工作流名称:',
            'dialog.cancel': '取消',
            'dialog.confirm': '确认',
            'dialog.renameNode': '重命名此节点——控制台将显示它的名字而不是 node-N（留空恢复类型默认名）：',
            'conn.fanin.name': '「{node}」是工作流命名节点——运行会拒绝任何连入它的线,命名节点不能有上游。',
            'conn.fanin.ignore': '「{node}」完全不读取上游数据——这条连线在运行时无任何作用。',
            'conn.fanin.first': '「{node}」只使用第一条连入的表,其余上游在运行时被静默忽略。',
            'conn.fanin.source': '「{node}」(数据源)最多只使用一条上游:若这种采集内容支持被投喂,它只读取第一个带表格的父节点;若不支持,运行会拒绝这条连线。',
            'conn.fanin.analysis': '「{node}」的表连接只用两张表——第一条作左表、第二条作右表;第三条及以后的上游会被丢弃,非连接类步骤只读第一条。',
            'conn.fanin.merge': '「{node}」(输出)会把每一条连入的表纵向合并成一个文件;若两张表的列不一致,运行会被具名拒绝。',
            'conn.fanout': '「{node}」现在连向 {count} 个下游节点。这是安全的:每个分支都会拿到它完整的同一份数据,不会分流、也不会互相覆盖。',
            'conn.help': '完整对照见 README「连线分支」一节。',
            'conn.undo': '撤销这条连线',
            'conn.keep': '保留',
            'conn.dismiss': '本次会话不再提示',
            'toast.cookieExpired': '检测到登录墙——COOKIE 可能已在爬取中途失效。已采集数据不会丢失：请到「设置 → Cookie」更新后断点续跑。',
            'settings.nodeType': '节点类型',
            'settings.platform': '平台',
            'settings.collect': '采集内容',
            'settings.collectPosts': '帖子 / 文章',
            'settings.collectVideos': '视频',
            'settings.collectComments': '评论',
            'settings.collectAuthor': '某作者的作品',
            'settings.collectHot': '热榜',
            'settings.hotBoard': '榜单',
            'settings.hotBoardPopular': '热门榜',
            'settings.hotBoardRanking': '周排行榜',
            'settings.author': '作者',
            'settings.authorHint': '填 @handle、频道链接或 UC… ID；不是拿来搜索的显示名',
            'settings.authorHintZhihu': '填作者主页链接，或 /people/ 后面那段 id——知乎的回答页里没有指向主页的链接，按昵称找人不可行',
            'settings.authorHintBili': '填 space.bilibili.com 链接或数字 UID——投稿列表读的是页面本身（它的接口要按请求算签名），所以能用的是这个号码',
            'settings.authorHintDouyin': '填 douyin.com/user/… 主页链接，或链接里那串 sec_uid——抖音 web 没有按昵称找人的入口，作品列表读的是主页那个网格',
            'settings.authorHintWeibo': '填 weibo.com/u/<UID> 主页链接或数字 UID——作品是从作者页自己的接口读的，昵称定位不到人',
            'settings.withFacts': '逐条获取精确数据',
            'settings.withFactsHint': '每行多一次请求（约 0.3 秒），换来点赞数、完整正文与真实发布时间；关闭则沿用列表里的粗略数值。',
            'settings.fullBody': '展开全文',
            'settings.fullBodyHint': '搜索结果页本身只给摘要（实测每行 35–109 字）。每张「回答」卡就地点击一次「阅读全文」（约 0.3 秒/张）；专栏文章卡一律不点——它会把页面带走，后面整列表的句柄全断。',
            'settings.articleUrls': '文章正文',
            'settings.capFailed': '未能从服务器读取采集清单，而数据源表单正是由它生成的。',
            'settings.capLoaded': '采集清单已重新载入',
            'settings.capNoMode': '该平台还没有可用的采集模式，因此不能作为数据源运行。',
            'settings.keyword': '关键词',
            'settings.targetCount': '目标数量',
            'settings.startTime': '开始时间',
            'settings.endTime': '结束时间',
            'settings.operation': '操作',
            'settings.unknownOption': '「{value}」不是可选项，请改选',
            'settings.textColumn': '文本列',
            'settings.topic': '主题',
            'settings.filename': '文件名',
            'settings.filenameTimestamp': '文件名追加本次运行时间（不覆盖旧文件）',
            'settings.filenameTimeRange': '文件名追加本次采集的时间范围',
            'settings.workflowName': '工作流名称',
            'settings.layoutOrder': '排布顺序',
            'settings.layoutOrderHint': '数值小的排在上方；留空表示沿用创建顺序，排在已编号项之后。',
            'nodeType.source': '数据源',
            'nodeType.upload': '上传文件',
            'nodeType.process': '处理',
            'nodeType.analysis': '分析',
            'nodeType.visualize': '可视化',
            'nodeType.tokenize': '分词',
            'nodeType.resume': '断点续跑', 'nodeType.name': '工作流命名',
            'nodeType.output': '输出',
            'nodeType.compile': '编译',
            'nodeType.comment': '评论采集',
            'nodeType.misc': '节点',
            'op.clean': '清洗',
            'op.emotion': '情感分析',
            'op.sentiment': '情感极性',
            'op.tendency': '倾向分析',
            'op.save_csv': '保存 CSV',
            'op.save': '保存',
            'op.chart': '图表',
            'op.drop_null': '删除空值行',
            'op.fill_null': '填充空值',
            'op.drop_duplicates': '去重',
            'op.dedupe_similar': '近重复去重（SimHash）',
            'settings.dedupeMode': '判重依据',
            'settings.dedupeModeExact': '完全相同的文本',
            'settings.dedupeModeNormalized': '归一化后的文本（忽略链接/@/话题/表情）',
            'settings.dedupeDistance': '位距离',
            'settings.dedupeSimilarHint': 'SimHash 比的是「这条评论在说什么」，不是逐字相同，所以改一个词的转发、拉长一串的「哈哈」都会并进同一组。每组保留第一次出现的那行，填 0 只合并指纹完全一致的评论。在微博评论上实测：改一个词大约差 5–18 位，两条互不相关的评论差 26–28 位。默认 8 只合并明确相同的改写，其余不动；想提高召回就往 15 调，代价是精确率下降。',
            'op.extract_time': '提取时间维度',
            'op.bin_time': '按时间划分阶段',
            'op.suggest_stages': '按发文量建议阶段边界',
            'op.topic_model': 'LDA 主题模型',
            'op.topic_by_stage': '分阶段 LDA 主题模型',
            'op.topic_label': '主题概括（模型）',
            'op.topic_map': '主题距离图（数据）',
            'op.topic_salience': '各主题显著词（数据）',
            'op.topic_timeline': '主题生命周期（次生舆情）',
            'op.topic_flow': '主题跨阶段流向',
            'op.topic_coherence': '主题数扫描（一致性+困惑度）',
            'op.cooccur': '共词关系边',
            'op.forecast': '情感走向外推',
            'op.alert': '二次爆发预警',
            'settings.forecastPeriodColumn': '时段列（须是日期）',
            'settings.forecastValueColumn': '要外推的数值列',
            'settings.forecastMethod': '外推方法',
            'settings.forecastMethodMa': '移动平均（持平）',
            'settings.forecastMethodHolt': 'Holt（水平+趋势）',
            'settings.forecastHorizon': '往后预测几期',
            'settings.forecastWindow': '窗口期数（移动平均）',
            'settings.forecastAlpha': 'α（水平平滑）',
            'settings.forecastBeta': 'β（趋势平滑）',
            'settings.forecastMinPeriods': '最少观测期数',
            'settings.forecastHint': '这里外推的是曲线的**形状**，不是事件：模型不知道有没有通报。历史行仍留在表里，每行带实际值与"当时本可预测出的下一步"（horizon=0）；未来的行只有 predicted/lower/upper。Holt 的置信带按 √步数 变宽，因为趋势推得越远确实越不确定；移动平均没有趋势，所以带子是平的——把它的带也画宽就是演戏。时段列必须能解析成日期（"发酵期"这类阶段名没法外推），间隔不齐时会说明有多少步不是众数间隔，未来的日期按众数间隔标。',
            'settings.alertPeriodColumn': '时段列（须是日期）',
            'settings.alertIndexColumn': '情感指数列',
            'settings.alertIntensityColumn': '强度列（留空=不看升温信号）',
            'settings.alertVolumeColumn': '热度列（留空=不判衰减）',
            'settings.alertStreak': '连续期数',
            'settings.alertSwing': '转向幅度阈值 |Δ指数|',
            'settings.alertHeating': '强度上升斜率阈值',
            'settings.alertVolumeFloor': '热度保持倍率（0–1）',
            'settings.alertHint': '转向：连续 N 步每步的指数变化都超过阈值且同向；升温：强度在这 N 步里平均每步上升超过阈值。两者都要热度还在（不低于前 N 期均量的设定倍率）才算触发——只剩少数人在发帖时的剧烈摆动不是爆发。被"热度已衰减"压掉的候选仍会出一行说明被压掉了；一条都没触发时也出一行「未触发」并带上实测到的最大值，因为空表会被读成"没检查过"。',
            'op.sentiment_evolution': '情感演化曲线',
            'settings.newColumn': '新列名',
            'settings.timePart': '提取哪一部分',
            'settings.timePartDate': '日期（YYYY-MM-DD）',
            'settings.timePartHour': '小时',
            'settings.timePartWeekday': '星期',
            'settings.timePartMonth': '月份',
            'settings.timePartYear': '年份',
            'settings.phaseEdges': '时间边界（从早到晚）',
            'settings.phaseLabels': '阶段名称',
            'settings.phaseOrderColumn': '阶段序号列（留空=不生成）',
            'settings.phaseHint': '边界是「左闭右开」：划分 5 个阶段要填 6 个日期，最后一个是最后一阶段结束的次日。按自然日比较，所以边界前一天 23:59 的行仍算在前一阶段。填上「阶段序号列」会额外写一列**数字**位置（首个阶段=1）——这是阶段先后唯一能跨过节点边界的写法：有序 categorical 在节点边界会退化成普通字符串，而中文阶段名按码点排序会把「二次爆发期」排到「发酵期」前面。',
            'settings.stagesMinDays': '最短窗口（天）',
            'settings.stagesMaxWindows': '最多切几个窗口',
            'settings.stagesPeakRatio': '峰要不小于平日的多少倍',
            'settings.stagesHint': '只是「建议」，不改任何一行：它读每日发文量曲线，找出峰、在峰与峰之间的谷底落刀。控制台会打印出边界串和阶段名串，可直接粘进「按时间划分阶段」。官方通报、道歉、立案这些日期曲线里没有，得你自己补。',
            'settings.nTopics': '主题个数',
            'settings.topicTopn': '每主题特征词数',
            'settings.topicMaxFeatures': '词表上限',
            'settings.topicHint': '用 scikit-learn 实现 LDA，不额外装依赖。输出是「每个(主题,特征词)一行」，所以可以直接按主题分组画图。控制台会按主题打印特征词和困惑度——主题个数就靠它定：多试几个值看它如何下降。',
            'settings.stageColumn': '阶段列',
            'settings.stageOrderColumn': '阶段先后取自（时间列）',
            'settings.stageTopicCounts': '每阶段主题数（一个数=各阶段同数，或逐阶段列举）',
            'settings.topicSampleN': '每主题代表帖数',
            'settings.topicWordSource': '特征词来源',
            'settings.topicWordSourceTfidf': '该主题文本的 TF-IDF',
            'settings.topicWordSourceLda': 'LDA 主题-词权重',
            'settings.topicStageHint': '这就是论文的「表 1」：一行一个（阶段, 主题），编号 TopicⅠ-1 … 按阶段在生命周期里的先后。整库跑一次 LDA 出不来这张表——混合模型会把主题让给文本最多的阶段，发酵期那 349 条要么没自己的主题，要么和三周后的阶段共用。TF-IDF 会丢掉单字词（比如「捞」），LDA 权重不会，两种来源的差别是有意保留的。',
            'settings.labelWordsColumn': '特征词列',
            'settings.labelSamplesColumn': '代表文本列（可留空）',
            'settings.labelSummaryColumn': '写入的概括列名',
            'settings.labelOnFail': '模型拒答时',
            'settings.labelOnFailAbort': '让节点失败（默认）',
            'settings.labelOnFailBlank': '该格留空继续',
            'settings.labelMaxTopics': '最多问几个主题',
            'settings.topicLabelHint': '一行主题一次模型调用——表 1 是 25 次，所以这一步设了上限。它按本次运行的语言回答，把短语写进「主题概括」；论文里这一列是作者读原文写下的，这里读到的是同一批特征词，请当作本项目的读法而不是原结论。',
            'settings.topicMapTopn': '每个气泡显示词数',
            'settings.topicMapHint': 'pyLDAvis 那张图的左半边，先出「表」：一行一个主题，含地图坐标（PC1/PC2 由主题词分布两两的 JS 散度做 MDS 得到）、占全文比例与代表词。接到「主题距离图」可视化节点即可画。气泡重叠说明这几个主题在文本里本就分不开——那是结论，不是画错了。',
            'settings.topicTermsTopn': '每主题词数',
            'settings.topicLambda': 'λ（相关性权重）',
            'settings.topicSalienceHint': '图的右半边，出「表」：每个主题排好序的词，同时给两个计数——overall_freq（全库频次，蓝条）与 within_freq（该主题自身应产生的频次，红条）。λ 决定排序口径：1=按主题内概率，0=按相对全库的溢出；论文的图用滑块调这个，本次用的值会随表一起打进控制台。先用筛选节点留下一个主题，再接「显著词图」。',
            'settings.timelineStageColumn': '阶段列',
            'settings.timelineTopicColumn': '主题列（只用作名字）',
            'settings.timelineWordsColumn': '特征词列',
            'settings.timelineSizeColumn': '规模列（用来定峰值）',
            'settings.timelineOrderColumn': '阶段排序列',
            'settings.timelineOverlap': '同主题词重合度（0–1）',
            'settings.timelineHint': '一行一个「主题本身」，不是一个主题编号：分阶段 LDA 每个阶段都重新编号（TopicⅠ-1 与 TopicⅡ-1 不是同一个对象），所以只能按特征词的重合度把一个主题从首现阶段追到峰值与末现。次生舆情（is_secondary）要同时满足两条：它不是开场那个主题，且它在首现之后才长大。阶段先后由「按时间划分阶段」写的有序列给出，或指定一个时间列来排；两者都没有就拒绝，而不是按中文字的码点猜顺序。',
            'settings.flowStageColumn': '阶段列',
            'settings.flowTopicColumn': '主题列',
            'settings.flowWordsColumn': '特征词列（标在边上）',
            'settings.flowWeightsColumn': '词权重列（词:权重）',
            'settings.flowOrderColumn': '阶段排序列',
            'settings.flowLabelColumn': '主题名称列（留空=TopicⅠ-1）',
            'settings.flowMinSimilarity': '最低相似度（0–1）',
            'settings.flowHint': '只比相邻阶段，用的是词分布两两的 JS 散度（读 word:weight 那一格），再换成相似度 =1/(1+d)。输出 source/target/value 正好是「桑基图」节点要的：x=source、y=target、数值列选 similarity。一条边都达不到阈值时它会拒绝并说出实测最相似的一对是多少——交一张空流向表会被读成「没有承接」，而那并不是这次检查得到的结论。',
            'settings.coherenceMinTopics': '最少主题数',
            'settings.coherenceMaxTopics': '最多主题数',
            'settings.coherenceMaxDocuments': '参与拟合的文本数（0=全部）',
            'settings.coherenceHint': '每个主题数各拟合一次，并把两个口径的数一起打出来：困惑度（越低越好，但低到在背原文就没意义了）与一致性（一个主题的头部词是否真的同现于同一篇文本）。这里的一致性是「按文档的 NPMI」，只是发表口径 C_v 的一部分而非 C_v 本身，所以不要拿它去对论文里的数字。抽样按表固定，同一张表跑两次结果相同。',
            'settings.cooccurTopn': '候选词数（上限 120）',
            'settings.cooccurMinCount': '最少共现次数',
            'settings.cooccurWindow': '窗口词数（0=整篇）',
            'settings.cooccurHint': '论文的另一半——知识图谱：两个词连边，是因为读者把它们写进了同一条文本。候选词取全库 TF-IDF 表（与关键词节点同一套分词、同样「至少两字」的规则），输出 source/target/value 可接「关系图」或「桑基图」。候选词上限 120，因为图对候选词是全覆盖的：120 词意味着每条文本要数 7140 个词对。',
            'settings.labelColumn': '情感列',
            'settings.labelPositive': '积极标签',
            'settings.labelNeutral': '中性标签',
            'settings.labelNegative': '消极标签',
            'settings.scoreColumn': '分数列（算强度）',
            'settings.evolutionOrderColumn': '阶段排序列（序号或时间）',
            'settings.evolutionHint': '这就是「情感演化图」的数据。情感指数 =(积极数−消极数)/总数：+1 表示该时段全为积极，−1 全为消极；0 表示要么全是中性，要么正负相抵。每个时段还会给出 volume_pct（它占全文量的比例），也就是图里的「舆情热度」。填上分数列（情感节点的 0~1 score）后会再算 intensity = |score−0.5|×2 的均值，表示网民「用了多大劲」（不分方向）；把它和 volume_pct 放进双轴折线图，就能读出论文那句爆发期与二次爆发期热度与强度反向。按「阶段」分组时请把它的序号列也填上（划分阶段 写的 阶段序号）：不填就按阶段名排序，而「二次爆发期」按中文字典序排在「发酵期」前面，生命周期会被排乱。',
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
            'platform.twitter': 'X（推特）',
            'platform.instagram': 'Instagram',
            'platform.youtube': 'YouTube',
            'btn.uploadFile': '上传文件',
            'btn.preview': '预览图表',
            'palette.analysis': '分析',
            'palette.visualize': '可视化',
            'palette.tokenize': '分词',
            'ctx.newAnalysis': '新建分析节点',
            'ctx.newVisualize': '新建可视化节点',
            'ctx.newTokenize': '新建分词节点',
            'chart.header': '图表预览',
            'chart.saveImage': '存为图片',
            'chart.fullscreen': '全屏',
            'chart.saveNothing': '还没有画出来的图：先点「预览」或把节点跑完，再存图',
            'chart.copyLatex': '复制 LaTeX', 'chart.downloadLatex': '下载 LaTeX（.txt）',
            'chart.copyTable': '复制三线表', 'chart.downloadTable': '下载三线表（.txt）',
            'chart.copied': '已复制到剪贴板',
            'settings.emitLatex': '生成 LaTeX 图（.txt）',
            'settings.emitLatexHint': '除出图外，另在导出目录写一份可被 MiKTeX 编译的 standalone 图源码。默认开启，取消勾选则不生成。',
            'settings.emitLatexTable': '生成 LaTeX 三线表（booktabs）',
            'settings.compileHint': '把已连接的可视化节点产出的 LaTeX（图和/或三线表）用本机 MiKTeX 编译成一个 PDF。连到输出节点并选 PDF 即可落盘；编译程序路径在「设置」里指定。',
            'settings.outputPdfHint': '该输出节点的上游是图表/编译节点，所以格式只有 PDF——上面的 LaTeX 会在这里编译成文件。',
            'chart.bar': '柱状图', 'chart.line': '折线图', 'chart.dual_line': '双轴折线', 'chart.stack_pct': '占比堆叠图', 'chart.pie': '饼图',
            'chart.topic_map': '主题距离图', 'chart.topic_terms': '显著词图',
            'chart.scatter': '散点图', 'chart.histogram': '直方图', 'chart.box': '箱线图',
            'chart.heatmap': '热力图', 'chart.model_agreement': '模型一致率', 'chart.wordcloud': '词云',
            'chart.sankey': '桑基图', 'chart.network': '关系图', 'chart.map': '地图（中国）',
            'format.csv': 'CSV', 'format.json': 'JSON', 'format.excel': 'Excel (.xlsx)',
            'format.txt': '文本 (.txt)', 'format.html': 'HTML', 'format.markdown': 'Markdown', 'format.pdf': 'PDF（由 LaTeX 编译）',
            'settings.format': '格式',
            'settings.columns': '列',
            'settings.commentPreview': '每篇评论预览数',
            'settings.commentPreviewHint': '每条笔记行附带多少条评论；填 0 表示跳过评论面板（也最快）。',
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
            'settings.y2Field': 'Y2 字段（右轴）',
            'settings.stackFields': '堆叠字段',
            'hint.stackFields': '逗号分隔的若干列，每列是柱内的一段。每个分类都会归一到 100%，所以传入某一步写出的占比列（如 积极占比, 中性占比, 消极占比），或任何构成同一分布的计数列都可以。',
            'hint.bertModelsMulti': '已勾选 2 个以上模型：本节点将输出「每行 × 每模型」的多模型对比表（新增 模型 与 原行 两列），供可视化对比。',
            'hint.modelAgreement': '模型一致率：两两模型在同一批文本上判定相同标签的行占比。上游须为多模型对比表（分析节点勾选 ≥2 个模型）。',
            'settings.agg2': '右轴聚合方式',
            'settings.labelField': '气泡标签列',
            'hint.dualLine': '一个横轴、两根纵轴：左轴画舆情热度（行数或 volume_pct），右轴画情感强度。只有 ECharts 支持这种图型，选 Matplotlib 会明确拒绝。',
            'settings.title': '图表标题',
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
            'settings.chartAnnotations': '事件标注（日期=名称; …）',
            'hint.annotations': '每个事件画一条竖直虚线，位置就是你写的那个「横轴标签」——这样「4/23 遗体打捞」「5/19 通报」才落在它们解释的那段曲线上方。多个事件用 ; 分隔，写成 日期=名称（= 或 : 都认）。标签必须和这一列的真实取值一字不差：日期格式不同就什么也画不出来，所以轴上没有的名字会连可选标签一起报出来拒绝，而不是交一张悄悄丢了日期的图。只有 柱状图 / 折线图 / 双轴折线 支持。',
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
            'chart.noRunData': '尚无运行数据，请先运行一次工作流。',
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
            'history.remove': '删除',
            'history.confirmRemove': '删除运行 {rid} 已记录的指标？其余历史保留。',
            'history.removed': '该运行已从执行历史中删除',
            'history.removeGone': '这条运行已不在执行历史里（期间被自动清理）',
            'history.removeFailed': '删除失败',
            'settings.mode': '分析模式',
            'settings.nodeModel': '模型（本节点）',
            'settings.followGlobalModel': '跟随全局 AI 模型',
            'mode.llm': '大模型（本地 Ollama / OpenRouter）',
            'mode.llmCloud': '大模型（OpenRouter）',
            'mode.ml': '传统机器学习 (sklearn)',
            'mode.snownlp': 'SnowNLP 传统极性模型（无需下载模型）',
            'mode.bert': 'BERT 预训练模型（需 torch 与情感模型）',
            'settings.posThreshold': '判定为正面的下限',
            'settings.negThreshold': '判定为负面的上限',
            'settings.sentimentThresholdHint': 'SnowNLP 给出的是「这段文本偏正面」的概率（0–1）。两个数之间记为中性：站子说话越客气越要把区间调宽，想少一些中性就把它调窄。score 列始终保留原始概率。',
            'settings.bertModel': 'BERT 模型',
            'settings.bertModelsPick': '已注册模型（勾选多个做对比）',
            'settings.modelField': '模型列',
            'settings.networkCenter': '中心节点（可选）',
            'settings.networkCenterPlaceholder': '图中已有的某个词（留空 = 全图）',
            'hint.networkCenter': '填入某个词，只画它的「邻域图」——该词 + 与它直接共现的词，把密集的「关系图」变成一张可读、可导出的图（不再只在鼠标悬停时才显出信息）。留空则画全部候选词。',
            'settings.agreementLabelField': '要比对的标签列',
            'settings.idField': '行号列（跨模型对齐同一条文本）',
            'settings.batchSize': '批大小',
            'settings.bertModelHint': '填本机已有的模型目录或模型名。留空时节点会直接拒绝运行，而不会改用别的方法代替。整列文本按批推理，有显卡时自动走显卡。',
            'mode.regex': '正则规则（无需模型）',
            'settings.cleanRegexHint': '清掉转发留下的痕迹：//@ 转发链（只保留你自己写的那段）、@提及、#话题# 标记、链接与 O网页链接 占位符、展开c、[表情] 代码。整行只剩这些内容的会被判为删除。它不判断评论是否与你的主题相关——那是模型模式的职责。原始文本列会保留，不会丢数据。',
            'settings.methodCorpusIdf': '基于自己语料的 TF-IDF',
            'settings.outputMergeHint': '多条上游连线会在这里合并成一张表，而合并后的表会继续往下游传——所以可以在这个节点后面接一整套分析。上游的列名必须一致；不一致时节点会直接报错并点名多出/缺少哪些列，而不是做外连接合并成一张到处是空值的表。',
            'settings.allowPos': '词性过滤',
            'settings.allowPosHint': '逗号分隔的 jieba 词性，例如 n,vn,v,a（名词、动名词、动词、形容词）。留空=不过滤，也就是这个节点一直以来的行为。微博关键词表里的「转发 / 哈哈 / 回复」就是靠它去掉的。',
            'settings.entityTypes': '实体类型',
            'settings.entityTypesPlaceholder': 'PERSON,ORG,LOC,DATE',
            'settings.entityTypesHint': '逗号分隔，留空表示全部四类',
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
            'set.latexBinary': 'MiKTeX 编译程序路径',
            'set.window': '窗口大小',
            'set.pageLoad': '页面加载超时(秒)',
            'set.elementWait': '元素等待超时(秒)',
            'set.ollamaHost': 'Ollama 服务地址',
            'set.cookiePreflight': '执行前自动验证 Cookie',
            'set.overseasAsk': '海外平台运行前问一句外网',
            'set.overseasAskInline': '画布里有海外平台时，运行前先问一句 VPN 是否已开',
            'dialog.overseasNetwork':
                '本次要爬海外平台：{overseas}。\n它们需要外网（VPN）——在国内这些站点根本打不开，而没开时交回的空结果看起来'
                + '跟「什么都没搜到」一模一样。你的外网已经开了吗？',
            'dialog.overseasNetworkYes': '已开，继续运行',
            'dialog.overseasNetworkNo': '还没开，先别跑',
            'dialog.commentRegionNotice':
                '部分平台/视频的评论区不发布 IP 属地，「评论地区」这一列可能会是空的——这是站点本身没有，不是程序出错，继续运行即可。',
            'dialog.commentRegionOk': '知道了，继续',
            'set.cookiePreflightInline': '运行前用本次真要用的浏览器各加载一次该平台，问它 Cookie 还认不认',
            'set.sameQueue': '同平台真排队',
            'set.sameQueueInline': '真排队：同一平台一次只跑一条，前一条跑完才轮到下一条',
            'set.stagger': '同平台错峰间隔（秒）',
            'set.useProfile': '持久浏览器 Profile',
            'set.useProfileInline':
                '一个平台/账号一台自己的浏览器目录：站点看到的始终是同一台连续设备——微博、小红书、抖音要的就是这个，'
                + '而你取的 Cookie 就是抓取用的那份会话。关掉之后，每次采集都是一台全新设备带着一个旧快照。',
            'set.maxVisible': '窗口运行最大并发浏览器',
            'set.maxHeadless': '无头运行最大并发浏览器',
            'set.clearConsole': '每次运行前清空控制台',
            'set.clearConsoleInline': '新运行一开始就清空控制台，连各工作流标签页连同其历史一并删除',
            'set.gentleCrawl': '慢速采集（降风控）',
            'set.gentleCrawlInline': '只放慢采集节奏（每次动作间多等数秒），绝不改浏览器身份；刚被风控/验证码挡过时开启，用退避换更低的再次触发',
            'set.adviceButton': '采集建议（Profile / 并行 / 串行）',
            'advice.title': '各平台的建议',
            'advice.profile': '建议启用持久 Profile（一次性浏览器/旧快照会被拒）：',
            'advice.live': '自动化测试必须复用同一个真实 Profile 会话（复制的登录＝第二台设备）：',
            'advice.serial': '只能串行、不能并行（同一账号两开即撞登录墙）：',
            'advice.parallel': '推荐并行采集（两会话实测可共存）：',
            'advice.none': '无',
            'advice.unavailable': '平台能力清单还没加载——请到数据源面板重试加载',
            'lock.lock': '锁定：清空/删除时保留这一项',
            'lock.unlock': '解锁：允许被清空/删除',
            'set.profileDir': 'Profile 目录',
            'set.profileStatus': '各平台 Profile',
            'set.profileDirPlaceholder': '留空 = 内置 data/chrome_profile/平台；也可填绝对路径',
            'set.profileUnavailable': '读不到 Profile 状态（服务未响应）',
            'set.profileSuggested': '建议开启',
            'set.profileOff': '功能已关闭',
            'set.profileReady': '已在使用，会话由它自己保存',
            'set.profileWillImport': '首次使用时导入已存 Cookie',
            'set.profileNeedsLogin': '尚未在其中登录，请到 Cookie 面板登录一次',
            'set.templateReady': '新设备初始模板：干净——之后新建的账号都从它克隆',
            'set.templateMissing': '新设备初始模板：还没有——第一次需要新账号时由一个空白浏览器当场生成',
            'set.templateDirty': '新设备初始模板：里面出现了登录痕迹——任何账号再用它之前会先销毁重建',
            'dialog.profileOff': '本次工作流包含 {n} 个已知会被"一次性浏览器"刁难的平台（它们的会话会换票，或重放的票几分钟内就被拒）。请到「设置」打开持久浏览器 Profile，并在 Cookie 面板里往那个 profile 登录一次；把同一份登录态拷进第二个浏览器，站点看到的就是第二台设备——实测直接弹回登录页。也可以无视上面这句继续运行。',
            'dialog.profileGoOn': '继续运行',
            'dialog.profileSetup': '先去设置',
            'dialog.profileClash':
                '这条并行画布里有 {n} 个平台（{platforms}）被两个以上的工作流同时采集，而一份 profile 同时只能开'
                + '一个 Chrome。请选这次执行要换到什么：\n'
                + '· 继续用 Profile —— 站点看到的是同一台连续设备（微博/小红书就是针对一次性浏览器的），'
                + '但同平台的采集会一个跑完再跑下一个，这部分并行等于没有。\n'
                + '· 本次不用 Profile —— 这些工作流真的同时爬，但每个都是全新设备 + 导入一份旧 Cookie 快照，'
                + '而这正是那些站点会拒绝的形态。',
            'dialog.profileClashUse': '继续用 Profile',
            'dialog.profileClashSkip': '本次不用 Profile',
            'dialog.serialWarn':
                '{platforms} 的多条采集会被强制排队、一条跑完才跑下一条：同一账号并行翻页一定会被弹回登录页'
                + '（实测），所以这里的并行买不到任何东西。这是站点的规矩，不是设置能改的。仍要继续这次运行吗？',
            'dialog.serialWarnGo': '继续运行（自动排队）',
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
            'op.aggression': '网络暴力言论识别',
            'mode.lexicon': '词库规则（无需模型）',
            'settings.aggressionHint': '判的是言论有多**暴力**，不是有多负面：谩骂、人身攻击、隐私披露（人肉/开盒）、造谣转述四类特征，分三档 none / mild / severe。产出三列：aggression、aggression_score、aggression_hits（命中了什么词，让你能核对结论而不必信一个数）。词库模式是**召回器不是判定器**：换了说法的攻击它就看不见，而这一点在这里无法度量——词表就放在代码里，让你看得见它有多不全。severe 特意偏向隐私披露，因为那是把线上辱骂变成现实伤害的那一步。与「分组聚合」按阶段列汇总，就得到论文那条"各阶段暴力言论占比"曲线。',
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
            'settings.groupOrderColumn': '按此列排行（留空=按组名）',
            'settings.joinHow': '关联方式',
            'settings.leftOn': '左表键',
            'settings.rightOn': '右表键',
            'settings.newCol': '新列名',
            'settings.urls': '文章链接',
            'settings.urlsHint': '每行一个链接，微信按这些文章逐个抓取',
            'settings.commentUrls': '文章链接',
            'settings.inputColumn': '上游列名',
            'settings.inputColumnHint':
                '填上游表格的列名＝逐行读该列链接去爬（链接框此时失效、其内容被忽略）；一格多链接自动拆开；不接表格请留空',
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
            'settings.commentStart': '评论时间筛选 · 开始（YYYY-MM-DD）',
            'settings.commentEnd': '评论时间筛选 · 结束（YYYY-MM-DD）',
            'settings.commentTimeHint': '只保留「评论时间」落在 [开始, 结束] 内的评论；两端都留空则保留全部。要填就两端都填，只填一端会被拒绝。',
            'settings.commentLimit': '评论条数上限',
            'settings.commentLimitHint': '0 表示采集全部评论',
            'settings.partSize': '分片大小',
            'settings.partSizeHint': '0 表示不生成分片文件，仅输出合并后的单个文件',
            'settings.sourcePartSizeHint': '0 表示关闭。大于 0 时，每爬满 N 行写入一个带编号的分片文件，运行中即可打开查看，结束时合并为一个文件。',
            'settings.liveExport': '实时导出（按批）',
            'settings.liveExportHint': '每处理完一批就重写一次本节点的 .live 文件，节点未跑完也能查看当前结果。',
            'settings.perArticleFile': '每篇文章单独输出文件',
            'settings.keepParts': '合并后保留分片文件',
            'settings.partTimestamp': '分片文件名加本次创建时间',
            'settings.partTimestampHint': '按本次运行的开始时间命名分片（以及合并后的文件），再跑一次不会覆盖上一次的文件。同一次运行的「续跑」仍然写同一组名字。',
            'settings.commentHint': '评论区靠滚动页面加载。选窗口运行会可见地滚动；选无头运行则不弹窗，采集到的行数一样（#148）。每 part_size 条评论写入一个分片文件到导出目录。',
            'settings.commentFetchHint': '此平台的评论在页面内一次性取数，开窗口也只是停在首页。无头运行不弹窗，采集到的行数一样。每 part_size 条评论写入一个分片文件到导出目录。',
            'settings.fetchQuietNote': '这个模式只打开一次页面、再从页面内部读取数据：可见窗口只会停在上面什么都不显示，用「无头」跑效果完全一样。',
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
            'summary.fedColumn': '列「{col}」',
            'settings.textColumnPlaceholder': '例如：正文',
            'toast.mlUpstreamNeeded': '请先连接一个带标签数据的上游节点',
            'toast.languageChanged': '语言：{lang}',
            'boot.partial': '界面有 {steps} 个模块启动失败，详见浏览器控制台',
            'stats.noChartLibrary': '图表库未加载（离线？），这两个饼图暂不可用；其余功能不受影响',
            'validate.empty': '工作流为空',
            'validate.sourceNoPlatform': '数据源节点 "{title}"：没有选择平台',
            'validate.sourceUnknownPlatform': '数据源节点 "{title}"：{platform} 不在本工具可采集的站点里',
            'validate.sourceUnknownMode': '数据源节点 "{title}"：{platform} 没有这种采集内容',
            'validate.capUnavailable': '数据源节点 "{title}"：平台能力清单尚未加载，无法核对它需要哪些字段——请到设置面板重试',
            'validate.sourceFieldMissing': '数据源节点 "{title}"：{field} 不能为空',
            'validate.sourceDownstream': '数据源节点 "{title}"：必须连接到下游节点',
            'validate.sourceFeedNoMode': '数据源节点 "{title}"：这种采集内容不接受上游表格，请断开连线或改选采集内容',
            'validate.sourceFeedNoColumn': '数据源节点 "{title}"：已接上游表格，请填写要逐行读取的列名（{field}）',
            'validate.sourceFeedNoInput': '数据源节点 "{title}"：填写了上游列名但没有连接数据表格',
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
            'runsMgr.queueHeader': '排队中（{n}）',
            'runsMgr.queueCancel': '取消',
            'runsMgr.queueCancelled': '已从队列移除',
            'runsMgr.queueGone': '该运行已开始或已被移除',
            'runsMgr.queueCancelFailed': '无法访问队列',
            'exportsMgr.header': '导出产物',
            'exportsMgr.empty': '还没有导出文件——运行一个含输出节点的工作流',
            'exportsMgr.loadFailed': '读取导出目录失败',
            'exportsMgr.summary': '共 {files} 个文件，合计 {size}',
            'exportsMgr.colName': '文件名',
            'exportsMgr.colKind': '类型',
            'exportsMgr.colSize': '大小',
            'exportsMgr.colModified': '修改时间',
            'exportsMgr.download': '下载',
            'exportsMgr.view': '查看报告',
            'exportsMgr.report': '生成报告',
            'exportsMgr.reportHint': '生成一个自包含 HTML 文件：本次运行的每张表格，外加图表。',
            'exportsMgr.reportPlaceholder': '报告标题（留空则用工作流名）',
            'exportsMgr.reportGo': '生成',
            'exportsMgr.reportAi': '生成并附 AI 结论',
            'exportsMgr.reportDone': '报告已生成',
            'exportsMgr.reportFailed': '报告生成失败',
            'exportsMgr.reportPdf': '生成并导出 PDF',
            'exportsMgr.reportPdfDone': 'PDF 已导出',
            'exportsMgr.reportPdfFailed': 'PDF 导出失败',
            'exportsMgr.reportTCharts': '包含图表',
            'exportsMgr.reportTTables': '包含数据表',
            'exportsMgr.reportTFacts': '包含运行信息',
            'exportsMgr.reportRows': '每表最多行数',
            'runsMgr.report': '报告',
            'exportsMgr.remove': '删除',
            'exportsMgr.confirmRemove': '删除这个导出文件？删除后无法恢复。',
            'exportsMgr.clearAll': '清空',
            'exportsMgr.confirmClearAll': '清空导出目录里的全部文件？删除后无法恢复（正在运行的那次会被拒绝）。',
            'exportsMgr.clearAllDone': '已清空导出产物：删除 {n} 个文件',
            'exportsMgr.clearAllFailed': '清空导出产物失败',
            'exportsMgr.smartClearRun': '按运行清除',
            'exportsMgr.smartClearParts': '清除分片',
            'exportsMgr.pickRun': '选择要清除哪一次运行的文件（按开始时间从新到旧）：',
            'exportsMgr.runField': '运行记录',
            'exportsMgr.next': '下一步',
            'exportsMgr.clearGo': '清除',
            'exportsMgr.confirmClearRun': '删除这次运行写入的全部文件（共 {n} 个）？合并表、图表、导出都会一并删掉，无法恢复。',
            'exportsMgr.clearRunDone': '已按运行清除：删除 {removed} 个，保留 {skipped} 个（固定）',
            'exportsMgr.unnamedRun': '（未命名运行）',
            'exportsMgr.noLedger': '还没有运行写过导出文件，无可清除',
            'exportsMgr.pickNode': '选择要清除哪个数据源节点的分片文件（合并文件会保留）：',
            'exportsMgr.nodeField': '数据源节点',
            'exportsMgr.noParts': '该运行没有留下可清除的分片文件',
            'exportsMgr.clearPartsDone': '已清除分片：删除 {removed} 个，保留 {skipped} 个（固定）',
            'exportsMgr.clearFailed': '智能清除失败',
            'exportsMgr.removeDone': '导出文件已删除',
            'exportsMgr.removeFailed': '删除失败',
            'datasetMgr.header': '数据集',
            'datasetMgr.empty': '还没有已保存的数据集——先上传或粘贴一份数据',
            'datasetMgr.loading': '正在读取数据集列表…',
            'datasetMgr.loadFailed': '数据集列表读取失败',
            'datasetMgr.colName': '名称',
            'datasetMgr.colSource': '来源',
            'datasetMgr.sourceUpload': '上传文件',
            'datasetMgr.sourcePaste': '粘贴文本',
            'datasetMgr.sourceAnalysis': '清洗结果',
            'datasetMgr.colRows': '行数',
            'datasetMgr.colSize': '大小',
            'datasetMgr.colUsedBy': '被引用',
            'datasetMgr.rename': '重命名',
            'datasetMgr.renamePrompt': '给这个数据集起个新名字',
            'datasetMgr.renamePlaceholder': '例如：三亚攻略-9月',
            'datasetMgr.renameDone': '数据集已重命名',
            'datasetMgr.renameFailed': '重命名失败',
            'datasetMgr.remove': '删除',
            'datasetMgr.confirmRemove': '删除数据集 {name}？引用它的工作流下次打开会变空。',
            'datasetMgr.clearAll': '清空',
            'datasetMgr.confirmClearAll': '清空全部已保存文件？逐条删除会护住被引用那份，这里连被工作流引用的也一起删——那些节点下次读不到东西。',
            'datasetMgr.clearAllDone': '已清空数据集：删除 {n} 个文件',
            'datasetMgr.clearAllFailed': '清空数据集失败',
            'datasetMgr.stillUsed': '有已保存的工作流正在引用这个文件——请先移除那个节点',
            'datasetMgr.removeDone': '数据集已删除',
            'datasetMgr.removeFailed': '删除失败',
            'wfMgr.header': '工作流文件',
            'wfMgr.empty': '还没有已保存的工作流——先把画布保存下来',
            'wfMgr.loading': '正在读取工作流列表…',
            'wfMgr.loadFailed': '工作流列表读取失败',
            'wfMgr.colName': '名称',
            'wfMgr.colNodes': '节点数',
            'wfMgr.colModified': '修改时间',
            'wfMgr.current': '当前',
            'wfMgr.broken': '已损坏',
            'wfMgr.open': '打开',
            'wfMgr.confirmOpen': '打开 {name}？画布上的内容会被它替换。',
            'wfMgr.rename': '重命名',
            'wfMgr.renamePrompt': '给工作流 {name} 起个新名字',
            'wfMgr.renamePlaceholder': '例如：微博舆情-9月',
            'wfMgr.renameDone': '工作流已重命名',
            'wfMgr.renameFailed': '重命名失败',
            'wfMgr.remove': '删除',
            'wfMgr.confirmRemove': '删除工作流 {name}？它已经跑出的运行记录和数据集会保留。',
            'wfMgr.removeDone': '工作流已删除',
            'wfMgr.removeFailed': '删除失败',
            'wfMgr.busy': '有任务正在运行——先停止它再改动工作流文件',
            'runsMgr.empty': '还没有运行记录',
            'runsMgr.colWorkflow': '工作流',
            'runsMgr.tagParallel': '并行 ×{n}',
            'runsMgr.tagSerial': '串行 ×{n}',
            'runsMgr.tagHeadless': '无头',
            'runsMgr.tagWindow': '窗口',
            'runsMgr.skipped': '本次跳过：{names}',
            'runsMgr.colStatus': '状态',
            'runsMgr.colNodes': '节点',
            'runsMgr.colRows': '行数',
            'runsMgr.colStarted': '开始时间',
            'runsMgr.colDuration': '运行时长',
            'runsMgr.status.running': '运行中',
            'runsMgr.status.stopping': '正在停止',
            'runsMgr.status.interrupted': '已中断',
            'runsMgr.status.completed': '已完成',
            'runsMgr.status.failed': '失败',
            'runsMgr.status.abandoned': '已放弃',
            'runsMgr.resume': '继续',
            'runsMgr.restart': '重新开始',
            'runsMgr.remove': '删除',
            'runsMgr.detail': '详情',
            'runsMgr.detailNodes': '节点明细',
            'runsMgr.groupDone': '{done}/{total} 节点',
            'runsMgr.confirmRestart': '丢弃这次中断的尝试，从头重新运行？',
            'runsMgr.confirmRemove': '删除这条运行及其保留的数据行？',
            'runsMgr.clearAll': '清空',
            'runsMgr.confirmClearAll': '清空全部运行记录与它们的数据行？正在跑的那条不动。已采集台账会一并交回，所以同样的采集下次会重新爬一遍。',
            'runsMgr.clearAllDone': '已清空运行记录：删除 {n} 条',
            'runsMgr.clearAllFailed': '清空运行记录失败',
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
            'validate.visualizeAgreementLabel': '图表节点 "{title}"：一致率标签列不能为空',
            'validate.outputInput': '输出节点 "{title}"：必须有一个输入连接',
            'validate.outputFilename': '输出节点 "{title}"：文件名不能为空',
            'validate.compileInput': '编译节点 "{title}"：请先连接一个可视化节点——它编译的是该节点产出的 LaTeX。',
            'validate.compileBadParent': '编译节点 "{title}"：它的上游必须是可视化节点（只有图表才携带可编译的 LaTeX）。',
            'validate.compileSourceBothOff': '编译节点 "{title}"：所连的可视化节点没有勾选任何 LaTeX（图与三线表都关着），没有可编译的内容。',
            'validate.outputPdfOnly': '输出节点 "{title}"：PDF 输出的上游必须是可视化节点或编译节点。',
            'validate.outputPdfMixed': '输出节点 "{title}"：PDF 输出不能同时合并表格数据——请断开表格上游，或改选表格格式。',
            'validate.outputPdfTwoSources': '输出节点 "{title}"：PDF 请由可视化节点或编译节点之一提供，不能同时接两者。',
            'validate.outputNeedsPdf': '输出节点 "{title}"：它的上游是图表/编译节点，因此格式必须为 PDF。',
            'validate.noTerminal': '至少需要一个输出（保存）或可视化节点',        },
    },
    /* Keys no dictionary defines, in the order they were first asked for. A
       silent fallback is exactly how a raw "nodeType.upload" reached the screen
       once: warn on the first miss (and keep the list available as
       I18n.missing()) so a gap can never hide again. */
    _missing: new Set(),

    t(key, vars) {
        const d = this.dict[this.lang] || this.dict.en;
        let text = d[key];
        if (text === undefined) {
            /* Show the other language before showing the raw key — a missing
               translation should still read as a sentence ("Upload File"), not as
               an identifier ("palette.upload"). */
            const other = this.dict[this.lang === 'zh' ? 'en' : 'zh'] || {};
            if (!this._missing.has(key)) {
                this._missing.add(key);
                console.warn('[i18n] missing ' + this.lang + ' string: ' + key);
            }
            text = other[key] !== undefined ? other[key] : key;
        }
        return vars ? I18n.fill(text, vars) : text;
    },

    /* Fill EVERY occurrence of each slot. `String.prototype.replace` with a string needle
       replaces the FIRST occurrence only, and the cookie-delete template names the platform
       twice — so `.replace('{platform}', …)` left a literal `{platform}` inside a Chinese
       sentence the user read (measured 2026-09-28). A call site that formats through here
       cannot half-fill a sentence again. */
    fill(text, vars) {
        let out = String(text);
        Object.keys(vars || {}).forEach(function (name) {
            out = out.split('{' + name + '}').join(String(vars[name]));
        });
        return out;
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
        /* A placeholder is the only place some inputs explain themselves (the
           Profile directory field is empty by design, and what empty means is the
           information), so it has to switch language with the rest of the panel. */
        document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
            el.placeholder = this.t(el.dataset.i18nPlaceholder);
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
        /* The outline rows are built by JS (not data-i18n), so their type chips and
           labels must be re-rendered when the language flips. Guarded on typeof: this
           is `const Outline` in another file, which is NOT a window property. */
        if (typeof Outline !== 'undefined') Outline.render();
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
        /* The draft is user-editable and survives every upgrade, so a broken one is
           expected input rather than a crash: apply() runs from DOMContentLoaded, and
           an exception here stopped the rest of start-up — canvas.init() never ran,
           so the page stayed blank with nothing in the console the user could read.
           Same fallback LLMSettings.load() already gives its own draft. */
        const raw = localStorage.getItem(this._key);
        if (!raw) return Object.assign({}, this.defaults);
        try {
            const stored = JSON.parse(raw);
            if (!stored || typeof stored !== 'object' || Array.isArray(stored)) return Object.assign({}, this.defaults);
            return Object.assign({}, this.defaults, stored);
        } catch (e) {
            return Object.assign({}, this.defaults);
        }
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

/* ── What this server can serve ─────────────────────────────────────────────
   The cloud flag is the SERVER's fact (`python app.py cloud`), read once from
   /api/config, and it decides which controls exist: a cloud host has no display to
   open a window on and no Ollama daemon on its own machine.

   Hiding is only the visible half. Every route behind one of these controls still
   answers a request — a saved workflow, an old tab, a hand-written POST — and each of
   those refuses by name server-side. A button that disappeared is not a permission. */
const CloudMode = {
    on: false,
    applied: false,

    /* Fed by the one /api/config read the page already makes at boot
       (``LLMSettings.loadDefaults``) — this module does not fetch, because a second
       request for the same payload would be a second answer to keep in sync. */
    set(flag) {
        this.on = !!flag;
        this.apply();
        /* The panel is filled from localStorage, which may name a transport this
           host cannot serve. Re-apply it from the truth instead of leaving a selected
           「本地 Ollama」 on a server that has none. */
        if (typeof LLMSettings !== 'undefined' && LLMSettings.applyToPanel) LLMSettings.applyToPanel();
        /* And say, once, what this kind of host keeps on its own disk. The flag landing
           is the moment the page knows it is standing in front of a stranger. */
        if (this.on && typeof PrivacyNotice !== 'undefined') PrivacyNotice.maybeShow();
    },

    apply() {
        document.documentElement.dataset.cloud = this.on ? '1' : '0';
        if (this.on) {
            /* The transport is taken OUT of the select, not merely styled away: a hidden
               <option> is still a value the element can be asked for (keyboard, a stale
               restore, an autofill), and this host cannot serve it. */
            var sel = document.getElementById('ai-provider');
            var local = sel && sel.querySelector('option[value="ollama"]');
            if (local && sel.removeChild) sel.removeChild(local);
        }
        this.applied = true;
    },
};

/* ── The first-entry notice on a cloud host ────────────────────────────────
   On a desktop the person IN FRONT of the page is the machine's owner. On a server they
   may be a stranger, and the two things they are about to hand over — a paste of cookies
   and an uploaded table — land in the SAME `data/` the operator's own runs use. So the
   page says, once, what is stored where.

   It rides `showDialog` rather than getting its own markup: that dialog already handles
   the backdrop click, Esc, and the button values this needs, and a second modal would be
   a second implementation of "how does this box close" to get wrong.

   The ack lives in localStorage — it is this BROWSER declining to be told again, not a
   server-side preference about a person the server cannot identify. */
const PrivacyNotice = {
    KEY: 'crawler_privacy_ack',
    shown: false,

    maybeShow() {
        if (this.shown || this.acked()) return;
        this.shown = true;
        showDialog({
            message: I18n.t('privacy.body'),
            buttons: [
                { label: I18n.t('privacy.never'), value: 'never' },
                { label: I18n.t('privacy.gotIt'), value: null, primary: true },
            ],
        }).then((answer) => {
            if (answer === 'never') {
                try {
                    localStorage.setItem(this.KEY, '1');
                } catch (e) {
                    /* A browser that refuses localStorage (private mode with storage
                       blocked) is asked again next visit. Saying so in a toast would be
                       noise; the notice reappearing is the honest answer. */
                }
            }
        });
    },

    acked() {
        try {
            return localStorage.getItem(this.KEY) === '1';
        } catch (e) {
            return false;
        }
    },

    /* Test seam and a genuine product need: 「我在本机重新看看这条说明」 is how a user
       unsends an ack they clicked in passing. */
    reset() {
        try {
            localStorage.removeItem(this.KEY);
        } catch (e) {
            /* Nothing to undo — an unreadable storage never held an ack. */
        }
        this.shown = false;
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
           backend (which treats every non-OpenRouter provider as Ollama).

           On a cloud host the same normalization runs the other way, and for the same
           reason: there is no local daemon here, so a stored 「ollama」 — one that came
           from a desktop profile, or from before the flag was set — must not stay the
           active transport. The server refuses that transport by name anyway; this is
           what makes the panel ask for the key it actually needs. */
        if (typeof CloudMode !== 'undefined' && CloudMode.on) s.provider = 'openrouter';
        else if (s.provider !== 'openrouter') s.provider = 'ollama';
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
            /* The server states its own shape before anything else reads it: the AI panel
               is applied from localStorage right after this, and on a cloud host that
               stored value is allowed to name a transport with no daemon behind it. */
            if (typeof CloudMode !== 'undefined') CloudMode.set(cfg && cfg.cloud_mode);
            const input = document.getElementById('ai-ollama-model');
            if (input && cfg && cfg.ollama_model) input.placeholder = cfg.ollama_model;
        } catch (e) {
            /* Unreachable server: the built-in placeholder stands, and the flag stays
               "not cloud" — stripping controls on no answer is not this page's job. */
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
        latex_binary: 'set-latex',
        window_size: 'set-window',
        page_load_timeout: 'set-pageload',
        element_timeout: 'set-elementwait',
        ollama_host: 'set-ollamahost',
        cookie_preflight_before_run: 'set-cookie-preflight',
        ask_overseas_network: 'set-ask-overseas-network',
        same_platform_queue: 'set-same-platform-queue',
        same_platform_stagger: 'set-same-platform-stagger',
        use_browser_profile: 'set-use-profile',
        browser_profile_dir: 'set-profile-dir',
        max_visible_browsers: 'set-max-visible-browsers',
        max_headless_browsers: 'set-max-headless-browsers',
        clear_console_before_run: 'set-clear-console',
        gentle_crawl: 'set-gentle-crawl',
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

/* Per-platform browser-profile state, so "启用" is not a blind switch: the panel
   shows which platforms the crawl matrix flags as needing one and whether that
   platform's directory has already been used (``imported``). A platform reading
   需要登录 is the case the user has to act on — turning the setting on does nothing
   by itself until they have logged into *that* profile once through the Cookie panel.

   Built with textContent rather than innerHTML: the row carries a platform name and
   a state sentence, and a list assembled by string concatenation is one future
   server-side string away from being markup. */
const BrowserProfiles = {
    data: null,
    _generation: 0,

    _row(entry) {
        /* Structured, and text-only on purpose: the block sits in a narrow menu
           where a single unbroken line scrolls it sideways, so the name, the
           建议 chip and the state are separate cells that wrap between them. */
        const line = document.createElement('div');
        line.className = 'profile-item';
        line.dataset.kind = entry.recommended ? 'suggested' : 'plain';
        const name = document.createElement('span');
        name.className = 'profile-name';
        name.textContent = I18n.t('platform.' + entry.platform);
        line.appendChild(name);
        if (entry.recommended) {
            const chip = document.createElement('span');
            chip.className = 'profile-chip';
            chip.textContent = I18n.t('set.profileSuggested');
            line.appendChild(chip);
        }
        const state = document.createElement('span');
        state.className = 'profile-state';
        state.textContent = this._stateOf(entry);
        line.appendChild(state);
        return line;
    },

    _noteRow(text, kind) {
        const line = document.createElement('div');
        line.className = 'profile-item';
        line.dataset.kind = kind;
        const state = document.createElement('span');
        state.className = 'profile-state';
        state.textContent = text;
        line.appendChild(state);
        return line;
    },

    _stateOf(entry) {
        if (!entry.enabled) return I18n.t('set.profileOff');
        if (entry.imported) return I18n.t('set.profileReady');
        if (entry.has_saved_cookie) return I18n.t('set.profileWillImport');
        return I18n.t('set.profileNeedsLogin');
    },

    _templateState(template) {
        if (!template.exists) return I18n.t('set.templateMissing');
        if (!template.pristine) return I18n.t('set.templateDirty');
        return I18n.t('set.templateReady');
    },

    async refresh() {
        const box = document.getElementById('profile-status');
        if (!box) return;
        /* Opening the panel while a read is still in flight used to append both
           answers to the same box (the harness caught it: 16 rows for 8 platforms).
           A generation stamp makes an older answer leave the table alone. */
        const generation = ++this._generation;
        try {
            const resp = await fetch('/api/browser/profiles');
            const result = await resp.json();
            this.data = result && Array.isArray(result.profiles) ? result : null;
        } catch (e) {
            this.data = null;
        }
        if (generation !== this._generation) return;
        /* Assigning textContent is the documented way to empty a node here: it
           replaces every descendant in a browser and in the DOM stub both, while a
           `while (box.firstChild)` loop stops dead in the stub (no firstChild) and
           would leave a re-render appending to the old rows. */
        box.textContent = '';
        /* An empty list is not "nothing to report": the endpoint answers one row per
           matrix platform, so no rows means the table broke, and a blank box would
           read as a clean bill of health. */
        if (!this.data || !this.data.profiles.length) {
            box.appendChild(this._noteRow(I18n.t('set.profileUnavailable'), 'unavailable'));
            return;
        }
        this.data.profiles.forEach(function (entry) {
            box.appendChild(BrowserProfiles._row(entry));
        });
        /* One line for the template, because it is the state this panel cannot be given
           any other way: the directory every NEW account is cloned from is made by the
           program, on the server, and nobody clicked anything to create it. A payload
           without the field says nothing — an older server that never answered the
           question is not evidence that the answer is 「缺失」. */
        if (this.data.enabled && this.data.template && typeof this.data.template.exists === 'boolean') {
            box.appendChild(BrowserProfiles._noteRow(BrowserProfiles._templateState(this.data.template), 'template'));
        }
    },
};

function renderBrowserProfiles() {
    return BrowserProfiles.refresh();
}

window.BrowserProfiles = BrowserProfiles;
window.renderBrowserProfiles = renderBrowserProfiles;

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
    /* Each start-up step is allowed to fail on its own. This body used to run
       straight through, so ONE throwing module took every later step with it —
       a missing chart CDN blanked the Data Source panel's capability list, the
       dataset re-link, the autosave and the 断点续跑 banner at once, and nothing
       on screen said which part had failed. Settings.load already learned this
       lesson the hard way; now the whole boot does. */
    const _bootSteps = [];
    const boot = (name, fn) => {
        try {
            fn();
        } catch (e) {
            _bootSteps.push(`${name}: ${(e && e.message) || e}`);
            console.error(`startup step failed: ${name}`, e);
        }
    };
    boot('settings', () => Settings.apply());
    boot('menu', () => TopMenu.init());
    boot('canvas', () => canvas.init());
    // Restore which saved file this draft belongs to BEFORE anything reads runName()
    // (resume bar, dashboard rehydrate, exports) — a refresh/restart reopens the file,
    // and only 新建 starts a new one.
    boot('openFile', () => workflow.restoreOpenFile());
    // Then re-fetch that file's CONTENT from the server: the local draft is a snapshot and the file
    // may have been updated outside this browser, so entering must open the latest saved version,
    // not the stale view. A new (unnamed) canvas keeps its draft.
    boot('reloadOpenFile', () => workflow.reloadOpenFile());
    boot('stats', () => stats.init());
    /* Replace every OS-drawn candidate UI (select popups, datalist suggestions)
       with the themed equivalents. Runs last so it also catches anything the
       other modules rendered during init. */
    boot('customSelect', () => CustomSelect.init());

    /* The Data Source panel is generated from the backend's crawl matrix, so the
       browser has to have it before a source node can be configured. Fetched at
       start-up rather than on first open: the first settings panel should show a
       form, not a spinner, and a failure says so with a retry. */
    Capabilities.load();

    /* Registered fine-tuned models (the 网暴模型 etc.) are fetched the same way, so
       the bert-mode picker can name them instead of the user typing a path. */
    BertModels.load();

    /* Uploaded files are stored on the server, so the canvas restored from
       localStorage very likely still owns every file it referenced. Verify
       each one instead of clearing it — see dataNodes.reconcileDatasets. */
    boot('datasets', () => dataNodes.reconcileDatasets());
    /* Sweep orphaned files (only ones no saved workflow points at go). */
    fetch('/api/data/clear', { method: 'POST' }).catch(() => { });

    /* Palette drag */
    boot('palette', () => {
        document.querySelectorAll('.palette-item').forEach(item => {
            item.addEventListener('dragstart', (e) => {
                e.dataTransfer.setData('text/plain', item.dataset.type);
                e.dataTransfer.effectAllowed = 'copy';
            });
        });
        /* The panel boots expanded; label its toggle to say what the next click does. */
        var palToggle = document.querySelector('#node-palette .palette-toggle');
        if (palToggle) palToggle.title = I18n.t('palette.collapse');
    });

    /* Outline sidebar: a jump-to-node navigator. Its rows re-render from the model on
       every saveState, so init only has to restore the collapsed state and paint once. */
    boot('outline', () => Outline.init());

    /* Auto-save every 30 seconds */
    setInterval(() => {
        canvas.saveState();
    }, 30000);

    /* An interrupted run may be waiting from before this page opened. */
    boot('resumeBar', () => {
        if (typeof resumeBar !== 'undefined' && resumeBar) resumeBar.refresh();
    });
    /* A run may also be GOING, in which case this page's console is not a new console —
       it is the same run's log with a browser that reloaded in the middle of it. Nothing
       else starts the poll, so without this step the box stays empty for the rest of the
       crawl while the server keeps writing. `workflow` is a top-level const in
       workflow.js, so it is named directly: `window.workflow` could never be truthy. */
    boot('consoleReconnect', () => {
        if (typeof workflow !== 'undefined' && workflow) workflow.reconnectConsole();
    });
    boot('locks', () => {
        /* #182: fetch the lock set ONCE at startup, then repaint any docked panel that
           is already open so a locked row shows its lock immediately. Loading here (not
           in each panel refresh) keeps the per-refresh paths free of an extra request. */
        if (typeof Locks === 'undefined') return Promise.resolve();
        return Locks.load().then(function () {
            var open = function (mgr) {
                return mgr && mgr.panel && mgr.panel() && mgr.panel().classList.contains('open');
            };
            if (typeof exportsManager !== 'undefined' && open(exportsManager)) exportsManager.render();
            if (typeof runsManager !== 'undefined' && open(runsManager)) runsManager.render(runsManager._shown || []);
            if (typeof wfFiles !== 'undefined' && open(wfFiles) && wfFiles._last) wfFiles.render();
        });
    });
    if (_bootSteps.length) {
        showToast(I18n.t('boot.partial').replace('{steps}', _bootSteps.length));
    }
});

/* Background selection is handled by setBg() in workflow.js, which the menu
   delegates to — no separate listener needed here. */

/* ── Panel Drag & Resize Utilities ── */

const _DS = {}; // shared drag state

function makeDraggable(el, handleSelector) {
    const handle = typeof handleSelector === 'string'
        ? el.querySelector(handleSelector) : handleSelector;
    if (!handle) return;
    /* Pointer events, not mouse: one code path serves mouse, touch and pen. touch-action:none
       stops the browser claiming a finger drag as a page scroll before we see a pointermove. */
    handle.style.touchAction = 'none';

    handle.addEventListener('pointerdown', (e) => {
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

document.addEventListener('pointermove', (e) => {
    if (!_DS.isDragging || !_DS.el) return;
    _DS.el.style.setProperty('left', (e.clientX - _DS.offX) + 'px', 'important');
    _DS.el.style.setProperty('top', (e.clientY - _DS.offY) + 'px', 'important');
});

document.addEventListener('pointerup', () => {
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
    handle.style.touchAction = 'none'; /* a finger drag on the handle is ours, not the page's scroll */
    handle.addEventListener('pointerdown', (e) => {
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

    /* One shared pointermove/pointerup for every resizable — mouse, touch and pen alike. */
    if (!window._resizeInit) {
        window._resizeInit = true;
        document.addEventListener('pointermove', (e) => {
            const r = window._rs;
            if (!r || !r.active) return;
            const newW = Math.max(r.minW, Math.min(r.maxW, r.startW + (e.clientX - r.startX)));
            const newH = Math.max(r.minH, Math.min(r.maxH, r.startH + (e.clientY - r.startY)));
            r.el.style.setProperty('width', newW + 'px', 'important');
            r.el.style.setProperty('height', newH + 'px', 'important');
            if (r.onResize) r.onResize(newW, newH);
        });
        document.addEventListener('pointerup', () => {
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

    handle.style.touchAction = 'none';
    handle.addEventListener('pointerdown', (e) => {
        const panel = document.getElementById('console-panel');
        if (panel.classList.contains('popout')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('pointermove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('pointerup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
})();

/* ─── Docked panel height resize ────────────────────────────────
   Four panels share this behaviour, so one function drives all of them.
   Measured from mousedown (not from a stored value) because each panel can be
   resized again after a drag, and the second drag has to start from where the
   first left off. */
function initDockResize(handleId, panelId) {
    const handle = document.getElementById(handleId);
    if (!handle) return;
    let cs = {};

    handle.style.touchAction = 'none';
    handle.addEventListener('pointerdown', (e) => {
        const panel = document.getElementById(panelId);
        if (!panel || !panel.classList.contains('open')) return;
        e.preventDefault();
        cs.panel = panel;
        cs.startY = e.clientY;
        cs.startH = panel.offsetHeight;
        cs.active = true;
        handle.classList.add('active');
    });

    document.addEventListener('pointermove', (e) => {
        if (!cs.active) return;
        const newH = Math.max(80, Math.min(window.innerHeight - 100, cs.startH + (cs.startY - e.clientY)));
        cs.panel.style.height = newH + 'px';
        cs.panel.classList.add('open'); /* keep open while resizing */
    });

    document.addEventListener('pointerup', () => {
        if (cs.active) {
            cs.active = false;
            handle.classList.remove('active');
        }
    });
}

initDockResize('runs-resize-handle', 'runs-panel');
initDockResize('exports-resize-handle', 'exports-panel');
initDockResize('dataset-resize-handle', 'dataset-panel');
initDockResize('workflows-resize-handle', 'workflows-panel');
/* The saved-logins dock is a dock like these: same bottom slot, same one-handle-to-resize,
   and ``closeDockedPanels`` already lists it, so opening it shuts the other five. */
initDockResize('cookies-resize-handle', 'cookies-panel');

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
    /* A click inside the board popup itself, the sibling history popup, or any overlay
       the user legitimately stacks on top of the board — the fullscreen chart, the data
       preview panel, the chart studio — must not dismiss the board. Those are top-level
       siblings, not children of #dashboard-panel, so without this list every click in one
       of them read as "outside" and the board vanished. (#node-settings stays OUTSIDE on
       purpose: opening a node's settings is meant to close the board.) */
    if (
        e.target.closest('#dashboard-panel, #history-panel, #chart-fullscreen-panel, #data-preview-panel, #studio-overlay')
    )
        return;
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
window.openCookieDialog = function (...args) {
    /* EVERY argument is forwarded, as a list, on purpose. This wrapper exists to hang
       drag/resize off the first open, and it used to declare `function (platform)` and call
       `_origOpenCookie(platform)` — which silently dropped the SECOND argument the day the
       account landed there: the pre-run block and the saved-logins row both ask for
       「this platform, this account」, and in a browser the wrapper is the function they get.
       Measured in real Chrome (tests/integration/test_ui_layout.py): the panel opened on the
       right platform and the account box stayed on whatever the user had typed, so 「打开」
       looked half-dead. Restating the parameter list is exactly how this breaks again, so
       the list is passed through untouched. */
    _origOpenCookie(...args);
    const dialog = document.getElementById('cookie-dialog');
    if (dialog.classList.contains('open') && !dialog.dataset._uiInit) {
        dialog.dataset._uiInit = '1';
        makeDraggable(dialog, '.settings-header');
        /* Viewport-relative bounds, not fixed pixels: this dialog carries six
           platforms' worth of translated guidance plus two textareas, so a
           maxH of 500 clipped it to about a third of its content and the
           remainder could not be reached at any window size. */
        makeResizable(dialog, {
            minW: 320,
            minH: 260,
            maxW: Math.min(760, window.innerWidth - 40),
            maxH: window.innerHeight - 40,
        });
    }
};

/* Patch openSettings to init drag+resize on first open */
const _origOpenSettings = window.openSettings;
window.openSettings = function (nodeId) {
    var panel = document.getElementById('node-settings');
    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.settings-header');
        /* Same reasoning as the cookie dialog: the node panel grows with the node
           (a source node in comments mode, an analysis op with five fields), and a
           fixed 800px ceiling left fields unreachable on a tall window. */
        makeResizable(panel, {
            minW: 300,
            minH: 240,
            maxW: Math.min(680, window.innerWidth - 40),
            maxH: window.innerHeight - 40,
        });
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
