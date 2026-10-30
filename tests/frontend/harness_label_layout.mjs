/* The bibliometric label solver, driven against the REAL page scripts under node.

   `workflow.js` places a graph label where ECharts put it, then shifts it until it touches no
   other label. Two things the canvas itself decided and no Python test can see:

     · the series' own left/top/right/bottom is the band the backend reserved for the chart
       title and the cluster legend. A solver that only avoids other labels happily pushes a
       term INTO that band — the real-browser probe measured exactly that (`风险沟通` landing
       on `#5 数据治理；…`);
     · a percentage inset ('10%') is a length too, and reading it as a number makes the whole
       band collapse to zero, so the clamp silently does nothing.

   Every case states which box it handed the solver and what came back, and the last one goes
   through `applyEchartsOption` so the wiring (the solver receives the instance it must measure)
   is covered, not just the maths.

   Usage: node harness_label_layout.mjs <jsDir>
   Prints one JSON object to stdout.
*/
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const [jsDir] = process.argv.slice(2);

const sandbox = { ...baseSandbox() };
vm.createContext(sandbox);
fixWindow(vm, sandbox);
loadPageScripts(sandbox, { jsDir });
vm.runInContext('globalThis.__x = {_graphLabelLayout, applyEchartsOption};', sandbox);
const api = sandbox.__x;

const BANDS = { left: 24, top: 70, right: 170, bottom: 30 };
const SIZE = { width: 1000, height: 600 };

function instanceFor(size) {
    return {
        getWidth: () => size.width,
        getHeight: () => size.height,
        setOption() {},
        resize() {},
        dispose() {},
    };
}

function solver(series, size) {
    return api._graphLabelLayout({ type: 'graph', data: [1], dataLength: 1, ...series }, instanceFor(size || SIZE));
}

/* One call as ECharts would make it: the node's own rect is handed over first, then the label. */
function place(fn, rect, index) {
    const params = { dataIndex: index === undefined ? 0 : index, labelRect: rect };
    const handle = {
        getItemRect: () => ({ x: rect.x + rect.width / 2 - 5, y: rect.y + rect.height / 2 - 5, width: 10, height: 10 }),
        getLabelRect: () => rect,
    };
    const out = fn(params, handle);
    /* The solver answers with a dx/dy offset so the label stays attached to its node and
       follows roam; the cases below still compare the resulting BOX. */
    if (out && out.ignore !== true && (out.dx !== undefined || out.dy !== undefined)) {
        return {
            x: rect.x + (out.dx || 0),
            y: rect.y + (out.dy || 0),
            width: rect.width,
            height: rect.height,
            hideOverlap: out.hideOverlap,
            priority: out.priority,
        };
    }
    return out;
}

const inside = (box, pad) =>
    box.x >= pad.x0 && box.y >= pad.y0 && box.x + box.width <= pad.x1 && box.y + box.height <= pad.y1;

const pad = { x0: BANDS.left, y0: BANDS.top, x1: SIZE.width - BANDS.right, y1: SIZE.height - BANDS.bottom };
const cases = {};

// 1 · a label already inside the band is left alone.
{
    const fn = solver(BANDS);
    const rect = { x: 300, y: 300, width: 60, height: 16 };
    const out = place(fn, rect, 0);
    cases.left_alone = { asked: rect, got: out, inside: out.ignore !== true && inside(out, pad) };
}

// 2 · a label sitting in the legend column is pulled back, not left there.
{
    const fn = solver(BANDS);
    const out = place(fn, { x: 880, y: 300, width: 60, height: 16 }, 0);
    cases.legend_column = {
        got: out,
        hidden: out.ignore === true,
        inside: out.ignore === true ? false : inside(out, pad),
    };
}

// 3 · a label above the reserved title band, likewise.
{
    const fn = solver(BANDS);
    const out = place(fn, { x: 300, y: 20, width: 60, height: 16 }, 0);
    cases.title_band = { got: out, hidden: out.ignore === true, inside: out.ignore === true ? false : inside(out, pad) };
}

// 4 · percentage insets are lengths, not zeroes.
{
    const fn = solver({ left: '10%', top: '20%', right: '20%', bottom: '10%' });
    const box = { x0: 100, y0: 120, x1: 800, y1: 540 };
    const out = place(fn, { x: 850, y: 300, width: 60, height: 16 }, 0);
    cases.percent_insets = {
        got: out,
        hidden: out.ignore === true,
        inside: out.ignore === true ? false : inside(out, box),
    };
}

// 5 · two labels on one spot: the second is moved, never painted on the first.
{
    const fn = solver(BANDS);
    const first = place(fn, { x: 300, y: 300, width: 60, height: 16 }, 0);
    const second = place(fn, { x: 300, y: 300, width: 60, height: 16 }, 1);
    cases.siblings = {
        first,
        second,
        hidden: second.ignore === true,
        apart:
            second.ignore !== true &&
            (second.x !== first.x || second.y !== first.y) &&
            inside(second, pad),
    };
}

// 6 · a series that declares no bands is clamped to the canvas only.
{
    const fn = solver({});
    const out = place(fn, { x: 930, y: 570, width: 60, height: 16 }, 0);
    cases.no_bands = {
        got: out,
        hidden: out.ignore === true,
        inCanvas: out.ignore === true ? false : inside(out, { x0: 0, y0: 0, x1: SIZE.width, y1: SIZE.height }),
    };
}

// 7 · the wiring: applyEchartsOption hands the solver the instance it measures.
{
    const option = { series: [{ type: 'graph', data: [{ name: '甲' }], left: 24, top: 70, right: 170, bottom: 30 }] };
    const small = { width: 600, height: 400 };
    api.applyEchartsOption(instanceFor(small), option);
    const fn = option.series[0].labelLayout;
    const raw = fn(
        { dataIndex: 0, labelRect: { x: 560, y: 200, width: 60, height: 16 } },
        { getItemRect: () => ({ x: 585, y: 205, width: 10, height: 10 }), getLabelRect: () => ({ x: 560, y: 200, width: 60, height: 16 }) }
    );
    const out = raw && (raw.dx !== undefined || raw.dy !== undefined)
        ? { x: 560 + (raw.dx || 0), y: 200 + (raw.dy || 0), width: 60, height: 16, ignore: raw.ignore }
        : raw;
    /* The band is read back from the series: applyEchartsOption re-fits a free graph into a
       square rect first, and the solver must measure THAT band, not the authoring one. */
    const s = option.series[0];
    const box = { x0: s.left, y0: s.top, x1: small.width - s.right, y1: small.height - s.bottom };
    cases.wired_to_instance = {
        installed: typeof fn === 'function',
        got: out,
        hidden: out.ignore === true,
        inside: out.ignore === true ? false : inside(out, box),
    };
}

process.stdout.write(JSON.stringify(cases));
