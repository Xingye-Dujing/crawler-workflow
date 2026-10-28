/* The Cookie panel: the login dialog, the saved-logins dock and the account picker.
 *
 * Split out of ``workflow.js`` (Stage 8, 2026-10-28) byte for byte. The browser itself is opened
 * server-side by a single-flight login job; this file polls that job, refuses to close while a login
 * is still waiting, renders the server-owned guidance, and manages the saved logins dock. Every
 * name here is global because the markup and the other panels call it by name.
 */

/* Cookie Configuration — driven by the server-side single-flight login job.
   The browser opens server-side and the job lives in app state; this dialog
   polls its status, offers Done/Cancel, and REFUSES to close while a login is
   waiting: the dialog's buttons are the only way to finish or abort that
   browser, and closing it used to leave the login window orphaned. */
var cookieJob = { active: false, known: false, timer: null, platform: '', kind: 'login' };
/* The server owns the guidance (translated, and next to the code that enforces
   which link is acceptable), so it is fetched once and rendered from cache. */
var cookieFlows = null;
var cookieFlowsLoading = false;
/* The profile state comes from its own endpoint (it is the same table the settings panel
   renders) and is cached by platform name, because the one thing the user cannot see from
   outside is that the cookie file in data/cookies is NOT the session this profile holds. */
var cookieProfiles = {};
var cookieProfilesLoaded = false;
var cookieProfilesLoading = false;

function loadCookieProfiles() {
    /* In-flight as well as loaded: the guide repaints when its own fetch lands, and a
       second call during that window would buy the same table twice — the reason the
       panel is allowed to cache it at all is that it is fetched once. A failed read
       leaves ``loaded`` false, so the next render asks again. */
    if (cookieProfilesLoaded || cookieProfilesLoading) return;
    cookieProfilesLoading = true;
    fetchJSON('/api/browser/profiles').then(function (result) {
        cookieProfilesLoading = false;
        if (!result || !result.ok) return;
        var byName = {};
        (result.profiles || []).forEach(function (row) {
            byName[row.platform] = row;
        });
        cookieProfiles = byName;
        cookieProfilesLoaded = true;
        renderCookieGuide();
    });
}

function renderCookieGuide() {
    var body = document.getElementById('cookie-guide-body');
    if (!body) return;
    var platform = document.getElementById('cookie-platform').value;
    loadCookieProfiles();
    // The account offers follow the platform the guide is being drawn for.
    renderCookieAccounts();
    if (!cookieFlows) {
        body.textContent = I18n.t('cookie.guideLoading');
        /* The same in-flight guard the profile table needs: this function is called again
           when either fetch lands, and without it a repaint mid-flight bought the flow a
           second time for a panel that caches it precisely because it is fetched once. */
        if (cookieFlowsLoading) return;
        cookieFlowsLoading = true;
        fetchJSON('/api/cookies/flow').then(function (result) {
            cookieFlowsLoading = false;
            if (!result.ok) {
                body.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
                return;
            }
            var byName = {};
            result.flows.forEach(function (flow) {
                byName[flow.platform] = flow;
            });
            cookieFlows = byName;
            renderCookieGuide();
        });
        return;
    }
    var flow = cookieFlows[platform];
    if (!flow) {
        body.textContent = '';
        return;
    }
    var lines = [flow.purpose];
    flow.steps.forEach(function (step) {
        lines.push(step);
    });
    /* The staleness sentence is only ever true because the server measured it: the
       profile records WHICH cookie file went into it, and the answer here is "a
       different one is sitting in data/cookies now". Without that hint the button is
       a mystery door, and with it the panel says the one thing the user cannot
       find out from outside: that their re-taken cookie is not being used yet. */
    var profile = cookieProfiles[platform];
    if (profile && profile.needs_refresh) {
        lines.push(I18n.t('cookie.refreshHint'));
    }
    body.textContent = '';
    lines.forEach(function (line) {
        var row = document.createElement('div');
        row.className = 'cookie-guide-line';
        row.textContent = line;
        body.appendChild(row);
    });
    /* The entry field only means something when the platform's cookie can be
       captured from a page the user chooses — WeChat above all. */
    var entry = document.getElementById('cookie-entry');
    if (entry) {
        entry.disabled = !flow.accepts_custom_url;
        entry.placeholder = flow.login_url || 'https://…';
    }
}

