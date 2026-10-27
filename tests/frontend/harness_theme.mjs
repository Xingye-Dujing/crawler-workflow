/* Drives the REAL theme layer under node: the chrome switch (app.js setTheme/applyTheme +
   persistence) and the chart recolour (workflow.js chartPalette/patchOptionForTheme).

   Theme is pure DOM + a single resolved flag on <html data-theme>; neither is reachable from
   Python. The whole page is loaded in index.html's own order (page_scripts.mjs), then: picks a
   theme and reads the resolved flag, the persisted choice, and which control is marked active;
   and patches a sample ECharts option under each theme to prove the chart colours flip with the
   theme (a dark ground with light-only charts was the whole risk). */
import vm from 'node:vm';

import { baseSandbox, fixWindow } from './harness_dom.mjs';
import { loadPageScripts } from './page_scripts.mjs';

const jsDir = process.argv[2];
const sandbox = baseSandbox();
vm.createContext(sandbox);
fixWindow(vm, sandbox);
loadPageScripts(sandbox, { jsDir });

const doc = sandbox.document;
function mkBtn(choice) {
    const b = doc.createElement('button');
    b.classList.add('theme-opt');
    b.dataset.themeChoice = choice;
    doc.getElementById('style-menu').appendChild(b);
}
mkBtn('auto');
mkBtn('light');
mkBtn('dark');

const R = (expr) => vm.runInContext(expr, sandbox);

const report = {};
for (const choice of ['light', 'dark', 'auto']) {
    report[choice] = R(
        `(function () {
            setTheme(${JSON.stringify(choice)});
            var active = [];
            document.querySelectorAll('.theme-opt').forEach(function (el) {
                if (el.classList.contains('active')) active.push(el.dataset.themeChoice);
            });
            return {
                resolved: document.documentElement.dataset.theme,
                stored: JSON.parse(localStorage.getItem('crawler_settings')).theme,
                active,
            };
        })()`,
    );
}

function chartColors(theme) {
    return R(
        `(function () {
            document.documentElement.dataset.theme = ${JSON.stringify(theme)};
            var o = {
                title: { textStyle: {} },
                tooltip: { textStyle: {} },
                legend: { textStyle: {} },
                xAxis: [{ axisLabel: {}, axisLine: { lineStyle: {} }, splitLine: { lineStyle: {} } }],
                series: [{ label: {} }],
            };
            patchOptionForTheme(o);
            return {
                title: o.title.textStyle.color,
                tooltipBg: o.tooltip.backgroundColor,
                axisLabel: o.xAxis[0].axisLabel.color,
                splitLine: o.xAxis[0].splitLine.lineStyle.color,
                exportBg: chartPalette().exportBg,
            };
        })()`,
    );
}
report.chart_light = chartColors('light');
report.chart_dark = chartColors('dark');

process.stdout.write(JSON.stringify(report));
