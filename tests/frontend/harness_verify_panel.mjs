/* 采集校验 / 内容去重 as a real browser renders them.
 *
 * Two things only the rendered page can prove:
 *
 *   · **the roles are shown.** Both the audit node and the analysis node's 反向筛选 step read
 *     two tables by CONNECTION ORDER. A panel that asks for two column names without saying
 *     which wire is the list and which is the result has told the user nothing they can check;
 *     this harness wires two titled nodes and asserts the card and the panel name them.
 *   · **the card follows the wires.** A card captured before a `swap_tables` edit (or a wire
 *     change) would describe the opposite question from the run.
 *
 * Wording is read from `I18n.t(...)` in the same sandbox, never pasted, so a translation is
 * never a test fixture.
 *
 * Usage: node harness_verify_panel.mjs <jsDir>
 * Prints one JSON object to stdout.
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const [jsDir] = process.argv.slice(2);

function world() {
    const sandbox = {
        ...baseSandbox(),
        console: { log() {}, warn() {}, error() {} },
        localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    /* The page's modules in the page's order, through the shared loader, so app.js's catalogue
       files come with it — without them the panel's words are raw keys. */
    loadPageScripts(sandbox, { jsDir, only: ['canvas.js', 'workflow.js', 'app.js'] });
    vm.runInContext(
        'globalThis.__x = { canvas, I18n, openSettings, updateParam, nodeTypeWord, Diagnostics };',
        sandbox,
    );
    sandbox.fetch = () => Promise.resolve({ text: () => Promise.resolve('{"ok":true}'), status: 200 });
    const { canvas } = sandbox.__x;
    canvas.nodes = {};
    canvas.connections = [];
    canvas._settingsNodeId = '';
    canvas.saveState = () => {};
    canvas.updateNodeDisplay = () => {};
    canvas.updateSettingsButton = () => {};
    canvas.closeSettingsIfStale = () => {};
    canvas.multiEditTargets = () => [];
    sandbox.__x.Diagnostics._columns = {};
    return { sandbox, x: sandbox.__x, html: () => String(sandbox.document.getElementById('settings-content').innerHTML) };
}

function addNode(w, id, type, params) {
    w.x.canvas.nodes[id] = { id, type, title: id, params, x: 0, y: 0 };
}

function wire(w, fromId, toId) {
    w.x.canvas.connections.push({ from: fromId, to: toId });
}

/** Every I18n key a case asked for, resolved in the same sandbox. */
function words(w, keys) {
    const out = {};
    keys.forEach((key) => {
        out[key] = w.x.I18n.t(key);
    });
    return out;
}

const out = {};