function refreshCookieStatus(updateSummary) {
    fetchJSON('/api/cookies/status').then(function (result) {
        var statusEl = document.getElementById('cookie-status');
        if (!statusEl || cookieJob.active) return;
        if (!result.ok) {
            if (updateSummary !== false) statusEl.textContent = I18n.t('cookie.unreachable');
            return;
        }
        /* One read, four renderers. The rows answer per (platform, account), and the
           account line has to repaint on every keystroke in the box — refetching for a
           character typed would make the panel ask the server eight file listings per
           name. `updateSummary === false` still refreshes rows + the account renderers,
           but leaves the #cookie-status sentence the caller just wrote (a save/plant note)
           standing — used right after 保存 so the account line stops saying 「还没有保存过」
           while that note says it is saved. */
        cookieRows = result.rows || [];
        var lines = [];
        Object.keys(result.cookies).forEach(function (p) {
            /* Both halves come from the catalog. Written raw this line read
               "zhihu: OK" in a Chinese interface — and a bare "OK" overstates
               the fact anyway: what is known here is that a jar is saved,
               not that the session inside it still opens pages (that is what
               验证 Cookie and the pre-run probe answer). */
            var saved = result.cookies[p];
            // A named account is said by its WORD: "知乎: 未存（work）" tells the
            // default file is empty while a second login exists — two facts
            // the old boolean could not separate. Joined raw, the default
            // account came out as an empty name ("知乎: 已存（, work）").
            var names = cookieRows
                .filter(function (row) {
                    return row.platform === p;
                })
                .map(cookieAccountLabel);
            var tag = names.length ? ' (' + names.join(', ') + ')' : '';
            lines.push(
                I18n.t('platform.' + p) + tag + ': ' + I18n.t(saved ? 'cookie.savedYes' : 'cookie.savedNo')
            );
        });
        // With updateSummary === false the caller just wrote a save/plant message here that
        // must survive; we still refresh the rows + the two account renderers below.
        if (updateSummary !== false) {
            statusEl.textContent = lines.join('  |  ');
        }
        renderCookieAccounts();
        renderCookieAccountStatus();
        renderCookieManager();
    });
}

function cookieRowFor(platform, account) {
    /* The row for exactly this pair, or null when nothing is saved under it.
       Matched on the account KEY and never on the label: 「默认账号」 is how one account is
       worded, and a label match would also answer for a login the user happened to name
       that. Both spellings of the default fold to the same key, so a row written before
       multi-account and one named ``default`` are found by either. */
    var want = cookieAccountKey(account);
    for (var i = 0; i < cookieRows.length; i++) {
        var row = cookieRows[i];
        if (row.platform === platform && cookieAccountKey(row.account) === want) return row;
    }
    return null;
}

function cookieAccountLabel(row) {
    if (!row) return '';
    // The backend knows which names IT generated (default, default2) and sends a
    // catalogue key with its arguments; anything else the user typed is shown exactly
    // as typed, because a name they chose is not this program's word to translate.
    return row.label_key ? I18n.t(row.label_key, row.label_args || {}) : cookieAccountKey(row.account);
}

function cookieAccountWord(account) {
    /* The WORD for an account key, in both of its spellings: the default has a name like any
       other account, and what the user reads for it is 默认账号. */
    return cookieAccountKey(account) === COOKIE_DEFAULT_ACCOUNT ? String(I18n.t('cookies.accountDefault')) : cookieAccountKey(account);
}

function renderCookieAccountStatus() {
    /* The line under the box: what THIS account holds, changing as the box changes.
       It answers from the cached rows, so it is a re-render and not a request — the
       question "have I saved a login under that name" is already in the payload. */
    var el = document.getElementById('cookie-account-status');
    if (!el) return;
    var select = document.getElementById('cookie-platform');
    var platform = select ? select.value : '';
    var account = cookieAccount();
    var row = cookieRowFor(platform, account);
    var parts = [
        I18n.t('cookies.accountStatusHead', {
            platform: I18n.t('platform.' + platform),
            account: cookieAccountWord(account),
        }),
    ];
    if (!row) {
        parts.push(I18n.t('cookies.accountStatusNone'));
    } else {
        parts.push(I18n.t('cookies.accountStatusSaved', { n: row.entries, when: row.saved_at }));
    }
    el.textContent = parts.join(' — ');
}

/* The profile sentence is gone (user, 2026-09-28): an account, its cookie file and its
   browser directory are one thing now — saving a cookie plants it into that account's own
   profile by itself — so 「它的浏览器里就是这份 Cookie」 described a state the panel is
   responsible for, not one the user can act on. Same for 「其中 N 条关窗口即失效」: since
   #148 every crawl runs in a headless browser that carries a desktop fingerprint, and a
   session cookie's lifetime is not a fact anybody chooses. What stays readable is the one
   case that is still the user's to know about: a cookie re-saved while its profile was
   held by a running crawl (``cookie.refreshHint``). */

function setCookieJobUI(on) {
    var actions = document.getElementById('cookie-job-actions');
    /* A verification resolves itself — showing "Done — I logged in" over it
       would invite a click that means nothing (and the server refuses it). */
    if (actions) actions.style.display = on && cookieJob.kind === 'login' ? 'flex' : 'none';
    ['cookie-platform', 'cookie-wait', 'cookie-json', 'cookie-entry', 'cookie-account'].forEach(function (id) {
        var el = document.getElementById(id);
        if (el) el.disabled = !!on;
    });
    var buttons = document.querySelectorAll('#cookie-content button');
    for (var i = 0; i < buttons.length; i++) {
        if (!buttons[i].closest('#cookie-job-actions')) buttons[i].disabled = !!on;
    }
}

