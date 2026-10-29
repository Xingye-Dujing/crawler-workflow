/* Node settings panel: the dock that opens on a node, the source panel, the field renderers every
   node shares (input / select / checkbox), the resume and output panels, and the rule for which
   process nodes really call a model.
 *
 * Split out of workflow.js as `panels/settings.js`, then cut again on 2026-10-29 by node type:
 * `panels/node-analysis.js`, `panels/node-biblio.js` and `panels/node-chart.js` hold each node's own
 * option lists and form. Every name across those four files is still a page global, because inline
 * `onclick="…"` handlers call it by name; `tests/frontend/splits.json` declares the three as
 * companions of this file so a harness naming one receives all four. */
/* Every control the source panel builds writes exactly one node parameter, and
   the parameter's *name* arrives over the network with the rest of the matrix.
   The handlers are written as inline JS, so a key has to look like an
   identifier: the parity test pins the shape on the Python side, and the guard
   here is what stops a payload that ever stops matching it from becoming a
   script. Values never go through this — they are HTML-escaped where they are
   printed. */
var ID_SHAPE = /^[\w.-]{1,64}$/;

function paramCall(nodeId, key, expr) {
    if (!ID_SHAPE.test(String(nodeId)) || !ID_SHAPE.test(String(key))) return '';
    return "updateParam('" + nodeId + "','" + key + "'," + expr + ')';
}

function numberCall(nodeId, key, fallback) {
    /* The fallback travels as a number the panel itself showed, never as the
       payload's own text: an empty box means "put that back", while a typed 0 is
       a real choice (0 分片 = 不分片, 0 评论预览 = 跳过评论面板) and stays 0. */
    if (!ID_SHAPE.test(String(nodeId)) || !ID_SHAPE.test(String(key))) return '';
    var safe = typeof fallback === 'number' && isFinite(fallback) ? fallback : 0;
    return (
        "updateParam('" +
        nodeId +
        "','" +
        key +
        "',isNaN(parseInt(this.value,10)) ? " +
        safe +
        ' : parseInt(this.value,10))'
    );
}

function reopenCall(nodeId) {
    return ID_SHAPE.test(String(nodeId)) ? ";openSettings('" + nodeId + "')" : '';
}

/* The fields that name *which login* a crawl asks, shown one at a time.

   A node declares a Selenium 账号 and a CatBus 账号; only the one its 采集方式 will read can be filled
   in honestly, and a panel showing both would have the user pick a session for a crawl that never
   looks at it. 采集方式 itself always stays: an unreachable backend is greyed and named on its option
   (``Capabilities.backendState``), because a canvas that STORED the value must show what it holds —
   removing the field would make the panel read as Selenium while the run starts the other one. */
function visibleSourceFields(fields, p) {
    var catbus = String(p.backend || '') === 'catbus';
    return fields.filter(function (f) {
        /* 采集引擎 is rendered above the 采集内容 selector from the platform's engine list, so the
           stored backend keeps one control on screen even though every shared form declares it.
           A payload that predates the engine dimension has no such list; the old in-form select is
           the only control then, and hiding it would leave the stored backend invisible. */
        if (f.key === 'backend') return !Capabilities.engines(String(p.platform || '')).length;
        if (f.key === 'catbus_account') return catbus;
        if (f.key === 'account') return !catbus;
        return true;
    });
}

/* Switching the engine is a change of WHAT this node runs, not a cosmetic filter: if the stored mode
   is not offered by the new engine, the node's ``collect`` moves to the mode the panel will show (the
   engine's first runnable one) in the same write, so the saved canvas and the panel never disagree. */
function setSourceBackend(nodeId, value) {
    if (!ID_SHAPE.test(String(nodeId))) return;
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var params = node.params || {};
    var platform = String(params.platform || '');
    var current = String(params.collect || params.mode || '');
    var offered = Capabilities.modes(platform, value);
    var keys = offered.map(function (m) { return m.key; });
    if (keys.length && keys.indexOf(current) < 0) {
        var fallback = Capabilities.mode(platform, current, value);
        if (fallback && fallback.key !== current) updateParam(nodeId, 'collect', fallback.key);
    }
    updateParam(nodeId, 'backend', value);
}

function sourcePanelHtml(nodeId, p) {
    if (!Capabilities.ready()) {
        return (
            '<div class="settings-group">' +
            '<div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">' +
            I18n.t('settings.capFailed') +
            '</div>' +
            '<button class="menu-btn" type="button" onclick="reloadCapabilities()">' +
            I18n.t('btn.retry') +
            '</button></div>'
        );
    }
    var platform = String(p.platform || '');
    var backend = String(p.backend || '') || Capabilities.defaultBackend(platform);
    var pick = ID_SHAPE.test(String(nodeId)) ? "selectSourcePlatform('" + nodeId + "',this.value)" : '';
    var html = sourceSelectHtml(
        nodeId,
        'settings.platform',
        Capabilities.platforms().map(function (entry) {
            return { value: entry.platform, labelKey: entry.labelKey || 'platform.' + entry.platform };
        }),
        platform,
        pick
    );
    /* 平台 → 引擎 → 功能, in that order. The engine is a first-class choice: it decides which
       functions the next select offers, and a stored choice the adapter no longer supports stays on
       screen, greyed and named, rather than being replaced by Selenium behind the user's back. */
    var engines = Capabilities.engines(platform);
    if (engines.length) {
        var engineOptions = engines.map(function (e) {
            var unavailable = e.available === false;
            return {
                value: e.key,
                labelKey: e.labelKey,
                disabled: unavailable,
                labelSuffix: unavailable ? '（' + I18n.t(e.reasonKey || 'settings.backendProbeFailed') + '）' : '',
            };
        });
        if (
            backend &&
            !engineOptions.some(function (o) {
                return o.value === backend;
            })
        ) {
            var gone = Capabilities.engine(platform, backend);
            engineOptions.push({
                value: backend,
                labelKey: '',
                disabled: true,
                labelSuffix: '（' + I18n.t((gone && gone.reasonKey) || 'settings.backendUnknown') + '）',
            });
        }
        html += sourceSelectHtml(
            nodeId,
            'settings.crawlEngine',
            engineOptions,
            backend,
            ID_SHAPE.test(String(nodeId)) ? "setSourceBackend('" + nodeId + "',this.value)" : ''
        );
        html +=
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);margin-top:-2px;">' +
            I18n.t('settings.engineHint') +
            '</div></div>';
    }
    var mode = Capabilities.mode(platform, p.collect || p.mode, backend);
    if (!mode) {
        /* A platform × engine with no functions cannot be crawled, and the run
           would say so too — but saying it while the panel is open beats letting
           the user fill a form and find out later. The engine's own reason is
           quoted when it has one (no Node, adapter not installed, platform not
           listed, nothing runnable). */
        var engine = Capabilities.engine(platform, backend);
        var engineWhy =
            engine && engine.available === false ? I18n.t(engine.reasonKey || 'settings.backendProbeFailed') : '';
        return (
            html +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.capNoMode') +
            (engineWhy ? '（' + engineWhy + '）' : '') +
            '</div>'
        );
    }
    var offeredModes = Capabilities.modes(platform, backend);
    var wantedMode = String(p.collect || p.mode || '');
    if (offeredModes.length > 1) {
        /* One mode is not a choice: WeChat offers a single form, and a select
           with one option only makes the panel look unfinished. */
        var modeOptions = offeredModes.map(function (m) {
            /* A mode this machine or engine cannot run stays in the list and says why, rather
               than disappearing: a node restored from another canvas has that mode STORED, and
               an option that is simply absent would show the engine's first mode instead — the
               panel lying about what the run would do. Disabled + named is the honest shape. */
            var runnable = Capabilities.runnable(m) && Capabilities.cellRunnable(m, backend);
            var why = runnable ? '' : Capabilities.modeRefusal(platform, m, backend);
            return {
                value: m.key,
                labelKey: m.labelKey,
                disabled: !runnable,
                labelSuffix: runnable ? '' : '（' + why + '）',
            };
        });
        if (
            wantedMode &&
            !offeredModes.some(function (m) {
                return m.key === wantedMode;
            })
        ) {
            /* The stored function is not in this engine's list at all (an old canvas, or a cell
               CatBus dropped). Keep it visible and named: removing it would paint a different
               function as if it were the one written, which is the mismatch this panel exists to
               prevent. The run refuses the stored key by name until the user picks another. */
            modeOptions.unshift({
                value: wantedMode,
                labelKey: '',
                disabled: true,
                labelSuffix: '（' + I18n.t('settings.backendNoCell') + '）',
            });
        }
        html += sourceSelectHtml(
            nodeId,
            'settings.collect',
            modeOptions,
            mode.key,
            paramCall(nodeId, 'collect', 'this.value') + reopenCall(nodeId)
        );
    }
    var fields = visibleSourceFields(Capabilities.fields(platform, mode.key, backend), p);
    for (var i = 0; i < fields.length; i++) {
        html += sourceFieldHtml(nodeId, fields[i], p[fields[i].key], p);
    }
    if (mode.noteKey) {
        html +=
            '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);margin-bottom:6px;">' +
            I18n.t(mode.noteKey) +
            '</div>';
        /* A button the page cannot service is worse than no button, and the name
           arrives over the network: it has to both look like a function name and
           resolve to one before it is wired to a click. */
        if (mode.actionKey && ID_SHAPE.test(String(mode.actionJs)) && typeof window[mode.actionJs] === 'function') {
            html +=
                '<button class="menu-btn" type="button" onclick="' +
                escapeHtml(mode.actionJs) +
                '()">' +
                I18n.t(mode.actionKey) +
                '</button>';
        }
        html += '</div>';
    }
    return html;
}