/* ─── the audit node: two wired tables, roles named ───────────────────────────── */
{
    const w = world();
    addNode(w, 'p1', 'upload', { dataset_id: 'd1', dataset_name: '帖子.csv', row_count: 3 });
    w.x.canvas.nodes.p1.title = '帖子表';
    addNode(w, 'p2', 'upload', { dataset_id: 'd2', dataset_name: '评论.csv', row_count: 9 });
    w.x.canvas.nodes.p2.title = '评论表';
    addNode(w, 'v1', 'verify', w.x.canvas.getDefaultParams('verify'));
    wire(w, 'p1', 'v1');
    wire(w, 'p2', 'v1');
    w.x.openSettings('v1');
    const html = w.html();
    out.verify_type_word = w.x.I18n.t('nodeType.verify');
    out.verify_header_uses_word = html.includes(out.verify_type_word);
    out.verify_raw_key = html.includes('nodeType.verify');
    const keys = words(w, ['settings.verifyListRole', 'settings.verifyResultRole', 'settings.verifyHint']);
    out.verify_role_words = keys;
    out.verify_role_line = html.includes(keys['settings.verifyListRole']) && html.includes(keys['settings.verifyResultRole']);
    out.verify_names_p1 = html.includes('帖子表');
    out.verify_names_p2 = html.includes('评论表');
    out.verify_hint_shown = html.includes(keys['settings.verifyHint']);
    /* The stored defaults come back out of the markup. */
    out.verify_values = ['链接', '文章URL', '评论数'].map((value) => html.includes('value="' + value + '"'));
    out.verify_summary = w.x.canvas.getNodeSummary('verify', w.x.canvas.nodes.v1.params, 'v1');
    out.verify_summary_names_p1 = out.verify_summary.includes('帖子表');
    out.verify_summary_names_p2 = out.verify_summary.includes('评论表');

    /* One table is a refusal the panel states, not a run-time surprise. */
    w.x.canvas.connections = [{ from: 'p1', to: 'v1' }];
    out.verify_one_wire_summary = w.x.canvas.getNodeSummary('verify', w.x.canvas.nodes.v1.params, 'v1');
    out.verify_needs_two = out.verify_one_wire_summary.includes(w.x.I18n.t('settings.twoTableNeedTwo'));

    /* Swapping flips the roles the card prints — the executor will read the same flag. */
    w.x.canvas.connections = [
        { from: 'p1', to: 'v1' },
        { from: 'p2', to: 'v1' },
    ];
    w.x.updateParam('v1', 'swap_tables', true);
    out.verify_swapped_summary = w.x.canvas.getNodeSummary('verify', w.x.canvas.nodes.v1.params, 'v1');
    out.verify_swap_flips = out.verify_swapped_summary.split('\n')[1].startsWith(
        w.x.I18n.t('settings.verifyResultRole'),
    );

    /* A number edit repaints the same panel (the openSettings path). */
    w.x.updateParam('v1', 'tolerance', '5');
    out.verify_edit_lands = String(w.x.canvas.nodes.v1.params.tolerance) === '5';
    out.verify_edit_repaints = w.html().includes('value="5"');

    /* The connection warning explains the two-wire rule instead of "first only". */
    out.verify_conn_category = String((w.x.canvas.classifyConnection('p1', 'v1') || {}).category);
}

/* ─── 内容去重 inside the analysis node ───────────────────────────────────────── */
{
    const w = world();
    addNode(w, 'p1', 'upload', { dataset_id: 'd1', dataset_name: 'all.csv', row_count: 10 });
    w.x.canvas.nodes.p1.title = '全部帖子';
    addNode(w, 'p2', 'upload', { dataset_id: 'd2', dataset_name: 'done.csv', row_count: 4 });
    w.x.canvas.nodes.p2.title = '已采评论';
    addNode(w, 'a1', 'analysis', { operation: 'anti_join', left_on: '', right_on: '' });
    wire(w, 'p1', 'a1');
    wire(w, 'p2', 'a1');
    w.x.openSettings('a1');
    const html = w.html();
    const keys = words(w, [
        'settings.antiJoinKeepRole',
        'settings.antiJoinBasisRole',
        'settings.antiJoinHint',
        'op.anti_join',
        'matchMode.url',
    ]);
    out.anti_role_words = keys;
    out.anti_role_line = html.includes(keys['settings.antiJoinKeepRole']) && html.includes(keys['settings.antiJoinBasisRole']);
    out.anti_names_p1 = html.includes('全部帖子');
    out.anti_names_p2 = html.includes('已采评论');
    out.anti_hint_shown = html.includes(keys['settings.antiJoinHint']);
    out.anti_mode_options = html.includes(keys['matchMode.url']);
    out.anti_summary = w.x.canvas.getNodeSummary('analysis', w.x.canvas.nodes.a1.params, 'a1');
    out.anti_summary_names = out.anti_summary.includes('全部帖子') && out.anti_summary.includes('已采评论');
    out.anti_summary_uses_word = out.anti_summary.includes(keys['op.anti_join']);
    out.anti_conn_category = String((w.x.canvas.classifyConnection('p1', 'a1') || {}).category);

    /* The panel's mode lists are the backend's, read here for the Python comparison. */
    out.match_modes = vm.runInContext('MATCH_MODES.slice()', w.sandbox);
    out.count_match_modes = vm.runInContext('COUNT_MATCH_MODES.slice()', w.sandbox);
    out.keep_modes = vm.runInContext('KEEP_MODES.slice()', w.sandbox);
}

process.stdout.write(JSON.stringify(out, null, 2));
