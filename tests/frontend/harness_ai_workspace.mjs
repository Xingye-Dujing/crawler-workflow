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

fs.writeFileSync(1, JSON.stringify(out));