/* A stored switch, read in whichever grammar wrote it.

   Two spellings are on disk and always have been: `renderParamCheckbox` stored the TEXTS
   'true'/'false' until it started storing `this.checked`, every other checkbox stored the
   boolean, and a hand-written or exported workflow file holds either. `p.x ? 'checked' : ''`
   reads the text 'false' as ON — the box then shows the opposite of what the run does, which
   is the one thing a settings panel may not do. Same rule as the backend's
   `utils.helpers.as_bool`: a value that states nothing (absent, blank, a word neither list
   knows) answers the default the panel shows. */
function boolParam(value, defVal) {
    if (value === undefined || value === null) return !!defVal;
    if (typeof value === 'boolean') return value;
    if (typeof value === 'number') return value === value && value !== 0;
    var text = String(value).trim().toLowerCase();
    if (['true', '1', 'yes', 'y', 'on', '是'].indexOf(text) >= 0) return true;
    if (['false', '0', 'no', 'n', 'off', 'none', 'null', 'nan', '否', '不', '假'].indexOf(text) >= 0) return false;
    return !!defVal;
}

/* One select's options, with the node's own stored value kept on screen when it is not one
   of the choices. Painting the first option instead would show a choice the run then
   refuses BY NAME (the backend refuses an unoffered `select` rather than guessing), so the
   user would re-pick exactly what was already written and still be refused. The extra
   option carries the raw text through escapeHtml: it is the user's own data, most often
   from a file they edited by hand. */
function selectOptionTags(items, stored, defVal) {
    var value =
        stored === undefined || stored === null || String(stored).trim() === ''
            ? String(defVal === undefined ? '' : defVal)
            : String(stored);
    var known = items.some(function (item) {
        return String(item.value) === value;
    });
    var html = items
        .map(function (item) {
            /* ``disabled`` is the one thing a select cannot do with styling: an option the machine
               cannot honour is still a value the element can be asked for (keyboard, a stale draft,
               an autofill). A node restored onto a Linux server keeps its stored mode and shows it
               here as a selected-but-disabled row — the panel says what the canvas already knows,
               and ``sourceNodeErrors`` refuses the run rather than starting it. */
            return (
                '<option value="' +
                escapeHtml(String(item.value)) +
                '"' +
                (known && String(item.value) === value ? ' selected' : '') +
                (item.disabled ? ' disabled' : '') +
                '>' +
                item.label +
                '</option>'
            );
        })
        .join('');
    if (known || value === '') return html;
    return (
        html +
        '<option value="' +
        escapeHtml(value) +
        '" selected>' +
        escapeHtml(I18n.t('settings.unknownOption').replace('{value}', value)) +
        '</option>'
    );
}

function sourceSelectHtml(nodeId, labelKey, options, value, onChange) {
    if (!onChange) return '';
    var html =
        '<div class="settings-group"><label class="settings-label">' +
        I18n.t(labelKey) +
        '</label><select class="settings-select" onchange="' +
        onChange +
        '">';
    html += selectOptionTags(
        options.map(function (o) {
            // A real catalogue key is translated; an empty one (a user-typed account name)
            // shows the value as typed — a name they chose is not the program's word to look up.
            // ``labelSuffix`` is for a reason the option needs to carry itself (a machine
            // requirement this host does not meet), already in the canvas's language.
            return {
                value: o.value,
                label: (o.labelKey ? I18n.t(o.labelKey) : o.value) + (o.labelSuffix || ''),
                disabled: !!o.disabled,
            };
        }),
        value,
        ''
    );
    return html + '</select></div>';
}

