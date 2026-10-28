/* Data views: the upload/preview helpers, the dashboard grid and the execution history.
 * Split out of workflow.js; loaded after it so every global name stays resolvable. */

/* ── Data helpers for the Upload node: pick a file / preview it ──
   The Upload node is the single entry point for files, so a workflow can
   start from an uploaded CSV/JSON/TXT instead of a crawl. Downstream
   nodes just see rows, whoever produced them. */
var dataNodes = {
    _pendingNodeId: null,
    _datasets: null,
    _filter: {},

    pickFile(nodeId) {
        this._pendingNodeId = nodeId;
        document.getElementById('dataset-file-input').click();
    },

    async handleFileSelected(evt) {
        var file = evt.target.files[0];
        var nodeId = this._pendingNodeId;
        evt.target.value = '';
        if (!file || !nodeId) return;
        var form = new FormData();
        form.append('file', file);
        try {
            var resp = await fetch('/api/data/upload', { method: 'POST', body: form });
            var result = await resp.json();
            if (result.ok) {
                var node = canvas.nodes[nodeId];
                if (node) {
                    node.params.dataset_id = result.dataset_id;
                    node.params.dataset_name = result.name || '';
                    node.params.row_count = result.row_count || 0;
                    /* A .txt arrives as one row in a 'content' column — worth
                       saying out loud, since word clouds read that column. */
                    var uploadMsg = result.biblio_format
                        ? I18n.t('toast.biblioUploaded').replace('{format}', result.biblio_format).replace('{n}', result.row_count)
                        : result.is_txt
                            ? I18n.t('toast.txtUploaded') + ' (' + result.row_count + ' rows)'
                            : I18n.t('toast.datasetUploaded') + ' (' + result.row_count + ' rows)';
                    /* Dropped duplicates / year-less records are part of what
                       the import decided; a toast that only says "N records"
                       would hide the rows that did not arrive. */
                    if (result.warnings && result.warnings.length) {
                        uploadMsg += ' · ' + result.warnings.join('；');
                    }
                    showToast(uploadMsg);
                    canvas.updateNodeDisplay(nodeId);
                    canvas.saveState();
                }
                if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
            } else {
                showToast(I18n.t('toast.uploadFailed') + ': ' + result.error);
            }
        } catch (e) {
            showToast(I18n.t('toast.uploadFailed') + ': ' + e.message);
        }
    },

    /* Fill the Upload node's dataset dropdown from the stored files.
       The panel renders synchronously with only the current selection, so the
       list is fetched here, cached with its full metadata, and rendered through
       renderDatasetOptions (which can filter it). */
    async loadDatasetOptions(nodeId) {
        var result = await fetchJSON('/api/data/datasets?limit=1000').catch(function () { return null; });
        if (!result || !result.ok) return;
        var datasets = result.datasets || [];
        dataNodes._datasets = {};
        datasets.forEach(function (d) { dataNodes._datasets[d.dataset_id] = d; });
        /* Re-look-up after the await: the panel may have been rebuilt or closed
           while the request was in flight. */
        if (canvas._settingsNodeId !== nodeId) return;
        if (!canvas.nodes[nodeId]) return;
        dataNodes.renderDatasetOptions(nodeId);
    },

    /* A dropdown row is a whole file description, not just a name: many uploads share
       a filename, so source, size and shape are what tell them apart. */
    _dsLabel(d) {
        var parts = [d.name || I18n.t('name.unnamed'), (d.row_count || 0) + ' ' + I18n.t('settings.rows')];
        if (d.columns && d.columns.length) parts.push(d.columns.length + ' ' + I18n.t('settings.columns'));
        if (d.source && typeof datasetManager !== 'undefined') parts.push(datasetManager._sourceLabel(d.source));
        return parts.join(' · ');
    },

    /* Rebuild the dropdown from the cache, filtered by this node's search term and
       ordered most-recently-used first. selectOptionTags keeps a value that is no
       longer in the list visible rather than silently dropping it to option #0. */
    renderDatasetOptions(nodeId) {
        var select = document.getElementById('dataset-pick-' + nodeId);
        if (!select) return;
        var all = dataNodes._datasets || {};
        var ids = Object.keys(all);
        var list = ids.map(function (id) { return all[id]; });
        list.sort(function (a, b) {
            var ka = String(a.last_used_at || a.created_at || '');
            var kb = String(b.last_used_at || b.created_at || '');
            return ka < kb ? 1 : (ka > kb ? -1 : 0);
        });
        var term = String((dataNodes._filter && dataNodes._filter[nodeId]) || '').trim().toLowerCase();
        if (term) list = list.filter(function (d) { return String(d.name || '').toLowerCase().indexOf(term) >= 0; });
        var node = canvas.nodes[nodeId];
        var current = node && node.params && node.params.dataset_id ? node.params.dataset_id : '';
        var items = list.map(function (d) {
            return { value: d.dataset_id, label: escapeHtml(dataNodes._dsLabel(d)) };
        });
        select.innerHTML = '<option value="">' + escapeHtml(I18n.t('dataSource.choosePlaceholder')) + '</option>' +
            selectOptionTags(items, current, '');
        select.value = current;
        var hint = document.getElementById('dataset-hint-' + nodeId);
        if (hint) {
            if (!ids.length) {
                hint.innerHTML = escapeHtml(I18n.t('dataSource.emptyLibrary')) +
                    ' <button class="menu-btn" onclick="datasetManager.toggle()">' +
                    escapeHtml(I18n.t('dataSource.openManager')) + '</button>';
            } else if (!list.length) {
                hint.textContent = I18n.t('dataSource.noMatch');
            } else {
                hint.innerHTML = '';
            }
        }
    },

    async loadBiblioBasemapOptions(nodeId) {
        var result = await fetchJSON('/api/data/datasets?limit=1000').catch(function () { return null; });
        if (!result || !result.ok) return;
        dataNodes._datasets = {};
        (result.datasets || []).forEach(function (d) { dataNodes._datasets[d.dataset_id] = d; });
        var select = document.getElementById('biblio-basemap-' + nodeId);
        if (!select || !canvas.nodes[nodeId]) return;
        var current = String(canvas.nodes[nodeId].params.basemap_dataset_id || '');
        var items = Object.keys(dataNodes._datasets).map(function (id) {
            return { value: id, label: escapeHtml(dataNodes._dsLabel(dataNodes._datasets[id])) };
        });
        select.innerHTML = '<option value="">' + escapeHtml(I18n.t('biblio.ui.noBasemap')) + '</option>' +
            selectOptionTags(items, current, '');
        select.value = current;
    },

    filterDatasets(nodeId, term) {
        if (!dataNodes._filter) dataNodes._filter = {};
        dataNodes._filter[nodeId] = term;
        dataNodes.renderDatasetOptions(nodeId);
    },

    /* Show the attached file's shape and who reads it: the metadata the dropdown row
       had no room for, plus which nodes on THIS canvas point at the same dataset. */
    toggleDatasetDetail(nodeId) {
        var box = document.getElementById('dataset-detail-' + nodeId);
        if (!box) return;
        if (box.style.display !== 'none') { box.style.display = 'none'; return; }
        var node = canvas.nodes[nodeId];
        var id = node && node.params ? node.params.dataset_id : '';
        if (!id) { box.style.display = 'none'; return; }
        var render = function (meta) {
            if (!meta) { box.style.display = 'none'; return; }
            var users = Object.keys(canvas.nodes).filter(function (nid) {
                var n = canvas.nodes[nid];
                return n && n.type === 'upload' && n.params && n.params.dataset_id === meta.dataset_id;
            });
            var rows = [
                [I18n.t('settings.file'), meta.name || I18n.t('name.unnamed')],
                [I18n.t('datasetMgr.colSource'), typeof datasetManager !== 'undefined' ? datasetManager._sourceLabel(meta.source) : (meta.source || '-')],
                [I18n.t('settings.rows'), String(meta.row_count || 0)],
                [I18n.t('settings.columns'), (meta.columns && meta.columns.length) ? meta.columns.join(', ') : '-'],
                ['id', meta.dataset_id],
                [I18n.t('dataSource.thisCanvasNodes'), users.join(', ') || '-'],
            ];
            if (meta.workflows && meta.workflows.length) rows.push([I18n.t('datasetMgr.colUsedBy'), meta.workflows.join(', ')]);
            box.innerHTML = '<table class="dataset-detail-table"><tbody>' + rows.map(function (r) {
                return '<tr><th>' + escapeHtml(r[0]) + '</th><td>' + escapeHtml(r[1]) + '</td></tr>';
            }).join('') + '</tbody></table>';
            box.style.display = '';
        };
        var cached = dataNodes._datasets && dataNodes._datasets[id];
        if (cached) { render(cached); return; }
        fetchJSON('/api/data/datasets/' + encodeURIComponent(id))
            .then(function (res) {
                if (res && res.ok && res.dataset) { render(res.dataset); return; }
                /* The file is gone from the library, or the read failed. Hiding the box silently
                   is what made 详情 look like a dead button — name the reason instead. */
                showToast(I18n.t('dataSource.detailFailed').replace('{err}', (res && res.error) || ''));
            })
            .catch(function (e) {
                showToast(I18n.t('dataSource.detailFailed').replace('{err}', (e && e.message) || ''));
            });
    },

    /* One crawl paid for is worth reusing across every Upload node on the canvas:
       copy this node's dataset pointer to all the others, no re-picking. */
    applyToOtherUploadNodes(nodeId) {
        var src = canvas.nodes[nodeId];
        if (!src || !src.params || !src.params.dataset_id) return;
        var others = Object.keys(canvas.nodes).filter(function (nid) {
            var n = canvas.nodes[nid];
            return nid !== nodeId && n && n.type === 'upload';
        });
        if (!others.length) { showToast(I18n.t('dataSource.noOtherUploadNodes')); return; }
        others.forEach(function (nid) {
            var n = canvas.nodes[nid];
            n.params.dataset_id = src.params.dataset_id;
            n.params.dataset_name = src.params.dataset_name;
            n.params.row_count = src.params.row_count;
            n._datasetMissing = false;
            var el = canvas._nodeEl(nid);
            if (el) el.classList.remove('node-missing');
            canvas.updateNodeDisplay(nid);
        });
        canvas.saveState();
        showToast(I18n.t('dataSource.appliedToOthers').replace('{n}', others.length));
    },

    /* Attach a stored dataset to the Upload node without re-uploading it: set the
       same three params a fresh upload writes, so the card, preview and the run
       executor all treat it identically. */
    pickFromDataset(nodeId, datasetId) {
        var node = canvas.nodes[nodeId];
        if (!node) return;
        if (!datasetId) {
            node.params.dataset_id = '';
            node.params.dataset_name = '';
            node.params.row_count = '';
            canvas.updateNodeDisplay(nodeId);
            canvas.saveState();
            if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
            return;
        }
        var apply = function (meta) {
            if (!meta) return;
            node.params.dataset_id = meta.dataset_id;
            node.params.dataset_name = meta.name || '';
            node.params.row_count = meta.row_count || 0;
            /* Attaching a live file clears any "reference is broken" state. */
            node._datasetMissing = false;
            var el = canvas._nodeEl(nodeId);
            if (el) el.classList.remove('node-missing');
            canvas.updateNodeDisplay(nodeId);
            canvas.saveState();
            showToast(I18n.t('dataSource.datasetSelected').replace('{name}', meta.name || meta.dataset_id));
            if (canvas._settingsNodeId === nodeId) openSettings(nodeId);
        };
        var cached = dataNodes._datasets && dataNodes._datasets[datasetId];
        if (cached) {
            apply(cached);
            return;
        }
        fetchJSON('/api/data/datasets/' + encodeURIComponent(datasetId))
            .then(function (result) { apply(result && result.ok ? result.dataset : null); })
            .catch(function () { /* offline: leave the node untouched */ });
    },

    /* Keep every Upload node in touch with the file it points at.

       Uploaded files are stored in a database on the server, so a node's
       dataset_id is a pointer that outlives the page: a refresh, a restart or
       reopening the saved workflow should leave the file attached. Instead of
       throwing those ids away on every load, re-check them — the file is used
       when it is still there, and only nodes whose file really is gone fall
       back to asking for it again. */
    async reconcileDatasets() {
        var pending = Object.keys(canvas.nodes).filter(function (id) {
            var n = canvas.nodes[id];
            return n && n.type === 'upload' && n.params && n.params.dataset_id;
        });
        if (!pending.length) return;
        var known = {};
        try {
            var resp = await fetch('/api/data/datasets?limit=1000');
            var result = await resp.json();
            /* A SUCCESSFUL list is the only answer that licenses clearing an id. A non-OK status,
               a refusal body (the cross-origin guard answers ``{ok:false}`` with a 403), or a shape
               with no ``datasets`` array is the server saying NOTHING — reading it as "every file is
               gone" would clear every Upload node's ``dataset_id`` and then autosave the emptied
               canvas over the author's workflow file. A genuinely empty library returns
               ``{ok:true, datasets:[]}`` and is still honoured below. */
            if (!resp.ok || !result || result.ok === false || !Array.isArray(result.datasets)) return;
            result.datasets.forEach(function (d) { known[d.dataset_id] = d; });
        } catch (e) {
            /* Offline or a dead server: keep the ids. Losing them would mean
               re-uploading a file that is very likely still on disk. */
            return;
        }
        var missing = [];
        var changed = false;
        pending.forEach(function (id) {
            var node = canvas.nodes[id];
            if (!node) return;
            var meta = known[node.params.dataset_id];
            if (!meta) {
                node.params.dataset_id = '';
                node.params.dataset_name = '';
                node.params.row_count = '';
                /* The file is gone: the id is cleared so a run never reads a dead
                   pointer, but the node remembers it WAS broken so the panel and the
                   box say so, not just "no file". */
                node._datasetMissing = true;
                var missEl = canvas._nodeEl(id);
                if (missEl) missEl.classList.add('node-missing');
                missing.push(node.title || id);
                changed = true;
            } else {
                var beforeName = node.params.dataset_name;
                var beforeCount = node.params.row_count;
                node.params.dataset_name = meta.name || node.params.dataset_name || '';
                node.params.row_count = meta.row_count || 0;
                if (beforeName !== node.params.dataset_name || beforeCount !== node.params.row_count) changed = true;
                if (node._datasetMissing) {
                    node._datasetMissing = false;
                    changed = true;
                }
                var okEl = canvas._nodeEl(id);
                if (okEl) okEl.classList.remove('node-missing');
            }
            canvas.updateNodeDisplay(id);
            if (canvas._settingsNodeId === id) openSettings(id);
        });
        /* Only a real change earns a save; a healthy canvas merely refreshed must not push an undo
           step, light the dirty dot, or rewrite the workflow file every time it loads. */
        if (changed) canvas.saveState();
        if (missing.length) showToast(I18n.t('toast.datasetsMissing') + ': ' + missing.join(', '));
    },

    async previewVisualize(nodeId) {
        var node = canvas.nodes[nodeId];
        if (!node) return;
        var p = node.params;
        _chartPreviewName = node.title || nodeId;
        _chartPreviewNodeId = nodeId;
        var payload = {
            chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
            y_field: p.y_field, value_field: p.value_field, agg: p.agg,
            center_node: p.center_node,
            label_field: p.label_field, stack_fields: p.stack_fields,
            model_field: p.model_field, agreement_label_field: p.agreement_label_field, id_field: p.id_field,
            title: p.title, tokenize: boolParam(p.tokenize, false),
            emit_latex: boolParam(p.emit_latex, true), emit_latex_table: boolParam(p.emit_latex_table, true),
            wordcloud_style: p.wordcloud_style || 'vibrant',
        };
        /* A chart always renders whatever its upstream produced — a crawl or
           an Upload node's file, it makes no difference here. */
        var upstream = canvas.getUpstreamNodeId(nodeId);
        if (!upstream) {
            showToast(I18n.t('toast.previewNeedsInput'));
            return;
        }
        payload.node_id = upstream;
        /* The chart is re-rendered from the upstream node's rows. Right after a run
           those are still in the server's memory; after a page refresh AND a server
           restart they only exist in the run store, which is addressed by workflow —
           so send the same identity `previewData` sends, or a chart cannot be brought
           back once the process that ran it is gone. */
        payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
        /* Pin the run the user loaded, so a historical preview does not read the
           newest rows of each node independently. */
        if (typeof runResults !== 'undefined') runResults.payload(payload);
        /* Show panel with loading spinner immediately */
        var panel = document.getElementById('chart-preview-panel');
        panel.classList.add('open');
        var echartsDiv = document.getElementById('chart-preview-echarts');
        if (_chartPreviewInstance) {
            _chartPreviewInstance.dispose();
            _chartPreviewInstance = null;
        }
        echartsDiv.innerHTML = '<div class="loading-container"><div class="loading-spinner"></div></div>';
        echartsDiv.style.display = 'block';
        document.getElementById('chart-preview-image').style.display = 'none';
        try {
            var resp = await fetch('/api/visualize/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            if (result.ok) {
                renderChartPreview(result);
            } else {
                var fv = _renderFailureView(result);
                if (!fv.note) showToast(I18n.t('toast.renderFailed') + ': ' + result.error);
                echartsDiv.innerHTML = fv.note
                    ? '<div class="dashboard-cell-note">' + escapeHtml(fv.message) + '</div>'
                    : '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:12px;">' + escapeHtml(fv.message) + '</div>';
            }
        } catch (e) {
            showToast(I18n.t('toast.renderFailed') + ': ' + e.message);
            echartsDiv.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:12px;">' + escapeHtml(e.message) + '</div>';
        }
    },

    /* Preview the raw tabular data produced by a node:
        - source / process / analysis nodes → show their own result (post-transform)
        - output / visualize nodes → show whatever their upstream connection
          last produced (pass-through / consume-only nodes).
       Requires the workflow to have been executed at least once so
       execution_state has a result for the requested node. */
    async previewData(nodeId) {
        var node = canvas.nodes[nodeId];
        if (!node) return;
        var payload = {};
        if (node.type === 'upload') {
            /* Its own file, no execution needed. */
            if (!node.params.dataset_id) {
                showToast(I18n.t('toast.previewNeedsUpload'));
                return;
            }
            payload.dataset_id = node.params.dataset_id;
        } else if (['source', 'process', 'analysis', 'tokenize'].indexOf(node.type) >= 0) {
            payload.node_id = nodeId;
        } else {
            var upstream = canvas.getUpstreamNodeId(nodeId);
            if (!upstream) {
                showToast(I18n.t('toast.previewNeedsInput'));
                return;
            }
            payload.node_id = upstream;
            // Pass output format so preview matches saved file format.
            if (node.type === 'output' && node.params.format) {
                payload.preview_format = node.params.format;
            }
        }
        if (payload.node_id) {
            /* Which workflow's rows this is: recorded rows are looked up by name
               once the live results are gone (a refresh, a server restart). */
            payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
            if (typeof runResults !== 'undefined') runResults.payload(payload);
        }
        await dataPreview.open(payload);
    },
};