function pollCookieJob() {
    fetchJSON('/api/cookies/generate/status').then(function (s) {
        if (!s.ok) return;
        var statusEl = document.getElementById('cookie-status');
        if (s.active) {
            cookieJob.active = true;
            cookieJob.known = true;
            cookieJob.platform = s.platform;
            cookieJob.kind = s.kind || 'login';
            setCookieJobUI(true);
            if (statusEl) {
                statusEl.textContent =
                    cookieJob.kind === 'verify'
                        ? I18n.t('cookie.verifying')
                        : I18n.t('cookie.waiting', { platform: platformLabels([s.platform]) });
            }
            return;
        }
        clearInterval(cookieJob.timer);
        cookieJob.timer = null;
        if (!cookieJob.known) {
            cookieJob.active = false;
            setCookieJobUI(false);
            return;
        }
        cookieJob.active = false;
        cookieJob.known = false;
        setCookieJobUI(false);
        if (!statusEl) return;
        if (s.phase === 'saved') {
            statusEl.textContent = I18n.t('cookie.savedN', { platform: platformLabels([s.platform]), n: s.count });
            showToast(I18n.t('toast.cookiesSaved') + ' - ' + platformLabels([s.platform]));
            refreshCookieStatus();
        } else if (s.phase === 'verified') {
            statusEl.textContent = (s.lines || []).join('\n');
        } else if (s.phase === 'cancelled') {
            statusEl.textContent = I18n.t('cookie.cancelledMsg', { platform: platformLabels([s.platform]) });
        } else if (s.phase === 'error') {
            statusEl.textContent = I18n.t('cookie.failed').replace('{err}', s.error || '');
        }
    });
}

function openCookieDialog(platform, account) {
    var dialog = document.getElementById('cookie-dialog');
    /* An optional platform AND account: the pre-run block sends the user here with the dead
       session already selected, because a panel that opens on whatever was last picked makes
       them hunt for the one login that is broken — and on a platform that holds several,
       naming the platform alone still leaves the wrong account in the box. */
    var select = document.getElementById('cookie-platform');
    var landed = false;
    if (platform && select) {
        var known = Array.prototype.some.call(select.options || [], function (option) {
            return option.value === platform;
        });
        if (known) {
            select.value = platform;
            landed = true;
            /* The visible half of an enhanced select is a span CustomSelect paints from the
               option text (the native control is kept at 1px and opacity 0), and it re-reads
               itself only on a pick or a refresh. Setting ``value`` alone lands the answer
               for every button below while the user still sees the platform they came in
               with — which is how 「打开」 in the saved-logins list read as doing nothing. */
            if (window.CustomSelect) CustomSelect.refreshAll();
        }
    }
    /* The account FOLLOWS the platform. Writing the box while the select refused to move
       would leave the panel showing one platform and naming another one's login — and
       every button below acts on the pair, so a half-landing is worse than none. */
    if (landed && account !== undefined) {
        setCookieAccountBox(account);
    }
    if (platform) {
        /* Naming a platform is never a toggle: the toolbar button opens and shuts
           this panel, and closing the panel over the answer the user was just sent
           to look at is the opposite of what a refusal wants. */
        dialog.classList.add('open');
    } else {
        dialog.classList.toggle('open');
        if (!dialog.classList.contains('open')) return;
    }
    renderCookieGuide();
    /* Adopt a job that is already running (started before the dialog was
       closed/reopened, or from another tab of this page). */
    fetchJSON('/api/cookies/generate/status').then(function (s) {
        if (s.ok && s.active) {
            cookieJob.active = true;
            cookieJob.known = true;
            cookieJob.platform = s.platform;
            cookieJob.kind = s.kind || 'login';
            setCookieJobUI(true);
            if (!cookieJob.timer) cookieJob.timer = setInterval(pollCookieJob, 1000);
        }
    });
    refreshCookieStatus();
}

function closeCookieDialog() {
    if (cookieJob.active) {
        /* While a login browser waits, this dialog's Done/Cancel buttons are
           the only way to resolve it — closing here would orphan that browser
           (and its driver process) with nobody watching. */
        showToast(I18n.t('cookie.mustStay'));
        return;
    }
    document.getElementById('cookie-dialog').classList.remove('open');
    /* The candidate popup lives on <body>, outside the dialog it belongs to: closing the
       panel over an open popup would leave a list of accounts floating on the canvas. */
    hideCookieAccountCandidates();
}

