/* Chart preview and the full-screen window.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-28) without a byte of rewriting: this file owns
 * the figure surfaces — the ECharts palette and its theme chokepoint, the label-collision resolver,
 * the preview panel with its LaTeX toolbar, the year-by-year replay, PNG/SVG export, and the
 * full-screen window those all share. Everything here is reached through a global name from
 * ``workflow.js`` (onclick attributes and dashboard tiles), which is why nothing was renamed.
 *
 * Loaded after ``workflow.js`` and before ``app.js``: every reference to a word (``I18n``) or a
 * toast happens at call time, so the order only has to be stable, not dependency-ordered.
 */

/* Some chart types need extra client-side setup before echarts can render
   them: the wordcloud series type needs the echarts-wordcloud extension
   script (loaded in index.html), and the map series type needs a GeoJSON
   registered via echarts.registerMap() first. This wraps setOption so
   every render path (chart preview, dashboard) gets that for free. */
/* ── A bundle that did not load says so ────────────────────────────────────
   The figure area is the only part of this UI that depends on a third-party bundle. It is served
   from /vendor now, but a damaged install used to read as an empty panel: `echarts.init` threw in
   the caller's try/catch, nothing was painted, and the user concluded the chart had no data. Each
   render path now names the file that is missing — a refusal the user can act on, never a blank. */
function hasChartLibrary() {
    return typeof echarts !== 'undefined' && !!(echarts && echarts.init);
}

function chartLibraryMissingMessage() {
    return I18n.t('chart.noLibrary', { file: '/vendor/echarts.min.js' });
}

/* textContent, never innerHTML: the wording comes from the language catalogue, which is text. */
function paintChartLibraryNote(host) {
    if (!host) return false;
    host.textContent = '';
    var note = document.createElement('div');
    note.className = 'chart-missing';
    note.textContent = chartLibraryMissingMessage();
    host.appendChild(note);
    return true;
}

/* Draw the refusal through the live instance instead of replacing its DOM: the surface keeps an
   instance to resize, export and dispose, and the saved PNG/SVG carries the sentence rather than
   showing an empty frame as if it were a result. */
function drawChartRefusal(instance, message) {
    if (!instance || !hasChartLibrary()) return;
    instance.clear();
    instance.setOption({
        title: { text: message, left: 'center', top: 'middle', textStyle: { fontSize: 13, fontWeight: 'normal' } }
    });
}

var _mapRegistryPromises = {};
/* Resolves '' once the basemap is registered, otherwise the refusal sentence — ONE string used for
   both the toast and the figure, because two wordings of the same failure drift and then one of
   them is a lie. A failure is not cached: fixing the file needs no page reload, and every retry
   says so again. */
function ensureMapRegistered(mapName) {
    if (_mapRegistryPromises[mapName]) return _mapRegistryPromises[mapName];
    /* Both basemaps are files the app serves, so a map figure draws on a machine with no network:
       the world map is Natural Earth (public domain, derived by tools/build_world_geojson.py) and
       the China map is DataV.GeoAtlas province boundaries with the nine-dash line, vendored
       byte-for-byte by tools/vendor_frontend_assets.py. The two world entries read the SAME file
       and differ only in which name column ECharts keys the data on, so a Chinese run's data names
       and its printed labels stay the same words. */
    var WORLD = '/geo/world.json';  // static_url_path is '' — the app serves its assets at the root
    var urls = {
        china: '/geo/china.json',
        world: WORLD,
        world_zh: WORLD
    };
    var url = urls[mapName];
    if (!url) return Promise.resolve(I18n.t('chart.mapUnavailable', { file: mapName, reason: I18n.t('chart.mapNoFile') }));
    var pending = fetch(url)
        .then(function (r) {
            if (!r.ok) throw new Error('HTTP ' + r.status);
            return r.json();
        })
        .then(function (geoJson) {
            // ECharts 5 takes {geoJSON, nameProperty}; the Chinese world map keys on the file's
            // own `zh` column so a Chinese run's data names and its printed labels are the same
            // words. The China basemap has one spelling per region and needs nothing here.
            echarts.registerMap(mapName, mapName === 'world_zh' ? { geoJSON: geoJson, nameProperty: 'zh' } : geoJson);
            return '';
        })
        .catch(function (e) {
            delete _mapRegistryPromises[mapName];
            var message = I18n.t('chart.mapUnavailable', { file: url, reason: (e && e.message) || String(e) });
            showToast(message);
            return message;
        });
    _mapRegistryPromises[mapName] = pending;
    return pending;
}

/* Theme-aware chart colours. patchOptionForTheme is the single chokepoint every console chart
   passes through, so reading the resolved <html data-theme> here recolours all of them at once;
   the history panel builds its option inline and uses chartPalette() the same way. */
function _isDarkTheme() {
    return document.documentElement.dataset.theme === 'dark';
}

function chartPalette() {
    if (_isDarkTheme()) {
        return {
            ink: '#e7e5df', dim: 'rgba(231,229,223,0.55)', faint: 'rgba(231,229,223,0.10)',
            axisLine: '#4b525d', splitLine: 'rgba(231,229,223,0.10)', labelLine: '#8b909a',
            tooltipBg: 'rgba(30,34,42,0.96)', tooltipBorder: '#3b414b', tooltipText: '#e7e5df',
            exportBg: '#1c2027',
        };
    }
    return {
        ink: '#111', dim: 'rgba(26,26,26,0.55)', faint: 'rgba(26,26,26,0.06)',
        axisLine: '#ccc', splitLine: '#e8e8e8', labelLine: '#bbb',
        tooltipBg: 'rgba(248,248,248,0.95)', tooltipBorder: '#ddd', tooltipText: '#222',
        exportBg: '#ffffff',
    };
}