function sourceFieldHtml(nodeId, f, value, allParams) {
    if (!ID_SHAPE.test(String(f.key))) return '';
    var v = value === undefined || value === null || value === '' ? f.default : value;
    var hint = sourceFieldHint(f);
    var tail = hint ? '<div style="font-size:11px;color:var(--text-dim);">' + hint + '</div>' : '';
    if (f.control === 'checkbox') {
        /* The label wraps the box on purpose: a 12px caption beside a checkbox is
           a click target, and the panel's other toggles already work that way. */
        return (
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' +
            (boolParam(v, f.default) ? 'checked' : '') +
            ' onchange="' +
            paramCall(nodeId, f.key, 'this.checked') +
            '">' +
            I18n.t(f.labelKey) +
            '</label>' +
            tail +
            '</div>'
        );
    }
    var label = '<label class="settings-label">' + I18n.t(f.labelKey) + '</label>';
    var input;
    if (f.control === 'textarea') {
        /* A field whose list can be fed from an upstream column shows itself disabled
           the moment the user names one: the executor crawls the table, not this box,
           and grey says so before the run rather than after. Which fields can be fed
           is the matrix's answer (f.fedBy), never a list the panel keeps by hand. */
        var fedAway = f.fedBy && allParams && String(allParams[f.fedBy] || '').trim();
        input =
            '<textarea class="settings-input" rows="5" placeholder="' +
            escapeHtml(f.placeholder || '') +
            '" onchange="' +
            paramCall(nodeId, f.key, 'this.value') +
            '"' +
            (fedAway ? ' disabled' : '') +
            '>' +
            escapeHtml(v) +
            '</textarea>';
    } else if (f.control === 'number') {
        input =
            '<input class="settings-input" type="number"' +
            (f.minimum != null ? ' min="' + parseInt(f.minimum, 10) + '"' : '') +
            (f.maximum != null ? ' max="' + parseInt(f.maximum, 10) + '"' : '') +
            ' value="' +
            escapeHtml(v) +
            '" onchange="' +
            numberCall(nodeId, f.key, f.default) +
            '">';
    } else if (f.control === 'select') {
        var isBackend = f.key === 'backend';
        var html = sourceSelectHtml(
            nodeId,
            f.labelKey,
            f.options.map(function (o) {
                if (!isBackend) return { value: o.value, labelKey: o.labelKey };
                /* Which tool this cell can actually run is the server's answer, not a rule here. */
                var ok = Capabilities.backendState(allParams.platform, allParams.collect || allParams.mode, o.value);
                return {
                    value: o.value,
                    labelKey: o.labelKey,
                    disabled: !ok.runnable,
                    labelSuffix: ok.runnable ? '' : '（' + I18n.t(ok.wordKey) + '）',
                };
            }),
            String(v),
            paramCall(nodeId, f.key, 'this.value') + (isBackend ? reopenCall(nodeId) : '')
        );
        return hint ? html + '<div class="settings-group">' + tail + '</div>' : html;
    } else {
        input =
            '<input class="settings-input" value="' +
            escapeHtml(v) +
            '" placeholder="' +
            escapeHtml(f.placeholder || '') +
            '" onchange="' +
            paramCall(nodeId, f.key, 'this.value') +
            '">';
    }
    return '<div class="settings-group">' + label + input + tail + '</div>';
}

function sourceFieldHint(f) {
    if (f.hintKey) return I18n.t(f.hintKey);
    if (f.linksOf) {
        /* The selected platform decides what a usable link looks like, so the
           panel names it instead of listing every site's URL shape at once. */
        return I18n.t('settings.commentUrlsHintPlat').replace('{plat}', I18n.t('platform.' + f.linksOf));
    }
    return '';
}