function saveCookieConfig() {
    var platform = document.getElementById('cookie-platform').value;
    var jsonStr = document.getElementById('cookie-json').value.trim();
    if (!jsonStr) {
        showToast(I18n.t('cookie.pasteFirst'));
        return;
    }
    try {
        var cookies = JSON.parse(jsonStr);
        fetchJSON('/api/cookies/save', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ platform: platform, cookies: cookies, account: cookieAccount() }),
        })
            .then(function (result) {
                if (result.ok) {
                    var savedWho = entryLabels([{ platform: platform, account: cookieAccount() }]);
                    showToast(I18n.t('toast.cookiesSaved') + ' - ' + savedWho);
                    document.getElementById('cookie-json').value = '';
                    /* The reply says what happened to the browser that crawls with this login —
                       planted, or deferred because that account's profile is held right now.
                       Showing only my own 「已保存」 toast hides the half the user acts on, and the
                       status refresh must not run first either: it answers asynchronously and
                       would overwrite this sentence a moment later. */
                    var statusEl = document.getElementById('cookie-status');
                    if (result.profile_note && statusEl) {
                        statusEl.textContent = result.message || '';
                        /* The cookie is on disk now, so refresh the cached rows — the per-account
                           line reads them, and without this it keeps claiming 「还没有保存过 Cookie」
                           while the summary right above says it is saved (the contradiction the user
                           hit after a save-into-profile). updateSummary=false keeps THIS planted
                           message: the refresh only re-reads rows + repaints the two account renderers. */
                        refreshCookieStatus(false);
                    } else {
                        refreshCookieStatus();
                    }
                    // The login is on disk now even when its profile plant was deferred, so
                    // the data-source account box must offer it without a page reload.
                    refreshAccountCandidates();
                } else {
                    showToast(I18n.t('cookie.failed', { err: result.error || '' }));
                }
            });
    } catch (e) {
        showToast(I18n.t('cookie.invalidJson', { err: e.message }));
    }
}

async function deleteCookie(platform, account) {
    /* Remove ONE saved cookie file. Called with nothing it speaks for the panel's own
       selection; a management row calls it WITH its row, because deleting whatever happens
       to be typed in the box is a different login than the one that was clicked.

       The confirmation has to be honest about what a file is: since a browser profile
       imports it once and is never re-planted, a platform that has logged in inside its own
       profile keeps that session, and deleting the snapshot does not sign it out. Saying
       「已删除，等于退出登录」 here would send the user to re-log in a session that is still
       live — the response's own profile_holds line says which of the two just happened. */
    var statusEl = document.getElementById('cookie-status');
    var named = platform !== undefined && platform !== null && platform !== '';
    if (!named) platform = cookiePlatform();
    if (!platform) return;
    if (account === undefined || account === null) account = cookieAccount();
    /* Two fixes in one line. The template names the platform TWICE and the old call used
       `.replace('{platform}', …)`, which fills the first occurrence only — so the user read a
       literal `{platform}` in the middle of a Chinese sentence, next to a raw `zhihu` key.
       And the dialog has to name the SESSION it is about to delete: one platform holds
       several logins, and 「删除 知乎 的 Cookie 文件」 while the account box says `work`
       describes a file this request does not touch. */
    var who = entryLabels([{ platform: platform, account: account }]);
    var answer = await showDialog({
        message: I18n.t('dialog.cookieDelete', { platform: who }),
        buttons: [
            { label: I18n.t('dialog.cookieDeleteYes'), value: 'delete', primary: true },
            { label: I18n.t('dialog.cancel'), value: null },
        ],
    });
    if (answer !== 'delete') return;
    var result = await fetchJSON('/api/cookies/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, account: String(account || '') }),
    });
    if (result.ok) {
        showToast(result.message || I18n.t('toast.cookieDeleted', { platform: who }));
        if (statusEl) statusEl.textContent = result.message || '';
        refreshCookieStatus();
        refreshAccountCandidates();
    } else if (statusEl) {
        statusEl.textContent = result.error || I18n.t('cookie.failed').replace('{err}', '');
    }
}

async function deleteCookieProfile(platform, account) {
    /* Throw away one account's browser PROFILE directory — the device itself, not the cookie
       file. The two are independent on purpose: 「删除 Cookie」 removes only the snapshot a
       throwaway browser is planted from, and a platform crawled inside its own profile keeps
       its live session in that profile, so retiring the device needs this separate action.

       Called with nothing it speaks for the dialog's own selection (platform dropdown + account
       box) exactly like ``deleteCookie``, so the Cookie dialog's 「删除已存 Profile」 button reuses
       it; a management row calls it WITH its row, because the clicked login is a different one
       than whatever is typed in the box.

       The default account is refused here as well as in the panel button: its browser data is
       the platform root folder that nests every named account, so deleting it would silently
       wipe them all — the same structural reason rename refuses the default. The server repeats
       the refusal, so a hand-built request cannot reach the platform root either. */
    var named = platform !== undefined && platform !== null && platform !== '';
    if (!named) platform = cookiePlatform();
    if (!platform) return;
    if (account === undefined || account === null) account = cookieAccount();
    var from = cookieAccountKey(account);
    if (from === COOKIE_DEFAULT_ACCOUNT) {
        showToast(I18n.t('cookies.profileDeleteDefaultRefused'));
        return;
    }
    var answer = await showDialog({
        message: I18n.t('dialog.profileDelete', {
            platform: I18n.t('platform.' + platform),
            account: cookieAccountWord(from),
        }),
        buttons: [
            { label: I18n.t('dialog.profileDeleteYes'), value: 'delete', primary: true },
            { label: I18n.t('dialog.cancel'), value: null },
        ],
    });
    if (answer !== 'delete') return;
    var result = await fetchJSON('/api/profiles/delete', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, account: from }),
    });
    var statusEl = document.getElementById('cookie-status');
    if (result.ok) {
        showToast(result.message || I18n.t('toast.profileDeleted'));
        if (statusEl) statusEl.textContent = result.message || '';
        // The device is gone, so the profile chip and the whole row state must be re-read.
        refreshCookieStatus();
        refreshAccountCandidates();
    } else if (statusEl) {
        statusEl.textContent = result.error || '';
    }
}