function patchOptionForTheme(option) {
    var p = chartPalette();
    if (option.title && option.title.textStyle) option.title.textStyle.color = p.ink;
    if (option.tooltip) {
        option.tooltip.backgroundColor = p.tooltipBg;
        option.tooltip.borderColor = p.tooltipBorder;
        if (option.tooltip.textStyle) option.tooltip.textStyle.color = p.tooltipText;
    }
    if (option.legend && option.legend.textStyle) option.legend.textStyle.color = p.tooltipText;
    [].concat(option.xAxis || []).concat(option.yAxis || []).forEach(function (ax) {
        if (!ax) return;
        if (ax.axisLabel) ax.axisLabel.color = p.ink;
        if (ax.nameTextStyle) ax.nameTextStyle.color = p.tooltipText;
        if (ax.axisLine && ax.axisLine.lineStyle) ax.axisLine.lineStyle.color = p.axisLine;
        if (ax.axisTick && ax.axisTick.lineStyle) ax.axisTick.lineStyle.color = p.axisLine;
        if (ax.splitLine && ax.splitLine.lineStyle) ax.splitLine.lineStyle.color = p.splitLine;
    });
    (option.series || []).forEach(function (s) {
        if (!s) return;
        /* A label that paints its own chip keeps the backend's light chip in BOTH themes
           (the biblio builders write rgba(255,255,255,…)), so its ink must stay dark.
           Recolouring it to the theme's foreground painted white text on a white box in
           the dark theme — measured on the 关键词共现 graph, where every label vanished. */
        if (s.label) s.label.color = s.label.backgroundColor ? '#222' : p.tooltipText;
        if (s.label && s.label.backgroundColor && _isDarkTheme()) {
            /* 0.8 white over a dark canvas turned every chip mid-grey; a paper chip keeps
               its ink readable against the figure behind it. */
            s.label.backgroundColor = 'rgba(246,247,249,0.94)';
        }
        (s.data || []).forEach(function (item) {
            if (item && item.label && item.label.backgroundColor) item.label.color = '#222';
        });
        if (s.labelLine && s.labelLine.lineStyle) s.labelLine.lineStyle.color = p.labelLine;
        if (s.type === 'wordCloud' && s.textStyle) s.textStyle.color = p.tooltipText;
    });
    if (option.visualMap && option.visualMap.textStyle) option.visualMap.textStyle.color = p.ink;
}

/* ECharts' hideOverlap is not enough for a bibliometric graph: the labels are
   placed before the solver settles, so dense Chinese terms still print on top of
   one another. labelLayout runs after the node rect is known, so it can shift a
   label into the first free slot and hide only what cannot fit.
   The series' own left/top/right/bottom are the band the backend reserved for the
   title and the cluster legend; a label the solver pushes out of that band reads as
   a rendering bug even though it touches no other label. */
function _graphLabelLayout(series, instance) {
    var placed = [];
    function overlaps(a, b) {
        return a.x < b.x + b.width + 6 && b.x < a.x + a.width + 6 &&
               a.y < b.y + b.height + 6 && b.y < a.y + a.height + 6;
    }
    function inset(value, span) {
        if (typeof value === 'number') return value;
        var text = String(value === undefined || value === null ? '' : value).trim();
        if (text.slice(-1) === '%') return parseFloat(text) / 100 * span;
        return 0;
    }
    function bounds() {
        var width = instance && instance.getWidth ? instance.getWidth() : 0;
        var height = instance && instance.getHeight ? instance.getHeight() : 0;
        return {
            x0: inset(series.left, width),
            y0: inset(series.top, height),
            x1: width - inset(series.right, width),
            y1: height - inset(series.bottom, height)
        };
    }
    return function (params, api) {
        if (params.dataIndex === 0) placed = [];
        var item = api && api.getItemRect && api.getItemRect();
        if (item) placed.push({x: item.x - 3, y: item.y - 3, width: item.width + 6, height: item.height + 6});
        var rect = params.labelRect || (api && api.getLabelRect && api.getLabelRect());
        var width = rect.width, height = rect.height;
        var box = bounds();
        function fits(candidate) {
            return candidate[0] >= box.x0 && candidate[1] >= box.y0 &&
                   candidate[0] + width <= box.x1 && candidate[1] + height <= box.y1;
        }
        var candidates = [[rect.x, rect.y]];
        /* A label may step away from its node, but not wander across the figure: the old
           600px reach let every surplus label pile up in the first free corner, which is
           exactly the white stack measured on a 330px dashboard cell. Beyond a short hop
           the truthful answer is "no room", and the label is dropped (the node stays). */
        var reach = Math.max(12, Math.min(box.x1 - box.x0, box.y1 - box.y0) * 0.09);
        for (var shift = 4; shift <= reach; shift += 4) {
            candidates.push([rect.x, rect.y - shift]);
            candidates.push([rect.x, rect.y + shift]);
            candidates.push([rect.x - shift, rect.y]);
            candidates.push([rect.x + shift, rect.y]);
            candidates.push([rect.x - shift, rect.y - shift]);
            candidates.push([rect.x + shift, rect.y + shift]);
            candidates.push([rect.x - shift, rect.y + shift]);
            candidates.push([rect.x + shift, rect.y - shift]);
        }
        for (var i = 0; i < candidates.length; i++) {
            if (!fits(candidates[i])) continue;
            var placedBox = {x: candidates[i][0], y: candidates[i][1], width: width, height: height};
            var clear = true;
            for (var j = 0; j < placed.length; j++) {
                if (overlaps(placedBox, placed[j])) { clear = false; break; }
            }
            if (clear) {
                placed.push(placedBox);
                /* Returning hideOverlap hands the label to ECharts' own second pass, which
                   hides the losers of a collision by priority. The callback's `ignore` flag is
                   read by 5.4.4 only at creation, not from this return, so it cannot hide. */
                return {
                    x: placedBox.x, y: placedBox.y, width: width, height: height,
                    hideOverlap: true, priority: 100000 - (params.dataIndex || 0)
                };
            }
        }
        /* No free slot: clamp inside the plot and let hideOverlap drop the losers rather
           than paint a box clipped by the canvas edge. */
        var clamped = {
            x: Math.min(Math.max(rect.x, box.x0), Math.max(box.x0, box.x1 - width)),
            y: Math.min(Math.max(rect.y, box.y0), Math.max(box.y0, box.y1 - height))
        };
        placed.push({x: clamped.x, y: clamped.y, width: width, height: height});
        return {
            x: clamped.x, y: clamped.y, width: width, height: height,
            hideOverlap: true, priority: 100000 - (params.dataIndex || 0)
        };
    };
}

