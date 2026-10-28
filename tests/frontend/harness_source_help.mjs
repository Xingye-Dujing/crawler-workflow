/* The export-guide overlay, driven against the REAL canvas.js + workflow.js + app.js.
 *
 * The guide answers "where does this file come from?" at the moment a user is holding the file
 * picker. Every sentence in it is served (GET /api/biblio/sources) because which site exports
 * which fields — and which fields a real export lacks — is the parser's knowledge. So the
 * failures a browser test can actually catch are the panel inventing an opinion anyway:
 *
 *   · opening must not paint guessed sources: before the answer lands the body holds the loading
 *     sentence and nothing else;
 *   · a failed request has to be reported with the server's own words and still paint no source,
 *     because a half guide is worse than an empty one;
 *   · a site link carries rel="noopener noreferrer" and shows the URL as text, since the point
 *     is that the user can copy it;
 *   · server values are escaped in both slots — the label is text, the URL is an attribute;
 *   · `accept` on the file input comes from the registry's extension list, not from this file;
 *   · toggle is class-only (a `style.display` write would outrank the stylesheet), the
 *     backdrop closes and the sheet does not;
 *   · a language switch refetches only while open — the sentences are served per language.
 *
 * Wording is compared against `I18n.t(...)` evaluated in the same sandbox, never a pasted
 * sentence.
 *
 * Usage: node harness_source_help.mjs <jsDir>
 * Prints one JSON object to stdout.
 */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const [jsDir] = process.argv.slice(2);

const SOURCES = [
    {
        id: 'CSSCI', label: 'CSSCI', group: 'library', site: 'https://cssci.nju.edu.cn/',
        extensions: ['.txt'], capabilities: { refs: true, tc: false },
        purpose: '引文入口', steps: ['1. 进入检索页', '2. 导出文本'], missing: ['无【摘要】'],
    },
    {
        id: 'CNKI', label: '中国知网 · RefWorks', group: 'library', site: 'https://kns.cnki.net/',
        extensions: ['.txt'], capabilities: {}, purpose: '共现入口', steps: ['1. 检索'], missing: [],
    },
    {
        id: 'WoS', label: 'Web of Science', group: 'library', site: 'https://www.webofscience.com/',
        extensions: ['.txt', '.xls'], capabilities: {}, purpose: '完整入口', steps: ['1. 检索', '2. 导出'], missing: ['Excel 无 CR'],
    },
    {
        id: 'RIS', label: 'RIS', group: 'exchange', site: 'https://www.zotero.org/',
        extensions: ['.ris'], capabilities: {}, purpose: '交换格式', steps: ['1. 导出 RIS'], missing: [],
    },
    {
        /* A source the server hands over without a site: the panel must not build an empty link. */
        id: 'NoSite', label: '无站点的来源', group: 'exchange', site: '',
        extensions: ['.weird'], capabilities: {}, purpose: '占位', steps: ['1. 导出'], missing: [],
    },
];

function world(answers, acceptValue) {
    const sandbox = {
        ...baseSandbox(),
        console: { log() {}, warn() {}, error() {} },
        localStorage: { getItem: () => null, setItem: () => {}, removeItem: () => {} },
    };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    /* The page's modules in the page's order, through the shared loader, so app.js's catalogue
       files come with it — without them the guide's words are raw keys. */
    loadPageScripts(sandbox, { jsDir, only: ['canvas.js', 'workflow.js', 'app.js'] });
    vm.runInContext(
        'globalThis.__x = { canvas, I18n, sourceHelp,' +
            ' toggleSourceHelp, openSourceHelp, closeSourceHelp,' +
            ' isOpen: () => sourceHelp.isOpen(),' +
            ' body: () => document.getElementById("source-help-body"),' +
            ' overlay: () => document.getElementById("source-help-overlay"),' +
            ' input: () => document.getElementById("dataset-file-input") };',
        sandbox
    );
    const doc = sandbox.document;
    const input = doc.getElementById('dataset-file-input');
    if (acceptValue !== undefined) input.setAttribute('accept', acceptValue);
    const requests = [];
    sandbox.fetch = (url) => {
        requests.push(String(url));
        return Promise.resolve({ text: () => Promise.resolve(JSON.stringify(answers)), status: 200 });
    };
    return {
        sandbox,
        x: sandbox.__x,
        requests,
        html: () => String(sandbox.__x.body().innerHTML),
        input,
    };
}

/* `reload()` owns its promise chain (opening never waits for it), so a scenario drains
   microtasks instead of pretending to await a call that returns nothing. */
async function drain() {
    for (let i = 0; i < 24; i += 1) await Promise.resolve();
}

async function loaded(answers, acceptValue) {
    const w = world(answers || { ok: true, sources: SOURCES, extensions: ['.net', '.ris', '.txt'] }, acceptValue);
    w.x.openSourceHelp();
    await drain();
    return w;
}

const out = {};