async function renameCookieAccount(platform, account) {
    /* Give one saved login a new name. The box is prefilled with the name it carries now, so
       what the user edits is the thing being renamed — and the answer is sent as the pair
       (platform, account), never as "whatever is typed in the panel's box", because that box
       is a different control on a different panel and may name another account by now.

       The server moves the cookie file AND that account's own browser directory, or neither,
       and says which of the two happened; a name that only half-moved would leave the account
       pointing at a device that is still called the old one. */
    var from = cookieAccountKey(account);
    if (!platform || from === COOKIE_DEFAULT_ACCOUNT) {
        showToast(I18n.t('cookies.renameDefaultRefused'));
        return;
    }
    var answer = await showDialog({
        message: I18n.t('dialog.cookieRename', { account: cookieAccountWord(from), platform: I18n.t('platform.' + platform) }),
        input: { value: from, placeholder: I18n.t('cookies.renamePlaceholder') },
        buttons: [
            { label: I18n.t('dialog.confirm'), primary: true },
            { label: I18n.t('dialog.cancel'), value: null },
        ],
    });
    // An input dialog answers with the TYPED text (the confirm button carries no value of its
    // own — that is the rule in AGENTS), so a dismissed dialog is the only null here.
    if (!answer) return;
    var to = cookieAccountKey(answer);
    if (to === from) {
        showToast(I18n.t('cookies.renameSame'));
        return;
    }
    var result = await fetchJSON('/api/cookies/rename', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, account: from, to: to }),
    });
    var statusEl = document.getElementById('cookie-status');
    if (result.ok) {
        showToast(result.message || I18n.t('toast.cookieRenamed'));
        if (statusEl) statusEl.textContent = result.message || '';
        // The box follows the name: a panel still typing the old one would save a NEW login
        // under the name that was just freed, which is the opposite of what was asked for.
        setCookieAccountBox(result.account);
        refreshCookieStatus();
        refreshAccountCandidates();
    } else if (statusEl) {
        statusEl.textContent = result.error || I18n.t('cookie.failed').replace('{err}', '');
        showToast(result.error || I18n.t('cookie.failed').replace('{err}', ''));
    }
}

function cookieEntryUrl() {
    var el = document.getElementById('cookie-entry');
    return el ? String(el.value || '').trim() : '';
}

/* One account, one name, one rule (user, 2026-09-28: 「哪有同一个东西不同规范的」). The default
   login is named ``default`` like any other account; the empty string is only its historical
   spelling, and it is folded HERE, at the one place the box is read, so no other code path has
   to know that the same account was once addressed by leaving a field blank. A name typed with
   capitals is lowercased for the same reason: the jar's key on this OS cannot tell ``Work``
   from ``work``, and two spellings of one login is what this refuses to keep. */
var COOKIE_DEFAULT_ACCOUNT = 'default';

function cookieAccountKey(text) {
    var key = String(text || '').trim().toLowerCase();
    return key === '' ? COOKIE_DEFAULT_ACCOUNT : key;
}

function cookieAccount() {
    /* Which login the panel's actions speak for, as the server knows it. Free text, folded to
       the canonical key: blank means the default account and arrives as ``default``, so what
       the user sees and what the file is named are one thing said one way.

       Typing a NEW name here is how a second login is created: 生成/保存 then write that
       account's file, and every node can pick it. */
    return cookieAccountKey(document.getElementById('cookie-account') ? document.getElementById('cookie-account').value : '');
}

function setCookieAccountBox(account) {
    /* Write the box from an account key: a name as saved, the default as ``default``. */
    var el = document.getElementById('cookie-account');
    if (el) el.value = cookieAccountKey(account);
}

/* The per-(platform, account) rows, cached from the one status read the panel makes.
   Everything under the account box renders from here — the candidates, the live line and
   the management table — because a keystroke must not buy a directory listing. */
var cookieRows = [];

function cookieRowsOf(platform) {
    return cookieRows.filter(function (row) {
        return row.platform === platform;
    });
}

/* The account box's own candidate popup, appended to <body> like CustomSelect's two popups:
   the Cookie panel is a fixed box that scrolls, so a popup living inside it would be clipped
   by the panel's own overflow. ``_csSource`` is what makes ``CustomSelect.ownsPopup`` count a
   click inside it as "still inside the dialog" — without that field an outside-click guard
   would close the panel the moment the user picked a candidate. */
var cookieCand = null;