/* A free-layout graph is fitted by ECharts one axis at a time: scaleX = rect.width/spanX,
   scaleY = rect.height/spanY. The backend pins the data box to the square 50..950, so the
   rect must be square too or the picture is stretched — the measured dashboard defect,
   where a 330x257 tile drew a 900x900 layout 28% wider than tall. This gives the series a
   square rect (title above, cluster legend on the right only when there is room), scales
   symbols and label offsets with it, and puts the biggest nodes first so the label solver
   spends the space that exists on the labels that matter. Re-run on every resize: a
   percentage margin would stretch again the moment the panel changes shape. */
function _chartSurfaceSize(instance) {
    if (!instance || typeof instance.getWidth !== 'function' || typeof instance.getHeight !== 'function') return [0, 0];
    return [instance.getWidth(), instance.getHeight()];
}

function _fitFreeGraph(option, instance) {
    /* Every graph series, not only layout:'none': a circular/concentric ring drawn into a
       wide rect is an ellipse for the same reason, because the fit is per axis. */
    var graph = (option.series || []).find(function (s) { return s && s.type === 'graph'; });
    if (!graph) return;
    var free = graph.layout === 'none';
    var size = _chartSurfaceSize(instance);
    var w = size[0];
    var h = size[1];
    if (!w || !h) return;
    var showLegend = !!(option.legend && w >= 620 && h >= 380);
    if (option.legend) option.legend.show = showLegend;
    var top = 56, bottom = 22, left = 12, right = showLegend ? 196 : 12;
    var side = Math.max(120, Math.min(w - left - right, h - top - bottom));
    var x0 = left + (w - left - right - side) / 2;
    var y0 = top + (h - top - bottom - side) / 2;
    graph.left = Math.round(x0);
    graph.top = Math.round(y0);
    /* Derived, not rounded independently: two roundings can leave the rect one pixel out of
       square, which is precisely the stretch this function exists to remove. */
    graph.right = w - graph.left - side;
    graph.bottom = h - graph.top - side;
    // Symbols follow the square, but not below 62%: at a small tile a 3px disc reads as a
    // speck and the labels look like the graph. Above paper size they stop growing.
    if (!free) return;
    // Symbols follow the square, but not below 62%: at a small tile a 3px disc reads as a
    // speck and the labels look like the graph. Above paper size they stop growing.
    var k = Math.min(1.25, Math.max(0.62, side / 900));
    var offsetK = side / 1350;
    (graph.data || []).forEach(function (item) {
        if (!item) return;
        if (item._cixiSize === undefined) {
            item._cixiSize = typeof item.symbolSize === 'number' ? item.symbolSize : 0;
            item._cixiOffset = item.label && item.label.offset ? item.label.offset.slice() : null;
        }
        item.symbolSize = item._cixiSize > 0 ? Math.max(3, Math.round(item._cixiSize * k * 100) / 100) : 0;
        if (item.label && item._cixiOffset) {
            item.label.offset = [
                Math.round(item._cixiOffset[0] * offsetK * 10) / 10,
                Math.round(item._cixiOffset[1] * offsetK * 10) / 10
            ];
        }
    });
    (graph.data || []).sort(function (a, b) { return ((b && b.value) || 0) - ((a && a.value) || 0); });
    /* Label budget: a name chip is ~90x20px, and oversubscribing the square is exactly how a
       small cell became a white stack. Highest-frequency names claim the space first; a name
       that cannot be shown stays a hover target rather than a rectangle on top of its
       neighbours. */
    var budget = Math.max(4, Math.floor((side * side) * 0.35 / 1800));
    (graph.data || []).forEach(function (item, index) {
        if (!item || String(item.name || '').indexOf('_bbox_') === 0) return;
        item.label = item.label || {};
        item.label.show = index < budget;
    });
}

/* A category axis reserves its longest name out of the plot: the biblio timeline asks for
   a 260px label column, which is fine at paper width and leaves a 330px board cell with
   almost no plot. The label keeps its truncation, but its column follows the surface. */
function _fitCategoryAxes(option, instance) {
    var w = _chartSurfaceSize(instance)[0];
    if (!w) return;
    var width = Math.round(Math.max(64, Math.min(260, w * 0.28)));
    [].concat(option.yAxis || []).forEach(function (ax) {
        if (!ax || ax.type !== 'category' || !ax.axisLabel) return;
        ax.axisLabel.width = width;
        ax.axisLabel.overflow = 'truncate';
    });
    /* A year axis: ECharts prints 2023 as "2,023" and six of them touch in a board cell.
       Write the year plainly and tilt the ticks once the surface is too narrow for the row. */
    var narrow = w < 640;
    [].concat(option.xAxis || []).forEach(function (ax) {
        if (!ax || ax.type !== 'value' || ax.minInterval !== 1) return;
        if (!(ax.min >= 1900 && ax.max <= 2100)) return;
        ax.axisLabel = ax.axisLabel || {};
        /* Tilted years need a bottom band a 300px board cell does not have (measured: cut
           in half). Drop every other year instead — the axis still says where it starts and
           ends, and no tick is clipped. */
        ax.axisLabel.rotate = 0;
        ax.axisLabel.formatter = function (value) {
            var year = Math.round(value);
            if (w < 560 && year % 2 !== 0) return '';
            return String(year);
        };
    });
    /* Point labels on a cartesian scatter (cluster timeline) hang to the right of their
       bubble; in a narrow cell the last ones are cut by the canvas edge. Below the width
       at which they fit, the chart keeps its bubbles and drops the printed names — the
       hover tooltip still answers. */
    (option.series || []).forEach(function (s) {
        if (!s || s.type !== 'scatter' || !option.xAxis) return;
        if (s._cixiLabelShow === undefined) s._cixiLabelShow = !(s.label && s.label.show === false);
        if (s.label) s.label.show = s._cixiLabelShow && !narrow;
        (s.data || []).forEach(function (item) {
            if (!item || !item.label) return;
            if (item._cixiLabelShow === undefined) item._cixiLabelShow = item.label.show !== false;
            item.label.show = item._cixiLabelShow && !narrow;
        });
    });
}

/* A floating panel settles its width one frame after it is shown (measured: the full-screen
   host was 1202px during init and 1260px after layout), so the fit is repeated once the
   surface is final. Without this the square rect is computed for a width nobody sees. */
function settleChart(instance) {
    if (!instance || !instance.__cixiRefit) return;
    var run = function () {
        if (instance.__cixiRefit) instance.__cixiRefit();
    };
    if (typeof requestAnimationFrame === 'function') requestAnimationFrame(run);
    else setTimeout(run, 0);
}