/* Settings Panel */
function openSettings(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) {
        /* Stale id (the node was deleted while the panel was open, or a redo
           dropped it): never leave an orphan panel on screen. */
        canvas.closeSettingsIfStale();
        return;
    }
    var previousNode = canvas._settingsNodeId;
    var wasOpen = !!previousNode;
    /* Rebuilding the SAME open panel (every parameter edit lands here) must keep its offset —
       the caret may be near the bottom. Opening a DIFFERENT node starts at the top. */
    var sameNode = previousNode === nodeId;
    canvas._settingsNodeId = nodeId;
    /* Focus moves into the panel only on a CLOSED→OPEN transition. openSettings is also the
       rebuild path after every parameter edit, and stealing focus there would drop the caret out
       of the field the user is typing in. Remember the opener so closeSettings can hand focus
       back to it (keyboard users are not dumped to the top of the page). */
    if (!wasOpen) {
        canvas._settingsReturnFocus = document.activeElement;
    }
    var panel = document.getElementById('node-settings');
    var content = document.getElementById('settings-content');
    panel.classList.add('open');
    var html = '<div class="settings-group">' +
        '<label class="settings-label">' + I18n.t('settings.nodeType') + '</label>' +
        '<span style="font-size:12px;color:var(--text-dim);">' + nodeTypeWord(node.type) + '</span>' +
        '</div>';
    /* The columns this node will emit — the edit-time lineage. A producer whose shape
       the server can see lists them; a crawl/comment/resume says so plainly rather than
       guessing. */
    var OUTPUT_PRODUCERS = ['source', 'upload', 'process', 'analysis', 'biblio', 'fuse', 'accumulate', 'tokenize', 'resume', 'comment'];
    if (OUTPUT_PRODUCERS.indexOf(node.type) >= 0 && typeof Diagnostics !== 'undefined') {
        var _oc = Diagnostics.outputColumns(nodeId);
        var _ocText = _oc === null
            ? I18n.t('diagnostics.unknownCols')
            : (_oc.length ? I18n.t('diagnostics.outputCols') + ': ' + escapeHtml(_oc.join(', ')) : I18n.t('diagnostics.outputColsNone'));
        html += '<div class="settings-group node-output-cols" style="font-size:11px;color:var(--text-dim);">' + _ocText + '</div>';
    }
    if (node.type === 'source') {
        /* The form is the matrix: which platforms exist, which of them want
           links instead of a keyword, and every field in between come from
           /api/capabilities (see Capabilities above), so the panel and the
           executor cannot disagree about what a platform offers. */
        html += sourcePanelHtml(nodeId, node.params);
        /* Only a mode whose walk is newest-first and has a stable item identity can
           stop at the previous completed run's boundary. Today that is Bilibili's
           author uploads (BV号); the backend refuses the switch everywhere else. */
        var wmPlatform = node.params.platform || node.platform || '';
        var wmMode = (typeof Capabilities !== 'undefined' && Capabilities.ready())
            ? Capabilities.mode(wmPlatform, node.params.collect || node.params.mode)
            : null;
        if (wmPlatform === 'bilibili' && wmMode && wmMode.handler === 'author') {
            html += '<div class="settings-group"><label class="settings-label">' +
                '<input type="checkbox" ' + (boolParam(node.params.watermark, false) ? 'checked' : '') + ' ' +
                'onchange="updateParam(\'' + nodeId + '\',\'watermark\',this.checked)"> ' +
                I18n.t('settings.watermark') + '</label>' +
                '<div class="settings-hint">' + I18n.t('settings.watermarkHint') + '</div></div>';
        }
    } else if (node.type === 'comment') {
        /* Source-like crawler: article links go in, comment rows come out. The
           panel mirrors the WeChat source block (a multi-line textarea) and the
           recrawl checkbox markup, because zhihu comment pages refuse headless
           sessions — so the hint has to warn that a visible window opens. */
        var p = node.params;
        /* The legacy standalone Comment node (kept for older canvases) has no
           platform selector — each link is dispatched by its own domain, so
           the hint says the mix is deliberate, not an oversight. */
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentUrls') + '</label>' +
            '<textarea class="settings-input" rows="5" placeholder="https://www.zhihu.com/question/... &#10;https://weibo.com/... &#10;https://www.xiaohongshu.com/explore/..." ' +
            'onchange="updateParam(\'' + nodeId + '\',\'urls\',this.value)">' + escapeHtml(p.urls || '') + '</textarea>' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentUrlsHintMixed') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentLimit') + '</label>' +
            '<input class="settings-input" type="number" min="0" value="' + escapeHtml(p.comment_limit != null ? p.comment_limit : 0) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_limit\',parseInt(this.value)||0)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentLimitHint') + '</div></div>' +
            /* A table-side time filter over the comments already crawled — distinct from a
               crawl node's start/end (which bound how far back to CRAWL). Keys are
               comment_start/comment_end so the two never share a name. Both ends or neither:
               a half range is refused by the backend, not guessed. */
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentStart') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.comment_start || '') + '" placeholder="2026-01-01" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_start\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.commentEnd') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.comment_end || '') + '" placeholder="2026-12-31" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'comment_end\',this.value)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentTimeHint') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.partSize') + '</label>' +
            '<input class="settings-input" type="number" min="0" value="' + escapeHtml(p.part_size != null ? p.part_size : 50) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'part_size\',parseInt(this.value)||0)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.partSizeHint') + '</div></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.format') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'format\',this.value)">' +
            selectOptionTags(
                ['csv', 'json'].map(function (f) {
                    return { value: f, label: I18n.t('format.' + f) };
                }),
                p.format,
                'csv'
            ) +
            '</select></div>' +
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (boolParam(p.per_article_file, false) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'per_article_file\',this.checked)">' + I18n.t('settings.perArticleFile') + '</label></div>' +
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (boolParam(p.keep_parts, true) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'keep_parts\',this.checked)">' + I18n.t('settings.keepParts') + '</label></div>' +
            /* 重新采集 belongs here for the same reason it exists on a source node: the comment
               walk shares that walk's ledger, so a comment already stored is skipped rather than
               re-fetched — and a node whose form cannot say "collect again" leaves the user with
               an empty table and no explanation. (Measured: it was missing on every platform's
               comment node, which is what the matrix test now refuses.) */
            '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
            '<input type="checkbox" ' + (boolParam(p.recrawl, false) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'recrawl\',this.checked)">' + I18n.t('settings.recrawl') + '</label>' +
            '<div class="settings-hint">' + I18n.t('settings.recrawlHint') + '</div></div>' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.commentHint') + '</div>';
    } else if (node.type === 'upload') {
        /* The single place a file enters a workflow: pick a CSV / JSON / TXT
           and this node publishes its rows to whatever is connected below. */
        var p = node.params;
        /* Two buttons and a status word share one row; a narrow panel has to wrap them instead
           of pushing the status out of the frame (measured on a 300 px panel: 已加载 was cut). */
        html += '<div class="settings-group upload-actions">' +
            '<button class="menu-btn" onclick="dataNodes.pickFile(\'' + nodeId + '\')">' + I18n.t('btn.uploadFile') + '</button>' +
            /* Asked where this file comes from at the moment the user is holding the picker,
               not from a menu he has to remember existed. */
            '<button class="menu-btn" onclick="toggleSourceHelp()">' + I18n.t('sourceHelp.button') + '</button>' +
            '<span class="upload-status">' +
            (p.dataset_id ? I18n.t('dataSource.loaded') + ': ' + escapeHtml(p.dataset_name || p.dataset_id) : I18n.t('dataSource.none')) +
            '</span></div>';
        if (node._datasetMissing) {
            /* The file this node pointed at is gone from the library, so its id was
               cleared to keep a run off a dead pointer — say what happened, not just
               "no file". */
            html += '<div class="settings-group dataset-missing">' + I18n.t('dataSource.missingRef') + '</div>';
        }
        /* A file already in the dataset library (a prior upload, a paste, an analysis
           result) can be attached without re-uploading it: the executor only needs a
           valid dataset_id. The list is fetched and rendered after the panel opens
           (loadDatasetOptions), so it can be filtered and carry per-file metadata. */
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.chooseDataset') + '</label>' +
            '<div class="dataset-picker">' +
            '<input class="settings-input" id="dataset-filter-' + nodeId + '" placeholder="' +
            escapeHtml(I18n.t('settings.datasetFilter')) + '" oninput="dataNodes.filterDatasets(\'' + nodeId + '\', this.value)">' +
            '<select class="settings-select" id="dataset-pick-' + nodeId + '" ' +
            'onchange="dataNodes.pickFromDataset(\'' + nodeId + '\', this.value)">' +
            '<option value="' + escapeHtml(p.dataset_id || '') + '" selected>' +
            escapeHtml(p.dataset_name || I18n.t('dataSource.chooseLoading')) + '</option></select>' +
            '</div>' +
            '<div id="dataset-hint-' + nodeId + '" class="dataset-hint" style="font-size:11px;color:var(--text-dim);"></div>' +
            '<div style="display:flex;gap:8px;margin-top:6px;">' +
            /* Only offered when there is a dataset to describe: with no file attached the old
               button was rendered anyway and its handler returned without a word, so it looked
               broken (the fused demo's upload node is exactly that state). */
            (p.dataset_id
                ? '<button class="menu-btn" onclick="dataNodes.toggleDatasetDetail(\'' + nodeId + '\')">' +
                  I18n.t('settings.datasetDetail') + '</button>'
                : '') +
            (p.dataset_id ? '<button class="menu-btn" onclick="dataNodes.applyToOtherUploadNodes(\'' + nodeId + '\')">' + I18n.t('settings.applyToOthers') + '</button>' : '') +
            '</div>' +
            '<div id="dataset-detail-' + nodeId + '" class="dataset-detail" style="display:none;"></div></div>';
        if (p.dataset_id && p.row_count) {
            html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
                p.row_count + ' ' + I18n.t('settings.rows') + '</div>';
        }
        if (p.dataset_id) {
            /* Worth saying out loud: this is the reason reopening the saved
               workflow does not ask for the file again. */
            html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('dataSource.persisted') + '</div>';
        }
        html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' +
            I18n.t('btn.previewData') + '</button></div>';
    } else if (node.type === 'accumulate') {
        /* The node appends this run's rows to a named, versioned table and passes the
           full table downstream. Identity is an explicit choice: whole-row equality
           or named key columns; the backend refuses a missing key by name. */
        var p = node.params;
        html += renderParamInput(nodeId, p, 'lineage_name', 'settings.accumulateName', 'text', '');
        html += renderParamSelect(nodeId, p, 'identity', 'settings.accumulateIdentity', 'row', [
            { v: 'row', l: I18n.t('settings.accumulateRow') },
            { v: 'columns', l: I18n.t('settings.accumulateColumns') },
        ]);
        html += renderParamInput(nodeId, p, 'key_columns', 'settings.accumulateKeys', 'text', '');
        var lineageArg = attrJsArg(String(p.lineage_name || '').trim());
        if (lineageArg) {
            html += '<div class="settings-group upload-actions">' +
                '<button class="menu-btn" style="color:var(--err)" ' +
                'onclick="datasetManager.resetLineage(\'' + lineageArg + '\')">' +
                I18n.t('datasetMgr.lineageReset') + '</button></div>';
        }
        html += '<div class="settings-hint">' + I18n.t('settings.accumulateHint') + '</div>';
    } else if (node.type === 'reusable') {
        /* The group's form is about its boundary: the template it carries, the ordered
           input slots an outside wire lands in, its single output, and the two view
           controls. The inside is read-only here — see ReusableNodes. */
        if (typeof ReusableNodes !== 'undefined') html += ReusableNodes.settingsHtml(nodeId);
    } else if (node.type === 'biblio') {
        html += renderBiblioSettings(nodeId, node.params);
    } else if (node.type === 'fuse') {
        html += renderFuseSettings(nodeId, node.params);
    } else if (node.type === 'process') {
        var p = node.params;
        var PROCESS_OPS = ['clean', 'emotion', 'tendency', 'sentiment', 'keyword', 'cluster', 'ner', 'aggression', 'bot', 'anomaly', 'correlation', 'significance'];
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.operation') + '</label>' +
            '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'operation\',this.value);openSettings(\'' + nodeId + '\')">' +
            selectOptionTags(
                PROCESS_OPS.map(function (op) {
                    return { value: op, label: I18n.t('op.' + op) };
                }),
                p.operation,
                'clean'
            ) +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.text_column || '正文') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>';

        /* Clean operation. Two ways to wash a table: the model reads each row and judges
           both artifacts and relevance; the rule set strips what a repost leaves behind
           (转发链, @提及, 话题标签, O网页链接, 展开c) for free. The topic box belongs to the model
           alone, and is therefore not shown for the rules that would ignore it. */
        if (p.operation === 'clean') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'llm', [
                { v: 'llm', l: llmModeLabel() },
                { v: 'regex', l: I18n.t('mode.regex') },
            ]);
            if (p.mode === 'regex') {
                html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                    I18n.t('settings.cleanRegexHint') + '</div></div>';
            } else {
                html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.topic') + '</label>' +
                    '<input class="settings-input" value="' + escapeHtml(p.topic || '') + '" placeholder="e.g. topic" ' +
                    'onchange="updateParam(\'' + nodeId + '\',\'topic\',this.value)"></div>';
            }
        }

        /* Mode selector for emotion / tendency. The default is the fine-tuned BERT path (the
           recommended main model — see docs/why_finetuned_bert.md); a node that names no model runs
           the op's registered default, and the executor degrades to ml with a printed line when bert
           truly cannot run. Both also offer llm (row-by-row) and ml (offline sklearn). */
        if (p.operation === 'emotion' || p.operation === 'tendency') {
            var modeOptions = [
                { value: 'bert', label: I18n.t('mode.bert') },
                { value: 'llm', label: llmModeLabel() },
                { value: 'ml', label: I18n.t('mode.ml') },
            ];
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.mode') + '</label>' +
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'mode\',this.value)">' +
                selectOptionTags(modeOptions, p.mode, 'bert') +
                '</select></div>';
            if (p.mode === 'ml') {
                html += '<div class="settings-group"><button class="menu-btn" onclick="trainMLModel(\'' + nodeId + '\',\'' + p.operation + '\')">' + I18n.t('settings.trainModel') + '</button></div>';
            }
            if (p.mode === 'bert') {
                html += renderBertField(nodeId, p);
            }
        }

        /* Sentiment polarity. Four ways to answer 正面/负面/中性. The default is the fine-tuned BERT
           path (the recommended main model): a node that names no model runs the op's registered
           default, and the executor degrades to SnowNLP with a printed line when bert truly cannot
           run. The thresholds only mean anything to the two modes that answer with a POLARITY
           PROBABILITY — ml and llm answer with a label they were trained or prompted to pick, and
           re-deciding it from their confidence number would be a second opinion about the model's
           own answer (see analyzers/sentiment.py). */
        if (p.operation === 'sentiment') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'bert', [
                { v: 'bert', l: I18n.t('mode.bert') },
                { v: 'snownlp', l: I18n.t('mode.snownlp') },
                { v: 'ml', l: I18n.t('mode.ml') },
                { v: 'llm', l: llmModeLabel() },
            ]);
            if (p.mode === 'snownlp') {
                html += renderParamInput(nodeId, p, 'pos_threshold', 'settings.posThreshold', 'number', 0.6);
                html += renderParamInput(nodeId, p, 'neg_threshold', 'settings.negThreshold', 'number', 0.4);
                html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                    I18n.t('settings.sentimentThresholdHint') + '</div></div>';
            }
            if (p.mode === 'bert') {
                html += renderBertField(nodeId, p);
            }
            if (p.mode === 'ml') {
                html += '<div class="settings-group"><button class="menu-btn" onclick="trainMLModel(\'' + nodeId + '\',\'' + p.operation + '\')">' + I18n.t('settings.trainModel') + '</button></div>';
            }
        }

        /* Keyword extraction. Three methods, and the third is the one for social text:
           jieba's built-in IDF table comes from a news corpus, so Weibo colloquial words
           score wrongly; tfidf_corpus fits the IDF on the user's own table instead. The
           word-class filter is what keeps 转发/哈哈 out of the list. */
        if (p.operation === 'keyword') {
            html += renderParamSelect(nodeId, p, 'method', 'settings.method', 'tfidf',
                [{ v: 'tfidf', l: 'TF-IDF' }, { v: 'textrank', l: 'TextRank' },
                 { v: 'tfidf_corpus', l: I18n.t('settings.methodCorpusIdf') }]);
            html += renderParamInput(nodeId, p, 'topk', 'settings.topk', 'number', 10);
            html += renderParamInput(nodeId, p, 'allow_pos', 'settings.allowPos', 'text', '');
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('settings.allowPosHint') + '</div></div>';
            html += renderParamCheckbox(nodeId, p, 'merge', 'settings.merge', true);
        }

        /* Text clustering */
        if (p.operation === 'cluster') {
            html += renderParamSelect(nodeId, p, 'cluster_method', 'settings.clusterMethod', 'kmeans',
                [{ v: 'kmeans', l: 'K-Means' }, { v: 'kmeans++', l: 'K-Means++' }, { v: 'dbscan', l: 'DBSCAN' }]);
            html += renderParamInput(nodeId, p, 'n_clusters', 'settings.nClusters', 'number', 3);
            html += renderParamInput(nodeId, p, 'eps', 'settings.eps', 'number', 0.5);
            html += renderParamInput(nodeId, p, 'min_samples', 'settings.minSamples', 'number', 2);
        }

        /* Named entities. The rules need no model and stay the default; the
           model is for texts that name people and places without any of the
           surface cues the regexes look for. The category filter applies to
           both, so asking for persons only costs persons only. */
        if (p.operation === 'ner') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'regex',
                [{ v: 'regex', l: I18n.t('mode.regex') }, { v: 'llm', l: llmModeLabel() }]);
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.entityTypes') +
                '</label><input class="settings-input" value="' + escapeHtml(p.entity_types || '') + '" placeholder="' +
                I18n.t('settings.entityTypesPlaceholder') + '" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'entity_types\',this.value)">' +
                '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.entityTypesHint') +
                '</div></div>';
        }

        /* Cyberbullying speech — the study's own object. The word-list path needs no model,
           costs nothing and gives the same answer twice; the model path is for the euphemisms
           a fixed list cannot see. */
        if (p.operation === 'aggression') {
            html += renderParamSelect(nodeId, p, 'mode', 'settings.mode', 'lexicon',
                [{ v: 'lexicon', l: I18n.t('mode.lexicon') }, { v: 'llm', l: llmModeLabel() }]);
            if (p.mode === 'llm') {
                html += renderParamInput(nodeId, p, 'model', 'settings.model', 'text', '');
            }
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('settings.aggressionHint') + '</div></div>';
        }

        /* Bot / 水军 likelihood — per-author coordinated posting, a recall device (not a classifier). */
        if (p.operation === 'bot') {
            html += renderParamInput(nodeId, p, 'text_column', 'settings.textColumn', 'text', '正文');
            html += renderParamInput(nodeId, p, 'author_column', 'settings.botAuthorColumn', 'text', '评论者');
            html += renderParamInput(nodeId, p, 'time_column', 'settings.botTimeColumn', 'text', '评论时间');
            html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
                I18n.t('settings.botHint') + '</div></div>';
        }

        /* Anomaly detection */
        if (p.operation === 'anomaly') {
            html += renderParamInput(nodeId, p, 'columns', 'settings.columns', 'text', '');
            html += renderParamInput(nodeId, p, 'contamination', 'settings.contamination', 'number', 0.1);
        }

        /* Correlation analysis */
        if (p.operation === 'correlation') {
            html += renderParamInput(nodeId, p, 'columns', 'settings.columns', 'text', '');
            html += renderParamSelect(nodeId, p, 'corr_method', 'settings.corrMethod', 'pearson',
                [{ v: 'pearson', l: 'Pearson' }, { v: 'spearman', l: 'Spearman' }, { v: 'kendall', l: 'Kendall' }]);
            html += renderParamInput(nodeId, p, 'min_abs', 'settings.minAbs', 'number', 0.0);
        }

        /* Significance test: compare one numeric column across the levels of one group column.
           ttest/mannwhitney are two-group; anova/kruskal are two-or-more — the analyzer refuses a
           method whose group count it cannot serve, by name, so the panel offers all four and the
           server is the single authority on which is legal (mirrors PROCESS_ENUMS.sig_method). */
        if (p.operation === 'significance') {
            html += renderParamInput(nodeId, p, 'group_column', 'settings.groupColumn', 'text', '');
            html += renderParamInput(nodeId, p, 'value_column', 'settings.valueColumn', 'text', '');
            html += renderParamSelect(nodeId, p, 'sig_method', 'settings.sigMethod', 'ttest', [
                { v: 'ttest', l: "Welch's t" },
                { v: 'anova', l: 'ANOVA' },
                { v: 'mannwhitney', l: 'Mann-Whitney U' },
                { v: 'kruskal', l: 'Kruskal-Wallis H' },
            ]);
        }

        /* AI 调用实时导出: the LLM ops rewrite a {stem}.live.{ext} snapshot
           after every settled batch — watch the enriched rows grow without
           waiting for the node (or the run) to finish. */
        var isLlmOp = nodeNeedsLlm(p, node.operation);
        if (isLlmOp) {
            /* Per-node model override: the transport (provider/host/key) stays
               run-global, but a node may pick its own local Ollama tag. Only
               offered on the ollama provider — an OpenRouter run cannot use a
               daemon tag it has no id for. The real tag list is filled in async
               by renderNodeModelSelect once the panel mounts; until then the box
               shows 跟随全局 plus whatever value is already stored. */
            if (typeof LLMSettings !== 'undefined' && LLMSettings.load().provider === 'ollama') {
                var modelOpts = [{ value: '', label: I18n.t('settings.followGlobalModel') }];
                if (p.model) modelOpts.push({ value: p.model, label: escapeHtml(p.model) });
                html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.nodeModel') + '</label>' +
                    '<select class="settings-select" id="node-model-' + nodeId + '" ' +
                    'onchange="updateParam(\'' + nodeId + '\',\'model\',this.value)">' +
                    selectOptionTags(modelOpts, p.model, '') +
                    '</select></div>';
            }
            html += '<div class="settings-group"><label style="display:flex;gap:6px;align-items:center;font-size:12px;cursor:pointer;">' +
                '<input type="checkbox" ' + (boolParam(p.live_export, false) ? 'checked' : '') + ' ' +
                'onchange="updateParam(\'' + nodeId + '\',\'live_export\',this.checked)">' + I18n.t('settings.liveExport') + '</label>' +
                '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.liveExportHint') + '</div></div>';
        }

        html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    } else if (node.type === 'analysis') {
        html += renderAnalysisSettings(nodeId, node.params);
    } else if (node.type === 'visualize') {
        html += renderVisualizeSettings(nodeId, node.params);
    } else if (node.type === 'tokenize') {
        var p = node.params;
        // Force word_freq when a visualize node is downstream. This is a derived default filled on a
        // MERE OPEN, not a user edit: the value is written so the preview/run reads it, but the panel
        // may not saveState() or updateNodeDisplay() here — that pushed an undo step and lit the dirty
        // dot for looking at a node (the same rule test_opening_a_tokenize_visualize_panel… guards on
        // the visualize side; connectNodes already persists it as a real edit at WIRING time).
        var hasDownstreamVisualize = canvas.connections.some(function (c) { return c.from === nodeId && canvas.nodes[c.to] && canvas.nodes[c.to].type === 'visualize'; });
        if (hasDownstreamVisualize && p.output_mode !== 'word_freq') {
            p.output_mode = 'word_freq';
        }
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.text_column || '') + '" placeholder="' + I18n.t('settings.textColumnPlaceholder') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.outputMode') + '</label>' +
            (hasDownstreamVisualize ? '<div style="font-size:12px;color:var(--accent);padding:4px 0;">' + I18n.t('settings.tokenizeOutputLocked') + '</div>' :
                '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'output_mode\',this.value)">' +
                selectOptionTags(
                    ['word_freq', 'words_only', 'csv_line'].map(function (m) {
                        return { value: m, label: I18n.t('outputMode.' + m) };
                    }),
                    p.output_mode,
                    'word_freq'
                ) +
                '</select>') + '</div>' +
            ((p.output_mode || 'word_freq') === 'word_freq' ?
                '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.topN') + '</label>' +
                '<input class="settings-input" type="number" value="' + escapeHtml(p.top_n || '') + '" placeholder="' + I18n.t('settings.topNPlaceholder') + '" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'top_n\',this.value)"></div>' : '') +
            '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
    } else if (node.type === 'name') {
        /* The workflow's label for the Execution History panel. It is the one
           node that must sit at the head of a workflow and wire into what
           follows, so the panel says so and validates the same way. */
        var p = node.params;
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('name.hint') + '</div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.workflowName') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.workflow_name || '') + '" placeholder="' + I18n.t('name.unnamed') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'workflow_name\',this.value)"></div>' +
            /* 排布顺序 drives autoLayout's vertical stack. Store the RAW string (never
               parseInt || 0): a cleared field must stay blank = "no preference", whereas
               forcing 0 would silently pin this workflow above the other untouched ones. */
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.layoutOrder') + '</label>' +
            '<input class="settings-input" type="number" value="' + escapeHtml(p.layout_order != null ? p.layout_order : '') + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'layout_order\',this.value)">' +
            '<div style="font-size:11px;color:var(--text-dim);">' + I18n.t('settings.layoutOrderHint') + '</div></div>';
    } else if (node.type === 'resume') {
        /* Adopts rows a previous run already paid for. Both lists live on the
           server, so the panel fills them asynchronously below. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('resume.hint') + '</div>' +
            '<div id="resume-pick" data-node="' + nodeId + '">' +
            '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">…</div></div>' +
            '<div class="settings-group"><button class="menu-btn" onclick="renderResumeSettings(\'' + nodeId + '\')">' +
            I18n.t('resume.refresh') + '</button></div>';
    } else if (node.type === 'compile') {
        /* The compile node has no fields of its own: it runs the LaTeX its upstream visualize node produced
           through the local MiKTeX (the xelatex path is set under 设置) and hands a PDF downstream. The one
           precondition worth stating is the one a run otherwise refuses. */
        html += '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' +
            I18n.t('settings.compileHint') + '</div>';
    } else if (node.type === 'output') {
        var p = node.params;
        var pdfOnly = _outputIsPdfOnly(nodeId);
        /* An output fed only by a chart / compile has exactly one valid format; force it in the live
           model so the run sends pdf even if the select is never touched (the extension itself is
           enforced server-side). Filling a derived default on a mere OPEN is not a user edit, so this
           branch must not saveState() — that pushed an undo step and lit the dirty dot for looking. */
        if (pdfOnly && p.format !== 'pdf') {
            p.format = 'pdf';
        }
        var fmt = pdfOnly ? 'pdf' : (p.format || 'csv');
        html += '<div class="settings-group"><div style="font-size:11px;color:var(--text-dim);">' +
            I18n.t(pdfOnly ? 'settings.outputPdfHint' : 'settings.outputMergeHint') + '</div></div>';
        var formatOptions = pdfOnly
            ? [{ value: 'pdf', label: I18n.t('format.pdf') }]
            : ['csv', 'json', 'excel', 'txt', 'html', 'markdown', 'parquet'].map(function (f) {
                  return { value: f, label: I18n.t('format.' + f) };
              });
        html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.format') + '</label>' +
            '<select class="settings-select" onchange="onOutputFormatChange(\'' + nodeId + '\',this.value)">' +
            selectOptionTags(formatOptions, p.format, pdfOnly ? 'pdf' : 'csv') +
            '</select></div>' +
            '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.filename') + '</label>' +
            '<input class="settings-input" value="' + escapeHtml(p.filename || (pdfOnly ? 'export.pdf' : 'export.csv')) + '" ' +
            'onchange="updateParam(\'' + nodeId + '\',\'filename\',this.value)"></div>' +
            '<div class="settings-group"><label class="settings-checkbox-label">' +
            '<input type="checkbox" ' + (boolParam(p.filename_timestamp, false) ? 'checked' : '') + ' ' +
            'onchange="updateParam(\'' + nodeId + '\',\'filename_timestamp\',this.checked)"> ' +
            I18n.t('settings.filenameTimestamp') + '</label></div>';
        if (!pdfOnly && _upstreamDeclaresWindow(nodeId)) {
            html += '<div class="settings-group"><label class="settings-checkbox-label">' +
                '<input type="checkbox" ' + (boolParam(p.filename_time_range, false) ? 'checked' : '') + ' ' +
                'onchange="updateParam(\'' + nodeId + '\',\'filename_time_range\',this.checked)"> ' +
                I18n.t('settings.filenameTimeRange') + '</label></div>';
        }
        if (!pdfOnly && fmt === 'txt') {
            html += '<div class="settings-group"><label class="settings-label">' + I18n.t('settings.textColumn') + '</label>' +
                '<input class="settings-input" value="' + escapeHtml(p.text_column || '') + '" placeholder="optional: one column per line" ' +
                'onchange="updateParam(\'' + nodeId + '\',\'text_column\',this.value)"></div>';
        }
        if (!pdfOnly) {
            html += '<div class="settings-group"><button class="menu-btn" onclick="dataNodes.previewData(\'' + nodeId + '\')">' + I18n.t('btn.previewData') + '</button></div>';
        }
    }
    content.innerHTML = html;
    if (!sameNode) {
        /* Opening for a DIFFERENT node starts at the top. The panel is the scroll container, and
           it used to keep the previous form's offset: open a long node, scroll to its bottom,
           then open a short one and the panel shows blank space below the content until you
           scroll up yourself. A rebuild of the SAME open panel (every parameter edit) keeps its
           offset — the caret may be down there. */
        panel.scrollTop = 0;
        content.scrollTop = 0;
        /* The resize grip is pinned by cancelling the panel's scroll; after a reset the cancelling
           transform has to follow the new offset or the grip lands somewhere else for a frame. */
        var grip = panel.querySelector('.resize-handle');
        if (grip) grip.style.transform = 'translate(0px,0px)';
    }
    if (node.type === 'resume') renderResumeSettings(nodeId);
    if (node.type === 'upload') dataNodes.loadDatasetOptions(nodeId);
    if (
        node.type === 'process' &&
        nodeNeedsLlm(node.params, node.operation) &&
        typeof LLMSettings !== 'undefined' &&
        LLMSettings.load().provider === 'ollama'
    ) {
        renderNodeModelSelect(nodeId);
    }
    canvas.updateSettingsButton();
    if (!wasOpen) _focusFirstSetting();
}

