/* Drives the REAL AI workspace against a stub page: repaint and delegated clicks.
 *
 * Two defects lived here that Python cannot see and the stream harness could not reach:
 *   · `_renderMessages` appended to the array it was iterating, so reopening any saved
 *     conversation never finished;
 *   · the delegated click/change listeners hung off `#ai-chat` while the session list, the
 *     side panel and the context bar are its siblings — every button outside the transcript
 *     was inert.
 *
 * The page's own load order is used (index.html), so `ai/settings.js`, `ai/context.js` and the
 * i18n catalogue are the shipped files, not copies. Usage: node harness_ai_workspace.mjs <jsDir>
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox, dispatchOn, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const jsDir = process.argv[2];
const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);
loadPageScripts(sandbox, { jsDir, only: ['app.js', 'ai-workspace.js', 'panels/settings.js', 'panels/data-views.js'] });

const workspace = sandbox.AIWorkspace;
workspace.init();

const out = {};

/* A repaint draws the transcript it was handed. The count of model rows and the count of drawn
   user messages must both equal the seed — a repaint that records a second copy is the loop. */
workspace._messages = [
    { role: 'user', content: 'first <question>', meta: { context: {}, attachments: [] } },
    { role: 'assistant', content: '', blocks: [{ type: 'text', text: 'answer' }], usage: {} },
    { role: 'tool', content: '{"ok":true}', meta: { name: 'run_status' } },
    { role: 'user', content: 'second', meta: { context: { dataset_id: 'd1' }, attachments: [] } },
];
workspace._renderMessages([]);
const firstUser = workspace._dom.chat.querySelectorAll('.ai-message.user')[0];
out.repaint = {
    stored: workspace._messages.length,
    users: workspace._dom.chat.querySelectorAll('.ai-message.user').length,
    assistants: workspace._dom.chat.querySelectorAll('.ai-message.assistant').length,
    escaped: !!firstUser && firstUser.innerHTML.includes('&lt;question&gt;'),
};

/* The sessions list is rendered into #ai-sessions, OUTSIDE #ai-chat. A click on one of its rows
   must reach the delegated handler; the spy records the id the product passed through. */
workspace._bootstrap = {
    providers: [],
    runtime: { kind: 'desktop', label_key: 'ai.runtime.desktop' },
    conversations: [{ id: 'c1', title: 'Saved conversation', message_count: 2 }],
    monitors: [{ id: 'm1', status: 'armed', spec: { events: ['run.finished'] }, auto_analyze: false }],
};
workspace._renderSessions();
workspace._renderSide();

const calls = [];
workspace.selectConversation = async (id) => calls.push('conversation:' + id);
workspace._renderContextBar = () => calls.push('context');
workspace._disarmMonitor = async (id) => calls.push('disarm:' + id);

const sessionRow = workspace._dom.sessions.querySelector('[data-ai-conversation]');
const disarmRow = workspace._dom.side.querySelector('[data-ai-disarm-monitor]');
const refreshRow = workspace._dom.context.querySelector('[data-ai-context-refresh]');
for (const row of [sessionRow, disarmRow, refreshRow]) {
    if (!row) continue;
    dispatchOn(workspace._dom.root, 'click', { target: row });
}

const renameRow = workspace._dom.sessions.querySelector('[data-ai-rename-conversation]');
const deleteRow = workspace._dom.sessions.querySelector('[data-ai-delete-conversation]');
workspace._renameConversation = async (id) => calls.push('rename:' + id);
workspace._deleteConversation = async (id) => calls.push('delete:' + id);
for (const row of [renameRow, deleteRow]) {
    if (!row) continue;
    dispatchOn(workspace._dom.root, 'click', { target: row });
}

out.delegated = {
    session: calls.includes('conversation:c1'),
    disarm: calls.includes('disarm:m1'),
    context: calls.includes('context'),
    // Nothing outside a data-ai target may act: a click on the transcript body is a no-op.
    ignored: (() => {
        const before = calls.length;
        dispatchOn(workspace._dom.root, 'click', { target: workspace._dom.chat });
        return calls.length === before;
    })(),
    sessionRowFound: !!sessionRow,
    disarmRowFound: !!disarmRow,
    refreshRowFound: !!refreshRow,
    rename: calls.includes('rename:c1'),
    delete: calls.includes('delete:c1'),
    renameRowFound: !!renameRow,
    deleteRowFound: !!deleteRow,
};

/* Session management: pin / archive / export reach their own methods, and typing in the search box
   asks the SERVER (a page of 80 rows in memory cannot answer "not found" honestly). */
workspace._bootstrap.conversations = [
    { id: 'c1', title: 'Saved conversation', message_count: 2, pinned: 0, archived: 0 },
];
workspace._renderSessions();
workspace._toggleConversationPin = async (id) => calls.push('pin:' + id);
workspace._toggleConversationArchive = async (id) => calls.push('archive:' + id);
workspace._exportConversation = async (id) => calls.push('export:' + id);
workspace._refreshConversations = async () =>
    calls.push('refresh:' + workspace._sessionQuery + ':' + workspace._showArchived);

const pinRow = workspace._dom.sessions.querySelector('[data-ai-pin-conversation]');
const archiveRow = workspace._dom.sessions.querySelector('[data-ai-archive-conversation]');
const exportRow = workspace._dom.sessions.querySelector('[data-ai-export-conversation]');
const archivedToggle = workspace._dom.sessions.querySelector('[data-ai-toggle-archived]');
for (const row of [pinRow, archiveRow, exportRow, archivedToggle]) {
    if (!row) continue;
    dispatchOn(workspace._dom.root, 'click', { target: row });
}

/* The debounce is a real timer; run it inline for the scenario so the request is observable. */
const realTimeout = sandbox.setTimeout;
sandbox.setTimeout = (fn) => {
    fn();
    return 0;
};
dispatchOn(workspace._dom.root, 'input', {
    target: {
        hasAttribute: (name) => name === 'data-ai-session-search',
        value: 'old',
    },
});
sandbox.setTimeout = realTimeout;

out.sessions = {
    search: !!workspace._dom.sessions.querySelector('[data-ai-session-search]'),
    pin: calls.includes('pin:c1'),
    archive: calls.includes('archive:c1'),
    export: calls.includes('export:c1'),
    archivedToggle: calls.includes('refresh:old:true'),
    searchRows: [pinRow, archiveRow, exportRow, archivedToggle].filter(Boolean).length,
};

/* The studio's Memory tab lists what the server confirmed and offers add/delete; the assistant's
   proposal is a card whose button applies it. */
workspace._studioTab = 'memory';
workspace._memories = [{ id: 'mem1', text: '默认账号是 default' }];
workspace._memoryLimit = 200;
sandbox.AIStudio.render(workspace._dom.chat, workspace);
sandbox.AIStudio.saveMemory = async () => calls.push('memory-save');
sandbox.AIStudio.deleteMemory = async (_host, id) => calls.push('memory-delete:' + id);
const memoryAdd = workspace._dom.chat.querySelector('[data-ai-memory-add]');
const memoryDelete = workspace._dom.chat.querySelector('[data-ai-memory-delete]');
for (const row of [memoryAdd, memoryDelete]) {
    if (!row) continue;
    dispatchOn(workspace._dom.root, 'click', { target: row });
}
out.memoryTab = {
    cards: workspace._dom.chat.querySelectorAll('.ai-memory-card').length,
    text: String(workspace._dom.chat.innerHTML || ''),
    add: calls.includes('memory-save'),
    delete: calls.includes('memory-delete:mem1'),
    count: String(workspace._dom.chat.innerHTML || '').includes('1 / 200'),
};

const artifactHolder = sandbox.document.createElement('div');
artifactHolder.innerHTML = sandbox.AIRender.artifactCard({
    id: 'art1',
    kind: 'memory',
    title: '记住这条',
    payload: { text: '这个项目用默认账号' },
    summary: '',
});
const memoryArtifactButton = artifactHolder.querySelector('[data-ai-apply-memory]');
workspace._applyMemoryArtifact = (id) => calls.push('memory-artifact:' + id);
if (memoryArtifactButton) dispatchOn(workspace._dom.root, 'click', { target: memoryArtifactButton });
out.memoryArtifact = {
    button: !!memoryArtifactButton,
    applied: calls.includes('memory-artifact:art1'),
};

/* A chart_spec is no longer copy-only: its card carries the one mechanical action, and the click
   funnels through the same delegated selector as every other artifact button. */
const chartArtifactHolder = sandbox.document.createElement('div');
chartArtifactHolder.innerHTML = sandbox.AIRender.artifactCard({
    id: 'chart_art',
    kind: 'chart_spec',
    title: 'Bar chart',
    payload: { chart_type: 'bar', dataset_id: 'd1', x: 'city', y: 'likes' },
    summary: '',
});
const chartArtifactButton = chartArtifactHolder.querySelector('[data-ai-apply-chart]');
workspace._applyChartArtifact = (id) => calls.push('chart-artifact:' + id);
if (chartArtifactButton) dispatchOn(workspace._dom.root, 'click', { target: chartArtifactButton });
out.chartArtifact = { button: !!chartArtifactButton, applied: calls.includes('chart-artifact:chart_art') };