/* Every resize of a chart surface goes through here, so the free graph is re-fitted at
   the new aspect instead of only being re-painted into it. */
function resizeChart(instance) {
    if (!instance) return;
    instance.resize();
    if (instance.__cixiRefit) instance.__cixiRefit();
}

function applyEchartsOption(instance, option) {
    patchOptionForTheme(option);
    _fitFreeGraph(option, instance);
    _fitCategoryAxes(option, instance);
    (option.series || []).forEach(function (s) {
        if (s && (s.type === 'graph' || (s.type === 'scatter' && !option.xAxis)) && Array.isArray(s.data) && s.data.length) {
            s.labelLayout = _graphLabelLayout(s, instance);
        }
        /* A choropleth's labels sit on geometry the author cannot shift: at the preview panel's
           width two neighbouring countries' names land on each other (measured: 德国 over 英国,
           中华人民共和国 over 日本). ECharts' own overlap hiding is the honest answer — the region
           stays coloured and answers on hover, only the printed name goes away. `moveOverlap` is
           deliberately NOT set: measured, adding 'shiftY' turns hideOverlap off again (12 labels
           with the two collisions back, against 10 with them dropped). */
        if (s && s.type === 'map') {
            s.labelLayout = { hideOverlap: true };
        }
    });
    var mapSeries = (option.series || []).find(function (s) { return s.type === 'map'; });
    if (mapSeries) {
        ensureMapRegistered(mapSeries.map || 'china').then(function (refusal) {
            /* A basemap that would not register is refused on the figure, not drawn empty: an
               option whose series names an unregistered map paints a blank box and prints nothing
               about why, which a reader then exports as if it were a result. */
            if (refusal) { drawChartRefusal(instance, refusal); return; }
            instance.setOption(option, true);
            instance.resize();
        });
    } else {
        instance.setOption(option, true);
        instance.resize();
    }
    var needsFit = (option.series || []).some(function (s) {
        return s && s.type === 'graph';
    }) || [].concat(option.yAxis || []).some(function (ax) {
        return ax && ax.type === 'category';
    });
    instance.__cixiRefit = needsFit ? function () {
        _fitFreeGraph(option, instance);
        _fitCategoryAxes(option, instance);
        instance.setOption(option, true);
    } : null;
    /* The panel can settle to a different size between init and this call (measured on the
       fullscreen window: 1202 -> 1260 after resize()), and margins computed for the old size
       leave the square 58px wide of square. Re-fit at the size that is actually on screen. */
    if (instance.__cixiRefit) instance.__cixiRefit();
}

var _chartPreviewInstance = null;
var _chartPreviewResizeHandler = null;
/* Which node the open preview belongs to: the saved picture has to be named after
   the chart the user was looking at, not after whichever node was clicked last. */
var _chartPreviewName = '';
/* The node id the preview was opened for, so the preview panel's 全屏 button can hand
   the very same chart to the full-screen window instead of guessing from a title. */
var _chartPreviewNodeId = '';
/* One ECharts instance for the full-screen window, disposed on close so reopening a
   different chart never paints into a stale canvas. */
var _chartFullscreenInstance = null;
var _chartFullscreenImage = '';
/* The option the full-screen window was actually given. It is not always the preview's: the
   window can be opened from a dashboard tile, or re-render from the server for a node the
   preview never showed, and an export button has to describe the picture it is sitting under. */
var _chartFullscreenOption = null;
/* The raw option each surface was drawn from. The full-screen window reuses THIS rather
   than a live instance's getOption(), which returns an ECharts-resolved tree that is not
   meant to be fed back as an authoring option. */
var _chartPreviewOption = null;

/* ── Replay the network year by year ───────────────────────────────────────
   CiteSpace's animation is the one reading of a knowledge map a table cannot give: which
   cluster the field was growing at the time. The durable artifacts (PNG/SVG/LaTeX) stay the
   COMPLETE figure — an animation does not print — so this is an inspection affordance over
   the option the node already shipped, driven by each node's own 年份序列. Nothing is
   re-requested and no callback is stored in the option, so a saved chart is still the same
   JSON it was before the button existed.

   A link appears once BOTH of its endpoints have: the option carries no per-slice edges, and
   inventing an edge-year would put a claim the data does not make into a measured figure.
   The bar says so in its own words for the same reason. */
var _replaySurfaces = {};
var _REPLAY_TICK_MS = 900;

function _replayGraphSeries(option) {
    var series = option && (option.series || [])[0];
    return series && series.type === 'graph' && Array.isArray(series.data) && series.data.length ? series : null;
}

function _replayNodeName(series, ref) {
    if (typeof ref === 'number' && series.data[ref]) return String(series.data[ref].name);
    return String(ref);
}

function _replayYears(option) {
    var series = _replayGraphSeries(option);
    if (!series) return [];
    var seen = {};
    var years = [];
    series.data.forEach(function (node) {
        (node.yearSeries || []).forEach(function (pair) {
            var year = Number(pair[0]);
            if (!isFinite(year) || seen[year]) return;
            seen[year] = true;
            years.push(year);
        });
    });
    return years.sort(function (a, b) { return a - b; });
}

/* A frame is cut from the ORIGINAL option, never from the previous frame: a size scaled twice
   would be a size nobody measured, and the complete figure has to stay reachable. Each node is
   therefore scaled against ITS OWN total, so the last frame is byte-for-byte the whole network
   rather than an approximation of it. */
function _replayFrame(option, year) {
    var series = _replayGraphSeries(option);
    if (!series) return option;
    var totals = {};
    var grown = {};
    series.data.forEach(function (node) {
        var total = 0;
        var cum = 0;
        (node.yearSeries || []).forEach(function (pair) {
            var value = Number(pair[1]) || 0;
            total += value;
            if (Number(pair[0]) <= year) cum += value;
        });
        totals[String(node.name)] = total;
        grown[String(node.name)] = cum;
    });
    var frame = JSON.parse(JSON.stringify(option));
    var target = frame.series[0];
    target.data.forEach(function (node) {
        var name = String(node.name);
        var cum = grown[name] || 0;
        if (!cum) {
            node.symbolSize = 1;
            node.itemStyle = Object.assign({}, node.itemStyle, { opacity: 0 });
            node.label = Object.assign({}, node.label, { show: false });
            return;
        }
        var base = Number(node.symbolSize) || 10;
        var scale = totals[name] ? Math.sqrt(cum / totals[name]) : 1;
        node.symbolSize = Math.max(4, Math.round(base * scale * 100) / 100);
    });
    (target.links || []).forEach(function (link) {
        var live = (grown[_replayNodeName(series, link.source)] || 0) > 0
            && (grown[_replayNodeName(series, link.target)] || 0) > 0;
        if (!live) link.lineStyle = Object.assign({}, link.lineStyle, { opacity: 0 });
    });
    return frame;
}