/* Move the caret to the panel's first editable control when it is freshly opened, so a
   keyboard user who reaches a node lands inside its form rather than behind the canvas.
   Only ever called on a closed→open transition, so a rebuild during typing never fires it. */
function _focusFirstSetting() {
    var content = document.getElementById('settings-content');
    if (!content || !content.querySelector) return;
    var first = content.querySelector('input:not([type=hidden]), select, textarea, button');
    if (first && first.focus) first.focus();
}

/* ── Per-node Ollama model picker: fill the node's model select from the
   daemon's own tags ──
   The panel renders synchronously, so the box starts with just 跟随全局 + the
   stored value; this runs after mount and repopulates it with the real list.
   One fetch per session (the daemon list rarely changes while the page is
   open) — 刷新 in the AI panel stays the way to force a re-read. Guarded on the
   ollama provider by the caller. */
var _nodeOllamaModels = null; // cached tag list, or '' once a fetch failed
async function renderNodeModelSelect(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    if (_nodeOllamaModels === null) {
        try {
            var resp = await fetch('/api/llm/ollama/models');
            var result = await resp.json();
            _nodeOllamaModels = (result.ok && result.models) || [];
        } catch (e) {
            _nodeOllamaModels = ''; // say it failed once, do not re-hit every panel open
        }
    }
    // A node captured before the await is not on the page after it: re-look the
    // select up (the panel may have been rebuilt while we were fetching).
    node = canvas.nodes[nodeId];
    var sel = document.getElementById('node-model-' + nodeId);
    if (!node || !sel) return;
    var current = node.params && node.params.model ? node.params.model : '';
    var tags = _nodeOllamaModels === '' ? [] : _nodeOllamaModels;
    var items = [{ value: '', label: I18n.t('settings.followGlobalModel') }];
    tags.forEach(function (m) {
        items.push({ value: m, label: escapeHtml(m) });
    });
    if (current && !tags.some(function (m) { return m === current; })) {
        items.push({ value: current, label: escapeHtml(current) });
    }
    sel.innerHTML = selectOptionTags(items, current, '');
}

