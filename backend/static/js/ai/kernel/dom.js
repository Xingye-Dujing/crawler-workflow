/* Safe DOM plumbing for the workspace: the one paint and the lookups it must not lose.
 *
 * A streaming answer repaints the block stream on every delta, so "replace the HTML" is not an
 * operation this page can afford: `AIDom.morph` skips an unchanged picture, keeps the disclosures the
 * reader opened, and holds the scroll position. This is the paint the transcript's own turn rows
 * use (`_refreshTurnEl`); the live flow keeps `_paintAssistant`'s memo key, and both remember the
 * disclosures through the same store.
 */

/* One paint, one rule: an unchanged picture is not rewritten. */
const AIDom = {
    /** Paint `html` into `el` only when `signature` changed; `true` when it did. */
    morph(el, signature, html) {
        if (!el) return false;
        if (el.__aiSig === signature) return false;
        /* Replacing innerHTML briefly empties the flow and the browser clamps scrollTop to 0 before
         * the new content is measured — the reader lands at the top on every delta without this. */
        const scroller = el.closest ? el.closest('.ai-transcript') : null;
        const top = scroller ? scroller.scrollTop : 0;
        el.__aiSig = signature;
        el.innerHTML = html;
        if (scroller) scroller.scrollTop = top;
        return true;
    },
};

Object.assign(AIWorkspace, {
    /* Disclosure state belongs to the reader, not to the paint. Keyed by ``data-ai-detail`` (a
       thinking block's index, a tool call's id, an artifact's id), so the same card keeps its
       state across repaints AND across a stored-transcript repaint. */
    _collectOpenDetails(root) {
        if (!root || typeof root.querySelectorAll !== 'function') return;
        for (const el of root.querySelectorAll('details[data-ai-detail]')) {
            const key = String((el.getAttribute && el.getAttribute('data-ai-detail')) || '');
            if (!key) continue;
            const open = el.open === true || (el.hasAttribute && el.hasAttribute('open'));
            if (open) this._openDetails.add(key);
            else this._openDetails.delete(key);
        }
    },

    /* One writer for a disclosure's state, because a programmatic `.open` (the tool row click) does
       not always reach the capture listener in time for the next paint. */
    _setDetailOpen(detail, open) {
        if (!detail) return;
        detail.open = !!open;
        const key = String((detail.getAttribute && detail.getAttribute('data-ai-detail')) || '');
        if (key) {
            if (open) this._openDetails.add(key);
            else this._openDetails.delete(key);
        }
        const card = detail.parentElement;
        if (card && card.classList && card.classList.contains('ai-tool')) card.classList.toggle('is-open', !!open);
    },

    _applyOpenDetails(root) {
        if (!root || typeof root.querySelectorAll !== 'function' || !this._openDetails.size) return;
        for (const el of root.querySelectorAll('details[data-ai-detail]')) {
            const key = String((el.getAttribute && el.getAttribute('data-ai-detail')) || '');
            if (key && this._openDetails.has(key)) this._setDetailOpen(el, true);
        }
    },

    _findByData(root, attribute, value) {
        return Array.from(root.querySelectorAll('[' + attribute + ']')).find((el) => el.getAttribute(attribute) === String(value));
    },

    /* A repaint reuses the element it already drew for this turn; content is refreshed only when
       the stored picture actually changed, and never under the live turn (its blocks are ahead of
       the store while it streams). */
    _refreshTurnEl(el, turn) {
        if (this._current && el === this._current.el) return;
        if (!AIDom.morph(el, this._turnSignature(turn), this._turnHtml(turn))) return;
        this._fillTurnExtras(el, turn);
        this._applyOpenDetails(el);
    },

    _schedulePaint(current) {
        if (this._renderTimer) return;
        this._renderTimer = setTimeout(() => {
            this._renderTimer = null;
            this._paintAssistant();
        }, 90);
    },

});
