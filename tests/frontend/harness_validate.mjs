/* Runs the REAL workflow.validate() (backend/static/js/workflow.js) in node.
 *
 * workflow.validate() is the gate a run must pass before the browser POSTs
 * /api/workflow/execute — the exact place the user was bitten twice (a renamed
 * node reading 'node-1', a comments node demanding a keyword). The Python suite
 * rebuilds its own workflow dicts, so a rule that lives only in JS is invisible
 * to them. This harness loads the actual file and answers, for a batch of
 * canvases, which validation messages fire — the message KEYS, so the result
 * does not depend on UI language.
 *
 * Usage: node harness_validate.mjs <path/to/workflow.js> <scenarios.json>
 * scenarios.json = [ { "id": "...", "lang": "en",
 *                      "nodes": [{id,type,title,params}...],
 *                      "connections": [{from,to}...] } ]
 * Prints {id: [keys...]} to stdout.
 *
 * Two extra scenario shapes ride along, because they belong to the same file:
 *   {"node": {...}}        → render that node's settings panel, return its HTML
 *   {"needsLlm": {...}}    → answer nodeNeedsLlm(params, nodeOperation), which is
 *                            the browser's half of the "does this run need a
 *                            model?" gate (backend/app.py holds the other half)
 */
import fs from 'node:fs';
import vm from 'node:vm';

import { baseSandbox } from './harness_dom.mjs';

const wfPath = process.argv[2];
const scenarioPath = process.argv[3];
const src = fs.readFileSync(wfPath, 'utf8');
const scenarios = JSON.parse(fs.readFileSync(scenarioPath, 'utf8'));

/* A parseable stand-in for the catalog: validate messages come back as
   'key|<title>|<n>|<plat>|…' with unfilled placeholders left literal, so the
   Python side can assert WHICH rule fired AND with what values without
   depending on UI language. Node/platform labels resolve to short tokens. */
const SHORT = {
    'platform.zhihu': 'zhihu',
    'platform.weibo': 'weibo',
    'platform.xiaohongshu': 'xiaohongshu',
    'platform.wechat': 'wechat',
    'node.source': 'Source',
    'node.upload': 'Upload',
    'node.process': 'Process',
    'node.analysis': 'Analysis',
    'node.visualize': 'Visualize',
    'node.tokenize': 'Tokenize',
    'node.output': 'Output',
    'node.resume': 'Resume',
    'node.name': 'Name',
    'node.comment': 'Comment',
};
const I18n = {
    lang: 'en',
    dict: { en: {}, zh: {} },
    t(k) {
        if (k.startsWith('validate.')) return `${k}|{title}|{n}|{plat}|{col}|{op}`;
        return SHORT[k] || k;
    },
};

const sandbox = {
    ...baseSandbox(),
    I18n,
    canvas: {
        nodes: {},
        connections: [],
        _settingsNodeId: null,
        // updateParam's display/state hooks are canvas territory — stubbed so
        // selectSourcePlatform can run to its END (the collect reset) here.
        updateNodeDisplay: () => {},
        saveState: () => {},
        updateSettingsButton: () => {},
        closeSettingsIfStale: () => {},
    },
    RunState: { parallel: false, headless: true },
    showToast: () => {},
    escapeHtml: undefined,
};
vm.createContext(sandbox);
/* `const workflow` is lexically scoped to its own script — append a capture
   line (same trick as harness_canvas.mjs) to reach it from the host. */
vm.runInContext(
    src +
        '\n;globalThis.__wf = {' +
        ' workflow, urlPlatform, commentUrlPlaceholder, selectSourcePlatform, openSettings, nodeNeedsLlm };',
    sandbox,
);

const workflow = sandbox.__wf.workflow;
const urlPlatform = sandbox.__wf.urlPlatform;
const commentUrlPlaceholder = sandbox.__wf.commentUrlPlaceholder;
const selectSourcePlatform = sandbox.__wf.selectSourcePlatform;
const openSettings = sandbox.__wf.openSettings;
const nodeNeedsLlm = sandbox.__wf.nodeNeedsLlm;

const out = { validate: {}, url: [], placeholder: {}, settings: {}, needsLlm: {} };

for (const sc of scenarios) {
    I18n.lang = sc.lang || 'en';
    sandbox.canvas.nodes = {};
    sandbox.canvas._settingsNodeId = null;
    if (sc.needsLlm !== undefined) {
        // One params dict (+ the node-level operation the wire also carries) in,
        // one boolean out — the Python side compares the same table against
        // backend/app.py::_workflow_needs_llm.
        out.needsLlm[sc.id] = nodeNeedsLlm(sc.needsLlm, sc.operation);
        continue;
    }
    if (sc.node) {
        // Settings-panel render: capture the exact HTML the user would see.
        const n = sc.node;
        sandbox.canvas.nodes[n.id] = {
            id: n.id,
            type: n.type,
            title: n.title || '',
            params: n.params || {},
            el: null,
        };
        sandbox.canvas._settingsNodeId = n.id;
        sandbox.__byId('settings-content').innerHTML = '';
        openSettings(n.id);
        out.settings[sc.id] = sandbox.__byId('settings-content').innerHTML;
        continue;
    }
    for (const n of sc.nodes) {
        sandbox.canvas.nodes[n.id] = {
            id: n.id,
            type: n.type,
            title: n.title,
            params: n.params || {},
        };
    }
    sandbox.canvas.connections = sc.connections || [];
    out.validate[sc.id] = workflow.validate();
}

/* Pure URL helpers, exercised over a fixed table so the JS/Bakend routing
   agreement is pinned. */
for (const u of [
    'https://www.zhihu.com/question/1/answer/2',
    'https://www.xiaohongshu.com/explore/abc',
    'http://xhslink.com/abc',
    'https://weibo.com/123/AbCdEf',
    'https://m.weibo.cn/detail/9',
    'https://www.bilibili.com/video/BV1xx411c7mD',
    'https://search.bilibili.com/all?keyword=ai',
    'https://www.douyin.com/video/7665683746674183459',
    'https://v.douyin.com/abc123/',
    'https://mp.weixin.qq.com/s/xyz',
    'https://example.com/x',
    '',
]) {
    out.url.push([u, urlPlatform(u)]);
}
for (const p of ['zhihu', 'weibo', 'xiaohongshu', 'bilibili', 'douyin', 'wechat', '']) {
    out.placeholder[p] = commentUrlPlaceholder(p);
}

/* selectSourcePlatform must clear a stale comments flag when WeChat (no
   comment adapter) is picked, and leave it for the other platforms. */
const switchResults = {};
for (const [from, to, name] of [
    ['zhihu', 'wechat', 'zhihu_to_wechat'],
    ['wechat', 'zhihu', 'wechat_to_zhihu'],
    ['zhihu', 'weibo', 'zhihu_to_weibo'],
]) {
    sandbox.canvas.nodes = {
        n1: { id: 'n1', type: 'source', title: 'x', params: { platform: from, collect: 'comments' } },
    };
    selectSourcePlatform('n1', to);
    switchResults[name] = sandbox.canvas.nodes.n1.params.collect;
}
out.platformSwitch = switchResults;

process.stdout.write(JSON.stringify(out));
