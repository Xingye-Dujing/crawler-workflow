/* ============================================================================
   custom-select.js — themed dropdowns for every candidate UI in a form

   Two things in a native form escape the stylesheet, and both are drawn by the
   OS rather than by CSS, so they always break out of the ZENVIZ palette
   (white sheet, blue highlight, rounded chrome):

     1. a <select>'s option popup
     2. an <input list="datalist">'s suggestion popup, plus the browser's own
        saved-value autofill dropdown

   This module keeps the real control in the DOM — so `value`, `onchange` and
   form semantics keep working — and layers a themed trigger + option list on
   top that we fully control.

     · <select>      → .cselect  (trigger + option menu)
     · input[list]   → .cand     (filtering suggestion menu)
     · text inputs   → autocomplete="off" so the OS autofill popup never opens

   The wrapper inherits the control's own class (.settings-select, .studio-select,
   …) so sizing and layout stay exactly as before. Dynamically rendered controls
   (the node settings panel is re-injected via innerHTML on every param change)
   are picked up by a body-level MutationObserver.
   ========================================================================== */
; (function () {
  'use strict'

  var INSTANCES = []
  var openInst = null
  var openCand = null

  /* ── helpers ───────────────────────────────────────────────────────────── */
  function labelFor(sel) {
    if (sel.multiple) {
      /* A lone option with no value is the app saying "there is nothing to pick"
         (see chartStudio._renderNoSource) — show that sentence, not a count. */
      if (sel.options.length === 1 && !sel.options[0].value) return sel.options[0].textContent
      /* A <select multiple> has no single "current" option, so the trigger
         reports the count instead. The template comes from the owner (see
         dataset.multiLabel) so the wording still follows the app language. */
      var n = 0
      for (var i = 0; i < sel.options.length; i++) {
        if (sel.options[i].selected && !sel.options[i].disabled) n++
      }
      if (!n) return sel.dataset.placeholder || '—'
      return (sel.dataset.multiLabel || '{n} selected').replace('{n}', n)
    }
    var o = sel.options[sel.selectedIndex]
    if (o) return o.textContent
    return sel.dataset.placeholder || '—'
  }

  function svgArrow() {
    var ns = 'http://www.w3.org/2000/svg'
    var svg = document.createElementNS(ns, 'svg')
    svg.setAttribute('class', 'cselect-arrow')
    svg.setAttribute('viewBox', '0 0 24 24')
    svg.setAttribute('fill', 'none')
    svg.setAttribute('stroke', 'currentColor')
    svg.setAttribute('stroke-width', '2')
    svg.setAttribute('stroke-linecap', 'round')
    svg.setAttribute('stroke-linejoin', 'round')
    var poly = document.createElementNS(ns, 'polyline')
    poly.setAttribute('points', '6 9 12 15 18 9')
    svg.appendChild(poly)
    return svg
  }

  /* Place a freshly rendered menu under (or above) its anchor, flipping when
     there isn't room below. Rows may carry a reason beside the label, so the
     menu is allowed to grow wider than its anchor up to MENU_MAX_WIDTH. */
  var MENU_MAX_WIDTH = 340
  function place(menu, anchor, minWidth) {
    menu.classList.add('open')
    var r = anchor.getBoundingClientRect()
    menu.style.minWidth = (minWidth || r.width) + 'px'
    menu.style.width = r.width + 'px'
    var wanted = menu.scrollWidth || 0
    if (wanted > r.width) menu.style.width = Math.min(wanted + 2, MENU_MAX_WIDTH) + 'px'
    var mh = menu.offsetHeight
    var top = r.bottom + 3
    if (top + mh > window.innerHeight - 6) top = Math.max(6, r.top - mh - 3)
    var w = menu.offsetWidth || r.width
    var maxLeft = Math.max(6, (window.innerWidth || 0) - w - 8)
    menu.style.left = Math.max(6, Math.min(r.left, maxLeft)) + 'px'
    menu.style.top = top + 'px'
  }

  function closeAny() {
    if (openInst) openInst.close()
    if (openCand) openCand.hide()
  }

  /* ══ <select> ═══════════════════════════════════════════════════════════ */
  function enhance(sel) {
    if (!sel || sel.dataset.cselect) return
    sel.dataset.cselect = '1'

    var wrap = document.createElement('span')
    /* inherit the field class so width/padding/border stay identical */
    wrap.className = 'cselect' + (sel.className ? ' ' + sel.className : '')
    sel.parentNode.insertBefore(wrap, sel)

    var trigger = document.createElement('button')
    trigger.type = 'button'
    trigger.className = 'cselect-trigger'

    var value = document.createElement('span')
    value.className = 'cselect-value'
    value.textContent = labelFor(sel)

    trigger.appendChild(value)
    trigger.appendChild(svgArrow())
    /* Mirror the full text now, not only when the menu is next built: the label
       ellipsises inside a control whose width follows its field, and a control that
       has never been opened would have said nowhere what it had cut off. */
    trigger.title = value.textContent
    wrap.appendChild(trigger)
    wrap.appendChild(sel) /* move the native select inside (kept for value) */
    sel.tabIndex = -1

    var menu = document.createElement('div')
    menu.className = 'cselect-menu'
    /* The popup is rendered into <body>, so remember the control it belongs to.
       Outside-click guards use this to tell "picked an option" from "clicked
       away" — see CustomSelect.ownsPopup. */
    menu._csSource = sel
    document.body.appendChild(menu)

    var inst = { sel: sel, wrap: wrap, trigger: trigger, value: value, menu: menu }
    /* Set by the trigger's mousedown when it opens the menu, consumed by the
       outside-click guard below. See the note there. */
    inst.armed = false

    function syncLabel() {
      value.textContent = labelFor(sel)
      trigger.title = value.textContent
    }

    /* ── multiple ──────────────────────────────────────────────────────────
       A <select multiple> is a checklist rather than a menu: ticking a row adds
       to the selection instead of replacing it, and the menu stays open so
       several rows can be picked in one go. `activeIdx` is where the keyboard
       is — arrows move it, Enter / Space tick. */
    var multi = !!sel.multiple
    var activeIdx = -1

    /* Repaint one row's chosen state in place, so a long list keeps its scroll
       position while several rows are ticked. */
    function paintRow(i) {
      var rows = menu.querySelectorAll('.cselect-option')
      if (rows[i]) rows[i].classList.toggle('selected', !!sel.options[i].selected)
    }

    function paintActive() {
      var rows = menu.querySelectorAll('.cselect-option')
      Array.prototype.forEach.call(rows, function (row, i) {
        row.classList.toggle('active', i === activeIdx)
      })
      var cur = rows[activeIdx]
      if (cur && cur.scrollIntoView) cur.scrollIntoView({ block: 'nearest' })
    }

    function toggleAt(i) {
      var o = sel.options[i]
      if (!o || o.disabled) return false
      o.selected = !o.selected
      paintRow(i)
      /* let the original inline onchange / listeners run */
      sel.dispatchEvent(new Event('change', { bubbles: true }))
      syncLabel()
      return true
    }

    function build() {
      menu.textContent = ''
      var opts = sel.options
      for (var i = 0; i < opts.length; i++) {
        ; (function (i) {
          var o = opts[i]
          var chosen = multi ? !!o.selected : i === sel.selectedIndex
          var b = document.createElement('button')
          b.type = 'button'
          /* A disabled option is still worth painting: it is how the app says
             "this row exists, you cannot use it, and here is why". The reason
             rides on data-reason (full sentence, also the tooltip) and
             data-note (abbreviated, shown next to the label). */
          b.className =
            'cselect-option' +
            (chosen ? ' selected' : '') +
            (o.disabled ? ' disabled' : '') +
            (multi ? ' multi' : '') +
            (i === activeIdx ? ' active' : '')
          if (multi) {
            /* With several rows tickable at once an underline reads as
               "current", so a box says "chosen" instead. */
            var check = document.createElement('span')
            check.className = 'cselect-check'
            b.appendChild(check)
          }
          var label = document.createElement('span')
          label.className = 'cselect-option-label'
          label.textContent = o.textContent
          b.appendChild(label)
          if (o.dataset && o.dataset.note) {
            var note = document.createElement('span')
            note.className = 'cselect-option-note'
            note.textContent = o.dataset.note
            b.appendChild(note)
          }
          if (o.title || (o.dataset && o.dataset.reason)) {
            b.title = o.title || o.dataset.reason
          } else {
            /* The label ellipsises when the row is wider than the capped menu, so
               without this the full text exists nowhere the user can read it. */
            b.title = o.textContent
          }
          b.addEventListener('click', function (e) {
            e.stopPropagation()
            if (o.disabled) {
              /* Report the block instead of selecting it — the control's owner
                 knows how loud to be about it. A checklist stays open so the
                 user can carry on with the rows that do work. */
              sel.dispatchEvent(
                new CustomEvent('cselect-blocked', {
                  bubbles: true,
                  detail: {
                    value: o.value,
                    label: o.textContent,
                    reason: (o.dataset && o.dataset.reason) || o.title || '',
                  },
                })
              )
              if (!multi) close()
              return
            }
            if (multi) {
              activeIdx = i
              paintActive()
              toggleAt(i)
              return
            }
            if (sel.selectedIndex !== i) {
              sel.selectedIndex = i
              /* let the original inline onchange / listeners run */
              sel.dispatchEvent(new Event('change', { bubbles: true }))
            }
            syncLabel()
            close()
          })
          menu.appendChild(b)
        })(i)
      }
    }

    function open() {
      if (sel.disabled || !sel.options.length) return
      if (openInst && openInst !== inst) openInst.close()
      if (openCand) openCand.hide()
      /* Land the keyboard cursor on the current choice — or the first usable
         row — so the arrows start from where the user is. */
      activeIdx = -1
      if (multi) {
        for (var i = 0; i < sel.options.length; i++) {
          if (!sel.options[i].disabled && sel.options[i].selected) {
            activeIdx = i
            break
          }
        }
        if (activeIdx < 0) {
          for (var j = 0; j < sel.options.length; j++) {
            if (!sel.options[j].disabled) {
              activeIdx = j
              break
            }
          }
        }
      }
      build()
      place(menu, trigger)
      wrap.classList.add('open')
      openInst = inst
      /* The bar can re-wrap under us at any moment (see followAnchor). */
      startFollow()
    }

    function close() {
      menu.classList.remove('open')
      wrap.classList.remove('open')
      activeIdx = -1
      if (openInst === inst) openInst = null
    }

    inst.open = open
    inst.close = close

    /* Toggle on mousedown rather than click. A `click` only fires when press and
       release land on the same element, and both of those can move in between:
       the bar re-wraps, the popup animates in, the label changes width. When
       that happened the click was simply swallowed and the control looked like
       it needed a second press — mousedown always arrives. */
    trigger.addEventListener('mousedown', function (e) {
      if (e.button !== 0) return
      /* Don't let the press move focus (and with it the browser's
         scroll-the-target-into-view, which would slide the anchor out from
         under the popup we are about to place). */
      e.preventDefault()
      e.stopPropagation()
      if (sel.disabled) return
      if (menu.classList.contains('open')) close()
      else {
        open()
        inst.armed = true
      }
    })

    /* The click that pairs with that mousedown is now redundant, but it still
       bubbles — keep it away from the outside-click guard below. */
    trigger.addEventListener('click', function (e) {
      e.stopPropagation()
    })

    trigger.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') {
        close()
        return
      }
      if (e.key !== 'ArrowDown' && e.key !== 'ArrowUp' && e.key !== 'Enter' && e.key !== ' ') {
        return
      }
      e.preventDefault()
      if (!menu.classList.contains('open')) {
        open()
        return
      }
      var down = e.key === 'ArrowDown'
      var up = e.key === 'ArrowUp'
      var dir = up ? -1 : 1
      var opts = sel.options

      if (multi) {
        /* Checklist behaviour: arrows move the cursor, Enter / Space tick.
           Rows the picker disabled for a reason are walked past, never landed
           on — the same rule the single-choice path uses. */
        if (!down && !up) {
          toggleAt(activeIdx)
          return
        }
        var from = activeIdx < 0 ? (dir > 0 ? -1 : opts.length) : activeIdx
        for (var n = from + dir; n >= 0 && n < opts.length; n += dir) {
          if (!opts[n].disabled) {
            activeIdx = n
            paintActive()
            break
          }
        }
        return
      }

      var next = sel.selectedIndex
      for (var i = next + dir; i >= 0 && i < opts.length; i += dir) {
        if (!opts[i].disabled) {
          next = i
          break
        }
      }
      if (next !== sel.selectedIndex) {
        sel.selectedIndex = next
        sel.dispatchEvent(new Event('change', { bubbles: true }))
        syncLabel()
        build()
      }
    })

    sel.addEventListener('change', syncLabel)
    sel.addEventListener('input', syncLabel)
    /* sel.disabled flips over the session — a source list that starts empty and
       fills in later — so the wrapper has to follow it, not just sample it. */
    function syncDisabled() {
      wrap.classList.toggle('disabled', !!sel.disabled)
    }
    syncDisabled()
    inst.syncDisabled = syncDisabled

    /* option lists are often rebuilt by the app (and `disabled` flips with
       them) — stay in sync with both */
    if (window.MutationObserver) {
      new MutationObserver(function () {
        if (!inst.wrap.isConnected) return
        syncDisabled()
        syncLabel()
        if (menu.classList.contains('open')) {
          build()
          /* A rebuilt list can be wider (a new node's label) or appear after the
             bar has already shifted — re-seat it, don't just re-render it. */
          place(menu, trigger)
        }
      }).observe(sel, {
        childList: true,
        subtree: true,
        attributes: true,
        attributeFilter: ['disabled'],
      })
    }

    INSTANCES.push(inst)
  }

  /* ══ input[list] — suggestion candidates ════════════════════════════════ */
  function candOptions(input) {
    var id = input.dataset.clist
    if (!id) return []
    var dl = document.getElementById(id)
    if (!dl) return []
    return Array.prototype.map
      .call(dl.querySelectorAll('option'), function (o) {
        var v = o.getAttribute('value')
        return v !== null ? v : o.textContent || ''
      })
      .filter(function (v) {
        return v !== ''
      })
  }

  function enhanceInput(input) {
    if (!input || input.dataset.cinput) return
    if (!input.getAttribute('list')) return
    input.dataset.cinput = '1'
    /* Detach the list so the OS popup can never appear, but remember it so we
       can still read the source options. */
    input.dataset.clist = input.getAttribute('list')
    input.removeAttribute('list')

    var menu = document.createElement('div')
    menu.className = 'cand-menu'
    /* Same trick as the select popup: remember the owning input. */
    menu._csSource = input
    document.body.appendChild(menu)

    var active = -1
    var inst = { input: input, menu: menu }

    function render() {
      var all = candOptions(input)
      var q = (input.value || '').toLowerCase()
      var items = q
        ? all.filter(function (v) {
          return v.toLowerCase().indexOf(q) >= 0
        })
        : all
      if (active >= items.length) active = items.length - 1

      menu.textContent = ''
      if (!items.length) {
        hide()
        return
      }
      items.forEach(function (v, i) {
        var b = document.createElement('button')
        b.type = 'button'
        b.className = 'cand-option' + (i === active ? ' active' : '')
        b.textContent = v
        /* keep focus on the field so typing continues to filter */
        b.addEventListener('mousedown', function (e) {
          e.preventDefault()
        })
        b.addEventListener('click', function (e) {
          e.stopPropagation()
          input.value = v
          input.dispatchEvent(new Event('input', { bubbles: true }))
          input.dispatchEvent(new Event('change', { bubbles: true }))
          hide()
        })
        menu.appendChild(b)
      })
      place(menu, input)
    }

    function show() {
      if (input.disabled || input.readOnly) return
      if (openInst) openInst.close()
      if (openCand && openCand !== inst) openCand.hide()
      render()
      if (menu.classList.contains('open')) {
        openCand = inst
        startFollow()
      }
    }

    function hide() {
      menu.classList.remove('open')
      if (openCand === inst) openCand = null
      active = -1
    }

    function move(step) {
      var opts = menu.querySelectorAll('.cand-option')
      if (!opts.length) return
      active = (active + step + opts.length) % opts.length
      Array.prototype.forEach.call(opts, function (o, i) {
        o.classList.toggle('active', i === active)
      })
      opts[active].scrollIntoView({ block: 'nearest' })
    }

    function commit() {
      var cur = menu.querySelector('.cand-option.active')
      if (!cur) return false
      input.value = cur.textContent
      input.dispatchEvent(new Event('input', { bubbles: true }))
      input.dispatchEvent(new Event('change', { bubbles: true }))
      hide()
      return true
    }

    input.addEventListener('focus', show)
    input.addEventListener('click', show)
    input.addEventListener('input', function () {
      active = -1
      show()
    })
    input.addEventListener('keydown', function (e) {
      if (e.key === 'ArrowDown') {
        e.preventDefault()
        if (!menu.classList.contains('open')) show()
        else move(1)
      } else if (e.key === 'ArrowUp') {
        e.preventDefault()
        move(-1)
      } else if (e.key === 'Enter') {
        /* only swallow Enter when we actually completed something */
        if (menu.classList.contains('open') && commit()) e.preventDefault()
      } else if (e.key === 'Escape') {
        if (menu.classList.contains('open')) e.stopPropagation()
        hide()
      } else if (e.key === 'Tab') {
        hide()
      }
    })
    input.addEventListener('blur', function () {
      /* delayed so a click on a suggestion still lands */
      setTimeout(hide, 120)
    })

    /* the datalist itself may be swapped out — re-read every time */
    inst.hide = hide
    inst.el = menu
  }

  /* ══ text inputs: never let the OS autofill popup open ══════════════════ */
  function killAutofill(root) {
    var list = (root || document).querySelectorAll(
      'input[type="text"], input[type="search"], input:not([type])'
    )
    Array.prototype.forEach.call(list, function (el) {
      if (el.dataset.noautofill) return
      el.dataset.noautofill = '1'
      el.setAttribute('autocomplete', 'off')
      el.setAttribute('spellcheck', 'false')
    })
  }

  /* ── public surface ────────────────────────────────────────────────────── */
  var CustomSelect = {
    init() {
      this.scan(document)

      /* Node settings are re-rendered with innerHTML on every param change,
         so new controls keep appearing — watch for them. */
      if (window.MutationObserver) {
        var pending = false
        new MutationObserver(function () {
          if (pending) return
          pending = true
          requestAnimationFrame(function () {
            pending = false
            CustomSelect.scan(document)
          })
        }).observe(document.body, { childList: true, subtree: true })
      }
    },

    scan(root) {
      this.enhanceAll(root)
      this.enhanceInputs(root)
      killAutofill(root)
    },

    enhanceAll(root) {
      var list = (root || document).querySelectorAll('select:not([data-cselect])')
      Array.prototype.forEach.call(list, enhance)
    },

    enhanceInputs(root) {
      var list = (root || document).querySelectorAll('input[list]:not([data-cinput])')
      Array.prototype.forEach.call(list, enhanceInput)
    },

    /* Re-read every trigger label (option text follows the active language). */
    refreshAll() {
      INSTANCES = INSTANCES.filter(function (inst) {
        if (!inst.wrap.isConnected) {
          if (inst.menu.parentNode) inst.menu.parentNode.removeChild(inst.menu)
          return false
        }
        if (inst.syncDisabled) inst.syncDisabled()
        inst.value.textContent = labelFor(inst.sel)
        inst.trigger.title = inst.value.textContent
        return true
      })
    },

    /* True when `node` lies inside an open popup (dropdown rows / suggestion
       candidates) that belongs to a control within `container`. Both popups are
       appended to <body>, so a plain `container.contains(node)` test reports
       "clicked away" while the user is actually picking an option — and an
       outside-click guard would then close the panel being edited. */
    ownsPopup(node, container) {
      if (!node || !node.closest || !container) return false
      var popup = node.closest('.cselect-menu, .cand-menu')
      return !!(popup && popup._csSource && container.contains(popup._csSource))
    },

    close: closeAny,
  }

  /* ── Keeping an open popup glued to its anchor ─────────────────────────────

     Both popups are `position: fixed`, so any scroll — the page, a panel, or
     the browser bringing a just-focused control into view — slides the anchor
     out from under the popup. This used to close the popup on any scroll at all,
     and that is the other half of the "why does it take two clicks" bug: the
     first press scrolled the focused control into view, that scroll killed the
     brand-new popup, and only the second press (nothing left to scroll) stayed
     open. Re-place instead of dismiss — the popup follows its anchor, and it is
     only dropped when the anchor itself leaves the viewport. */
  function reanchor() {
    if (openInst) {
      var r = openInst.trigger.getBoundingClientRect()
      if (r.bottom < 0 || r.top > window.innerHeight) openInst.close()
      else place(openInst.menu, openInst.trigger)
    }
    if (openCand) place(openCand.menu, openCand.input)
  }

  /* ── Following a re-layout, which fires no event at all ────────────────────

     The studio bar is a flex row that right-aligns its fields, so *adding* a
     control — the combine-direction picker appearing as soon as a second node
     is ticked — pushes everything already in the row to the left. A popup opened
     before that change keeps the coordinates it was placed with and ends up
     floating beside its trigger instead of under it: no scroll, no resize, so
     neither browser event arrives.

     So while a popup is up, sample its anchor's box once a frame and re-place on
     any movement. rAF means this costs nothing when the tab is in the
     background, and it stops the moment the popup closes. `place()` only writes
     styles on the fixed-position popup, so the anchor's box cannot be disturbed
     by the re-placing itself — the loop settles instead of thrashing. */
  var followRaf = 0
  var lastBox = null

  function boxChanged(box) {
    if (!lastBox) return true
    return (
      lastBox.left !== box.left ||
      lastBox.top !== box.top ||
      lastBox.width !== box.width ||
      lastBox.height !== box.height
    )
  }

  function followAnchor() {
    followRaf = 0
    var anchor = openInst ? openInst.trigger : openCand ? openCand.input : null
    if (!anchor) {
      lastBox = null
      return
    }
    var box = anchor.getBoundingClientRect()
    if (boxChanged(box)) {
      lastBox = { left: box.left, top: box.top, width: box.width, height: box.height }
      reanchor()
    }
    followRaf = requestAnimationFrame(followAnchor)
  }

  function startFollow() {
    lastBox = null
    /* A popup only exists for a moment, so this is the cheapest moment to make
       sure the page's iframes are being listened to as well. */
    watchFrames()
    if (!followRaf) followRaf = requestAnimationFrame(followAnchor)
  }

  /* ── Presses that land inside an embedded frame ────────────────────────────

     The chart workbench under the studio bar is an iframe, and that frame is
     where most of an "outside click" actually lands. A press in there is
     dispatched to the *inner* document: it never reaches this one, so neither
     the click handler below nor any capture listener here ever sees it, and the
     popup stayed up over a bar the user had plainly clicked away from.

     The frame is same-origin, so we can listen in its document directly. A
     frame we are not allowed to touch (cross-origin) is skipped — the window
     blur fallback below still catches those. */
  function watchFrame(frame) {
    if (!frame || frame.__csWatched) return
    var doc
    try {
      doc = frame.contentDocument
    } catch (e) {
      return
    }
    if (!doc || !doc.addEventListener) return
    frame.__csWatched = true
    doc.addEventListener('mousedown', function () { closeAny() }, true)
    doc.addEventListener('keydown', function (e) {
      if (e.key === 'Escape') closeAny()
    })
  }

  function watchFrames() {
    Array.prototype.forEach.call(document.querySelectorAll('iframe'), function (frame) {
      watchFrame(frame)
      if (frame.__csLoadHooked) return
      frame.__csLoadHooked = true
      /* A reload swaps in a fresh document and our listener goes with the old
         one — start over once the new page is up. */
      frame.addEventListener('load', function () {
        frame.__csWatched = false
        watchFrame(frame)
      })
    })
  }

  /* ── Dismissal ─────────────────────────────────────────────────────────────

     One popup at a time, dismissed by a click that lands anywhere else — with
     one exception. The trigger opens on mousedown, so the menu is already on
     screen when the button is released; if the release happens to land on the
     popup (it appears right under the cursor), the click event's target becomes
     the nearest common ancestor of press and release — <body> — and the popup
     would close itself the instant it opened. `armed` marks exactly that one
     click so it can be swallowed. It is cleared by the next mousedown, so a
     press with no matching click (released outside the window) cannot leave it
     armed. */
  document.addEventListener(
    'mousedown',
    function () {
      if (openInst) openInst.armed = false
    },
    true
  )

  document.addEventListener('click', function (e) {
    if (!openInst && !openCand) return
    if (openInst && openInst.armed) {
      openInst.armed = false
      return
    }
    if (e.target.closest('.cselect-menu') || e.target.closest('.cand-menu')) return
    /* The trigger owns its own toggle — a click there must not also be read as
       "clicked away" (see the mousedown handler in enhance()). */
    if (e.target.closest('.cselect-trigger')) return
    /* Same for the input a candidate popup belongs to. `focus` opens the popup
       on mousedown; the click that follows bubbles up here, and without this
       exemption it would close what it just opened — the popup flashed and
       looked like "the click did nothing". Whether a click event even fires
       depends on press and release landing on the same element, which is why
       the field seemed to open on some clicks and not others. */
    if (openCand && (e.target === openCand.input || openCand.input.contains(e.target))) {
      return
    }
    closeAny()
  })
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') closeAny()
  })
  /* Last resort for a press we cannot see: a frame we are not allowed into, or
     one that swallows the event. Focus leaving the page means the press went
     somewhere outside it, which is all the dismissal rule needs to know. */
  window.addEventListener('blur', function () {
    if (openInst || openCand) closeAny()
  })
  window.addEventListener('resize', reanchor)
  /* Capture phase on purpose: a scroll inside a panel never reaches the window,
     and those are exactly the ones that move the popup off its anchor. */
  window.addEventListener('scroll', reanchor, true)

  window.CustomSelect = CustomSelect
})()