/* A monitor artifact offers two arms: the primary auto-analyzes (armed=true) and the ghost only
   watches (armed=false). The primary was a bare `return`, so arming from the card was unreachable —
   the only reachable button was the watch-only one. Both must reach _applyMonitor with the right
   armed flag, keyed by the ARTIFACT id from the button's data attribute. */
const monitorHolder = sandbox.document.createElement('div');
monitorHolder.innerHTML = sandbox.AIRender.artifactCard({
    id: 'mon_art',
    kind: 'monitor',
    title: 'Run monitor',
    payload: { events: ['run.finished'] },
    summary: '',
});
const monitorAuto = monitorHolder.querySelector('[data-ai-apply-monitor]');
const monitorWatch = monitorHolder.querySelector('[data-ai-watch-only]');
const monitorCalls = [];
workspace._applyMonitor = async (id, auto) => monitorCalls.push([id, !!auto]);
if (monitorAuto) dispatchOn(workspace._dom.root, 'click', { target: monitorAuto });
if (monitorWatch) dispatchOn(workspace._dom.root, 'click', { target: monitorWatch });
out.monitorArtifact = {
    autoButton: !!monitorAuto,
    watchButton: !!monitorWatch,
    calls: monitorCalls,
};

/* Attachments: a multi-file pick uploads each file (one request each) and keeps the successes; a
   drop and a pasted screenshot enter the SAME path, so neither can bypass the capability check. */
const realWorkspaceFetch = sandbox.fetch;
const uploadRequests = [];
sandbox.fetch = async (url, options) => {
    uploadRequests.push({ url, entries: (options && options.body && options.body.entries) || [] });
    return { json: async () => ({ ok: true, attachment: { id: 'att' + uploadRequests.length, name: 'f' } }) };
};
workspace._bootstrap.providers = [{ id: workspace._provider, capabilities: ['files'] }];
workspace._conversationId = 'c1';
workspace._attachments = [];
workspace._renderToggles = () => {};
const realRenderAttachments = workspace._renderAttachments;
workspace._renderAttachments = () => {};
const savedToast = workspace._toast;
workspace._toast = () => {};

await workspace._uploadFiles([new sandbox.File('a.txt'), new sandbox.File('b.txt')], 'key');
out.upload = {
    requests: uploadRequests.length,
    attachments: workspace._attachments.length,
    files: uploadRequests.map((row) => row.entries.find(([key]) => key === 'file')[1].name),
};

const realUploadFiles = workspace._uploadFiles;
const dropped = [];
workspace._uploadFiles = async (files) => dropped.push(files.length);
dispatchOn(workspace._dom.root, 'dragenter', { target: workspace._dom.root, dataTransfer: { files: [new sandbox.File('c.png')] } });
out.upload.dropActive = workspace._dom.root.classList.contains('ai-drop-active');
dispatchOn(workspace._dom.root, 'drop', { target: workspace._dom.root, dataTransfer: { files: [new sandbox.File('c.png')] } });
out.upload.dropped = dropped.length === 1 && dropped[0] === 1;
out.upload.dropCleared = !workspace._dom.root.classList.contains('ai-drop-active');

dispatchOn(workspace._dom.input, 'paste', {
    clipboardData: { items: [{ kind: 'file', getAsFile: () => new sandbox.File('shot.png') }] },
});
out.upload.pasted = dropped.length === 2 && dropped[1] === 1;
workspace._uploadFiles = realUploadFiles;
workspace._renderAttachments = realRenderAttachments;
workspace._toast = savedToast;
sandbox.fetch = realWorkspaceFetch;

/* Capability gate: a document no longer needs a provider Files API (the server extracts its
   words), an image needs the model to SEE, and a keyless local provider may still attach. */
sandbox.AISettings.save({ provider: 'localish', models: { localish: 'm' }, keys: { localish: '' } });
workspace._bootstrap.providers = [{ id: 'localish', requires_key: false, capabilities: [] }];
workspace._provider = 'localish';
workspace._model = 'm';
workspace._renderToggles = () => {};
const realStreamForGate = workspace._stream;
let lastSentBody = null;
workspace._stream = async (_url, body) => {
    lastSentBody = body;
};
const gateToasts = [];
workspace._toast = (message) => gateToasts.push(message);
out.capabilityGate = { localAttachKey: workspace._attachKey() === '' };

workspace._sending = false;
workspace._attachments = [{ id: 'att_txt', name: 'note.txt', mime: 'text/plain' }];
workspace._refs = [];
workspace._dom.input.value = 'read this';
out.capabilityGate.documentSent = await workspace._sendText(workspace._dom.input.value, {});
out.capabilityGate.sentAttachments = lastSentBody ? lastSentBody.attachments : null;

workspace._sending = false;
workspace._attachments = [{ id: 'att_img', name: 'shot.png', mime: 'image/png' }];
workspace._dom.input.value = 'look';
out.capabilityGate.imageSent = await workspace._sendText(workspace._dom.input.value, {});
out.capabilityGate.imageToast = gateToasts.some((message) => /vision|视觉|看图/i.test(String(message)));
workspace._attachments = [];
workspace._stream = realStreamForGate;
workspace._toast = savedToast;

/* The skill editor's two lists are the server's answer. */
workspace._bootstrap.context_sources = ['project', 'run'];
workspace._bootstrap.tools = [
    { name: 'run_status', control: false },
    { name: 'ask_user_question', control: true },
];
const editorHtml = sandbox.AIStudio.editor({ id: 'mine', context: [], tools: [] }, workspace);
const editor = sandbox.document.createElement('div');
editor.innerHTML = editorHtml;
const contextChecks = editor
    .querySelectorAll('[data-ai-skill-context]')
    .map((el) => String(el.getAttribute('data-ai-skill-context')));
const toolChecks = editor.querySelectorAll('[data-ai-skill-tool]').map((el) => String(el.getAttribute('data-ai-skill-tool')));
out.editor = { contextChecks, toolChecks };

/* A context source is still server data interpolated into a double-quoted attribute: escape it
   the same way the adjacent tool list does, or a crafted value can break out of the attribute. */
workspace._bootstrap.context_sources = ['x" onfocus="alert(1)'];
out.editorEscaped = { html: sandbox.AIStudio.editor({ id: 'mine', context: [], tools: [] }, workspace) };

/* A saved provider id is not rewritten by a browser-side list; the server catalog decides. */
sandbox.AISettings.save({ provider: 'custom_provider' });
out.provider = { stored: sandbox.AISettings.load().provider };

/* The provider settings page's three buttons. They were listed in the delegated selector but had
 * no branch in the handler, so 保存 — the only place the API key is typed — did nothing at all
 * (no toast, no request, no error). Each target must reach its own method. */
workspace.openSettings();
const settingsButtons = {
    save: workspace._dom.chat.querySelector('[data-ai-save-settings]'),
    models: workspace._dom.chat.querySelector('[data-ai-refresh-models]'),
    test: workspace._dom.chat.querySelector('[data-ai-test]'),
};
const settingsCalls = [];
workspace._saveSettings = async () => settingsCalls.push('save');
workspace._refreshModels = async () => settingsCalls.push('models');
workspace._testProvider = async () => settingsCalls.push('test');
for (const button of Object.values(settingsButtons)) {
    if (button) dispatchOn(workspace._dom.root, 'click', { target: button });
}
out.settings = {
    found: Object.keys(settingsButtons).filter((key) => settingsButtons[key]).length,
    calls: settingsCalls,
};

/* A control OUTSIDE the panel (the Python node's 管理脚本) opens the studio. If the workspace is
 * closed, that call has to open it — `_mode` only decides what the transcript would draw, so the
 * old code left the button looking dead. */
workspace.close();
workspace.openStudio('python');
out.studioOpensPanel = {
    open: workspace._open === true,
    hidden: workspace._dom.root.hidden === true,
    mode: workspace._mode,
};

/* The canvas Python node's settings form. Its script picker must offer one empty placeholder and
 * nothing whose VALUE is the placeholder sentence (that sentence would be stored as script_id), and
 * “管理脚本” must call the studio entry that exists. */
vm.runInContext('loadPythonNodePanel = function () {};', sandbox);
const pythonHtml = vm.runInContext('renderPythonSettings("n-python", {script_id: "", args: "{}"})', sandbox);
const holder = sandbox.document.createElement('div');
holder.innerHTML = pythonHtml;
const pick = vm.runInContext("I18n.t('settings.pythonPick')", sandbox);
const pickOptions = holder
    .querySelectorAll('option')
    .filter((option) => String(option.textContent) === pick)
    .map((option) => String(option.value));
const manageButton = holder.querySelectorAll('button').find((button) => String(button.onclick || '').includes('openStudio'));
out.pythonPanel = {
    pickOptions,
    manage: !!manageButton,
    manageTarget: manageButton ? String(manageButton.onclick) : '',
};