/* ── Train ML model from upstream node data ── */
async function trainMLModel(nodeId, modelType) {
    var node = canvas.nodes[nodeId];
    if (!node) return;
    var payload = {};
    /* Training data comes from upstream, like every other data-consuming
       node: a file reaches here through an Upload node, not from a dataset
       stored on this node. */
    var upstream = canvas.getUpstreamNodeId(nodeId);
    if (!upstream) {
        showToast(I18n.t('toast.mlUpstreamNeeded'));
        return;
    }
    payload.node_id = upstream;
    // The rows to train on may live only in the run store (a page refresh and a server
    // restart), and that store refuses a bare node id — name the workflow so training can
    // still find the labels after the process that produced them is gone.
    payload.workflow_name = workflow.runName();
    if (typeof runResults !== 'undefined') runResults.payload(payload);
    payload.model_type = modelType;
    payload.text_column = node.params.text_column || '正文';
    /* Which column holds the labels is the BACKEND's answer, not this file's. It used to be
       a ternary over two model names, so a third classifier trained itself from whichever
       column the `else` branch happened to name — and the training would have succeeded,
       silently, on the wrong column. `train_ml_model` reads the same table that decides
       what `mode='ml'` later loads, so the two cannot disagree. */
    try {
        var resp = await fetch('/api/analysis/train', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        });
        var result = await resp.json();
        if (result.ok) {
            showToast(I18n.t('toast.modelTrained') + ' (' + result.trained_on + ' rows, ' + result.label_count + ' labels)');
        } else {
            showToast(I18n.t('toast.modelTrainFailed') + ': ' + result.error);
        }
    } catch (e) {
        showToast(I18n.t('toast.modelTrainFailed') + ': ' + e.message);
    }
}

