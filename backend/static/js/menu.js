/* ============================================================================
   menu.js — ZENVIZ-style flat top menu (no dropdowns)

   Every entry lives directly in the bar (index.html). This module only keeps
   the dynamic bits truthful: run-state (Execute/Stop enabled), the
   Parallel/Headless toggles, the active language, the active background swatch,
   and the corner-radius slider. Nothing here opens a floating panel.
   ========================================================================== */

var TopMenu = {
    /* Keep the flat bar's stateful controls in sync with real state. */
    sync() {
        var p = document.getElementById('btn-parallel');
        var h = document.getElementById('btn-headless');
        if (p) p.className = 'menu-btn ' + (RunState.parallel ? 'toggle-on' : 'toggle-off');
        if (h) h.className = 'menu-btn ' + (RunState.headless ? 'toggle-on' : 'toggle-off');

        var ex = document.getElementById('btn-execute');
        var st = document.getElementById('btn-stop');
        if (ex) {
            ex.disabled = RunState.running;
            ex.textContent = I18n.t(RunState.running ? 'btn.running' : 'btn.execute');
        }
        if (st) st.disabled = !RunState.running;

        /* active language */
        var lang = document.body.dataset.lang || 'zh';
        document.querySelectorAll('.lang-btn').forEach(function (b) {
            b.classList.toggle('active', (b.dataset.lang || '') === lang);
        });

        /* active background swatch */
        var m = document.body.className.match(/bg-(\S+)/);
        var bg = m ? m[1] : 'grid';
        document.querySelectorAll('.bar-bg-dot').forEach(function (d) {
            d.classList.toggle('active', d.dataset.bg === 'bg-' + bg);
        });

        /* slider reflects the current radius token */
        var slider = document.getElementById('radius-slider');
        if (slider) {
            var cur = parseInt(getComputedStyle(document.documentElement).getPropertyValue('--radius'), 10);
            if (!isNaN(cur) && document.activeElement !== slider) slider.value = cur;
            var lbl = document.getElementById('radius-val');
            if (lbl) lbl.textContent = (isNaN(cur) ? 2 : cur) + 'px';
        }
    },

    init() {
        this.sync();

        /* Style / AI / 设置 submenus close on an outside click, Esc, or resize. */
        document.addEventListener('click', (e) => {
            var m = document.getElementById('style-menu');
            if (m && m.classList.contains('open') &&
                !e.target.closest('#style-menu') && !e.target.closest('#btn-style')) {
                closeStyleMenu();
            }
            var ai = document.getElementById('ai-menu');
            if (ai && ai.classList.contains('open') &&
                !e.target.closest('#ai-menu') && !e.target.closest('#btn-ai')) {
                closeAiMenu();
            }
            var sm = document.getElementById('settings-menu');
            if (sm && sm.classList.contains('open') &&
                !e.target.closest('#settings-menu') && !e.target.closest('#btn-settings')) {
                closeSettingsMenu();
            }
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') { closeStyleMenu(); closeAiMenu(); closeSettingsMenu(); }
        });
        window.addEventListener('resize', function () {
            closeStyleMenu(); closeAiMenu(); closeSettingsMenu();
        });

        /* Load the saved AI settings into the panel once at startup. */
        if (window.LLMSettings) LLMSettings.applyToPanel();
        if (window.AppSettings) AppSettings.pull();
    },

    /* Used by RunState / setLang / setBg so the bar stays truthful. */
    refresh() {
        this.sync();
    },

    /* Unpinning the bar also dismisses the style submenu. */
    close() {
        closeStyleMenu();
    },
};

/* ── Style submenu (background + corner radius) ───────────────────────────── */
function toggleStyleMenu(e) {
    if (e) e.stopPropagation();
    var menu = document.getElementById('style-menu');
    var btn = document.getElementById('btn-style');
    if (!menu || !btn) return;
    if (menu.classList.contains('open')) {
        closeStyleMenu();
        return;
    }
    TopMenu.sync();               /* reflect current bg / radius before showing */
    menu.classList.add('open');
    document.body.classList.add('style-menu-open');
    btn.classList.add('active');
    var r = btn.getBoundingClientRect();
    var left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = r.bottom + 3 + 'px';
}

function closeStyleMenu() {
    var menu = document.getElementById('style-menu');
    if (menu) menu.classList.remove('open');
    document.body.classList.remove('style-menu-open');
    var btn = document.getElementById('btn-style');
    if (btn) btn.classList.remove('active');
}

/* ── AI submenu (transport / model / key / batching) ──────────────────────── */
function toggleAiMenu(e) {
    if (e) e.stopPropagation();
    var menu = document.getElementById('ai-menu');
    var btn = document.getElementById('btn-ai');
    if (!menu || !btn) return;
    if (menu.classList.contains('open')) {
        closeAiMenu();
        return;
    }
    closeStyleMenu();
    closeSettingsMenu();
    if (window.LLMSettings) LLMSettings.applyToPanel();
    menu.classList.add('open');
    btn.classList.add('active');
    var r = btn.getBoundingClientRect();
    var left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = r.bottom + 3 + 'px';
}

function closeAiMenu() {
    var menu = document.getElementById('ai-menu');
    if (menu) menu.classList.remove('open');
    var btn = document.getElementById('btn-ai');
    if (btn) btn.classList.remove('active');
}

/* ── 设置 submenu (driver path / window / timeouts / Ollama host) ──────────── */
function toggleSettingsMenu(e) {
    if (e) e.stopPropagation();
    var menu = document.getElementById('settings-menu');
    var btn = document.getElementById('btn-settings');
    if (!menu || !btn) return;
    if (menu.classList.contains('open')) {
        closeSettingsMenu();
        return;
    }
    closeStyleMenu();
    closeAiMenu();
    if (window.AppSettings) AppSettings.applyToPanel();
    menu.classList.add('open');
    btn.classList.add('active');
    var r = btn.getBoundingClientRect();
    var left = Math.min(r.left, window.innerWidth - menu.offsetWidth - 8);
    menu.style.left = Math.max(8, left) + 'px';
    menu.style.top = r.bottom + 3 + 'px';
}

function closeSettingsMenu() {
    var menu = document.getElementById('settings-menu');
    if (menu) menu.classList.remove('open');
    var btn = document.getElementById('btn-settings');
    if (btn) btn.classList.remove('active');
}

/* ── Corner radius control ───────────────────────────────────────────────────
   One --radius token drives every rectangular corner in the app (see style.css).
   The slider writes it straight onto :root so the change is instant and global. */
function setRadius(value) {
    var px = Math.max(0, Math.min(16, parseInt(value, 10) || 0));
    document.documentElement.style.setProperty('--radius', px + 'px');
    var lbl = document.getElementById('radius-val');
    if (lbl) lbl.textContent = px + 'px';
    try {
        var s = JSON.parse(localStorage.getItem('crawler_settings') || '{}');
        s.radius = px;
        localStorage.setItem('crawler_settings', JSON.stringify(s));
    } catch (e) {
        /* ignore */
    }
}
