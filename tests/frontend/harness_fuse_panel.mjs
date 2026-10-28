/* The 跨源融合 settings panel, driven against the REAL canvas.js + workflow.js + app.js.
 *
 * The Python tests prove the fold, the refusals and the run. What only a browser-side test can
 * catch is the panel being *unable to say what it is showing*:
 *
 *   · the header resolves `nodeType.<type>` — a COMPUTED key, so neither the call-site scan nor
 *     the dead-key scan can see the missing half. The shipped page printed the identifier
 *     「nodeType.fuse」 for a whole commit (measured on screen 2026-10-24), and an unknown type
 *     from a newer build must now read as the type itself rather than as a key;
 *   · the panel lists the columns the node will emit only when the server can see them: a fuse
 *     node has a fixed contract, so omitting it from the producer list hides lineage the
 *     backend already answers for;
 *   · every candidate-column field echoes what is stored, including a multi-line per-parent
 *     source name — a field that renders blank and then writes the default on blur is a silent
 *     rewrite of the user's canvas;
 *   · the card summary counts the candidate columns the user actually listed, not the defaults;
 *   · an edit lands in the model AND repaints the panel (the same `openSettings` path).
 *
 * The panel body is one `innerHTML` assignment and the DOM stub parses only part of what it is
 * handed, so the cases read the assigned markup string itself — the exact bytes a browser gets.
 * Wording is compared against `I18n.t(...)` evaluated in the same sandbox, never a pasted
 * sentence.
 *
 * Usage: node harness_fuse_panel.mjs <jsDir>
 * Prints one JSON object to stdout.
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const [jsDir] = process.argv.slice(2);

const FUSE_COLUMNS = [
    '记录ID',
    '题名',
    '作者',
    '作者单位',
    '来源期刊',
    '年份',
    '关键词',
    '摘要',
    '参考文献',
    '来源',
];

const LABEL_KEYS = [
    'fuse.ui.entityColumns',
    'fuse.ui.yearColumns',
    'fuse.ui.titleColumns',
    'fuse.ui.authorColumns',
    'fuse.ui.affiliationColumns',
    'fuse.ui.textColumns',
    'fuse.ui.referenceColumns',
    'fuse.ui.sourceColumns',
    'fuse.ui.sourceLabels',
];

function world(columnsFor) {
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
    vm.runInContext('globalThis.__x = { canvas, I18n, openSettings, updateParam, nodeTypeWord, Diagnostics };', sandbox);
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
    /* The columns the server says this node emits — the edit-time lineage. */
    sandbox.__x.Diagnostics._columns = { ...columnsFor };
    return {
        sandbox,
        x: sandbox.__x,
        html: () => String(sandbox.document.getElementById('settings-content').innerHTML),
    };
}

function addNode(w, id, type, params) {
    w.x.canvas.nodes[id] = { id, type, title: id, params, x: 0, y: 0 };
}

const out = {};

/* ─── the shipped defaults, as the canvas seeds them ───────────────────────── */
const seeded = {
    entity_columns: '关键词,话题,主题,主题词,标签',
    year_columns: '年份,发布时间,发表日期,日期',
    title_columns: '题名,标题,内容,正文',
    author_columns: '作者,用户名,昵称,发布者',
    affiliation_columns: '作者单位,机构',
    text_columns: '摘要,正文,内容',
    reference_columns: '参考文献,引文',
    source_columns: '平台,来源',
    source_labels: 'node-1 = 文献\nnode-3 = 微博',
    keep_undated: true,
    export_files: true,
};

{
    const w = world({ 'fuse-1': FUSE_COLUMNS });
    addNode(w, 'fuse-1', 'fuse', { ...seeded });
    w.x.openSettings('fuse-1');
    const html = w.html();
    const words = LABEL_KEYS.map((k) => w.x.I18n.t(k));
    out.type_word = w.x.I18n.t('nodeType.fuse');
    out.header_uses_word = html.includes(out.type_word);
    out.raw_key_shown = html.includes('nodeType.fuse');
    out.labels_missing = words.filter((label) => !html.includes(label));
    /* Every stored value must come back out of the markup, or the panel shows a default the
       user never typed. `escapeHtml` only touches & < >, so these strings pass through as-is. */
    out.values_missing = Object.keys(seeded)
        .filter((k) => k !== 'keep_undated' && k !== 'export_files')
        .filter((k) => !html.includes(seeded[k]))
        .map((k) => k);
    out.lineage_shown = html.includes('node-output-cols') && html.includes(FUSE_COLUMNS[0]);
    /* Just that one div: the fields below it repeat several of the same names as candidate
       columns, and a slice to the end of the panel would pass on their text. */
    out.lineage_text = (() => {
        const start = html.indexOf('node-output-cols');
        if (start < 0) return '';
        const end = html.indexOf('</div>', start);
        return html.slice(start, end < 0 ? undefined : end);
    })();
    out.summary_count = w.x.canvas.getNodeSummary('fuse', { ...seeded });
    out.summary_uses_word = String(out.summary_count).includes(w.x.I18n.t('fuse.ui.summary'));

    /* An edit is the repaint path; the model must move and the panel must follow. */
    w.x.updateParam('fuse-1', 'entity_columns', '话题,标签');
    const after = w.html();
    out.edit_lands_in_model = w.x.canvas.nodes['fuse-1'].params.entity_columns;
    out.edit_repaints = after.includes('话题,标签') && !after.includes('关键词,话题,主题,主题词,标签');
    out.summary_after_edit = w.x.canvas.getNodeSummary('fuse', w.x.canvas.nodes['fuse-1'].params);
}

/* ─── a type this build has no word for ───────────────────────────────────── */
{
    const w = world({});
    addNode(w, 'fut-1', 'time_machine', {});
    w.x.openSettings('fut-1');
    const html = w.html();
    out.unknown_type_shows = w.x.nodeTypeWord('time_machine');
    out.unknown_raw_key = html.includes('nodeType.time_machine');
    out.unknown_lineage = html.includes('node-output-cols');
}

out.expected_columns = FUSE_COLUMNS.length;
process.stdout.write(JSON.stringify(out, null, 2));