function cookieCandMenu() {
    if (cookieCand && document.body.contains(cookieCand)) return cookieCand;
    var input = document.getElementById('cookie-account');
    if (!input) return null;
    var menu = document.createElement('div');
    menu.className = 'cand-menu';
    menu._csSource = input;
    document.body.appendChild(menu);
    cookieCand = menu;
    return menu;
}

function hideCookieAccountCandidates() {
    if (cookieCand) cookieCand.classList.remove('open');
}

function renderCookieAccounts(show) {
    /* The saved logins of the platform on screen, as the WORDS the user reads (a typed name
       as typed, a generated one as 默认账号 / 默认账号2), offered as a dropdown on the account
       box instead of a row of buttons permanently under it — the box is where the choice is
       made, and a permanent row made the panel taller for a choice made once per login.

       It stays a hand-built popup rather than the browser's own because the value it carries
       is the empty string: a <datalist> prints the VALUE, so the default account could only
       ever have appeared as a blank row, and a blank row is not a candidate anybody can
       decide to trust. Nothing saved, nothing shown — offering 「默认账号」 for a file that
       does not exist is how a node ends up naming a login this machine cannot produce. */
    var menu = cookieCandMenu();
    var input = document.getElementById('cookie-account');
    var select = document.getElementById('cookie-platform');
    if (!menu || !input) return;
    var rows = cookieRowsOf(select ? select.value : '');
    var typed = String(input.value || '').toLowerCase();
    var items = rows.filter(function (row) {
        if (!typed) return true;
        return cookieAccountLabel(row).toLowerCase().indexOf(typed) >= 0 || String(row.account || '').toLowerCase() === typed;
    });
    if (!show || !items.length) {
        menu.classList.remove('open');
        menu.textContent = '';
        return;
    }
    /* Listeners, not an inline onclick: the account name is user text, and putting it in an
       attribute means spanning two escaping grammars for a value that is only ever read back
       as a string. */
    menu.textContent = '';
    items.forEach(function (row) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = 'cand-option';
        b.dataset.account = cookieAccountKey(row.account);
        b.textContent = cookieAccountLabel(row);
        b.title = row.account || I18n.t('cookies.accountDefaultHint');
        b.addEventListener('mousedown', function (e) {
            e.preventDefault();  // keep the focus on the box so the click lands before blur hides it
        });
        b.addEventListener('click', function () {
            pickCookieAccount(b.dataset.account);
        });
        menu.appendChild(b);
    });
    var rect = input.getBoundingClientRect();
    menu.classList.add('open');
    menu.style.minWidth = rect.width + 'px';
    var wanted = menu.scrollWidth || rect.width;
    menu.style.width = Math.max(rect.width, wanted) + 'px';
    var top = rect.bottom + 3;
    if (top + menu.offsetHeight > window.innerHeight - 6) top = Math.max(6, rect.top - menu.offsetHeight - 3);
    menu.style.left = Math.max(6, Math.min(rect.left, window.innerWidth - menu.offsetWidth - 8)) + 'px';
    menu.style.top = top + 'px';
}

function pickCookieAccount(account) {
    /* Fill the box, not just the label: the box IS the answer every action below sends,
       so a candidate that only repainted the line under it would save under a different
       account than the one that was clicked. The box gets the account's NAME — ``default``
       for the platform's own login, which is why picking it no longer looks like a click that
       did nothing (reported 2026-09-28: the box went blank exactly when the right account was
       chosen, because blank used to be that account's spelling). */
    setCookieAccountBox(account);
    hideCookieAccountCandidates();
    renderCookieAccountStatus();
    renderCookieManager();
    showToast(
        I18n.t('cookies.chosen', {
            platform: I18n.t('platform.' + cookiePlatform()),
            account: cookieAccountWord(String(account || '')),
        })
    );
}