/* ── Resume node: pick a stored run and one of its node outputs ── */
async function renderResumeSettings(nodeId) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var p = node.params;
    var runs = [];
    try {
        var resp = await fetch('/api/runs/resumable', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ workflow: canvas.toWorkflowJSON(), all: true }),
        });
        var result = await resp.json();
        runs = (result.ok && result.runs) || [];
    } catch (e) {
        runs = [];
    }
    /* Looked up AFTER the await, and attributed to the node it belongs to.
       `openSettings` rewrites the whole form — which any parameter edit does — so the
       holder this call started with can be off the page when the answer lands, and the
       dropdown then never appears while everything looks idle. The guard used to run
       before the await, which is the one moment it could not be wrong. */
    /* Looked up AFTER the await, and attributed to the node it belongs to.
       `openSettings` rewrites the whole form — which any parameter edit does — so the
       holder this call started with can be off the page when the answer lands, and the
       dropdown then never appears while everything looks idle. The guard used to run
       before the await, which is the one moment it could not be wrong. */
    var holder = document.getElementById('resume-pick');
    if (!holder || holder.dataset.node !== nodeId) return;
    if (!runs.length) {
        holder.innerHTML = '<div class="settings-group" style="font-size:11px;color:var(--text-dim);">' + I18n.t('resume.none') + '</div>';
        return;
    }
    /* Whatever it was pointed at may have been purged since; falling back to
       the newest keeps the node usable instead of silently reading nothing. This is
       the panel filling its own default on a render, not the user choosing — so it
       writes the value (the dropdown and the run both read it) but must not saveState(),
       or merely opening the resume panel would push an undo step and mark the file dirty. */
    if (!runs.some(function (r) { return r.run_id === p.resume_run_id; })) {
        p.resume_run_id = runs[0].run_id;
    }
    var run = runs.filter(function (r) { return r.run_id === p.resume_run_id; })[0] || runs[0];
    var nodes = (run.nodes || []).filter(function (n) { return (n.row_count || 0) > 0; });
    if (!nodes.some(function (n) { return n.node_id === p.resume_node_id; })) {
        p.resume_node_id = '';
    }
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.runSelect') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'resume_run_id\',this.value);renderResumeSettings(\'' + nodeId + '\')">' +
        runs.map(function (r) {
            var label = (r.started_at || r.run_id) + ' · ' + (r.rows_kept || 0) + ' ' + I18n.t('settings.rows');
            return '<option value="' + escapeHtml(r.run_id) + '"' + (r.run_id === p.resume_run_id ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('') +
        '</select></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.nodeSelect') + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'resume_node_id\',this.value);canvas.updateNodeDisplay(\'' + nodeId + '\')">' +
        '<option value=""' + (!p.resume_node_id ? ' selected' : '') + '>' + I18n.t('resume.autoNode') + '</option>' +
        nodes.map(function (n) {
            var label = (n.title || n.node_id) + ' · ' + n.row_count + ' ' + I18n.t('settings.rows');
            return '<option value="' + escapeHtml(n.node_id) + '"' + (n.node_id === p.resume_node_id ? ' selected' : '') + '>' + escapeHtml(label) + '</option>';
        }).join('') +
        '</select></div>';
    html += '<div class="settings-group"><label class="settings-label">' + I18n.t('resume.limit') + '</label>' +
        '<input class="settings-input" type="number" value="' + escapeHtml(p.resume_limit || 0) + '" placeholder="' + I18n.t('resume.limitPlaceholder') + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'resume_limit\',parseInt(this.value)||0)"></div>';
    holder.innerHTML = html;
    canvas.updateNodeDisplay(nodeId);
}

/* Format -> file-extension map for the Save node. Keeps the filename's
   extension in sync whenever the user picks a different export format,
   instead of leaving a stale ".csv" on a JSON/Excel/... export. */
var FORMAT_EXTENSIONS = { csv: '.csv', json: '.json', excel: '.xlsx', txt: '.txt', html: '.html', markdown: '.md', pdf: '.pdf' };

function onOutputFormatChange(nodeId, fmt) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var filename = node.params.filename || 'export.csv';
    var dot = filename.lastIndexOf('.');
    var base = dot > 0 ? filename.slice(0, dot) : filename;
    node.params.operation = 'save';
    node.params.format = fmt;
    node.params.filename = base + (FORMAT_EXTENSIONS[fmt] || '.csv');
    canvas.updateNodeDisplay(nodeId);
    canvas.saveState();
    openSettings(nodeId);
}