/* Slash commands: `/re` offers retry, Enter runs it, the composer clears and the menu closes.
 * The palette must not leak into `send()` — that is the one thing a typed `/` must never do. */
workspace._dom.input.value = '/re';
workspace._onCmdInput();
const cmdRows = workspace._dom.cmdMenu.querySelectorAll('[data-ai-cmd]').map((el) => el.getAttribute('data-ai-cmd'));
const cmdCalls = [];
workspace.retry = async () => cmdCalls.push('retry');
const cmdHandled = workspace._onCmdKey({ key: 'Enter', preventDefault() {} }, false);
out.commands = {
    ids: cmdRows,
    handled: cmdHandled,
    calls: cmdCalls,
    cleared: workspace._dom.input.value === '',
    closed: workspace._dom.cmdMenu.hidden === true,
};

/* Failed-node card and approval card: the button must name run + workflow + node, reach the
   delegated handler, and the answered card must keep the decision visible. The approval card is
   the same shell with a danger tone and all three choices. */
workspace._conversationId = 'c-cards';
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
const cardTurn = workspace._ensureAssistant();
cardTurn.blocks = [{ type: 'failed_nodes', run_id: 'r1', workflow_name: 'wf', nodes: [{ node: 'n2', error: 'boom' }] }];
workspace._paintAssistant();
const rerunButton = workspace._dom.chat.querySelectorAll('[data-ai-rerun-node]')[0];
const rerunCalls = [];
const realRerun = workspace._rerunFailedNode;
workspace._rerunFailedNode = async (run, node, name) => rerunCalls.push([run, node, name]);
if (rerunButton) dispatchOn(workspace._dom.root, 'click', { target: rerunButton });
workspace._rerunFailedNode = realRerun;
workspace._markRerunStarted('r1', 'n2', 'wf', cardTurn);
workspace._paintAssistant();
const failedSection = workspace._dom.chat.querySelectorAll('.ai-failed-nodes')[0];
const startedNode = workspace._dom.chat.querySelectorAll('.ai-question-answered')[0];

const approvalHtml = sandbox.AIRender.questionCard(
    {
        id: 'approval',
        kind: 'approval',
        header: 'Permission needed',
        question: 'Allow run_cmd?',
        preview: {
            tool: 'workspace_write',
            kind: 'write',
            exists: true,
            changed: true,
            truncated: false,
            error: '',
            facts: [{ key: 'path', value: 'notes.txt' }],
            diff: ['--- a/notes.txt', '+++ b/notes.txt', '@@ -1 +1 @@', '-old', '+new'],
        },
        options: [
            { label: 'Allow once', value: 'once' },
            { label: 'Allow for this session', value: 'session' },
            { label: 'Deny', value: 'deny' },
        ],
    },
    false
);
const approvalCard = sandbox.document.createElement('div');
approvalCard.innerHTML = approvalHtml;
workspace._ingestRunNodes(
    { run: { id: 'r2', workflow_name: 'wf2' }, nodes: { n9: { status: 'failed', error: 'bad' } } },
    cardTurn
);
workspace._paintAssistant();
const failingNodes = workspace._dom.chat.querySelectorAll('.ai-failed-node-id').map((el) => String(el.textContent));
out.cards = {
    runStatus: failingNodes,
    rerun: {
        button: !!rerunButton,
        run: rerunButton && rerunButton.getAttribute('data-ai-rerun-run'),
        workflow: rerunButton && rerunButton.getAttribute('data-ai-rerun-workflow'),
        clicked: rerunCalls,
        startedText: !!failedSection && failedSection.classList.contains('is-started') && !!startedNode && String(startedNode.textContent || '').includes(
            vm.runInContext("I18n.t('ai.rerunStarted', { node: 'n2' })", sandbox)
        ),
    },
    approval: {
        danger: approvalHtml.includes('ai-question-approval'),
        options: approvalCard.querySelectorAll('[data-ai-answer]').map((el) => el.getAttribute('data-ai-answer')),
        badge: approvalHtml.includes(vm.runInContext("I18n.t('ai.approvalBadge')", sandbox)),
        preview: approvalHtml.includes('ai-approval-preview'),
        path: approvalHtml.includes(vm.runInContext("I18n.t('ai.approvalField.path')", sandbox)),
        /* The DOM stub treats a <pre>'s children as text, so count the painted spans in the HTML. */
        added: (approvalHtml.match(/ai-diff-line add/g) || []).length,
        removed: (approvalHtml.match(/ai-diff-line del/g) || []).length,
    },
};

/* A reloaded transcript must keep WHAT FAILED and WHAT WAS ASKED. Both lived only in the live
   DOM: the stored assistant row carries meta.error, and an answered question's tool row carries
   the questions. Reopening a conversation used to show a silent gap in their place. */
workspace._messages = [
    {
        id: 'm1',
        role: 'assistant',
        status: 'error',
        blocks: [{ type: 'text', text: 'partial answer' }],
        meta: { error: '供应商拒绝了请求（400）：unresolved tool call' },
        usage: {},
    },
    {
        id: 'm2',
        role: 'tool',
        content: JSON.stringify({
            tool: 'ask_user_question',
            questions: [{ id: 'q1', question: 'Which dataset?', header: 'Scope' }],
            answers: [{ id: 'q1', selected: ['Dataset A'] }],
        }),
        meta: {},
    },
    {
        id: 'm3',
        role: 'tool',
        content: JSON.stringify({
            tool: 'ask_user_question',
            questions: [
                {
                    id: 'approval',
                    kind: 'approval',
                    header: 'Permission',
                    question: 'Allow write?',
                    preview: {
                        tool: 'workspace_write',
                        kind: 'write',
                        exists: false,
                        changed: true,
                        truncated: false,
                        error: '',
                        facts: [{ key: 'path', value: 'saved.txt' }],
                        diff: ['+kept line'],
                    },
                },
            ],
            answers: [{ id: 'approval', selected: ['Allow once'] }],
        }),
        meta: {},
    },
];
workspace._renderMessages([]);
const errorRow = workspace._dom.chat.querySelectorAll('.ai-error-text')[0];
const askedRow = workspace._dom.chat.querySelectorAll('.ai-question-text')[0];
const answeredRow = workspace._dom.chat.querySelectorAll('.ai-question-answered')[0];
out.storedEvidence = {
    error: errorRow ? String(errorRow.textContent) : '',
    asked: askedRow ? String(askedRow.textContent) : '',
    answered: answeredRow ? String(answeredRow.textContent) : '',
    approvalPath: String(workspace._dom.chat.innerHTML).includes('saved.txt'),
    approvalPreviews: workspace._dom.chat.querySelectorAll('.ai-approval-preview').length,
};

/* The folder picker must name the OTHER disks and offer the system dialog: walking down from one
   drive could never leave it (`dirname('C:\\')` is itself, so Up vanished at the root). */
workspace._folderState = {
    path: 'D:/work',
    parent: '',
    folder: '',
    roots: [
        { name: 'C:', path: 'C:/' },
        { name: 'D:', path: 'D:/' },
    ],
    entries: [{ name: 'data', path: 'D:/work/data', dir: true }],
};
workspace._renderFolder();
const rootButtons = workspace._dom.folderDialog.querySelectorAll('[data-ai-folder-root]');
const nativeButton = workspace._dom.folderDialog.querySelectorAll('[data-ai-folder-native]')[0];
const openedPaths = [];
workspace._openFolder = async (path) => openedPaths.push(path);
const pickedNative = [];
workspace._pickNativeFolder = async () => pickedNative.push('pick');
dispatchOn(workspace._dom.root, 'click', { target: rootButtons[1] });
dispatchOn(workspace._dom.root, 'click', { target: nativeButton });
out.folderPicker = {
    roots: rootButtons.map((el) => el.getAttribute('data-ai-folder-root')),
    native: !!nativeButton,
    opened: openedPaths,
    picked: pickedNative,
};

/* A local daemon's REAL model list replaces the one static name the bootstrap row carries, and a
   stored choice survives the refresh; an id the daemon no longer serves falls back to its first. */
const localProvider = {
    id: 'ollama',
    local_only: true,
    requires_key: false,
    capabilities: ['tools', 'thinking'],
    models: [{ id: 'qwen3.5:9b', label: 'qwen3.5:9b', capabilities: ['tools', 'thinking'] }],
};
workspace._bootstrap = { ok: true, providers: [localProvider], conversations: [] };
workspace._provider = 'ollama';
sandbox.AISettings.setModel('ollama', 'qwen3.5:4b');
sandbox.__routes['/models'] = {
    ok: true,
    models: [{ id: 'qwen3.5:4b' }, { id: 'qwen3.5:9b' }],
};
workspace._renderModelOptions = () => {};
workspace._renderToggles = () => {};
await workspace._refreshLocalModels();
out.localModels = {
    ids: (localProvider.models || []).map((row) => row.id),
    model: workspace._model,
};
sandbox.AISettings.setModel('ollama', 'gone:1b');
await workspace._refreshLocalModels();
out.localModels.missingFallsBackTo = workspace._model;