function cookieRowCells(row) {
    /* One row of the dock's table, built from the same classes 运行记录/导出产物 use, so a
       dock that is a different shape in every panel is not one panel but five. Elements, not
       a markup string: the account name is user text, and an inline
       ``onclick="fn('…','…')"`` would put it across two escaping grammars to reach a function
       that is right there anyway. */
    var cells = [
        { cls: 'runs-mgr-wf cookie-cell-platform', text: I18n.t('platform.' + row.platform) },
        { cls: 'runs-mgr-wf cookie-cell-account', text: cookieAccountLabel(row) },
        { cls: 'runs-mgr-id cookie-cell-entries', text: String(row.entries) },
        { cls: 'runs-mgr-time cookie-cell-saved', text: row.saved_at || I18n.t('cookies.unknownWhen') },
    ];
    var td = document.createElement('td');
    td.className = 'runs-mgr-ops';
    var ops = [{ label: 'cookies.renameOne', cls: 'cookie-mini runs-mgr-btn', go: function () { renameCookieAccount(row.platform, row.account); } }];
    if (cookieAccountKey(row.account) === COOKIE_DEFAULT_ACCOUNT) {
        /* 「重命名」 is offered for the other accounts only, and the reason is the directory
           layout rather than the name: 默认账号 owns no folder of its own — it IS
           ``<root>/<platform>``, the directory every other account of that platform is nested
           in. Naming it would move them with it. The row says that instead of offering a
           button that cannot do the thing. */
        ops[0].title = I18n.t('cookies.renameDefaultRefused');
        ops[0].cls += ' disabled';
        ops[0].disabled = true;
        ops[0].go = function () {
            showToast(I18n.t('cookies.renameDefaultRefused'));
        };
    }
    ops.push({ label: 'cookies.deleteOne', cls: 'cookie-mini runs-mgr-btn del', go: function () { deleteCookie(row.platform, row.account); } });
    /* 「删除 Profile」 only where there IS a profile directory to remove. The default account's
       row shows it greyed, not hidden — its browser data is the platform root that nests every
       named account, so the delete would over-reach; the tooltip says why, the same structural
       reason rename disables the default. A named account gets a working device-retire. */
    if (row.profile_exists) {
        var profOp = { label: 'cookies.deleteProfileOne', cls: 'cookie-mini runs-mgr-btn del', go: function () { deleteCookieProfile(row.platform, row.account); } };
        if (cookieAccountKey(row.account) === COOKIE_DEFAULT_ACCOUNT) {
            profOp.disabled = true;
            profOp.title = I18n.t('cookies.profileDeleteDefaultRefused');
            profOp.go = function () {
                showToast(I18n.t('cookies.profileDeleteDefaultRefused'));
            };
        }
        ops.push(profOp);
    }
    ops.forEach(function (spec) {
        var b = document.createElement('button');
        b.type = 'button';
        b.className = spec.cls;
        b.textContent = I18n.t(spec.label);
        if (spec.title) b.title = spec.title;
        if (spec.disabled) b.disabled = true;
        b.addEventListener('click', spec.go);
        td.appendChild(b);
    });
    return { cells: cells, ops: td };
}

function renderCookieManager() {
    /* Every saved login on this machine, one TABLE ROW per (platform, account): which platform,
       which account, how many entries, when it was taken, and the two actions. Metadata only —
       a cookie value is the login itself, and this is the one surface a stranger could stand
       in front of on a cloud deploy.

       It docks in the bottom slot with 控制台/运行记录/导出产物 (see ``toggleCookiesPanel``)
       rather than living inside the Cookie dialog: the list is the read side of a whole
       machine, and it used to push the paste box — the thing the user came to DO — off the
       bottom of a panel that only scrolls because of it. */
    var host = document.getElementById('cookies-mgr-body');
    if (!host) return;
    host.textContent = '';
    if (!cookieRows.length) {
        return void cookieListNote(host, 'cookies.noneSaved');
    }
    var table = document.createElement('table');
    table.className = 'data-preview-table runs-mgr-table';
    var head = document.createElement('thead');
    var headRow = document.createElement('tr');
    ['cookies.colPlatform', 'cookies.colAccount', 'cookies.colEntries', 'cookies.colSavedAt', 'cookies.colActions'].forEach(
        function (key) {
            var th = document.createElement('th');
            th.textContent = I18n.t(key);
            headRow.appendChild(th);
        }
    );
    head.appendChild(headRow);
    table.appendChild(head);
    var body = document.createElement('tbody');
    cookieRows.forEach(function (row) {
        var built = cookieRowCells(row);
        var tr = document.createElement('tr');
        /* The row carries its own account key: 「this row's delete/rename means THIS login」 has
           to be readable off the row it was clicked on, not inferred from what the dialog box
           happens to hold, and a test that presses the button must be able to say which row it
           pressed. */
        tr.className = 'cookie-row';
        tr.dataset.account = cookieAccountKey(row.account);
        tr.dataset.platform = String(row.platform || '');
        built.cells.forEach(function (cell) {
            var td = document.createElement('td');
            td.className = cell.cls;
            td.textContent = cell.text;
            tr.appendChild(td);
        });
        tr.appendChild(built.ops);
        body.appendChild(tr);
    });
    table.appendChild(body);
    host.appendChild(table);
}

function cookieListNote(host, key) {
    /* The empty answer and the failed answer are two different sentences and both are said
       the same way: one element, one textContent, no markup assembled from a response. */
    var note = document.createElement('div');
    note.className = 'cookie-row-empty';
    note.textContent = I18n.t(key);
    host.appendChild(note);
    return note;
}

/* ─── Saved logins panel (the bottom dock) ────────────────────── */
function toggleCookiesPanel() {
    var panel = document.getElementById('cookies-panel');
    if (!panel) return;
    if (panel.classList.contains('open')) {
        cookiesManager.close();
        return;
    }
    closeDockedPanels('cookies-panel');
    panel.classList.add('open');
    cookiesManager.refresh();
}