function _replayInstance(key) {
    return key === 'fullscreen' ? _chartFullscreenInstance : _chartPreviewInstance;
}

function _replayStop(key) {
    var state = _replaySurfaces[key];
    if (state && state.timer) {
        clearInterval(state.timer);
        state.timer = null;
    }
}

function _replayDetach(key) {
    _replayStop(key);
    var panel = _replayPanel(key);
    var bar = panel ? panel.querySelector('.chart-replay-bar') : null;
    if (bar) bar.remove();
    delete _replaySurfaces[key];
}

function _replayPanel(key) {
    return document.getElementById(key === 'fullscreen' ? 'chart-fullscreen-panel' : 'chart-preview-panel');
}

function _replayShow(key, index) {
    var state = _replaySurfaces[key];
    if (!state) return;
    var clamped = Math.max(0, Math.min(state.years.length - 1, index));
    state.index = clamped;
    var frame = _replayFrame(state.option, state.years[clamped]);
    var instance = _replayInstance(key);
    if (instance) {
        instance.setOption({ series: [{ data: frame.series[0].data, links: frame.series[0].links }] });
    }
    state.current = frame;
    var panel = _replayPanel(key);
    if (!panel) return;
    var slider = panel.querySelector('.chart-replay-range');
    if (slider) slider.value = String(clamped);
    var readout = panel.querySelector('.chart-replay-year');
    if (readout) readout.textContent = I18n.t('chart.replayYear', { year: state.years[clamped] });
}

function _replayAll(key) {
    var state = _replaySurfaces[key];
    if (!state) return;
    _replayStop(key);
    state.current = null;
    var instance = _replayInstance(key);
    if (instance) applyEchartsOption(instance, state.option);
    var panel = _replayPanel(key);
    var slider = panel ? panel.querySelector('.chart-replay-range') : null;
    if (slider) slider.value = String(state.years.length - 1);
    var readout = panel ? panel.querySelector('.chart-replay-year') : null;
    if (readout) readout.textContent = I18n.t('chart.replayAllYears');
    var play = panel ? panel.querySelector('.chart-replay-play') : null;
    if (play) play.textContent = I18n.t('chart.replayPlay');
}

function _replayTick(key) {
    var state = _replaySurfaces[key];
    if (!state) return;
    if (state.index >= state.years.length - 1) {
        _replayStop(key);
        var done = _replayPanel(key);
        var button = done ? done.querySelector('.chart-replay-play') : null;
        if (button) button.textContent = I18n.t('chart.replayReplay');
        return;
    }
    _replayShow(key, state.index + 1);
}

function _replayAttach(key, option) {
    var panel = _replayPanel(key);
    if (!panel) return;
    _replayDetach(key);
    var years = _replayYears(option);
    if (years.length < 2) return;
    var state = { option: option, years: years, index: years.length - 1, timer: null, current: null };
    _replaySurfaces[key] = state;
    var bar = document.createElement('div');
    bar.className = 'chart-replay-bar';
    var play = document.createElement('button');
    play.type = 'button';
    play.className = 'chart-replay-play runs-mgr-btn';
    play.textContent = I18n.t('chart.replayPlay');
    play.onclick = function () {
        if (state.timer) {
            _replayStop(key);
            play.textContent = I18n.t('chart.replayPlay');
            return;
        }
        if (state.index >= years.length - 1) _replayShow(key, 0);
        play.textContent = I18n.t('chart.replayPause');
        state.timer = setInterval(function () { _replayTick(key); }, _REPLAY_TICK_MS);
    };
    var slider = document.createElement('input');
    slider.type = 'range';
    slider.className = 'chart-replay-range';
    slider.min = '0';
    slider.max = String(years.length - 1);
    slider.step = '1';
    slider.value = String(years.length - 1);
    slider.title = I18n.t('chart.replayHint');
    slider.oninput = function () {
        _replayStop(key);
        play.textContent = I18n.t('chart.replayPlay');
        _replayShow(key, parseInt(slider.value, 10));
    };
    var readout = document.createElement('span');
    readout.className = 'chart-replay-year';
    readout.textContent = I18n.t('chart.replayAllYears');
    var reset = document.createElement('button');
    reset.type = 'button';
    reset.className = 'chart-replay-reset runs-mgr-btn';
    reset.textContent = I18n.t('chart.replayReset');
    reset.onclick = function () { _replayAll(key); };
    var hint = document.createElement('span');
    hint.className = 'chart-replay-hint';
    hint.textContent = I18n.t('chart.replayHint');
    [play, slider, readout, reset, hint].forEach(function (el) { bar.appendChild(el); });
    panel.appendChild(bar);
    // The canvas was sized for a panel with no bar under it. Measured in Chrome: the stale
    // absolutely-positioned canvas kept the height, overflowed the row the bar had just taken,
    // and swallowed the click meant for 播放 — the bar painted and did nothing.
    var instance = _replayInstance(key);
    if (instance) instance.resize();
}

function _replayCurrentOption(key) {
    var state = _replaySurfaces[key];
    return state && state.current ? state.current : null;
}

/* What an export of this surface should contain: the frame on screen if there is one, the whole
   figure otherwise. A file that disagrees with the picture the user just looked at is worse than
   no file, and the PNG path already gets this for free (it screenshots the instance). */
function _surfaceOption(key, stored) {
    return _replayCurrentOption(key) || stored;
}

/* ── Saving a drawn chart as a file ─────────────────────────────────────────
   A chart exists on screen in three places — the studio, the preview panel and a
   dashboard cell — and until now only the studio could put its picture on disk.
   All three go through the same endpoint (the studio's own /api/studio/save-image),
   and both engines are covered: an ECharts instance hands over a data URL, and a
   Matplotlib preview already IS one (the <img> the panel was given).
   A chart that was never drawn is refused with a sentence, because a silent button
   reads as "saving is broken" and the real cause is that there is no picture yet. */
