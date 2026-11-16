/* Run-monitor deliveries: poll the account's pending events and hand them to the workspace.
 *
 * The server never calls a provider on its own (it holds no key), so a monitor's reaction happens
 * here, in the page that owns the credentials. The poller starts with the page, not with the dock:
 * a run can finish while the workspace is closed, and the event must still reach the transcript.
 * Delivery is acknowledged only after the workspace took it; an event that arrived while a turn
 * was streaming is retried on the next tick instead of being dropped.
 */
const AIWatch = {
    _timer: null,
    _busy: false,
    _interval: 5000,

    start() {
        if (this._timer) return;
        this._timer = setInterval(() => this.tick(), this._interval);
        document.addEventListener('visibilitychange', () => {
            if (!document.hidden) this.tick();
        });
        this.tick();
    },

    stop() {
        if (this._timer) clearInterval(this._timer);
        this._timer = null;
    },

    async tick() {
        if (this._busy || typeof AIWorkspace === 'undefined') return;
        const conversationId = AIWorkspace._conversationId;
        const monitors = AIWorkspace._bootstrap?.monitors || [];
        if (!conversationId && !monitors.length) return;
        this._busy = true;
        try {
            const query = conversationId ? '?pending=1&conversation_id=' + encodeURIComponent(conversationId) : '?pending=1';
            const response = await fetch('/api/ai/monitors/events' + query);
            const data = await response.json();
            for (const event of data.events || []) {
                const handled = await AIWorkspace.deliverMonitor(event);
                if (!handled) break;
                await fetch('/api/ai/monitors/events/' + encodeURIComponent(event.id) + '/ack', { method: 'POST' });
            }
        } catch (error) {
            /* A poll failure is retried on the next tick; it must never break the page. */
        } finally {
            this._busy = false;
        }
    },
};
window.AIWatch = AIWatch;
