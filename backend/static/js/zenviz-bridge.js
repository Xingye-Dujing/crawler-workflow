/* ============================================================================
   zenviz-bridge.js — runs INSIDE the embedded chart studio (zenviz.html)

   The studio is a self-contained single-file app whose whole state lives in a
   closure, so this bridge deliberately drives it through its own public DOM
   instead of reaching into internals:

     · #paste-data  + #parse-paste  → inject a dataset
     · #splash-enter                → skip the splash when embedded
     · #stage-title / #status-text  → read back what is on screen
     · #chart-frame                 → snapshot the rendered chart
     · #top-menu .menu-btn          → hand the nav over to the host bar and
                                      drive its dropdowns from up there

   Messages in  : zenviz:setData, zenviz:snapshot, zenviz:ping,
                  zenviz:openMenu, zenviz:closeMenu
   Messages out : zenviz:ready, zenviz:dataApplied, zenviz:snapshot,
                  zenviz:error, zenviz:menuState

   Because the studio is served from the same origin as the host page, the
   parent could script this DOM directly — postMessage is used anyway so the
   contract stays explicit and survives being moved to a sub-path later.
   ========================================================================== */
; (function () {
  'use strict'

  var EMBEDDED = window.parent && window.parent !== window
  var EMBED_MODE = /(?:^|[?&])embed=1(?:&|$)/.test(window.location.search)
  var ORIGIN = window.location.origin || '*'

  if (!EMBEDDED) return

  function post(msg) {
    msg.source = 'zenviz-bridge'
    try {
      window.parent.postMessage(msg, ORIGIN)
    } catch (e) {
      /* parent went away — nothing to report to */
    }
  }

  function $(sel) {
    return document.querySelector(sel)
  }

  /* ── Embedded mode: skip the splash screen ─────────────────────────────── */
  function dismissSplash() {
    var btn = document.getElementById('splash-enter')
    var splash = document.getElementById('splash')
    if (!splash) return
    if (btn) btn.click()
    /* Belt and braces: the click animates a 600ms fade, force it away. */
    setTimeout(function () {
      splash.style.display = 'none'
    }, 650)
  }

  /* ── Embedded mode: hand the studio's nav over to the host bar ────────────

     The studio ships its own top nav (engine / data / style / export). The host
     already has a toolbar, so the studio's row is hidden and its chips are
     mirrored up there instead — one toolbar, not two stacked lines.

     The dropdowns themselves keep rendering in here. Because the host bar sits
     directly above this document, this document's y = 0 IS the bar's bottom
     edge, so a dropdown anchored just below y = 0 looks like it hangs off the
     chip the user clicked. Only x has to be relayed. */
  function embedChrome() {
    if (document.getElementById('zenviz-embed-chrome')) return
    var st = document.createElement('style')
    st.id = 'zenviz-embed-chrome'
    st.textContent = [
      '#top-menu,#menu-trigger{display:none!important}',
      /* The workspace used to be pushed down so the sliding nav could not cover
         it. That nav is gone here, so the compensation has to go too. */
      'body.menu-pinned #workspace,',
      'body.submenu-open:not(.menu-pinned) #workspace{padding-top:14px!important}',
      '@media (max-width:720px){',
      '  body.menu-pinned #workspace,',
      '  body.submenu-open:not(.menu-pinned) #workspace{padding-top:12px!important}',
      '}',
    ].join('\n')
    document.head.appendChild(st)
  }

  function menuModel() {
    return Array.prototype.map.call(
      document.querySelectorAll('#top-menu .menu-btn[data-menu]'),
      function (b) {
        var group = b.closest('.menu-group')
        var label = group ? group.querySelector('.menu-label') : null
        return { id: b.dataset.menu, label: label ? (label.textContent || '').trim() : '' }
      }
    )
  }

  /* Clicking a hidden nav button is enough to make the studio open its own
     dropdown — only the default position (the invisible button's box) is wrong,
     so we overwrite it with the host chip's x afterwards.

     Both directions are written as "make it so", never as "toggle". The host and
     the studio each keep their own idea of which dropdown is open, and a toggle
     applied to a dropdown that is *already* in the wanted state flips it the
     wrong way — that desync is exactly what made a chip need two clicks. So:
     ensure the wanted state, verify it, then report what is actually true. */
  function openStudioMenu(menu, left) {
    var btn = document.querySelector('#top-menu .menu-btn[data-menu="' + menu + '"]')
    if (!btn) return false
    var dd = null
    for (var attempt = 0; attempt < 2; attempt++) {
      dd = document.getElementById('dd-' + menu)
      /* Clicking the chip toggles, so an already-open dropdown must not be
         clicked. A stale element (present but closed) does have to be clicked —
         the studio would close it first and then open it for us. */
      if (dd && dd.classList.contains('open')) break
      btn.click()
    }
    dd = document.getElementById('dd-' + menu)
    if (!dd || !dd.classList.contains('open')) return false
    /* offsetWidth can read as 0/undefined before layout — clamp defensively so
       a bad read cannot turn the position into NaN. */
    var width = Number(dd.offsetWidth) || 0
    var room = Math.max(0, (Number(window.innerWidth) || 0) - width - 8)
    dd.style.top = '3px'
    dd.style.left = Math.min(Math.max(0, Number(left) || 0), room) + 'px'
    reportMenuState(true)
    return true
  }

  function closeStudioMenu() {
    /* Only click a chip that really owns an open dropdown — the studio treats a
       chip click as a toggle, so clicking a closed one would OPEN it and the
       user's "close" would do the opposite. Two passes in case the studio
       replaced the element mid-flight. */
    for (var attempt = 0; attempt < 2; attempt++) {
      var open = document.querySelector('.dropdown.open')
      if (!open) break
      var owner = open.dataset.menu
      var btn = owner
        ? document.querySelector('#top-menu .menu-btn[data-menu="' + owner + '"]')
        : document.querySelector('#top-menu .menu-btn.active')
      if (!btn) break
      btn.click()
    }
    /* Whatever is left is not open — sweep it, and undo the two pieces of state
       the studio parks on <body> / the chip while a dropdown exists. */
    document.querySelectorAll('.dropdown').forEach(function (el) {
      el.remove()
    })
    document.body.classList.remove('submenu-open')
    var active = document.querySelector('#top-menu .menu-btn.active')
    if (active) active.classList.remove('active')
    reportMenuState(true)
  }

  /* The studio is the authority on dropdown lifetime — clicking the chart
     closes one via its own outside-click handler — so watch it and let the host
     chip follow rather than guessing. */
  var lastMenuState = null
  function reportMenuState(force) {
    /* Only an *open* dropdown counts. Falling back to any `.dropdown` would let
       a leftover element be reported as the open one, and the host would then
       paint a chip as active and send a close on the user's next click. */
    var dd = document.querySelector('.dropdown.open')
    var id = dd ? dd.dataset.menu || '' : ''
    if (!force && id === lastMenuState) return
    lastMenuState = id
    post({ type: 'zenviz:menuState', menu: id })
  }

  function watchMenus() {
    if (typeof window.MutationObserver !== 'function') return
    /* Wrapped: passing reportMenuState straight in would hand it the mutation
       array as its `force` argument, which is truthy — every body mutation would
       then be broadcast to the host. */
    new MutationObserver(function () {
      reportMenuState()
    }).observe(document.body, { childList: true })
  }

  /* ── Dataset injection ─────────────────────────────────────────────────── */

  /* The studio's parser sniffs the delimiter from the first line, so we always
     emit TSV and scrub tabs/newlines out of the values — that guarantees the
     tab branch wins and no cell can shift a column. */
  function toTSV(headers, rows) {
    function cell(v) {
      if (v === null || v === undefined) return ''
      return String(v).replace(/[\t\r\n]+/g, ' ').trim()
    }
    /* The backend hands rows over as objects keyed by column name
       ({月份: '一月', 阅读: 120}); older callers may pass arrays. Normalise
       both to a value array in header order before joining. */
    function values(r) {
      if (Array.isArray(r)) return r
      if (r && typeof r === 'object') {
        return (headers || []).map(function (h) {
          return r[h]
        })
      }
      return [r]
    }
    var lines = [(headers || []).map(cell).join('\t')]
      ; (rows || []).forEach(function (r) {
        lines.push(values(r).map(cell).join('\t'))
      })
    return lines.join('\n')
  }

  function applyData(payload) {
    var headers = payload.headers || []
    var rows = payload.rows || []
    if (!headers.length) throw new Error('empty dataset: no columns')

    var paste = document.getElementById('paste-data')
    var parse = document.getElementById('parse-paste')
    if (!paste || !parse) throw new Error('studio is still booting')

    paste.value = toTSV(headers, rows)
    parse.click()
    /* The data modal is a scratch surface — don't leave it open on top of the
       freshly rendered chart. */
    var closeBtn = document.getElementById('data-close')
    if (closeBtn && $('#data-modal') && $('#data-modal').classList.contains('open')) {
      closeBtn.click()
    }

    return { rows: rows.length, cols: headers.length }
  }

  /* ── Chart snapshot ────────────────────────────────────────────────────── */
  function snapshot(requestId) {
    var frame = document.getElementById('chart-frame')
    if (!frame) throw new Error('no chart frame')
    var empty = document.getElementById('empty-state')
    if (empty && empty.classList.contains('show')) throw new Error('no chart rendered yet')

    if (typeof window.html2canvas !== 'function') {
      throw new Error('html2canvas not available')
    }

    return window
      .html2canvas(frame, {
        backgroundColor: '#ffffff',
        scale: Math.min(2, window.devicePixelRatio || 1) * (requestId && requestId.scale ? requestId.scale : 1),
        useCORS: true,
        logging: false,
      })
      .then(function (canvas) {
        return canvas.toDataURL('image/png')
      })
  }

  /* ── Message router ────────────────────────────────────────────────────── */
  window.addEventListener('message', function (evt) {
    if (!evt || !evt.data) return
    if (evt.source !== window.parent) return
    var msg = evt.data
    if (!msg || typeof msg !== 'object') return

    if (msg.type === 'zenviz:ping') {
      post({ type: 'zenviz:ready' })
      return
    }

    if (msg.type === 'zenviz:openMenu') {
      var opened = false
      try {
        opened = openStudioMenu(msg.menu, msg.left)
      } catch (e) {
        /* A menu the studio does not know about is not worth an error toast —
           the host simply keeps its chip inactive. */
        opened = false
      }
      if (!opened) post({ type: 'zenviz:menuState', menu: '' })
      return
    }

    if (msg.type === 'zenviz:closeMenu') {
      closeStudioMenu()
      return
    }

    if (msg.type === 'zenviz:setData') {
      try {
        var shape = applyData(msg)
        post({
          type: 'zenviz:dataApplied',
          rows: shape.rows,
          cols: shape.cols,
          name: msg.name || '',
        })
      } catch (e) {
        post({ type: 'zenviz:error', stage: 'setData', error: String(e && e.message ? e.message : e) })
      }
      return
    }

    if (msg.type === 'zenviz:snapshot') {
      snapshot(msg)
        .then(function (dataUrl) {
          post({ type: 'zenviz:snapshot', dataUrl: dataUrl, name: msg.name || 'chart' })
        })
        .catch(function (e) {
          post({
            type: 'zenviz:error',
            stage: 'snapshot',
            error: String(e && e.message ? e.message : e),
          })
        })
      return
    }
  })

  /* ── Boot ──────────────────────────────────────────────────────────────── */
  function announceReady() {
    var stage = document.getElementById('stage-title')
    post({
      type: 'zenviz:ready',
      title: stage ? (stage.textContent || '').trim() : '',
      /* The host mirrors this nav into its own toolbar. */
      menus: menuModel(),
    })
  }

  function boot() {
    /* `?embed=1` is the host saying "you are a panel inside my UI" — only then
       does it carry the nav for us. */
    if (EMBED_MODE) {
      dismissSplash()
      embedChrome()
    }
    watchMenus()
    /* Give the studio's own init() a tick to attach its handlers before we
       announce we can take data. */
    setTimeout(announceReady, 300)
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', boot)
  } else {
    boot()
  }

  window.addEventListener('load', announceReady)
})()