async function saveChartPicture(dataUrl, name) {
    if (!dataUrl) {
        showToast(I18n.t('chart.saveNothing'));
        return null;
    }
    try {
        var resp = await fetch('/api/studio/save-image', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ image: dataUrl, name: name || 'chart' }),
        });
        var result = await resp.json();
        if (!result.ok) throw new Error(result.error || 'request failed');
        showToast(I18n.t('studio.saved').replace('{path}', result.filename));
        return result.filename;
    } catch (e) {
        showToast(I18n.t('studio.saveFailed') + ': ' + e.message);
        return null;
    }
}

function savePreviewImage() {
    var dataUrl = '';
    if (_chartPreviewInstance) {
        dataUrl = _chartPreviewInstance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: chartPalette().exportBg });
    } else {
        var img = document.getElementById('chart-preview-image');
        if (img && img.style.display !== 'none' && String(img.src || '').indexOf('data:image/') === 0) {
            dataUrl = img.src;
        }
    }
    return saveChartPicture(dataUrl, _chartPreviewName || 'chart-preview');
}

/* ── Vector export ────────────────────────────────────────────────────────────
   A 2× PNG is a photograph of a figure: a reviewer zooming in sees dots, and a
   publisher asking for vector art cannot use the file at all. ECharts can draw the
   SAME option through its SVG renderer, so the vector twin is produced off-screen
   from the raw option the surface was painted from — never from a live instance's
   getOption(), which returns an ECharts-resolved tree that is not meant to be fed
   back as an authoring option. A Matplotlib chart has no browser-side option to
   redraw, so that path says so rather than handing over a raster with .svg on it. */
function chartSvgMarkup(option, width, height) {
    if (!option || typeof echarts === 'undefined' || !echarts.init) return '';
    var host = document.createElement('div');
    host.style.cssText =
        'position:absolute;left:-10000px;top:0;width:' + width + 'px;height:' + height + 'px;';
    document.body.appendChild(host);
    var instance = null;
    var markup = '';
    try {
        instance = echarts.init(host, null, { renderer: 'svg' });
        instance.setOption(option);
        var svg = host.querySelector('svg');
        if (svg) {
            if (!svg.getAttribute('xmlns')) svg.setAttribute('xmlns', 'http://www.w3.org/2000/svg');
            svg.setAttribute('width', String(width));
            svg.setAttribute('height', String(height));
            markup = svg.outerHTML || '';
        }
    } catch (e) {
        markup = '';
    }
    if (instance) instance.dispose();
    host.remove();
    return markup;
}

function _surfaceSize(hostId, fallback) {
    var el = document.getElementById(hostId);
    var width = el && el.clientWidth ? el.clientWidth : fallback[0];
    var height = el && el.clientHeight ? el.clientHeight : fallback[1];
    return [Math.max(320, Math.round(width)), Math.max(240, Math.round(height))];
}

async function saveChartVector(option, name, hostId) {
    if (!option) {
        showToast(I18n.t('chart.saveNothing'));
        return null;
    }
    if (!hasChartLibrary()) {
        /* The generic "vector export failed" would blame the exporter; the reason is that the
           bundle which draws SVG is not on the page, and that is what the user can fix. */
        showToast(chartLibraryMissingMessage());
        return null;
    }
    var size = _surfaceSize(hostId, [1200, 700]);
    var markup = chartSvgMarkup(option, size[0], size[1]);
    if (!markup) {
        showToast(I18n.t('chart.saveVectorFailed'));
        return null;
    }
    try {
        var resp = await fetch('/api/studio/save-vector', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ svg: markup, name: name || 'chart' }),
        });
        var result = await resp.json();
        if (!result.ok) throw new Error(result.error || 'request failed');
        showToast(I18n.t('studio.saved').replace('{path}', result.filename));
        return result.filename;
    } catch (e) {
        showToast(I18n.t('studio.saveFailed') + ': ' + e.message);
        return null;
    }
}

function savePreviewVector() {
    // Whatever is on screen: a vector cut from the whole network while the window shows 2019
    // would be a file that disagrees with the figure the user just looked at.
    return saveChartVector(
        _surfaceOption('preview', _chartPreviewOption),
        _chartPreviewName || 'chart-preview',
        'chart-preview-echarts'
    );
}

function saveDashboardImage(nodeId) {
    var inst = dashboard._instances[nodeId];
    var dataUrl = inst
        ? inst.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: chartPalette().exportBg })
        : dashboard._images[nodeId] || '';
    var node = canvas.nodes[nodeId];
    return saveChartPicture(dataUrl, (node && node.title) || nodeId);
}

function renderChartPreview(result) {
    var panel = document.getElementById('chart-preview-panel');
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, {
            minW: 300,
            minH: 200,
            maxW: window.innerWidth - 40,
            maxH: window.innerHeight - 40,
            onResize: function () { if (_chartPreviewInstance) resizeChart(_chartPreviewInstance); }
        });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var echartsDiv = document.getElementById('chart-preview-echarts');
    var imgEl = document.getElementById('chart-preview-image');
    if (result.engine === 'matplotlib') {
        _chartPreviewOption = null;
        _replayDetach('preview');
        echartsDiv.style.display = 'none';
        echartsDiv.innerHTML = '';
        imgEl.style.display = 'block';
        imgEl.src = result.image;
    } else {
        _chartPreviewOption = result.option;
        imgEl.style.display = 'none';
        echartsDiv.style.display = 'block';
        if (!hasChartLibrary()) {
            /* The option itself is real, so the LaTeX bar below still has something to offer: what
               is missing is only the browser-side painter. Say which file is gone — never a box. */
            paintChartLibraryNote(echartsDiv);
            _renderLatexBar(result);
            return;
        }
        if (!_chartPreviewInstance) {
            echartsDiv.innerHTML = '';
            _chartPreviewInstance = echarts.init(echartsDiv);
            if (!_chartPreviewResizeHandler) {
                _chartPreviewResizeHandler = function () { resizeChart(_chartPreviewInstance); };
                window.addEventListener('resize', _chartPreviewResizeHandler);
            }
        }
        applyEchartsOption(_chartPreviewInstance, result.option);
        settleChart(_chartPreviewInstance);
        _replayAttach('preview', result.option);
    }
    _renderLatexBar(result);
}

