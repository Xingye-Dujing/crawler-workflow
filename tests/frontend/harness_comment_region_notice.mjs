/* Runs the comment-region pre-run notice gate (workflow.js) under node, in isolation.

The gate must fire ONLY when the effective canvas actually crawls comments (a 「评论」
node, or a source node switched to comments mode), must stay silent otherwise (so a
search-only canvas is never interrupted), and must not fire for a comment node that is
disabled or starved by a disabled upstream. Driving `execute()` end-to-end would also
raise the profile/serial/overseas dialogs and blur what is asserted, so this calls the
two methods directly with a stubbed `showDialog`.

Usage: node harness_comment_region_notice.mjs <jsDir> <scenarios.json>
scenario = { id, nodes, connections, answers }  // answers: { comment: <button value to press> }
Prints {id: {hasComment, confirm, dialogs: [{message, labels}]}}
*/
import fs from 'node:fs';
import path from 'node:path';
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';

const jsDir = process.argv[2];
const scenarios = JSON.parse(fs.readFileSync(process.argv[3], 'utf8'));
const FILES = ['custom-select.js', 'canvas.js', 'workflow.js', 'app.js'];

const out = {};
for (const sc of scenarios) {
    const sandbox = { ...baseSandbox(), console: { log: () => {}, warn: () => {}, error: () => {} } };
    vm.createContext(sandbox);
    fixWindow(vm, sandbox);
    sandbox.fetch = () => Promise.resolve({ ok: true, json: () => Promise.resolve({}), text: () => Promise.resolve('{}') });
    for (const file of FILES) {
        vm.runInContext(fs.readFileSync(path.join(jsDir, file), 'utf8'), sandbox, { filename: file });
    }
    sandbox.__dialogs = [];
    vm.runInContext(
        `showDialog = function (options) {
            var buttons = options.buttons || [];
            globalThis.__dialogs.push({
                message: options.message,
                labels: buttons.map(function (b) { return b.label; }),
                values: buttons.map(function (b) { return ('value' in b) ? String(b.value) : '<absent>'; }),
            });
            var answers = ${JSON.stringify(sc.answers || {})};
            var hasGo = buttons.some(function (b) { return b.value === 'go'; });
            return Promise.resolve(hasGo ? ('comment' in answers ? answers.comment : 'go') : null);
        };`,
        sandbox,
    );
    vm.runInContext(
        `canvas.nodes = ${JSON.stringify(sc.nodes || {})};
         canvas.connections = ${JSON.stringify(sc.connections || [])};`,
        sandbox,
    );
    const hasComment = vm.runInContext('workflow._hasCommentCrawl()', sandbox);
    const confirm = await vm.runInContext('workflow._confirmCommentRegionBeforeRun()', sandbox);
    // The catalog's own wording, so the test compares the dialog to what the gate asked the
    // catalog for — never a pasted sentence that would go stale on the next translation edit.
    const noticeText = vm.runInContext('I18n.t("dialog.commentRegionNotice")', sandbox);
    const okText = vm.runInContext('I18n.t("dialog.commentRegionOk")', sandbox);
    out[sc.id] = { hasComment, confirm, dialogs: sandbox.__dialogs, noticeText, okText };
}
process.stdout.write(JSON.stringify(out));
