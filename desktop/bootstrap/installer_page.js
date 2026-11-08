/* The installer page: a thin view over the local server.
 *
 * The server owns every fact (which components exist, what is chosen, how far the download is,
 * whether a folder is writable). This file paints them and posts the user's intent; it never
 * guesses a size, a path or a refusal. All server text is inserted with textContent, never HTML.
 */
(function () {
    'use strict';

    var cfg = window.INSTALLER || {};
    var text = cfg.text || { zh: {}, en: {} };
    var labelMap = cfg.state_labels || { zh: {}, en: {} };
    var lang = 'zh';
    var theme = 'light';
    try {
        lang = window.localStorage.getItem('installer-lang') || cfg.lang || 'zh';
        theme = window.localStorage.getItem('installer-theme') || 'light';
    } catch (err) {
        /* a browser that refuses localStorage still gets the defaults */
    }
    var state = cfg.state || {};
    var base = '/' + cfg.token;
    var pollTimer = null;
    var doctorTimer = null;
    var doctorRequested = false;
    var signature = '';

    function byId(id) {
        return document.getElementById(id);
    }

    function t(key, vars) {
        var value = (text[lang] && text[lang][key]) || (text.zh && text.zh[key]) || key;
        if (vars) {
            Object.keys(vars).forEach(function (name) {
                value = value.split('{' + name + '}').join(String(vars[name]));
            });
        }
        return value;
    }

    function post(path, body) {
        return fetch(base + path, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body || {}),
        }).then(function (response) {
            return response.json();
        });
    }

    function notice(message) {
        var box = byId('notice');
        box.textContent = message || '';
        box.hidden = !message;
    }

    /* Bytes in the same shape plan.py prints on the server: the page renders the sentence. */
    function humanSize(size) {
        var value = Number(size) || 0;
        var units = ['B', 'KB', 'MB', 'GB'];
        for (var i = 0; i < units.length; i += 1) {
            if (value < 1024 || i === units.length - 1) {
                return units[i] === 'GB' ? value.toFixed(1) + ' GB' : Math.round(value) + ' ' + units[i];
            }
            value /= 1024;
        }
        return Math.round(size) + ' B';
    }

    function applyLang() {
        document.documentElement.lang = lang === 'zh' ? 'zh-CN' : 'en';
        document.title = t('title');
        var pairs = [
            ['title', 'title'], ['intro', 'intro'], ['dir-label', 'dir'], ['data-label', 'data_dir'],
            ['data-hint', 'data_hint'], ['preset-label', 'preset'], ['preset-one', 'preset_one'],
            ['preset-app', 'preset_app'], ['components-label', 'components'], ['vpn', 'vpn'],
            ['license', 'license'], ['install', 'install'], ['cancel', 'cancel'], ['open', 'open'],
            ['browse-root', 'browse'], ['browse-data', 'browse'], ['doctor-launch', 'launch'],
            ['doctor-close', 'close'],
        ];
        pairs.forEach(function (pair) {
            var node = byId(pair[0]);
            if (node) node.textContent = t(pair[1]);
        });
        byId('quit').textContent = t('quit');
        var buttons = document.querySelectorAll('.lang button[data-lang]');
        for (var i = 0; i < buttons.length; i += 1) {
            buttons[i].setAttribute('aria-pressed', String(buttons[i].dataset.lang === lang));
        }
        applyThemeLabel();
    }

    /* The two icons are inline SVG; CSS shows the moon on the light ground and the sun on the
       dark one. No glyph font, no Unicode character standing in for an icon. */
    function applyThemeLabel() {
        var button = byId('theme');
        if (!button) return;
        button.setAttribute('aria-label', t(theme === 'dark' ? 'theme_light' : 'theme_dark'));
        button.setAttribute('title', t(theme === 'dark' ? 'theme_light' : 'theme_dark'));
    }

    function applyTheme() {
        document.documentElement.dataset.theme = theme === 'dark' ? 'dark' : 'light';
        applyThemeLabel();
    }

    function componentRow(item) {
        var row = document.createElement('label');
        row.className = 'component' + (item.downloadable ? '' : ' manual');
        var box = document.createElement('input');
        box.type = 'checkbox';
        box.value = item.id;
        box.checked = Boolean(item.checked);
        box.disabled = !item.downloadable;
        box.addEventListener('change', onToggle);
        var name = document.createElement('span');
        name.className = 'name';
        name.textContent = item.id + ' ' + item.version + ' — ' + item.summary;
        var meta = document.createElement('span');
        meta.className = 'meta';
        meta.textContent = item.size_text || '';
        row.append(box, name, meta);
        return row;
    }

    function renderComponents(list) {
        var next = list
            .map(function (item) {
                return item.id + ':' + (item.checked ? '1' : '0') + ':' + (item.downloadable ? '1' : '0');
            })
            .join('|');
        if (next === signature) return;
        signature = next;
        var holder = byId('components');
        holder.textContent = '';
        list.forEach(function (item) {
            holder.append(componentRow(item));
        });
    }

    function selectedIds() {
        var boxes = document.querySelectorAll('#components input[type="checkbox"]:checked');
        return Array.prototype.map.call(boxes, function (box) {
            return box.value;
        });
    }

    function applyState(next) {
        if (next) state = next;
        var root = byId('root');
        var data = byId('data');
        if (document.activeElement !== root) root.value = state.root || '';
        if (document.activeElement !== data) data.value = state.data || '';
        var radios = document.querySelectorAll('input[name="preset"]');
        for (var i = 0; i < radios.length; i += 1) {
            radios[i].checked = radios[i].value === state.preset;
        }
        renderComponents(state.components || []);
        byId('total').textContent = t('size', { size: humanSize(state.total) });
        var job = state.job || {};
        var percent = job.total ? Math.round((job.done / job.total) * 100) : 0;
        byId('bar').style.width = Math.min(100, Math.max(0, percent)) + '%';
        var progress = document.querySelector('.progress');
        if (progress) progress.setAttribute('aria-valuenow', String(percent));
        var status = job.status_key ? t(job.status_key, job.status_params || {}) : '';
        byId('status').textContent = status || (job.error ? t('failed', { err: job.error }) : '');
        var log = byId('log');
        // No scrollbar anywhere on this page: the log keeps its newest lines and clips the rest.
        var lines = (job.log || []).slice(-4);
        log.textContent = lines.join('\n');
        byId('install').disabled = job.state === 'running';
        byId('cancel').disabled = job.state !== 'running';
        if (job.state === 'done') requestDoctor();
    }

    function startPolling() {
        if (pollTimer) return;
        pollTimer = window.setInterval(function () {
            fetch(base + '/api/state')
                .then(function (response) {
                    return response.json();
                })
                .then(function (answer) {
                    if (!answer.ok) return;
                    applyState(answer.state);
                    var job = answer.state.job || {};
                    if (job.state !== 'running') {
                        window.clearInterval(pollTimer);
                        pollTimer = null;
                    }
                })
                .catch(function () {
                    /* the server is shutting down (launch/elevation): stop asking */
                    window.clearInterval(pollTimer);
                    pollTimer = null;
                });
        }, 700);
    }

    async function onToggle() {
        try {
            var answer = await post('/api/select', { ids: selectedIds() });
            if (answer.ok) applyState(answer.state);
            else notice(answer.error || '');
        } catch (err) {
            notice(String(err.message || err));
        }
    }

    function onPreset(event) {
        post('/api/preset', { preset: event.target.value })
            .then(function (answer) {
                if (answer.ok) applyState(answer.state);
                else notice(answer.error || '');
            })
            .catch(function (err) {
                notice(String(err.message || err));
            });
    }

    function onBrowse(kind) {
        post('/api/browse', { kind: kind, lang: lang })
            .then(function (answer) {
                if (answer.ok && answer.path) {
                    byId(kind === 'data' ? 'data' : 'root').value = answer.path;
                }
            })
            .catch(function (err) {
                notice(String(err.message || err));
            });
    }

    async function onInstall() {
        notice('');
        try {
            var answer = await post('/api/start', {
                root: byId('root').value,
                data: byId('data').value,
                ids: selectedIds(),
                lang: lang,
            });
            if (!answer.ok) {
                notice(answer.error || '');
                return;
            }
            if (answer.relaunching) {
                notice(t('relaunching'));
                byId('install').disabled = true;
                return;
            }
            applyState(answer.state);
            startPolling();
        } catch (err) {
            notice(String(err.message || err));
        }
    }

    function onCancel() {
        post('/api/cancel').then(function (answer) {
            if (answer.ok) applyState(answer.state);
        });
    }

    function onOpen() {
        post('/api/open').catch(function () {});
    }

    function onQuit() {
        /* The server closes this window; a page cannot close a native WebView2 window itself. */
        notice(t('quit'));
        byId('quit').disabled = true;
        post('/api/shutdown').catch(function () {});
    }

    function openDoctor(report) {
        var rows = byId('doctor-rows');
        rows.textContent = '';
        var capabilities = (report && report.capabilities) || [];
        if (!capabilities.length) {
            var empty = document.createElement('p');
            empty.className = 'hint';
            empty.textContent = t('doctor_empty');
            rows.append(empty);
        }
        capabilities.forEach(function (row) {
            var line = document.createElement('div');
            line.className = 'row';
            var stateLabel = document.createElement('span');
            var tone = row.state || 'unknown';
            stateLabel.className = 'state ' + tone;
            stateLabel.textContent = (labelMap[lang] && labelMap[lang][tone]) || tone;
            var body = document.createElement('span');
            body.className = 'text';
            var sentence = String(row.label_text || row.label_key || '');
            if (row.reason_key) sentence += ' — ' + String(row.reason_text || row.reason_key);
            body.textContent = sentence;
            line.append(stateLabel, body);
            rows.append(line);
        });
        byId('doctor-title').textContent = t('doctor_title');
        byId('doctor-launch').textContent = t('launch');
        byId('doctor-close').textContent = t('close');
        byId('doctor').hidden = false;
    }

    function requestDoctor() {
        if (doctorRequested) return;
        doctorRequested = true;
        byId('notice').hidden = false;
        byId('notice').textContent = t('doctor_running');
        var tick = function () {
            fetch(base + '/api/doctor')
                .then(function (response) {
                    return response.json();
                })
                .then(function (answer) {
                    if (answer.state === 'running' || answer.state === 'idle') {
                        doctorTimer = window.setTimeout(tick, 900);
                        return;
                    }
                    byId('notice').textContent = t('done');
                    openDoctor(answer.report || {});
                })
                .catch(function () {
                    doctorTimer = window.setTimeout(tick, 1200);
                });
        };
        tick();
    }

    async function onLaunch() {
        try {
            var answer = await post('/api/launch', { lang: lang });
            if (answer.ok) {
                byId('notice').hidden = false;
                byId('notice').textContent = t('launched');
                byId('doctor').hidden = true;
            } else {
                notice(answer.error || '');
            }
        } catch (err) {
            notice(String(err.message || err));
        }
    }

    byId('theme').addEventListener('click', function () {
        theme = theme === 'dark' ? 'light' : 'dark';
        try {
            window.localStorage.setItem('installer-theme', theme);
        } catch (err) {
            /* private mode: the choice lasts for this page */
        }
        applyTheme();
    });
    byId('browse-root').addEventListener('click', function () {
        onBrowse('root');
    });
    byId('browse-data').addEventListener('click', function () {
        onBrowse('data');
    });
    byId('install').addEventListener('click', onInstall);
    byId('cancel').addEventListener('click', onCancel);
    byId('open').addEventListener('click', onOpen);
    byId('quit').addEventListener('click', onQuit);
    byId('doctor-launch').addEventListener('click', onLaunch);
    byId('doctor-close').addEventListener('click', function () {
        byId('doctor').hidden = true;
    });
    var presetInputs = document.querySelectorAll('input[name="preset"]');
    for (var i = 0; i < presetInputs.length; i += 1) {
        presetInputs[i].addEventListener('change', onPreset);
    }
    var langButtons = document.querySelectorAll('.lang button');
    for (var j = 0; j < langButtons.length; j += 1) {
        langButtons[j].addEventListener('click', function (event) {
            lang = event.currentTarget.dataset.lang;
            window.localStorage.setItem('installer-lang', lang);
            applyLang();
            applyState(state);
        });
    }
    applyTheme();
    applyLang();
    applyState(state);
    if (state.job && state.job.state === 'running') startPolling();
})();