/* The preview's LaTeX controls. ``emit_latex`` is on by default, so a chart node also files a
   compilable ``.txt``; here the user copies the source or downloads it. The file already lives in
   EXPORT_DIR (written by the node / render path), so download hits the same endpoint the exports
   browser uses; when a preview produced the text inline with no stored file, a Blob download covers it. */
var _lastLatex = '';
var _lastLatexTable = '';
var _lastLatexFile = '';
var _lastLatexTableFile = '';

function _renderLatexBar(result) {
    var panel = document.getElementById('chart-preview-panel');
    if (!panel) return;
    var old = document.getElementById('latex-action-bar');
    if (old) old.remove();
    _lastLatex = result.latex || '';
    _lastLatexTable = result.latex_table || '';
    _lastLatexFile = result.latex_file || '';
    _lastLatexTableFile = result.latex_table_file || '';
    if (!_lastLatex && !_lastLatexTable) return;
    var html = '';
    if (_lastLatex) {
        html += '<button class="menu-btn" onclick="copyLatexSource(\'fig\')">' + I18n.t('chart.copyLatex') + '</button>' +
            '<button class="menu-btn" onclick="downloadLatexFile(\'fig\')">' + I18n.t('chart.downloadLatex') + '</button>';
    }
    if (_lastLatexFile) {
        /* Only a source the run LEDGER knows about can be compiled — the button sends the name
           and nothing else, so an inline preview with no filed source offers nothing to compile. */
        html += '<button class="menu-btn" onclick="saveChartPdf()">' + I18n.t('chart.makePdf') + '</button>';
    }
    if (_lastLatexTable) {
        html += '<button class="menu-btn" onclick="copyLatexSource(\'tab\')">' + I18n.t('chart.copyTable') + '</button>' +
            '<button class="menu-btn" onclick="downloadLatexFile(\'tab\')">' + I18n.t('chart.downloadTable') + '</button>';
    }
    if (result.latex_error || result.latex_table_error) {
        html += '<span style="font-size:11px;color:#e67e22;">' + escapeHtml(String(result.latex_error || result.latex_table_error)) + '</span>';
    }
    var bar = document.createElement('div');
    bar.id = 'latex-action-bar';
    bar.className = 'latex-action-bar';
    bar.innerHTML = html;
    panel.appendChild(bar);
}

function copyLatexSource(kind) {
    var text = kind === 'tab' ? _lastLatexTable : _lastLatex;
    if (!text) return;
    var done = function () { if (typeof showToast === 'function') showToast(I18n.t('chart.copied')); };
    if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(text).then(done, function () { _fallbackCopy(text); done(); });
    } else {
        _fallbackCopy(text); done();
    }
}

function _fallbackCopy(text) {
    var ta = document.createElement('textarea');
    ta.value = text;
    ta.style.position = 'fixed';
    ta.style.opacity = '0';
    document.body.appendChild(ta);
    ta.select();
    try { document.execCommand('copy'); } catch (e) { /* clipboard blocked: the download path still works */ }
    document.body.removeChild(ta);
}

/* One click from a drawn chart to a vector PDF: the request carries only the NAME of the LaTeX
   source this node filed, and the server compiles what its own ledger vouches for. Sending the
   source instead would hand xelatex a document chosen by the page — LaTeX pulls readable files
   into its output, and the PDF comes back from our origin. */
async function saveChartPdf() {
    if (!_lastLatexFile) {
        showToast(I18n.t('chart.pdfNoSource'));
        return null;
    }
    /* A xelatex pass takes seconds; the default 2.5 s toast would be gone before the answer. */
    showToast(I18n.t('chart.pdfWorking'), 20000);
    try {
        var resp = await fetch('/api/studio/save-pdf', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ name: _lastLatexFile }),
        });
        var result = await resp.json();
        if (!result.ok) throw new Error(result.error || 'request failed');
        showToast(I18n.t('studio.saved').replace('{path}', result.filename));
        window.location.href = '/api/exports/download?name=' + encodeURIComponent(result.filename);
        return result.filename;
    } catch (e) {
        showToast(I18n.t('studio.saveFailed') + ': ' + e.message);
        return null;
    }
}

function downloadLatexFile(kind) {
    var name = kind === 'tab' ? _lastLatexTableFile : _lastLatexFile;
    if (name) {
        window.location.href = '/api/exports/download?name=' + encodeURIComponent(name);
        return;
    }
    var text = kind === 'tab' ? _lastLatexTable : _lastLatex;
    if (!text) return;
    var blob = new Blob([text], { type: 'text/plain;charset=utf-8' });
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = (kind === 'tab' ? 'latex-table' : 'latex-figure') + '.txt';
    document.body.appendChild(a);
    a.click();
    setTimeout(function () { URL.revokeObjectURL(a.href); a.remove(); }, 1000);
}

function toggleChartPreview() {
    var panel = document.getElementById('chart-preview-panel');
    panel.classList.remove('open');
    // The timer belongs to the window that was closed: a detached interval keeps cutting frames
    // out of an option whose instance is already gone.
    _replayDetach('preview');
    if (_chartPreviewInstance) {
        _chartPreviewInstance.dispose();
        _chartPreviewInstance = null;
    }
}

/* ── Full-screen chart window ──────────────────────────────────────────────
   A dashboard tile is ~300px; a figure meant for a paper has to be read at size.
   openChartFullscreen shows ONE chart in a draggable/resizable floating window (the
   same makeDraggable/makeResizable surface the preview panel uses). It sources the
   chart from what is already on screen — the board's stored option, then its
   matplotlib image, then the open preview — and only re-requests the render when the
   node has none of those. Nothing here pays for an LLM: a 主题概括 tile that has not
   run yet re-renders from the stored last-run rows via the SAME endpoint the cell used,
   and if that has no rows it says so rather than drawing an empty figure. */