/* Two overlapping bootstraps, answered out of order: the OLDER answer must not write the picker.
   That race made the provider chip and the actual request disagree right after a switch. */
const pendingBootstraps = [];
const realFetch = sandbox.fetch;
sandbox.fetch = (url) =>
    new Promise((resolve) => {
        pendingBootstraps.push({
            url: String(url),
            resolve: () =>
                resolve({
                    ok: true,
                    json: () =>
                        Promise.resolve({
                            ok: true,
                            providers: [{ id: String(url).includes('provider=ollama') ? 'ollama' : 'deepseek' }],
                            settings: {},
                        }),
                }),
        });
    });
workspace._provider = 'deepseek';
const firstBoot = workspace._loadBootstrap();
workspace._provider = 'ollama';
const secondBoot = workspace._loadBootstrap();
pendingBootstraps[1].resolve();
await secondBoot;
pendingBootstraps[0].resolve();
await firstBoot;
sandbox.fetch = realFetch;
out.staleBootstrap = workspace._provider;

/* The server's 联网搜索 default is adopted ONLY when this browser never chose: a browser that
   clicked the switch off must not have it turned back on by the next refresh. */
sandbox.localStorage.setItem(sandbox.AISettings._key, '{}');
const browserSearchDefault = sandbox.AISettings.load().search;
const searchboot = {
    ok: true,
    providers: [{ id: 'ollama', local_only: true, models: [{ id: 'm' }] }],
    settings: { web_search_default: true, context_scope: 'full' },
};
sandbox.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve(searchboot) });
await workspace._loadBootstrap();
const adopted = sandbox.AISettings.load().search;
sandbox.AISettings.save({ search: false });
await workspace._loadBootstrap();
const kept = sandbox.AISettings.load().search;
sandbox.fetch = realFetch;
out.searchDefault = { browserDefault: browserSearchDefault, adopted: adopted, kept: kept };

/* ONE turn, TWO provider rounds (a tool call between them). The transcript must stay one assistant
   bubble with one skill row — the daemon answers each round as its own assistant row, and drawing
   each round separately made a single answer look like two answers on screen. */