var cookiesManager = {
    panel() {
        return document.getElementById('cookies-panel');
    },

    close() {
        var panel = this.panel();
        if (!panel) return;
        panel.classList.remove('open');
        /* The dock resize handle leaves an inline height behind, and an inline height
           overrides the CSS ``height: 0`` — without this, Close looks dead. */
        panel.style.height = '';
    },

    refresh() {
        /* Ask the server, then paint: the dialog's own read is a different moment (it fires
           when a panel opens), and a list of what is on disk that answers from a cache the
           last paste left behind would be a list of what used to be on disk. */
        var self = this;
        return fetchJSON('/api/cookies/status')
            .then(function (result) {
                if (!result || !result.ok) throw new Error('status failed');
                cookieRows = result.rows || [];
                renderCookieManager();
            })
            .catch(function () {
                var body = document.getElementById('cookies-mgr-body');
                if (body) {
                    body.textContent = '';
                    cookieListNote(body, 'cookies.listFailed');
                }
            });
    },

    onLanguageChange() {
        /* Every word in this table is built by JS from a catalogue key — the platform name,
           the account's word, 「时间未知」, the two buttons — so ``I18n.apply()`` never reaches
           any of it, and the panel kept speaking the old language after a switch. Repainted
           from the rows already in hand: a language change is not new information about the
           disk, and asking the server for it would make the switch cost a directory listing. */
        renderCookieManager();
    },
};

function cookiePlatform() {
    var el = document.getElementById('cookie-platform');
    return el ? String(el.value || '') : '';
}

/* No 「把 Cookie 更新进 Profile」 button any more: saving a cookie now plants it into that
   account's own profile by itself (``app.py::_plant_saved_cookie_into_profile``), which is what
   the paste already meant. The one case the browser cannot take on the spot — its profile is
   held by a running crawl — is answered by the save message and by ``needs_refresh``, so the
   next crawl of that account brings the cookie in. A button that asked the user to notice a
   state the product is responsible for was itself the defect. */

function startCookiePolling() {
    cookieJob.active = true;
    cookieJob.known = true;
    setCookieJobUI(true);
    if (!cookieJob.timer) cookieJob.timer = setInterval(pollCookieJob, 1000);
}

function generateCookie() {
    if (cookieJob.active) return;  // single-flight: one login browser at a time
    var platform = document.getElementById('cookie-platform').value;
    var waitSeconds = parseInt(document.getElementById('cookie-wait').value) || 120;
    var statusEl = document.getElementById('cookie-status');
    statusEl.textContent = I18n.t('cookie.opening', {
        platform: entryLabels([{ platform: platform, account: cookieAccount() }]),
        s: waitSeconds,
    });
    fetchJSON('/api/cookies/generate', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
            platform: platform,
            wait_seconds: waitSeconds,
            url: cookieEntryUrl(),
            account: cookieAccount(),
        }),
    })
        .then(function (result) {
            if (result.ok) {
                cookieJob.platform = platform;
                cookieJob.kind = 'login';
                startCookiePolling();
                if (result.entry_rejected) {
                    /* The window is opening on the platform page instead — say
                       so, or the user logs into the wrong thing believing they
                       pasted a working link. */
                    showToast(result.entry_note || I18n.t('cookie.entryRejected'));
                }
            } else {
                statusEl.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
                if (result.busy) {
                    /* Another login is in flight (this tab or an earlier one):
                       adopt it so its Done/Cancel buttons appear here. */
                    startCookiePolling();
                }
            }
        });
}

function verifyCookie() {
    if (cookieJob.active) return;  // same single-flight as a login
    var platform = document.getElementById('cookie-platform').value;
    var statusEl = document.getElementById('cookie-status');
    statusEl.textContent = I18n.t('cookie.verifying');
    fetchJSON('/api/cookies/verify', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ platform: platform, url: cookieEntryUrl(), account: cookieAccount() }),
    }).then(function (result) {
        if (result.ok) {
            cookieJob.platform = platform;
            cookieJob.kind = 'verify';
            startCookiePolling();
            return;
        }
        cookieJob.kind = 'login';
        statusEl.textContent = result.error || I18n.t('cookie.failed').replace('{err}', '');
        if (result.busy) startCookiePolling();
    });
}

/* Why WeChat stops at the article body. Kept as one dialog rather than a
   disabled control with no reason: the platform's limit is a fact about the
   site, and the honest answer is shorter than the confusion of an empty box. */
function explainWechatLimits() {
    showDialog({
        message: I18n.t('settings.wechatLimitsBody'),
        buttons: [{ label: I18n.t('settings.close'), value: 'ok', primary: true }],
    });
}

function confirmCookieLogin() {
    fetchJSON('/api/cookies/generate/confirm', { method: 'POST' }).then(function (result) {
        var statusEl = document.getElementById('cookie-status');
        if (!result.ok && statusEl) {
            statusEl.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
        }
        /* Otherwise the 1s poll picks up the capture and settles the dialog. */
    });
}

function cancelCookieLogin() {
    fetchJSON('/api/cookies/generate/cancel', { method: 'POST' }).then(function (result) {
        var statusEl = document.getElementById('cookie-status');
        if (!result.ok && statusEl) {
            statusEl.textContent = I18n.t('cookie.failed').replace('{err}', result.error || '');
        }
    });
}