async function openChartFullscreen(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var panel = document.getElementById('chart-fullscreen-panel');
    var titleEl = document.getElementById('chart-fullscreen-title');
    if (titleEl) titleEl.textContent = node.title || nodeId;
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, {
            minW: 320,
            minH: 240,
            maxW: window.innerWidth - 20,
            maxH: window.innerHeight - 20,
            onResize: function () { if (_chartFullscreenInstance) resizeChart(_chartFullscreenInstance); }
        });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var opt = dashboard._options && dashboard._options[nodeId];
    if (opt) { _paintFullscreenOption(opt); return; }
    var img = dashboard._images && dashboard._images[nodeId];
    if (img) { _paintFullscreenImage(img); return; }
    if (nodeId === _chartPreviewNodeId) {
        if (_chartPreviewOption) { _paintFullscreenOption(_chartPreviewOption); return; }
        var previewImg = document.getElementById('chart-preview-image');
        if (previewImg && previewImg.style.display !== 'none' && String(previewImg.src).indexOf('data:image/') === 0) {
            _paintFullscreenImage(previewImg.src);
            return;
        }
    }
    if (node.type !== 'visualize') return;
    var p = node.params;
    var payload = {
        chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
        y_field: p.y_field, value_field: p.value_field, agg: p.agg,
        center_node: p.center_node,
        y2_field: p.y2_field, agg2: p.agg2, annotations: p.annotations,
        label_field: p.label_field, stack_fields: p.stack_fields,
        model_field: p.model_field, agreement_label_field: p.agreement_label_field, id_field: p.id_field,
        title: p.title, tokenize: boolParam(p.tokenize, false),
        emit_latex: boolParam(p.emit_latex, true), emit_latex_table: boolParam(p.emit_latex_table, true),
        wordcloud_style: p.wordcloud_style || 'vibrant',
    };
    var upstream = canvas.getUpstreamNodeId(nodeId);
    if (!upstream) { showToast(I18n.t('dashboard.noData')); return; }
    payload.node_id = upstream;
    // Re-fetched from the server when this node was never drawn on this page (a reopened
    // canvas): name the workflow so the upstream rows resolve from the run store, not just
    // from a live process that may have restarted.
    payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
    if (typeof runResults !== 'undefined') runResults.payload(payload);
    try {
        var resp = await fetch('/api/visualize/render', {
            method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(payload),
        });
        var result = await resp.json();
        if (!result.ok) { var fv = _renderFailureView(result); _paintFullscreenError(fv.message, fv.note); return; }
        if (result.engine === 'matplotlib') _paintFullscreenImage(result.image);
        else _paintFullscreenOption(result.option);
    } catch (e) {
        _paintFullscreenError(e.message);
    }
}

function _disposeFullscreenInstance() {
    if (_chartFullscreenInstance) {
        _chartFullscreenInstance.dispose();
        _chartFullscreenInstance = null;
    }
}

function _paintFullscreenOption(option) {
    var div = document.getElementById('chart-fullscreen-echarts');
    var img = document.getElementById('chart-fullscreen-image');
    _disposeFullscreenInstance();
    _chartFullscreenImage = '';
    if (img) img.style.display = 'none';
    div.style.display = 'block';
    div.innerHTML = '';
    if (!hasChartLibrary()) {
        /* The window remembers its own option so the export buttons still answer with a sentence
           rather than a file; what it cannot do is paint, and it says so. */
        _chartFullscreenOption = option;
        paintChartLibraryNote(div);
        return;
    }
    _chartFullscreenInstance = echarts.init(div);
    _chartFullscreenOption = option;
    applyEchartsOption(_chartFullscreenInstance, option);
    settleChart(_chartFullscreenInstance);
    _replayAttach('fullscreen', option);
}

function _paintFullscreenImage(dataUrl) {
    var div = document.getElementById('chart-fullscreen-echarts');
    var img = document.getElementById('chart-fullscreen-image');
    _disposeFullscreenInstance();
    _replayDetach('fullscreen');
    _chartFullscreenOption = null;
    div.style.display = 'none';
    div.innerHTML = '';
    _chartFullscreenImage = dataUrl || '';
    if (img) { img.style.display = 'block'; img.src = dataUrl; }
}

function _renderFailureView(result) {
    /* 'No run data yet' is the expected state of a canvas nobody has executed, not a fault:
       the board answers it HTTP 200 with code no_run_data so a cold-load rehydrate does not
       fill the dev console with red 400s. Show it as a muted note and never a toast; anything
       else is a real failure and keeps its red styling. */
    if (result && result.code === 'no_run_data') return { note: true, message: I18n.t('chart.noRunData') };
    return { note: false, message: (result && result.error) || 'render failed' };
}

function _paintFullscreenError(message, isNote) {
    var div = document.getElementById('chart-fullscreen-echarts');
    var img = document.getElementById('chart-fullscreen-image');
    _disposeFullscreenInstance();
    _replayDetach('fullscreen');
    _chartFullscreenOption = null;
    _chartFullscreenImage = '';
    if (img) img.style.display = 'none';
    div.style.display = 'block';
    div.innerHTML = '<div class="' + (isNote ? 'dashboard-cell-note' : 'dashboard-cell-error') + '">' + escapeHtml(message) + '</div>';
}

function closeChartFullscreen() {
    document.getElementById('chart-fullscreen-panel').classList.remove('open');
    _replayDetach('fullscreen');
    _chartFullscreenOption = null;
    _disposeFullscreenInstance();
    _chartFullscreenImage = '';
}

function saveFullscreenImage() {
    var dataUrl = '';
    if (_chartFullscreenInstance) {
        dataUrl = _chartFullscreenInstance.getDataURL({ type: 'png', pixelRatio: 2, backgroundColor: chartPalette().exportBg });
    } else if (_chartFullscreenImage) {
        dataUrl = _chartFullscreenImage;
    }
    var titleEl = document.getElementById('chart-fullscreen-title');
    return saveChartPicture(dataUrl, (titleEl && titleEl.textContent) || 'chart-fullscreen');
}

function saveFullscreenVector() {
    var titleEl = document.getElementById('chart-fullscreen-title');
    return saveChartVector(
        // The full-screen window's OWN option, and the frame it is showing: this button used to
        // hand over the preview panel's stored option, so a window opened from a dashboard tile
        // (or scrubbed to 2019) saved a different picture than the one on screen.
        _surfaceOption('fullscreen', _chartFullscreenOption),
        (titleEl && titleEl.textContent) || 'chart-fullscreen',
        'chart-fullscreen-echarts'
    );
}