// 1 · opening asks the server once and paints nothing it has not been told.
{
    const w = world({ ok: true, sources: SOURCES, extensions: [] }, '.csv,.json');
    w.x.openSourceHelp();
    const before = w.html();
    out.beforeLanding = {
        asked: w.requests.slice(),
        loading: before.indexOf(w.x.I18n.t('sourceHelp.loading')) >= 0,
        paintedSources: before.indexOf('source-help-item') >= 0,
        opened: w.x.isOpen() === true,
        // Toggling a class, never the element's own style: an inline display would outrank CSS.
        styleWritten: Boolean(w.x.overlay().style && w.x.overlay().style.display),
    };
    await drain();
    out.afterLanding = { asked: w.requests.length, hasItems: w.html().indexOf('source-help-item') >= 0 };
}

// 2 · groups, links and the extensions line, all from the served answer.
{
    const w = await loaded();
    const html = w.html();
    out.guide = {
        groupOrder: [...html.matchAll(/source-help-group">([^<]*)</g)].map((m) => m[1]),
        libraryFirst: html.indexOf(w.x.I18n.t('sourceHelp.groupLibrary')) < html.indexOf(w.x.I18n.t('sourceHelp.groupExchange')),
        linkAttrs: /<a href="https:\/\/www\.webofscience\.com\/"[^>]*target="_blank"[^>]*rel="noopener noreferrer">/.test(html),
        // The URL is also the text, because copying it is the point.
        urlAsText: html.indexOf('>https://cssci.nju.edu.cn/<') >= 0,
        steps: (html.match(/<li>/g) || []).length,
        missingLine: html.indexOf('Excel 无 CR') >= 0,
        noEmptyAnchor: html.indexOf('href=""') < 0,
        sitelessRendered: html.indexOf('无站点的来源') >= 0,
        extensionsShown: html.indexOf('.txt .xls') >= 0,
    };
}

// 3 · the picker's accept list is the registry's answer, merged with what it already offered.
{
    const w = await loaded(undefined, '.csv,.json');
    out.accept = {
        value: String(w.input.getAttribute('accept')),
        keepsOrdinary: String(w.input.getAttribute('accept')).split(',').indexOf('.csv') >= 0,
        gained: String(w.input.getAttribute('accept')).split(',').indexOf('.net') >= 0,
    };
}

// 4 · a refused load says why, with the server's own words, and draws no source.
{
    const w = await loaded({ ok: false, error: '没有可读的来源清单' });
    const html = w.html();
    out.refused = {
        namesReason: html.indexOf('没有可读的来源清单') >= 0,
        prefix: html.indexOf(w.x.I18n.t('sourceHelp.unavailable')) >= 0,
        paintedSources: html.indexOf('source-help-item') >= 0,
    };
}

// 5 · server values are escaped in both slots: label as text, URL as an attribute.
{
    const evil = {
        ok: true,
        sources: [{
            id: 'Evil', label: '<script>bad</script>', group: 'library',
            site: 'https://x.example/"><script>bad</script>', extensions: ['.txt'],
            capabilities: {}, purpose: '<img src=x>', steps: ['1. "quoted"'], missing: [],
        }],
        extensions: ['.txt'],
    };
    const w = await loaded(evil);
    const html = w.html();
    out.escaped = {
        noRawScript: html.indexOf('<script>bad') < 0,
        escapedLabel: html.indexOf('&lt;script&gt;bad&lt;/script&gt;') >= 0,
        attributeClosed: html.indexOf('"><script>') < 0,
        quoteEscaped: html.indexOf('&quot;') >= 0,
        purposeEscaped: html.indexOf('<img src=x>') < 0,
    };
}

// 6 · close/toggle/backdrop: one class, and only a click on the scrim counts.
{
    const w = await loaded();
    const overlay = w.x.overlay();
    w.x.closeSourceHelp();
    const closed = w.x.isOpen() === false;
    w.x.toggleSourceHelp();
    const reopened = w.x.isOpen() === true;
    const listeners = (overlay._events && overlay._events.click) || [];
    let closedBySheet = 'unknown';
    if (listeners.length) {
        // A click inside the sheet must not close it; one on the scrim must.
        listeners[0]({ target: w.x.body() });
        closedBySheet = w.x.isOpen() === true ? 'kept-open' : 'closed';
        listeners[0]({ target: overlay });
        closedBySheet = `${closedBySheet}/${w.x.isOpen() === false ? 'scrim-closed' : 'scrim-kept'}`;
    }
    out.toggle = { closed, reopened, backdropListeners: listeners.length, closedBySheet };
}

// 7 · a language switch refetches only while the guide is open.
{
    const w = await loaded();
    const seen = w.requests.length;
    w.x.closeSourceHelp();
    w.x.sourceHelp.onLanguageChange();
    const whileClosed = w.requests.length;
    w.x.openSourceHelp();
    w.x.sourceHelp.onLanguageChange();
    await drain();
    out.refetch = { seen, whileClosed, whileOpen: w.requests.length > whileClosed };
}

console.log(JSON.stringify(out));