workspace._messages = [];
workspace._conversationId = 'c-two';
workspace._current = null;
workspace._sending = true;
workspace._dom.chat.innerHTML = '';
workspace._streamConversation = '';
const rounds = [
    { type: 'meta', conversation_id: 'c-two', message_id: 'm1', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' },
    { type: 'thinking', text: '先看看文件夹。' },
    { type: 'tool_start', id: 'call_1', name: 'workspace_list', arguments: {} },
    { type: 'tool_result', id: 'call_1', name: 'workspace_list', ok: true, result: { entries: [] } },
    { type: 'meta', conversation_id: 'c-two', message_id: 'm2', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' },
    { type: 'thinking', text: '再回答。' },
    { type: 'text', text: '只有一个 notes.txt。' },
    { type: 'usage', usage: { prompt_tokens: 10, completion_tokens: 5 } },
    { type: 'done', stop_reason: 'end_turn' },
];
for (const event of rounds) workspace._onEvent(event);
out.twoRounds = {
    bubbles: workspace._dom.chat.querySelectorAll('.ai-message.assistant').length,
    skills: workspace._dom.chat.querySelectorAll('.ai-skill-row').length,
    tools: workspace._dom.chat.querySelectorAll('.ai-tool').length,
    text: String(workspace._dom.chat.textContent || ''),
};

/* The transcript the user was reading reopens after a reload: the id is browser-local, the rows
   stay on the server. Without this a refresh opened a NEW empty chat. */
sandbox.AISettings.save({ conversation: 'c-saved' });
workspace._conversationId = '';
out.restoreConversation = workspace._restoreConversation();
workspace._rememberConversation('');
out.clearedAfterNewChat = sandbox.AISettings.load().conversation;

/* An answer box on a question card takes `@` too: the menu opens for THAT box, the pick becomes a
   chip in the card, and the answer carries the reference to the server. */
workspace._messages = [];
workspace._conversationId = 'c-q';
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._appendQuestion({
    id: 'q1',
    message_id: 'm1',
    questions: [{ id: 'q1', header: 'Scope', question: 'Which data?', options: [{ label: 'A' }] }],
});
const answerBox = workspace._dom.chat.querySelector('textarea[data-ai-custom]');
answerBox.value = '用这个 @';
workspace._onRefInput({ target: answerBox });
const refTargetOk = workspace._refTarget === answerBox;
workspace._refResults = [{ kind: 'dataset', id: 'd1', label: 'Corpus' }];
workspace._refIndex = 0;
workspace._renderRefMenu();
workspace._pickRef('dataset', 'd1', 'Corpus');
const answerRefsHost = workspace._dom.chat.querySelector('[data-ai-question-refs]');
const answerChips = (answerRefsHost ? answerRefsHost.querySelectorAll('.ai-ref-label') : []).map((el) =>
    String(el.textContent || '')
);
let sentAnswer = null;
const realMaybeAnswer = workspace._maybeAnswer;
workspace._maybeAnswer = async () => {
    sentAnswer = workspace._current.answers.q1;
};
workspace._answerCustom('q1', answerBox.value);
workspace._maybeAnswer = realMaybeAnswer;
out.answerRefs = {
    targetOk: refTargetOk,
    chips: answerChips,
    custom: sentAnswer && sentAnswer.custom,
    refs: (sentAnswer && sentAnswer.references) || [],
};

/* A restored pending card has no live message element. The answer request must still carry the
   assistant row that asked it, or /api/ai/answer 404s with "找不到消息：". */
workspace._messages = [];
workspace._conversationId = 'c-restored';
workspace._current = null;
workspace._dom.chat.innerHTML = '';
workspace._streamConversation = '';
workspace._appendQuestion({
    id: 'q2',
    message_id: 'm-restored',
    questions: [{ id: 'q2', header: 'Scope', question: 'Which data?', options: [{ label: 'A' }] }],
});
let restoredPayload = null;
workspace._stream = async (url, payload) => {
    restoredPayload = { url, payload };
};
workspace._current.answers.q2 = { id: 'q2', selected: ['A'] };
await workspace._maybeAnswer();
out.restoredQuestion = {
    messageId: workspace._current.messageId,
    sentMessageId: restoredPayload && restoredPayload.payload.message_id,
    sentQuestionId: restoredPayload && restoredPayload.payload.question_id,
};

/* Multi-select: each click updates the answer set; the card's own answer button submits it. */
workspace._current = null;
workspace._dom.chat.innerHTML = '';
workspace._appendQuestion({
    id: 'q3',
    message_id: 'm-multi',
    questions: [
        {
            id: 'q3',
            header: 'Pick',
            question: 'Which ones?',
            multi_select: true,
            options: [{ label: 'A' }, { label: 'B' }],
        },
    ],
});
workspace._answerOption('q3', 'A');
workspace._answerOption('q3', 'B');
out.multiSelect = {
    selected: (workspace._current.answers.q3 && workspace._current.answers.q3.selected) || [],
};

/* A disclosure the reader opened survives the streaming repaint. The live turn used to rebuild the
   block stream on every delta, so an opened thinking block or tool result closed itself. */
workspace._messages = [];
workspace._conversationId = 'c-open';
workspace._current = null;
workspace._openDetails.clear();
workspace._dom.chat.innerHTML = '';
workspace._streamConversation = '';
workspace._sending = true;
for (const event of [
    { type: 'meta', conversation_id: 'c-open', message_id: 'm1', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' },
    { type: 'thinking', text: '先看看。' },
    { type: 'tool_start', id: 'call_9', name: 'workspace_list', arguments: {} },
    { type: 'tool_result', id: 'call_9', name: 'workspace_list', ok: true, result: { entries: [] } },
]) {
    workspace._onEvent(event);
}
workspace._paintAssistant();
const thinkingRow = workspace._dom.chat.querySelector('details.ai-thinking');
const toolDetail = workspace._dom.chat.querySelector('details.ai-tool-detail');
thinkingRow.open = true;
dispatchOn(workspace._dom.root, 'toggle', { target: thinkingRow });
toolDetail.open = true;
dispatchOn(workspace._dom.root, 'toggle', { target: toolDetail });
workspace._onEvent({ type: 'text', text: '继续写答案。' });
workspace._paintAssistant();
const thinkingAfter = workspace._dom.chat.querySelector('details.ai-thinking');
const toolAfter = workspace._dom.chat.querySelector('details.ai-tool-detail');
out.openDetails = {
    thinking: !!thinkingAfter && thinkingAfter.open === true,
    tool: !!toolAfter && toolAfter.open === true,
};
/* Nothing changed since the last paint: the DOM must be left alone (same node), not rebuilt. */
const before = workspace._dom.chat.querySelector('details.ai-thinking');
workspace._paintAssistant();
out.openDetails.sameNode = workspace._dom.chat.querySelector('details.ai-thinking') === before;

/* A stored tool row whose call was ALREADY drawn inside the assistant bubble must not paint a
   second, detached card — that was the misaligned box above every "AI" label. */
workspace._messages = [
    {
        role: 'assistant',
        blocks: [
            { type: 'thinking', thinking: '先跑命令。' },
            { type: 'tool_use', id: 'call_x', name: 'run_cmd', input: { command: 'ls' }, status: 'done', result: { ok: true } },
        ],
        usage: {},
    },
    {
        role: 'tool',
        content: JSON.stringify({ ok: true }),
        meta: { tool_call_id: 'call_x', name: 'run_cmd' },
    },
];
workspace._renderMessages([]);
const inlineCards = workspace._dom.chat.querySelectorAll('.ai-tool');
out.storedToolRow = {
    cards: inlineCards.length,
    insideBubble: inlineCards.length === 1 && !!inlineCards[0].closest('.ai-message-body'),
};

/* The SAME turn as `twoRounds`, but read back from the store: two assistant rows (one per provider
   round) + the tool row between them. It must draw ONE bubble, exactly like the live view — a row
   per bubble is what made the finished transcript look nothing like the streaming one. */
workspace._messages = [
    { id: 'u1', role: 'user', content: '列一下', meta: {} },
    {
        id: 'a1',
        role: 'assistant',
        blocks: [
            { type: 'skill', name: 'workflow', reason: 'auto' },
            { type: 'thinking', thinking: '先看看。' },
            { type: 'tool_use', id: 'call_r', name: 'workspace_list', input: {}, status: 'done', result: { entries: [] } },
        ],
        meta: { turn_id: 't-two' },
        usage: { prompt_tokens: 10, completion_tokens: 2 },
    },
    { role: 'tool', content: JSON.stringify({ entries: [] }), meta: { turn_id: 't-two', tool_call_id: 'call_r', name: 'workspace_list' } },
    {
        id: 'a2',
        role: 'assistant',
        blocks: [{ type: 'thinking', thinking: '再回答。' }, { type: 'text', text: '只有一个 notes.txt。' }],
        meta: { turn_id: 't-two' },
        usage: { prompt_tokens: 20, completion_tokens: 6 },
    },
];
workspace._renderMessages([]);
out.storedTwoRounds = {
    bubbles: workspace._dom.chat.querySelectorAll('.ai-message.assistant').length,
    skills: workspace._dom.chat.querySelectorAll('.ai-skill-row').length,
    tools: workspace._dom.chat.querySelectorAll('.ai-tool').length,
    detached: workspace._dom.chat.querySelectorAll('.ai-message-tool').length,
    /* The tool RESULT lives in its own stored row; the card must get it back, or it has no
       `<details>` and a finished card can never be opened after a reload. */
    details: workspace._dom.chat.querySelectorAll('details.ai-tool-detail').length,
};

/* Which model answered a saved conversation, and this session's numbers (tokens, cache hit rate,
   estimated money, balance). Both are the server's facts; the panel only words them. */
workspace._bootstrap.conversations = [
    { id: 'c-model', title: 'Old chat', message_count: 3, provider: 'deepseek', model: 'deepseek-v4-pro' },
];
workspace._renderSessions();
const modelRow = workspace._dom.sessions.querySelector('.ai-session-model');
workspace._balance = {
    supported: true,
    available: true,
    currency: 'CNY',
    balances: [{ currency: 'CNY', total: 110.25, granted: 10, topped_up: 100.25 }],
};
workspace._convoUsage = {
    prompt_tokens: 1000,
    completion_tokens: 100,
    total_tokens: 1100,
    cache_hit_rate: 0.8,
    cost: 0.00062,
    currency: 'CNY',
    cost_complete: true,
    models: [{ provider: 'deepseek', model: 'deepseek-flash', prompt_tokens: 1000 }],
};
workspace._renderSide();
const spendNumbers = workspace._dom.side.querySelectorAll('b').map((el) => String(el.textContent || ''));
out.spend = {
    sessionModel: modelRow ? String(modelRow.textContent) : '',
    numbers: spendNumbers,
};

/* The pin: while it is on, a press outside the dock must NOT close it; off is the old behaviour. */
workspace._pinned = true;
workspace._renderPin();
workspace._open = true;
workspace._onOutsidePress({ target: { closest: () => null } });
const pinnedStayedOpen = workspace._open === true;
const pinPressed = workspace._dom.pinBtn ? workspace._dom.pinBtn.getAttribute('aria-pressed') : '';
workspace._pinned = false;
workspace._renderPin();
workspace._onOutsidePress({ target: workspace._dom.chat });
out.pin = {
    pinnedStayedOpen: pinnedStayedOpen,
    ariaPressed: pinPressed,
    unpinnedClosed: workspace._open === false,
};

/* A running command card carries a live seconds counter; the counter disappears with its result. */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._sending = true;
workspace._onEvent({ type: 'meta', conversation_id: 'c-clock', message_id: 'm1', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' });
workspace._onEvent({ type: 'tool_start', id: 'call_c', name: 'run_cmd', arguments: { command: 'py x.py' } });
workspace._paintAssistant();
const runningClocks = workspace._dom.chat.querySelectorAll('.ai-tool-clock').length;
workspace._onEvent({ type: 'tool_result', id: 'call_c', name: 'run_cmd', ok: true, result: { ok: true } });
workspace._paintAssistant();
out.toolClock = { running: runningClocks, after: workspace._dom.chat.querySelectorAll('.ai-tool-clock').length };

/* The live line: while a turn is open the transcript says so, ALWAYS — including under a finished
   paragraph and during a silent minute. It used to be painted only when the last block was not
   text, so a paragraph followed by the model composing a tool call looked like a complete answer,
   and the tool clock that was supposed to prove life was written but never started. Deterministic
   clock: the wording is the phase, the number is the proof. */
const realNow = sandbox.Date.now;
const realSetInterval = sandbox.setInterval;
let clock = 1800000000000;
sandbox.Date.now = () => clock;
const ticks = [];
sandbox.setInterval = (fn) => {
    ticks.push(fn);
    return 1;
};
const tick = () => ticks.forEach((fn) => fn());
const statusText = () => String((workspace._dom.chat.querySelector('.ai-status-text') || {}).textContent || '');
const statusClock = () => String((workspace._dom.chat.querySelector('.ai-status-clock') || {}).textContent || '');
const statusHidden = () => {
    const node = workspace._dom.chat.querySelector('.ai-status');
    return node ? node.hidden === true : true;
};
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._conversationId = '';
workspace._sending = false;
workspace._stopClock();
workspace._beginTurn();
workspace._sending = true;
workspace._setSending(true);
workspace._onEvent({ type: 'meta', conversation_id: 'c-live', message_id: 'm1', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' });
workspace._onEvent({ type: 'text', text: '先看数据。' });
/* 42 s later, the provider has said nothing since the paragraph: the CLOCK (not an event) has to
   keep the line alive, and the line has to say which silence this is. */
clock += 42000;
workspace._lastEventAt = clock - 3000;
tick();
const liveAfterText = {
    visible: statusHidden() === false,
    text: statusText(),
    clock: statusClock(),
    ticks: ticks.length,
};
workspace._lastEventAt = clock - 40000;
tick();
const liveStalled = statusText();
workspace._onEvent({ type: 'tool_start', id: 'call_live', name: 'run_cmd', arguments: { command: 'py x.py' } });
workspace._paintAssistant();
clock += 65000;
tick();
const liveWaitingApp = statusText();
const toolClockText = String((workspace._dom.chat.querySelector('.ai-tool-clock') || {}).textContent || '');
workspace._onEvent({ type: 'done', stop_reason: 'end_turn' });
const i18n = (key, seconds = 42) => {
    const vars = seconds === undefined ? '' : `, { seconds: ${Number(seconds)} }`;
    return String(vm.runInContext(`I18n.t(${JSON.stringify(key)}${vars})`, sandbox));
};
out.liveLine = {
    afterText: liveAfterText,
    stalled: liveStalled,
    waitingApp: liveWaitingApp,
    toolClock: toolClockText,
    hiddenAfterDone: statusHidden(),
    expected: {
        generating: i18n('ai.working'),
        stalled: i18n('ai.stillWaiting'),
        waitingApp: i18n('ai.waiting'),
        clock: i18n('ai.elapsed', 42),
    },
};

/* A stream that closes without its ending event is a CUT, and the bubble says so once. */
workspace._turnEnded = false;
workspace._noteCutStream();
const cutNotes = () =>
    workspace._dom.chat.querySelectorAll('.ai-note').map((el) => String(el.textContent || ''));
const cutOnce = cutNotes();
workspace._noteCutStream();
out.cutStream = {
    notes: cutOnce,
    again: cutNotes().length,
    expected: String(vm.runInContext("I18n.t('ai.streamLost')", sandbox)),
};
sandbox.Date.now = realNow;
sandbox.setInterval = realSetInterval;

/* A reopened transcript whose last row never reached its ending names the fact — which one it is
   matters: `streaming` may still be running in another page, `interrupted` is the server's verdict. */
workspace._messages = [
    { id: 'u1', role: 'user', content: 'hello', meta: {}, status: 'done' },
    { id: 'a1', role: 'assistant', content: 'half', blocks: [{ type: 'text', text: 'half an answer' }], meta: { turn_id: 't9' }, status: 'interrupted', usage: {} },
    { id: 'u2', role: 'user', content: 'again', meta: {}, status: 'done' },
    { id: 'a2', role: 'assistant', content: 'live', blocks: [{ type: 'text', text: 'still going' }], meta: { turn_id: 't10' }, status: 'streaming', usage: {} },
];
workspace._renderMessages([]);
out.reloadNotes = {
    notes: workspace._dom.chat.querySelectorAll('.ai-note').map((el) => String(el.textContent || '')),
    expected: {
        interrupted: String(vm.runInContext("I18n.t('ai.interrupted')", sandbox)),
        live: String(vm.runInContext("I18n.t('ai.stillStreaming')", sandbox)),
    },
};

/* Switching conversations while an answer streams must not paint the rest of it into the NEW
   transcript (the dock stays usable, so this is reachable by one click), and the same events must
   still paint in the conversation that owns them. */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._streamConversation = 'c-a';
workspace._conversationId = 'c-b';
workspace._sending = true;
workspace._onEvent({ type: 'text', text: 'answer of the conversation you left' });
const droppedInOther = workspace._dom.chat.querySelectorAll('.ai-message').length;
workspace._sending = false;
workspace._setSending(false);
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._streamConversation = 'c-b';
workspace._conversationId = 'c-b';
workspace._sending = true;
workspace._onEvent({ type: 'meta', conversation_id: 'c-b', message_id: 'm9', turn_id: 't9', run_id: 'r9', skill: 'auto', skill_reason: 'auto' });
workspace._onEvent({ type: 'text', text: 'its own answer' });
const paintedInOwner = workspace._dom.chat.querySelectorAll('.ai-message.assistant').length;
workspace._sending = false;
workspace._setSending(false);
out.switchGuard = { dropped: droppedInOther, painted: paintedInOwner };

/* Local-only is a guard, not a preference: with it on, a paid provider is refused before any
   request leaves the page (this is the switch that makes "测试只用本地免费模型" enforceable). */
sandbox.AISettings.save({ localOnly: true, provider: 'deepseek' });
workspace._provider = 'deepseek';
workspace._sending = false;
workspace._bootstrap.providers = [
    { id: 'deepseek', requires_key: true, local_only: false, models: [{ id: 'deepseek-flash' }] },
    { id: 'ollama', requires_key: false, local_only: true, models: [{ id: 'qwen3.5:4b' }] },
];
const blockedToasts = [];
const realToast = workspace._toast;
workspace._toast = (message) => blockedToasts.push(String(message));
const blocked = await workspace._sendText('hello', {});
workspace._toast = realToast;
sandbox.AISettings.save({ localOnly: false });
out.localOnly = {
    refused: blocked === false,
    toast: blockedToasts.length ? blockedToasts[blockedToasts.length - 1] : '',
};

/* Clicking a FINISHED tool card's own row opens its result, and the skill row's detail loads when
   its summary is clicked (that branch was unreachable: `data-ai-skill` was missing from the
   delegated selector, so no click ever reached it). */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._sending = false;
workspace._onEvent({ type: 'meta', conversation_id: 'c-click', message_id: 'm1', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' });
workspace._onEvent({ type: 'tool_start', id: 'call_d', name: 'run_cmd', arguments: { command: 'py x.py' } });
workspace._onEvent({ type: 'tool_result', id: 'call_d', name: 'run_cmd', ok: true, result: { ok: true } });
workspace._paintAssistant();
const toolCard = workspace._dom.chat.querySelector('.ai-tool');
const toolRow = workspace._dom.chat.querySelector('.ai-tool-name');
dispatchOn(workspace._dom.root, 'click', { target: toolRow });
const clickedDetail = workspace._dom.chat.querySelector('details.ai-tool-detail');
const skillRow = workspace._dom.chat.querySelector('details.ai-skill-row');
const skillSummary = skillRow ? skillRow.querySelector('summary') : null;
let skillLoads = 0;
workspace._loadSkillDetail = async () => {
    skillLoads += 1;
};
dispatchOn(workspace._dom.root, 'click', { target: skillSummary });
out.clicks = {
    toolOpened: !!clickedDetail && clickedDetail.open === true,
    skillLoads: skillLoads,
};


/* A plan/chart artifact must be actionable too: its button hands the proposal back to the assistant.
   Only workflow drafts had a button, so every other card looked dead. */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._artifactsById = {};
workspace._sending = false;
workspace._onEvent({
    type: 'artifact',
    artifact: { id: 'art_plan', kind: 'analysis_plan', title: '执行计划 (S0-S7)', payload: { steps: [] } },
});
const planButton = workspace._dom.chat.querySelector('[data-ai-implement-artifact]');
let implementAsk = '';
workspace._sendText = async (text) => {
    implementAsk = String(text || '');
    return true;
};
dispatchOn(workspace._dom.root, 'click', { target: planButton });
out.artifactAction = {
    hasButton: !!planButton,
    asked: implementAsk.includes('执行计划 (S0-S7)'),
};


/* A three-question card submits only when all three are answered, so the FIRST click must show that
   it registered: the chosen option is marked and the card says how many are still missing. */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._sending = false;
workspace._appendQuestion({
    id: 'q3',
    message_id: 'm3',
    questions: [
        { id: 'model', header: 'Model', question: 'Which model?', options: [{ label: 'A' }, { label: 'B' }] },
        { id: 'data', header: 'Data', question: 'Which data?', options: [{ label: 'C' }, { label: 'D' }] },
        { id: 'task', header: 'Task', question: 'Which task?', options: [{ label: 'E' }] },
    ],
});
let submitted = 0;
workspace._maybeAnswer = async () => {
    submitted += 1;
};
/* The stub's selector engine has no descendant combinators: find the card, then its options. */
const card = workspace._dom.chat.querySelector('[data-ai-question-card="model"]');
const firstOption = card ? card.querySelector('[data-ai-answer]') : null;
dispatchOn(workspace._dom.root, 'click', { target: firstOption });
const hint = card ? card.querySelector('.ai-question-pending') : null;
out.answerClick = {
    selected: !!firstOption && firstOption.classList.contains('selected'),
    hint: hint ? String(hint.textContent) : '',
    submitted: submitted,
};


/* Local turns never think: qwen3.5 thinks by default, which doubles a local turn's wall time and
   leaks a trace the workspace does not show. The switch is disabled, not merely off. A paid
   provider keeps its own (on-by-default) choice. */
sandbox.AISettings.save({ thinkingLocal: true, thinking: true });
workspace._bootstrap.providers = [
    { id: 'ollama', local_only: true, requires_key: false, capabilities: ['thinking'], models: [{ id: 'qwen3.5:4b' }] },
    { id: 'deepseek', local_only: false, requires_key: true, capabilities: ['thinking'], models: [{ id: 'deepseek-flash' }] },
];
workspace._provider = 'ollama';
const localDefault = workspace._thinkingOn();
workspace._renderToggles();
const localDisabled = !!workspace._dom.thinking && workspace._dom.thinking.disabled;
workspace.toggleThinking();
const localOn = workspace._thinkingOn();
workspace._provider = 'deepseek';
const paidDefault = workspace._thinkingOn();
sandbox.AISettings.save({ thinkingLocal: false });
out.thinking = {
    localDefault: localDefault,
    localOn: localOn,
    localDisabled: localDisabled,
    paidDefault: paidDefault,
};

/* A URL with a query string must be escaped exactly once. The old inline() escaped the whole
   string first and then escaped the captured URL again: `&` became `&amp;amp;` and the browser
   opened `?a=1&amp;b=2`. */
out.markdownLink = sandbox.AIRender.inline('[知乎](https://www.zhihu.com/search?q=爬虫&type=content)');


/* A stored `present_artifact` row must still draw its artifact card (the reloaded transcript used to
   show only the tool card, so the plan looked like it had never been produced). */
workspace._messages = [
    {
        id: 'a_art',
        role: 'assistant',
        blocks: [
            { type: 'skill', name: 'workflow', reason: 'auto' },
            { type: 'tool_use', id: 'call_art', name: 'present_artifact', input: { title: '方案' }, status: 'done' },
        ],
        meta: { turn_id: 't_art' },
        usage: {},
    },
    {
        role: 'tool',
        content: JSON.stringify({ ok: true, artifact: { id: 'art_1', title: '方案', kind: 'analysis_plan', payload: {} } }),
        meta: { turn_id: 't_art', tool_call_id: 'call_art', name: 'present_artifact' },
    },
];
workspace._renderMessages([]);
/* The stub has no descendant combinators: find the extras host, then its card. */
const extrasHost = workspace._dom.chat.querySelector('.ai-extras');
out.storedArtifact = {
    cards: workspace._dom.chat.querySelectorAll('.ai-artifact').length,
    inExtras: !!(extrasHost && extrasHost.querySelector('.ai-artifact')),
};

/* A running present_artifact must say what it is doing, not “读取中…”. */
out.runningLabel = sandbox.AIRender.toolCard('present_artifact', {}, 'running', null, { id: 'c9' });


/* The jump button is a compact pill ABOVE the composer, and its anchor follows the composer's real
   height (a 26px circle holding the sentence “回到最新消息” wrapped into a vertical stack that sat
   on the composer's own buttons). */
/* The panel's own markup is not parsed by the stub, so the composer is built here; the button's
   MARKUP (glyph + labels) is asserted against index.html in the python test. */
const composerEl = sandbox.document.createElement('footer');
composerEl.className = 'ai-composer';
workspace._dom.root.appendChild(composerEl);
workspace._syncComposerHeight();
out.jumpButton = {
    composerVar: String(workspace._dom.root.style.getPropertyValue('--ai-composer-h') || ''),
};


/* Every tool family says what it does while it runs, and a stopped turn says it stopped. */
const labelOf = (name) => {
    const html = sandbox.AIRender.toolCard(name, {}, 'running', null, { id: 'x' + name });
    const m = /<span class="ai-tool-state">([^<]*)</.exec(html);
    return m ? m[1].replace(/\s+/g, ' ').trim() : '';
};
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._sending = true;
workspace._onEvent({ type: 'meta', conversation_id: 'c-stop', message_id: 'm1', turn_id: 't1', run_id: 'r1', skill: 'workflow', skill_reason: 'auto' });
await workspace.stop();
out.guidance = {
    read: labelOf('workspace_read'),
    peek: labelOf('dataset_peek'),
    plan: labelOf('update_plan'),
    unknown: labelOf('plugin_tool_x'),
    stoppedNote: workspace._dom.chat.querySelectorAll('.ai-note').length,
    stoppedText: String((workspace._dom.chat.querySelector('.ai-note') || {}).textContent || ''),
};

/* The same stop can arrive twice: the server answers the aborted stream with `done`+cancelled while
   the stop button's own call is still in flight. One sentence, not two. */
workspace._onEvent({ type: 'done', stop_reason: 'cancelled' });
await workspace.stop();
out.stopDedupe = workspace._dom.chat.querySelectorAll('.ai-note').length;

/* A turn the PROVIDER ended at `max_tokens` was painted as a finished answer: the sentence stopped
   mid-way and nothing said why. It is a quiet note, not an error — live and after a reload. */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
/* Every block here is its own turn: a closed turn owns no conversation, and a `meta` event adopts
   one. Without this the ownership check silently dropped the next scenario's events. */
workspace._streamConversation = '';
workspace._sending = true;
workspace._onEvent({ type: 'meta', conversation_id: 'c-cut', message_id: 'm2', turn_id: 't-cut', run_id: 'r2', skill: 'workflow', skill_reason: 'auto' });
workspace._onEvent({ type: 'text', text: '这是一段被截断的回答' });
workspace._onEvent({ type: 'done', stop_reason: 'max_tokens' });
const cutNote = workspace._dom.chat.querySelector('.ai-note');
workspace._messages = [
    { id: 'u2', role: 'user', content: '写长一点', meta: {} },
    {
        id: 'a3',
        role: 'assistant',
        blocks: [{ type: 'text', text: '这是一段被截断的回答' }],
        meta: { turn_id: 't-cut', stop_reason: 'max_tokens' },
    },
];
workspace._current = null;
workspace._renderMessages([]);
const storedCut = workspace._dom.chat.querySelector('.ai-note');
out.truncation = {
    live: String((cutNote || {}).textContent || ''),
    stored: String((storedCut || {}).textContent || ''),
};

/* The turn's LAST stored row carries the verdict: a round cut at `max_tokens` and then recovered is
   NOT a truncated answer, and the reverse is. Taking the first row's meta would tell the user their
   finished answer was cut, or hide a real cut behind a recovered round. */
workspace._messages = [
    { id: 'u5', role: 'user', content: '两轮', meta: {} },
    { id: 'a5', role: 'assistant', blocks: [{ type: 'text', text: '第一轮被截断' }], meta: { turn_id: 't-two', stop_reason: 'max_tokens' }, status: 'done' },
    { id: 'a6', role: 'assistant', blocks: [{ type: 'text', text: '第二轮写完了' }], meta: { turn_id: 't-two', stop_reason: 'end_turn' }, status: 'done' },
];
workspace._current = null;
workspace._renderMessages([]);
const recoveredNotes = workspace._dom.chat.querySelectorAll('.ai-note').length;
workspace._messages = [
    { id: 'u6', role: 'user', content: '反过来', meta: {} },
    { id: 'a7', role: 'assistant', blocks: [{ type: 'text', text: '第一轮写完' }], meta: { turn_id: 't-two-b', stop_reason: 'end_turn' }, status: 'done' },
    { id: 'a8', role: 'assistant', blocks: [{ type: 'text', text: '第二轮被截断' }], meta: { turn_id: 't-two-b', stop_reason: 'max_tokens' }, status: 'done' },
];
workspace._current = null;
workspace._renderMessages([]);
const cutLastNotes = workspace._dom.chat.querySelectorAll('.ai-note').length;
out.turnVerdict = { recovered: recoveredNotes, cutLast: cutLastNotes };

/* What the context inspector says was NOT sent: a budget cut the model could have used, and the
   replay cap that keeps a turn's block bounded. Silence there reads as "it saw everything". */
workspace._contextMeta = {
    scope: 'summary',
    tokens: 10,
    chars: 20,
    items: [{ title: '项目事实', chars: 20 }],
    omitted: ['运行'],
    replay_truncated: true,
    replay_chars: 16000,
    history: { window: 32768, budget: 20000, dropped: 4, kept: 12 },
    memories: { total: 25, shown: 20, omitted: 5 },
};
workspace._renderSide();
out.contextNotes = String(workspace._dom.side.innerHTML || '');
/* The words the assertions should look for, resolved from the catalogue rather than copied out of
   it: a reworded sentence must not fail a test that is really about "the inspector said it". */
out.contextWords = {
    omitted: String(vm.runInContext("I18n.t('ai.contextOmitted', { items: '运行' })", sandbox)),
    replay: String(vm.runInContext("I18n.t('ai.contextReplayCut', { n: 16000 })", sandbox)),
    history: String(vm.runInContext("I18n.t('ai.contextHistoryCut', { n: 4, window: 32768 })", sandbox)),
    memories: String(vm.runInContext("I18n.t('ai.contextMemoryCut', { n: 5, shown: 20 })", sandbox)),
};

/* A STOPPED turn came back from the store as a red error line, because stop wrote status='error'.
   It is the same kind of fact as a truncated answer: a quiet note. */
workspace._messages = [
    { id: 'u3', role: 'user', content: '写长一点', meta: {} },
    {
        id: 'a4',
        role: 'assistant',
        blocks: [{ type: 'text', text: '写到一半就停了' }],
        meta: { turn_id: 't-stop', stop_reason: 'cancelled', stopped: true },
    },
];
workspace._current = null;
workspace._renderMessages([]);
const stopNote = workspace._dom.chat.querySelector('.ai-note');
out.storedStop = {
    note: String((stopNote || {}).textContent || ''),
    errors: workspace._dom.chat.querySelectorAll('.ai-error-text').length,
    text: String(workspace._dom.chat.textContent || ''),
};

/* The composer stays usable while a turn runs: a disabled input threw the caret away and made the
   next message impossible to draft. */
workspace._setSending(true);
out.sendingInput = { disabled: workspace._dom.input.disabled === true };
workspace._setSending(false);

/* A control outside the workspace asks about a run: the entry opens a NEW chat, attaches the id as
   manual context and prefills the question without sending it. A panel must not have to know how
   the workspace stores a conversation or builds its context. */
const openedWith = [];
const realOpen = workspace.open;
const realNewChat = workspace.newChat;
const realRenderContextBar = workspace._renderContextBar;
workspace.open = (opts) => openedWith.push(opts);
let freshChats = 0;
workspace.newChat = async () => {
    freshChats += 1;
};
workspace._renderContextBar = () => {};
sandbox.AIContext.setManual({ dataset_id: '', run_id: '' });
workspace._dom.input.value = '';
await workspace.askAbout({ run_id: 'run-42', prompt: 'explain run-42' });
out.askAbout = {
    contexts: openedWith,
    fresh: freshChats,
    runId: sandbox.AIContext.manual.run_id,
    prompt: String(workspace._dom.input.value),
};
workspace.open = realOpen;
workspace.newChat = realNewChat;
workspace._renderContextBar = realRenderContextBar;

/* The inspector must SAY when secrets were scrubbed. The server reports only counts by source —
   never the matched value — and the panel sums them into one visible, localized sentence. */
workspace._contextMeta = { scope: 'summary', items: [], redacted: { '引用': 2, '项目事实': 1 } };
workspace._renderSide();
const redactedWord = vm.runInContext("I18n.t('ai.contextRedacted', { n: 3 })", sandbox);
const sideHtml = String(workspace._dom.side.innerHTML || '');
const withRedaction = sideHtml.includes(redactedWord);
workspace._contextMeta = { scope: 'summary', items: [] };
workspace._renderSide();
const withoutRedaction = String(workspace._dom.side.innerHTML || '').includes(redactedWord);
out.redactionNote = {
    shown: withRedaction,
    hidden: !withoutRedaction,
    total: redactedWord.includes('3'),
    noSecretValue: !sideHtml.includes('sk-'),
};

/* An artifact's preview door is additive to its primary apply button: it asks the server what the
   apply would change, lets the user tick the parts, and merges ONLY the selected nodes into the
   live canvas through the same apply path. The server owns the shape and the legality. */
const previewArtifact = {
    id: 'preview_art',
    kind: 'workflow_draft',
    title: 'Proposed canvas',
    payload: {
        nodes: [
            { id: 'n1', type: 'name', params: { workflow_name: 'draft' } },
            { id: 'n2', type: 'analysis', params: { operation: 'topic_label' } },
        ],
        connections: [
            { from: 'n1', to: 'n2' },
            { from: 'n2', to: 'n3' },
        ],
    },
};
const savedCurrent = workspace._current;
workspace._current = { artifacts: [previewArtifact] };
const previewHolder = sandbox.document.createElement('div');
previewHolder.innerHTML = sandbox.AIRender.artifactCard(previewArtifact);
const previewButton = previewHolder.querySelector('[data-ai-preview-artifact]');

const realPreview = workspace._previewArtifact;
const previewClicks = [];
workspace._previewArtifact = async (id) => previewClicks.push(id);
if (previewButton) dispatchOn(workspace._dom.root, 'click', { target: previewButton });
workspace._previewArtifact = realPreview;

const previewRequests = [];
const realFetchPreview = sandbox.fetch;
sandbox.fetch = async (url, options) => {
    previewRequests.push({ url, body: JSON.parse(String(options.body || '{}')) });
    return {
        json: async () => ({
            ok: true,
            preview: {
                kind: 'workflow_draft',
                title: 'Changes',
                summary: '2 nodes',
                items: [
                    { id: 'n1', label: 'overwrite n1', detail: 'name', action: 'change', selectable: true, checked: true },
                    { id: 'n2', label: 'add n2', detail: 'analysis', action: 'add', selectable: true, checked: true },
                ],
                warnings: [],
                selectable: true,
            },
        }),
    };
};
const dialogOpts = [];
const realShowDialog = sandbox.showDialog;
sandbox.showDialog = async (opts) => {
    dialogOpts.push(opts);
    // Uncheck the overwrite; keep only the new node.
    return { value: 'apply', toggles: { 'ai-preview-0': false, 'ai-preview-1': true } };
};
const applied = [];
const realApplyWorkflow = workspace._applyWorkflowPayload;
workspace._applyWorkflowPayload = async (payload, run, title) => applied.push({ payload, run, title });
/* The real serializeDraft() inherits getState(), whose nodes are KEYED BY ID. An array stub here
   hid the mismatch that made a one-tick preview apply replace the whole canvas. */
sandbox.canvas = {
    serializeDraft: () => ({
        nodes: { n1: { id: 'n1', type: 'name', params: { workflow_name: 'current' } } },
        connections: [],
    }),
};

await workspace._previewArtifact('preview_art');

workspace._current = savedCurrent;
sandbox.canvas = undefined;
sandbox.fetch = realFetchPreview;
sandbox.showDialog = realShowDialog;
workspace._applyWorkflowPayload = realApplyWorkflow;
out.artifactPreview = {
    button: !!previewButton,
    clicked: previewClicks.includes('preview_art'),
    request: previewRequests[0] || null,
    toggles: dialogOpts[0] ? dialogOpts[0].toggles.map((item) => item.id) : [],
    applied: applied.length === 1 ? applied[0] : null,
};

/* The manual monitor builder: the sidebar's new-monitor button fetches the SERVER's name catalog,
   opens one dialog, and arms through the SAME endpoint the artifact card uses. No second event
   table in this file. */
workspace._renderSide();
const newMonitorButton = workspace._dom.side.querySelector('[data-ai-monitor-new]');
const realNewMonitor = workspace._newMonitor;
let newMonitorClicks = 0;
workspace._newMonitor = async () => {
    newMonitorClicks += 1;
};
if (newMonitorButton) dispatchOn(workspace._dom.root, 'click', { target: newMonitorButton });
workspace._newMonitor = realNewMonitor;

const monitorRequests = [];
const realFetchMonitor = sandbox.fetch;
sandbox.fetch = async (url, options) => {
    monitorRequests.push({
        url: String(url),
        body: options && options.body ? JSON.parse(String(options.body)) : null,
    });
    if (String(url).indexOf('/api/ai/monitors/catalog') >= 0) {
        return {
            json: async () => ({
                ok: true,
                catalog: {
                    events: ['run.started', 'run.finished'],
                    statuses: ['failed', 'partial'],
                    outcomes: ['completed'],
                },
            }),
        };
    }
    return { json: async () => ({ ok: true, monitor: { id: 'mon_new', spec: {}, auto_analyze: true } }) };
};
const monitorDialogs = [];
const realShowDialogMonitor = sandbox.showDialog;
sandbox.showDialog = async (opts) => {
    monitorDialogs.push(opts);
    return {
        value: 'create',
        fields: {
            'ai-mon-event': 'run.finished',
            'ai-mon-statuses': 'failed,partial',
            'ai-mon-outcomes': '',
            'ai-mon-run': 'run-9',
            'ai-mon-console': '',
            'ai-mon-note': 'manual',
        },
        toggles: { 'ai-mon-auto': true },
    };
};
const savedEnsureConversation = workspace._ensureConversation;
const savedToastMonitor = workspace._toast;
const savedMonitors = workspace._bootstrap.monitors;
workspace._ensureConversation = async () => 'c-new';
workspace._toast = () => {};
workspace._bootstrap.monitors = [];

await workspace._newMonitor();
const builderArmed = (workspace._bootstrap.monitors || []).some((item) => item.id === 'mon_new');

workspace._ensureConversation = savedEnsureConversation;
workspace._toast = savedToastMonitor;
workspace._bootstrap.monitors = savedMonitors;
sandbox.fetch = realFetchMonitor;
sandbox.showDialog = realShowDialogMonitor;

const armRequest = monitorRequests.find(
    (row) => row.url.indexOf('/api/ai/monitors') >= 0 && row.url.indexOf('/catalog') < 0
);
out.monitorBuilder = {
    button: !!newMonitorButton,
    clicked: newMonitorClicks === 1,
    urls: monitorRequests.map((row) => row.url),
    arm: armRequest ? armRequest.body : null,
    eventOptions: monitorDialogs[0] ? monitorDialogs[0].fields[0].options.map((option) => option.value) : [],
    armed: builderArmed,
};

/* The dock's layout class follows the PAINTED width, not the configured one. A viewport cap can
   shrink the dock below 480 while localStorage still says 900; the old code kept the three-column
   grid and left the chat a few pixels. */
workspace._dom.root.getBoundingClientRect = () => ({ width: 360 });
sandbox.AISettings.save({ sessionsWidth: 360, sideWidth: 440 });
workspace._bindColumns();
workspace._applyWidthClass(900);
const narrowAt360 = workspace._dom.root.classList.contains('narrow');
const narrowSessions = parseInt(workspace._dom.root.style.getPropertyValue('--ai-sessions-w'), 10);
const narrowSide = parseInt(workspace._dom.root.style.getPropertyValue('--ai-side-w'), 10);
workspace._dom.root.getBoundingClientRect = () => ({ width: 900 });
workspace._applyWidthClass(360);
out.narrowDock = {
    narrowAt360: narrowAt360,
    wideAt900: workspace._dom.root.classList.contains('narrow'),
    sessions: narrowSessions,
    side: narrowSide,
};

/* A streaming repaint must not throw the reader back to the top. Simulate a scrolled-up reader,
   add a block, and repaint. */
workspace._messages = [];
workspace._current = null;
workspace._dom.chat.innerHTML = '';
try {
    Object.defineProperty(workspace._dom.chat, 'scrollHeight', { value: 1000, configurable: true });
    Object.defineProperty(workspace._dom.chat, 'clientHeight', { value: 400, configurable: true });
} catch (error) {
    /* the stub may expose them as plain values; the assignment below still exercises the path */
}
workspace._ensureAssistant();
workspace._current.blocks = [{ type: 'text', text: 'first paragraph' }];
workspace._paintAssistant();
workspace._dom.chat.scrollTop = 120;
workspace._current.blocks.push({ type: 'text', text: 'streamed paragraph' });
workspace._paintAssistant();
out.scrollAnchor = { top: workspace._dom.chat.scrollTop };

fs.writeFileSync(1, JSON.stringify(out));