/* ── Data Preview: generic paginated table for any dataset ──
   Used by Analysis/Visualize/Output node settings ("Preview Data"
   button) to inspect real rows instead of only JSON or a chart. */
function escapeHtml(str) {
    return String(str).replace(/[&<>"']/g, function (c) {
        return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
}

/* Escape a value destined for `fn('…')` written INSIDE a double-quoted HTML
   attribute — the shape every panel table builds its row buttons with. Two
   contexts have to be satisfied in order: the JavaScript literal needs `\` and
   `'` (and a raw newline would end it), then the attribute needs `&` and `"`.
   `escapeHtml` alone cannot serve: it also turns `'` into `&#39;`, which the
   parser hands back as a bare quote inside the literal. A panel that skipped the
   second half is how one double quote in a file name closed the attribute and
   made whatever followed into markup — which is why the run panel's buttons carry
   only a hex run id. Names are user data, so they need this. */
function attrJsArg(value) {
    return String(value)
        .replace(/\\/g, '\\\\')
        .replace(/'/g, "\\'")
        .replace(/\r/g, '\\r')
        .replace(/\n/g, '\\n')
        .replace(/&/g, '&amp;')
        .replace(/"/g, '&quot;');
}

var dataPreview = {
    _payload: null,
    _offset: 0,
    _limit: 50,
    _total: 0,

    async open(payload) {
        this._payload = payload;
        this._offset = 0;
        var fmt = payload.preview_format || '';
        if (fmt === 'txt' || fmt === 'json') {
            this._limit = 5000; // fetch enough for a full text view
        } else {
            this._limit = 50;
        }
        var panel = document.getElementById('data-preview-panel');
        panel.classList.add('open');
        document.getElementById('data-preview-meta').textContent = '';
        document.getElementById('data-preview-table-wrap').innerHTML =
            '<div class="loading-container"><div class="loading-spinner"></div></div>';
        document.getElementById('data-preview-pager').style.display = '';
        document.getElementById('data-preview-page-label').textContent = '';
        await this._fetch();
    },

    async _fetch() {
        var body = Object.assign({}, this._payload, { limit: this._limit, offset: this._offset });
        try {
            var resp = await fetch('/api/data/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
            });
            var result = await resp.json();
            if (!result.ok) {
                var fv = _renderFailureView(result);
                if (!fv.note) {
                    showToast(I18n.t('toast.previewFailed') + ': ' + result.error);
                    return;
                }
                document.getElementById('data-preview-table-wrap').innerHTML = '<div class="dashboard-cell-note">' + escapeHtml(fv.message) + '</div>';
                return;
            }
            this._total = result.total_rows;
            var fmt = this._payload.preview_format || '';
            if (fmt === 'txt' || fmt === 'json') {
                renderDataPreviewText(result, fmt);
            } else {
                renderDataPreviewTable(result);
            }
        } catch (e) {
            showToast(I18n.t('toast.previewFailed') + ': ' + e.message);
        }
    },

    prevPage() {
        if (this._offset - this._limit >= 0) { this._offset -= this._limit; this._fetch(); }
    },
    nextPage() {
        if (this._offset + this._limit < this._total) { this._offset += this._limit; this._fetch(); }
    },
};

// A stored data cell is the raw platform key (identity); the UI shows its localized name from the
// same catalog the rest of the page uses. Falls back to the raw value for a key the catalog lacks,
// so an unmapped platform still shows something instead of nothing.
function displayPlatform(v) {
    if (typeof I18n === 'undefined' || !I18n.t) return v;
    var key = 'platform.' + v;
    var label = I18n.t(key);
    return label && label !== key ? label : v;
}

function renderDataPreviewTable(result) {
    var panel = document.getElementById('data-preview-panel');
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, { minW: 320, minH: 220, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var meta = document.getElementById('data-preview-meta');
    meta.textContent = I18n.t('dataPreview.rows') + ': ' + result.total_rows + '  |  ' + I18n.t('dataPreview.columns') + ': ' + result.columns.length;

    var wrap = document.getElementById('data-preview-table-wrap');
    var html = '<table class="data-preview-table"><thead><tr>' +
        result.columns.map(function (c) { return '<th>' + escapeHtml(c) + '</th>'; }).join('') +
        '</tr></thead><tbody>';
    result.rows.forEach(function (row) {
        html += '<tr>' + result.columns.map(function (c) {
            var v = row[c];
            if (v === null || v === undefined) v = '';
            // The 平台 column stores the raw key (douyin, zhihu, …) as the row's storage identity;
            // the preview shows the localized name the rest of the UI already uses, but only when the
            // catalog knows it — an unmapped value falls back to the raw text rather than a blank.
            if (c === '平台' && v) v = displayPlatform(v);
            return '<td>' + escapeHtml(v) + '</td>';
        }).join('') + '</tr>';
    });
    html += '</tbody></table>';
    wrap.innerHTML = html;

    var page = Math.floor(result.offset / result.limit) + 1;
    var pages = Math.max(1, Math.ceil(result.total_rows / result.limit));
    document.getElementById('data-preview-page-label').textContent = page + ' / ' + pages;
}

function renderDataPreviewText(result, format) {
    var panel = document.getElementById('data-preview-panel');
    panel.classList.add('open');

    if (!panel.dataset._uiInit) {
        panel.dataset._uiInit = '1';
        makeDraggable(panel, '.panel-header');
        makeResizable(panel, { minW: 320, minH: 220, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
        if (!panel.querySelector('.resize-handle')) {
            var rh = document.createElement('div');
            rh.className = 'resize-handle';
            panel.appendChild(rh);
        }
    }

    var meta = document.getElementById('data-preview-meta');
    meta.textContent = I18n.t('dataPreview.rows') + ': ' + result.total_rows;

    var text;
    if (format === 'json') {
        text = JSON.stringify(result.rows, null, 2);
    } else {
        // txt: one line per row, columns separated by space
        text = result.rows.map(function (row) {
            return result.columns.map(function (c) { return row[c]; }).join('\t');
        }).join('\n');
    }

    var wrap = document.getElementById('data-preview-table-wrap');
    wrap.innerHTML = '<pre class="data-preview-text">' + escapeHtml(text) + '</pre>';

    document.getElementById('data-preview-pager').style.display = 'none';
}

function toggleDataPreview() {
    document.getElementById('data-preview-panel').classList.remove('open');
}

/* ── Dashboard: grid view of every Visualize node's chart at once ──
   Purely a *view* over existing Visualize nodes already configured on
   the canvas — it doesn't introduce a new workflow/DAG node type, it
   just renders each one's current settings side by side, like a simple
   BI board. Requires the workflow to have been executed at least once
   (so there's an upstream result to render). */
var dashboard = {
    _instances: {},
    /* A Matplotlib cell has no instance to ask for a picture, but the server already
       sent one as a data URL; keeping it beside the instance is what lets the same
       存图 button serve both engines. */
    _images: {},
    /* The raw authoring option each ECharts cell was drawn from, so the 全屏 window
       reuses the exact option instead of an instance's resolved getOption() tree. */
    _options: {},

    async open() {
        var panel = document.getElementById('dashboard-panel');
        panel.classList.add('open');
        var grid = document.getElementById('dashboard-grid');
        grid.innerHTML = '';
        this._instances = {};
        this._images = {};
        this._options = {};

        var vizNodeIds = Object.keys(canvas.nodes).filter(function (id) {
            return canvas.nodes[id].type === 'visualize';
        });

        if (!vizNodeIds.length) {
            grid.innerHTML = '<div class="dashboard-empty">' + I18n.t('dashboard.empty') + '</div>';
            return;
        }

        var self = this;
        vizNodeIds.forEach(function (id) {
            var node = canvas.nodes[id];
            var cell = document.createElement('div');
            cell.className = 'dashboard-cell';
            cell.innerHTML =
                '<div class="dashboard-cell-title">' + escapeHtml(node.title || id) +
                /* A node id is minted, never typed, so it is safe to put in the handler: the
                   name that could need escaping (the title) is read back at click time. */
                ' <button class="menu-btn" onclick="openChartFullscreen(\'' + id + '\')">' +
                I18n.t('chart.fullscreen') + '</button>' +
                ' <button class="menu-btn" onclick="saveDashboardImage(\'' + id + '\')">' +
                I18n.t('chart.saveImage') + '</button></div>' +
                '<div class="dashboard-cell-body"></div>';
            grid.appendChild(cell);
            self._renderCell(id, node, cell, grid);
        });
    },

    /* Is this cell still one of the board's cells?

       `open()` clears the grid and rebuilds it — on a refresh, a language switch or
       reopening the panel — so a cell from the previous board is an object with no place on
       the page. Tested by position rather than by selector because a node id is not a
       selector: a restored workflow may carry any id, and building a CSS string out of one
       asks the page to parse user data. */
    _isLiveCell(grid, cell) {
        if (!grid || !cell) return false;
        var cells = grid.querySelectorAll('.dashboard-cell');
        return Array.prototype.indexOf.call(cells, cell) >= 0;
    },

    async _renderCell(nodeId, node, cell, grid) {
        var body = cell ? cell.querySelector('.dashboard-cell-body') : null;
        if (!body) return;
        var p = node.params;
        var payload = {
            chart_type: p.chart_type, engine: p.engine, x_field: p.x_field,
            y_field: p.y_field, value_field: p.value_field, agg: p.agg,
            center_node: p.center_node,
            /* The board has to ask with the SAME fields the panel previews with. These three
               were left out, so every 双轴折线 cell answered "requires a second value field
               (y2)" — the cell that looked like a board bug was a payload bug — and every cell
               lost its event lines, which is the whole point of 图2/图8/图23~27. */
            y2_field: p.y2_field, agg2: p.agg2, annotations: p.annotations,
            /* The 主题距离图 / 流向图 read their Chinese bubble name from this field; a board
               that dropped it silently fell back to the Topic-1 code the user replaced. */
            label_field: p.label_field,
            /* The 占比堆叠图 draws its segments from a column list, not one y; a board that
               dropped it asked the service for a stacked field and got an opaque refusal. */
            stack_fields: p.stack_fields,
            model_field: p.model_field, agreement_label_field: p.agreement_label_field, id_field: p.id_field,
            title: p.title, tokenize: boolParam(p.tokenize, false),
            emit_latex: boolParam(p.emit_latex, true), emit_latex_table: boolParam(p.emit_latex_table, true),
            wordcloud_style: p.wordcloud_style || 'vibrant',
        };
        var upstream = canvas.getUpstreamNodeId(nodeId);
        if (!upstream) {
            body.innerHTML = '<div class="dashboard-cell-error">' + I18n.t('dashboard.noData') + '</div>';
            return;
        }
        payload.node_id = upstream;
        // A rebuilt board re-renders every cell from the server; name the workflow so a
        // cell still resolves its upstream rows after a page refresh AND a server restart,
        // when the in-memory result that first painted it is gone.
        payload.workflow_name = workflow.runName() || (typeof resumeBar !== 'undefined' && resumeBar.candidate && resumeBar.candidate.workflow_name) || '';
        if (typeof runResults !== 'undefined') runResults.payload(payload);

        try {
            var resp = await fetch('/api/visualize/render', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(payload),
            });
            var result = await resp.json();
            /* Re-checked after the await: `echarts.init` on a cell the board has since
               replaced paints nothing and still registers the instance, which is then
               resized on every window resize for the life of the page and never disposed.
               No chart, no instance and no error text is the honest outcome. */
            if (!this._isLiveCell(grid, cell)) return;
            if (!result.ok) {
                var fv = _renderFailureView(result);
                body.innerHTML = '<div class="' + (fv.note ? 'dashboard-cell-note' : 'dashboard-cell-error') + '">' + escapeHtml(fv.message) + '</div>';
                return;
            }
            if (result.engine === 'matplotlib') {
                body.innerHTML = '<img src="' + escapeHtml(result.image) + '" />';
                this._images[nodeId] = result.image;
            } else if (!hasChartLibrary()) {
                /* A board cell that cannot paint names the bundle that is gone: an empty cell reads
                   as "this node produced no chart", which is a different fact entirely. */
                body.innerHTML = '<div class="dashboard-cell-note">' + escapeHtml(chartLibraryMissingMessage()) + '</div>';
            } else {
                var inst = echarts.init(body);
                this._instances[nodeId] = inst;
                this._options[nodeId] = result.option;
                applyEchartsOption(inst, result.option);
            }
        } catch (e) {
            if (!this._isLiveCell(grid, cell)) return;
            body.innerHTML = '<div class="dashboard-cell-error">' + escapeHtml(e.message) + '</div>';
        }
    },

    close() {
        document.getElementById('dashboard-panel').classList.remove('open');
    },
};

window.addEventListener('resize', function () {
    Object.keys(dashboard._instances).forEach(function (id) {
        var inst = dashboard._instances[id];
        if (inst) inst.resize();
    });
});

/* ── Execution History: time-series comparison across runs ──
   Reads /api/history/* (populated automatically after each workflow run)
   to chart how a metric — emotion distribution, tendency distribution, or
   row count — has changed across runs over time, e.g. "how has sentiment
   on this topic shifted over the last two weeks of crawls". */
var historyPanel = {
    _instance: null,

    async open() {
        var panel = document.getElementById('history-panel');
        panel.classList.add('open');
        if (!panel.dataset._uiInit) {
            panel.dataset._uiInit = '1';
            makeDraggable(panel, '.panel-header');
            makeResizable(panel, { minW: 420, minH: 320, maxW: window.innerWidth - 40, maxH: window.innerHeight - 40 });
            if (!panel.querySelector('.resize-handle')) {
                var rh = document.createElement('div');
                rh.className = 'resize-handle';
                panel.appendChild(rh);
            }
            /* Bound once, on the container, because the rows are replaced by
               every reload: a listener per button would pile up one per refresh
               and a deleted row's button would still be listening. */
            var runsWrap = document.getElementById('history-runs-wrap');
            if (runsWrap && !runsWrap.dataset._delBound) {
                runsWrap.dataset._delBound = '1';
                runsWrap.addEventListener('click', function (e) {
                    var button = e.target && e.target.closest ? e.target.closest('.history-del') : null;
                    if (!button) return;
                    historyPanel.deleteRun(button.getAttribute('data-run-id'));
                });
            }
        }
        await this._loadRuns();
        await this.loadSeries();
    },

    async _loadRuns() {
        try {
            var resp = await fetch('/api/history/runs');
            var result = await resp.json();
            if (!result.ok) return;
            /* Kept, not only drawn: this table and the filter select are built in JS,
               so `I18n.apply()` never reaches them — a language switch has to redraw
               from what is already on hand instead of asking the server again. */
            this._runs = result;
            this._renderRuns();
        } catch (e) { /* non-fatal */ }
    },

    _renderRuns() {
        var result = this._runs;
        if (!result) return;
        var select = document.getElementById('history-workflow-select');
        var current = select.value;
        select.innerHTML = '<option value="">' + I18n.t('history.allWorkflows') + '</option>' +
            result.workflow_names.map(function (n) { return '<option value="' + escapeHtml(n) + '">' + escapeHtml(n) + '</option>'; }).join('');
        if (current) select.value = current;

        var wrap = document.getElementById('history-runs-wrap');
        if (!result.runs.length) {
            wrap.innerHTML = '<div class="dashboard-empty">' + I18n.t('history.empty') + '</div>';
            return;
        }
        var html = '<table class="history-runs-table"><thead><tr>' +
            '<th>' + I18n.t('history.runId') + '</th><th>' + I18n.t('history.workflowName') + '</th>' +
            '<th>' + I18n.t('history.startedAt') + '</th><th>' + I18n.t('history.metricCount') + '</th>' +
            '<th></th>' +
            '</tr></thead><tbody>';
        result.runs.forEach(function (r) {
            /* The id goes into a data attribute, not into an inline handler:
               it is database text, and one quote would end the attribute and
               start whatever the user typed next. */
            html += '<tr><td>' + escapeHtml(r.run_id) + '</td><td>' + escapeHtml(r.workflow_name || '') + '</td>' +
                '<td>' + escapeHtml(r.started_at) + '</td><td>' + r.metric_count + '</td>' +
                '<td class="history-ops"><button class="history-del" data-run-id="' + escapeHtml(r.run_id) +
                '">' + I18n.t('history.remove') + '</button></td></tr>';
        });
        html += '</tbody></table>';
        wrap.innerHTML = html;
    },

    onLanguageChange() {
        /* Same rule as the run-records and export panels: the header row is a
           catalogue string, so switching to English with this panel open used to
           leave the whole table Chinese until it was closed and opened again. */
        var panel = document.getElementById('history-panel');
        if (!panel || !panel.classList.contains('open')) return;
        this._renderRuns();
    },

    async loadSeries() {
        var workflowName = document.getElementById('history-workflow-select').value;
        var metric = document.getElementById('history-metric-select').value;
        var params = new URLSearchParams();
        if (workflowName) params.set('workflow_name', workflowName);
        if (metric) params.set('metric', metric);
        try {
            var resp = await fetch('/api/history/series?' + params.toString());
            var result = await resp.json();
            if (!result.ok) return;
            this._renderChart(result.rows, metric);
        } catch (e) { /* non-fatal */ }
    },

    /* Editorial palette drawn from the design system's muted accents
       (paper-white ground, ink #1a1a1a). The same label names the stats
       pies use are mapped here so a metric reads the same colour in both
       places. */
    _COLORS: {
        'Anger': '#a85454',
        'Joy': '#9a7740',
        'Sadness': '#4a6fa5',
        'Fear': '#8a6ea8',
        'Surprise': '#5f8a8a',
        'Neutral': '#6f7f8a',
        'Objective Statement': '#6f7f8a',
        'Praise/Affirmation': '#4e8061',
        'Criticism/Questioning': '#a85454',
        'Controversy/Reflection': '#9a7740',
        'Advocacy/Call-to-action': '#4a6fa5',
        'Satire/Mockery': '#8a6ea8',
    },
    _FALLBACK: ['#4a6fa5', '#9a7740', '#4e8061', '#a85454', '#8a6ea8', '#6f7f8a', '#b5895a', '#5a8a7a'],

    _colorFor(metric, label, i) {
        if (metric === 'rows') return '#4a6fa5';
        var named = this._COLORS[label];
        if (named) return named;
        return this._FALLBACK[(i || 0) % this._FALLBACK.length];
    },

    _rgba(hex, alpha) {
        var h = String(hex || '').replace('#', '');
        if (h.length === 3) h = h.split('').map(function (c) { return c + c; }).join('');
        var r = parseInt(h.slice(0, 2), 16) || 0;
        var g = parseInt(h.slice(2, 4), 16) || 0;
        var b = parseInt(h.slice(4, 6), 16) || 0;
        return 'rgba(' + r + ',' + g + ',' + b + ',' + alpha + ')';
    },

    _ensureChart() {
        var el = document.getElementById('history-chart');
        if (!hasChartLibrary()) {
            paintChartLibraryNote(el);
            return null;
        }
        if (this._instance) return el;
        /* SVG renderer: the chart is real, interactive SVG — crisp at any zoom,
           printable, and resizable without a canvas re-alloc. */
        this._instance = echarts.init(el, null, { renderer: 'svg' });
        if (window.ResizeObserver) {
            var inst = this._instance;
            new ResizeObserver(function () { inst.resize(); }).observe(el);
        }
        return el;
    },

    _renderChart(rows, metric) {
        /* null means "no chart library, and the panel already says so" — drawing on it would throw
           and replace a named refusal with a console error. */
        if (!this._ensureChart()) return;
        var inst = this._instance;
        var metricLabel = I18n.t('history.metric.' + (metric || 'rows'));
        var wf = document.getElementById('history-workflow-select').value;
        var subtext = wf ? wf : I18n.t('history.allWorkflows');
        var pal = chartPalette();
        var ink = pal.ink;
        var dim = pal.dim;
        var faint = pal.faint;
        /* Single source of truth is --font in style.css: Literata carries the
           latin glyphs and digits, 宋体/SimSun carries the CJK ones. ECharts
           text defaults to sans-serif, so the stack must be passed explicitly
           to every text block — reading the CSS variable keeps them in sync. */
        var chartFont = (getComputedStyle(document.documentElement)
            .getPropertyValue('--font') || '').trim()
            || '"Literata", "Songti SC", "SimSun", "宋体", serif';

        if (!rows.length) {
            var emptyFont = (getComputedStyle(document.documentElement)
                .getPropertyValue('--font') || '').trim()
                || '"Literata", "Songti SC", "SimSun", "宋体", serif';
            inst.setOption({
                title: {
                    text: I18n.t('history.empty'), left: 'center', top: 'middle',
                    textStyle: { color: 'rgba(26,26,26,0.4)', fontSize: 12, fontWeight: 400, fontFamily: emptyFont },
                },
                xAxis: { show: false }, yAxis: { show: false }, series: [],
            }, true);
            return;
        }

        var labelSet = {};
        rows.forEach(function (r) { labelSet[r.label || r.metric] = true; });
        var labels = Object.keys(labelSet);
        var self = this;
        var series = labels.map(function (label, i) {
            var color = self._colorFor(metric, label, i);
            var pts = rows
                .filter(function (r) { return (r.label || r.metric) === label; })
                .map(function (r) { return [r.timestamp, r.value]; });
            if (metric === 'rows') {
                return {
                    name: label, type: 'bar', data: pts, barWidth: '46%',
                    itemStyle: {
                        color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                            { offset: 0, color: color },
                            { offset: 1, color: self._rgba(color, 0.5) },
                        ]),
                        borderRadius: [3, 3, 0, 0],
                    },
                };
            }
            return {
                name: label, type: 'line', data: pts, smooth: true,
                symbol: 'circle', symbolSize: 5, showSymbol: true,
                lineStyle: { width: 2, color: color },
                itemStyle: { color: color },
                areaStyle: {
                    color: new echarts.graphic.LinearGradient(0, 0, 0, 1, [
                        { offset: 0, color: self._rgba(color, 0.22) },
                        { offset: 1, color: self._rgba(color, 0.02) },
                    ]),
                },
            };
        });

        inst.setOption({
            backgroundColor: 'transparent',
            /* Title → legend → plot are stacked with real gaps: the title block
               ends ~45px down, the legend sits below it, and the grid starts
               low enough that neither can clip the other. Legend is scroll
               type so many workflow labels stay on one line instead of
               wrapping down over the plot. Left/right grid margins stay
               symmetric so the plot area reads as centred in the panel. */
            title: {
                text: metricLabel, subtext: subtext, left: 'center', top: 8,
                textStyle: { color: ink, fontSize: 14, fontWeight: 500, fontFamily: chartFont },
                subtextStyle: { color: pal.dim, fontSize: 11, fontFamily: chartFont },
            },
            tooltip: {
                trigger: 'axis',
                backgroundColor: pal.tooltipBg,
                borderColor: pal.tooltipBorder, borderWidth: 1,
                textStyle: { color: ink, fontSize: 12, fontFamily: chartFont },
                axisPointer: { type: 'line', lineStyle: { color: pal.axisLine, type: 'dashed' } },
            },
            legend: {
                data: labels, top: 50, left: 'center', icon: 'circle',
                type: 'scroll', width: '86%',
                itemWidth: 8, itemHeight: 8, itemGap: 12,
                textStyle: { color: ink, fontSize: 11, fontFamily: chartFont },
            },
            grid: { top: 84, left: 44, right: 44, bottom: 56, containLabel: true },
            xAxis: {
                type: 'time',
                axisLine: { lineStyle: { color: pal.axisLine } },
                axisLabel: { color: dim, fontSize: 10, hideOverlap: true, fontFamily: chartFont },
                splitLine: { show: true, lineStyle: { color: faint } },
            },
            yAxis: {
                type: 'value',
                axisLine: { show: false }, axisTick: { show: false },
                axisLabel: { color: dim, fontSize: 10, fontFamily: chartFont },
                splitLine: { lineStyle: { color: faint } },
            },
            dataZoom: [
                { type: 'inside' },
                {
                    type: 'slider', height: 14, bottom: 4, borderColor: 'transparent',
                    fillerColor: 'rgba(26,26,26,0.06)', handleStyle: { color: ink },
                    textStyle: { color: dim, fontFamily: chartFont }, moveHandleSize: 4,
                },
            ],
            series: series,
        }, true);
        inst.resize();
    },

    async clear() {
        var confirmed = await showDialog({
            message: I18n.t('history.confirmClear'),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('dialog.confirm'), value: true, primary: true },
            ],
        });
        if (!confirmed) return;
        try {
            // The dialog above is the human half; ``confirm: true`` is the server's own gate,
            // held by every other bulk destructive route so a stray or cross-origin call cannot
            // wipe the whole comparison chart (see ``/api/history/clear``).
            const resp = await fetch('/api/history/clear', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ confirm: true }),
            });
            const result = await resp.json();
            if (!result.ok) {
                showToast(I18n.t('toast.previewFailed') + ': ' + (result.error || resp.status));
                return;
            }
            showToast(I18n.t('history.cleared'));
            await this._loadRuns();
            await this.loadSeries();
        } catch (e) {
            showToast(I18n.t('toast.previewFailed') + ': ' + e.message);
        }
    },

    async deleteRun(runId) {
        var id = String(runId || '').trim();
        if (!id) return;
        var confirmed = await showDialog({
            message: I18n.t('history.confirmRemove').replace('{rid}', id),
            buttons: [
                { label: I18n.t('dialog.cancel'), value: false },
                { label: I18n.t('dialog.confirm'), value: true, primary: true },
            ],
        });
        if (!confirmed) return;
        try {
            var resp = await fetch('/api/history/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ run_id: id }),
            });
            var result = await resp.json();
            if (!result.ok) {
                showToast(I18n.t('history.removeFailed') + ': ' + (result.error || ''));
                return;
            }
            /* Zero deleted rows is reported, not hidden: the list on screen was
               loaded before this click, and a run aged out by the retention
               policy in between is a different fact than "deleted". */
            showToast(result.deleted ? I18n.t('history.removed') : I18n.t('history.removeGone'));
            await this._loadRuns();
            await this.loadSeries();
        } catch (e) {
            showToast(I18n.t('toast.previewFailed') + ': ' + e.message);
        }
    },

    close() {
        document.getElementById('history-panel').classList.remove('open');
    },
};

