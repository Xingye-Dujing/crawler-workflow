/* Pre-paint theme/language bootstrap — the first script the page runs.
 *
 * Loaded as a blocking <script> at the top of <body> (index.html), so the saved theme,
 * background and language are on <html>/<body> BEFORE the first paint: a dark choice
 * never flashes light. It is a file rather than an inline block so the page needs no
 * inline script (a strict Content-Security-Policy can ban those) and `node --check`
 * sees it like every other module.
 *
 * app.js owns the same settings once it boots (Settings.apply / I18n.apply) and repaints
 * from them; this file only decides what the first frame looks like. A broken draft is
 * expected input (see Settings.load's fallback), so every read sits inside one try.
 */
(function () {
    'use strict';
    try {
        var settings = JSON.parse(localStorage.getItem('crawler_settings'));
        if (!settings) return;
        var choice = settings.theme || 'auto';
        var html = document.documentElement;
        var resolved = choice !== 'auto'
            ? choice
            : (window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
        html.dataset.themeChoice = choice;
        html.dataset.theme = resolved;
        /* Native scrollbars, form controls and the canvas backdrop follow the theme. */
        html.style.colorScheme = resolved;
        var body = document.body;
        ['bg-void', 'bg-grid', 'bg-dots', 'bg-cross', 'bg-diagonal'].forEach(function (name) {
            body.classList.remove(name);
        });
        if (settings.bg) body.classList.add(settings.bg);
        var lang = settings.lang || 'zh';
        body.dataset.lang = lang;
        /* The declared lang is zh-CN; a saved English choice has to reach screen readers too. */
        html.lang = lang === 'en' ? 'en' : 'zh-CN';
    } catch (error) {
        /* Unreadable draft: first paint keeps the page defaults; Settings.load reports later. */
    }
})();
