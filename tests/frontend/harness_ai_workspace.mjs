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
];
workspace._renderMessages([]);
const errorRow = workspace._dom.chat.querySelectorAll('.ai-error-text')[0];
const askedRow = workspace._dom.chat.querySelectorAll('.ai-question-text')[0];
const answeredRow = workspace._dom.chat.querySelectorAll('.ai-question-answered')[0];
out.storedEvidence = {
    error: errorRow ? String(errorRow.textContent) : '',
    asked: askedRow ? String(askedRow.textContent) : '',
    answered: answeredRow ? String(answeredRow.textContent) : '',
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

/* ONE turn, TWO provider rounds (a tool call between them). The transcript must stay one assistant
   bubble with one skill row — the daemon answers each round as its own assistant row, and drawing
   each round separately made a single answer look like two answers on screen. */
workspace._messages = [];
workspace._conversationId = 'c-two';
workspace._current = null;
workspace._sending = true;
workspace._dom.chat.innerHTML = '';
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
workspace._maybeAnswer = async () => {
    sentAnswer = workspace._current.answers.q1;
};
workspace._answerCustom('q1', answerBox.value);
out.answerRefs = {
    targetOk: refTargetOk,
    chips: answerChips,
    custom: sentAnswer && sentAnswer.custom,
    refs: (sentAnswer && sentAnswer.references) || [],
};

fs.writeFileSync(1, JSON.stringify(out));
