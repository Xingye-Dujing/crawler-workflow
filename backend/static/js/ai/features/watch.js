/* Run-monitor deliveries: poll the account's pending events and hand them to the workspace.
 *
 * The server never calls a provider on its own (it holds no key), so a monitor's reaction happens
 * here, in the page that owns the credentials. The poller starts with the page, not with the dock:
 * a run can finish while the workspace is closed, and the event must still reach the transcript.
 * Delivery is acknowledged only after the workspace took it; an event that arrived while a turn
 * was streaming is retried on the next tick instead of being dropped — but a few attempts later it
 * is acknowledged as undeliverable, so one unusable event cannot retry forever (and cannot reopen
 * the settings panel every five seconds).
 */
const AIWatch = {
    _timer: null,
    _busy: false,
    _interval: 5000,
    _maxAttempts: 6,
    _attempts: new Map(),
    _onVisible: null,

    start() {
        if (this._timer) return;
        this._timer = setInterval(() => this.tick(), this._interval);
        this._onVisible = () => {
            if (!document.hidden) this.tick();
        };
        document.addEventListener('visibilitychange', this._onVisible);
        /* Bootstrap is what tells this poller which monitors are armed. `open()` loads it too, but
           the dock may stay closed for the whole run, and the file's contract is that the event
           still arrives. */
        if (typeof AIWorkspace !== 'undefined' && !AIWorkspace._bootstrap && !AIWorkspace._loading) {
            AIWorkspace._loading = true;
            AIWorkspace._loadBootstrap()
                .catch(() => {})
                .finally(() => {
                    AIWorkspace._loading = false;
                });
        }
        this.tick();
    },

    stop() {
        if (this._timer) clearInterval(this._timer);
        this._timer = null;
        if (this._onVisible) document.removeEventListener('visibilitychange', this._onVisible);
        this._onVisible = null;
    },

    async tick() {
        if (this._busy || typeof AIWorkspace === 'undefined') return;
        const conversationId = AIWorkspace._conversationId;
        const monitors = AIWorkspace._bootstrap?.monitors || [];
        if (!conversationId && !monitors.length) return;
        this._busy = true;
        try {
            const query = conversationId ? '?pending=1&conversation_id=' + encodeURIComponent(conversationId) : '?pending=1';
            const { data } = await AIHttp.get('/monitors/events' + query);
            for (const event of data.events || []) {
                const handled = await AIWorkspace.deliverMonitor(event);
                if (handled) {
                    this._attempts.delete(event.id);
                    await AIHttp.post('/monitors/events/' + encodeURIComponent(event.id) + '/ack');
                    continue;
                }
                const tries = (this._attempts.get(event.id) || 0) + 1;
                this._attempts.set(event.id, tries);
                if (tries < this._maxAttempts) {
                    // A streaming turn owns the transcript; keep this one pending for the next tick
                    // and leave the rest of the queue alone (it would interleave two answers).
                    break;
                }
                this._attempts.delete(event.id);
                AIWorkspace._toast(I18n.t('ai.monitor.undeliverable'));
                await AIHttp.post('/monitors/events/' + encodeURIComponent(event.id) + '/ack');
            }
        } catch (error) {
            /* A poll failure is retried on the next tick; it must never break the page. */
        } finally {
            this._busy = false;
        }
    },
};
window.AIWatch = AIWatch;