/* ── Which process nodes really call a model ──
 * The run-gate and the AI 实时导出 checkbox used to spell this rule out
 * separately, and the two had already begun to drift. backend/app.py
 * (_workflow_needs_llm) keeps the same list, because a workflow that never
 * reaches a model must not be blocked by a missing API key or an unpicked
 * Ollama tag. Note the opposite defaults: emotion/tendency ask the model
 * unless told not to, NER uses its rules unless told otherwise. The second
 * argument is the node's own ``operation``, which toWorkflowJSON also carries:
 * the backend reads that one first, so this has to as well. */
function llmModeLabel() {
    /* Which transport the 「大模型」 option names. Guarded on the BINDING, not on
       `window.CloudMode`: app.js declares it at top level, so it is a global lexical
       binding that never appears on window, and `if (window.X)` would read as "no flag"
       forever — which is the mistake this repo already documents once. */
    var cloud = typeof CloudMode !== 'undefined' && CloudMode.on;
    return I18n.t(cloud ? 'mode.llmCloud' : 'mode.llm');
}

function nodeNeedsLlm(params, nodeOperation) {
    var p = params || {};
    var op = p.operation || nodeOperation || '';
    /* Trimmed, because a BLANK means the operation's declared default on the server —
       `'  '` is not a mode name and app.py reads it as "not stated". Comparing the raw
       value here answered "no model" for a whitespace-only field while the server
       answered "the default", so one of the two blocked a run the other would allow. */
    var mode = String(p.mode === undefined || p.mode === null ? '' : p.mode).trim();
    /* Asked by NAME, never by "not the one I special-case". `mode !== 'ml'` was the old
       reading and it charged a row-by-row model pass to a node whose mode said something
       else — sentiment has four modes now, three of which need no model at all. A blank
       means the operation's own declared default, which is what the backend reads too
       (app.py `_op_needs_llm`). */
    if (op === 'clean') return (mode || 'llm') === 'llm';
    if (op === 'emotion' || op === 'tendency') return (mode || 'bert') === 'llm';
    if (op === 'sentiment') return (mode || 'bert') === 'llm';
    if (op === 'ner') return mode === 'llm';
    return false;
}

/* ── Shared settings UI helpers ── */
function renderParamInput(nodeId, p, key, labelKey, type, defVal) {
    return '<div class="settings-group"><label class="settings-label">' + I18n.t(labelKey) + '</label>' +
        '<input class="settings-input" type="' + type + '" value="' + escapeHtml(p[key] !== undefined ? p[key] : defVal) + '" ' +
        'onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.value)"></div>';
}
function renderParamSelect(nodeId, p, key, labelKey, defVal, options) {
    var html = '<div class="settings-group"><label class="settings-label">' + I18n.t(labelKey) + '</label>' +
        '<select class="settings-select" onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.value)">';
    html += selectOptionTags(
        options.map(function (o) {
            return { value: o.v, label: o.l || o.v };
        }),
        p[key],
        defVal
    );
    html += '</select></div>';
    return html;
}
function renderParamCheckbox(nodeId, p, key, labelKey, defVal) {
    var checked = boolParam(p[key], defVal);
    return '<div class="settings-group"><label class="settings-label">' +
        '<input type="checkbox" ' + (checked ? 'checked' : '') + ' ' +
        'onchange="updateParam(\'' + nodeId + '\',\'' + key + '\',this.checked)"> ' +
        I18n.t(labelKey) + '</label></div>';
}

