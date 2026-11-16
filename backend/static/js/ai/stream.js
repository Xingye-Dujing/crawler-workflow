/* SSE reader for the AI workspace.
 *
 * POST + `fetch` is used instead of EventSource because the request carries a body and the
 * Authorization material is never placed in a URL. The decoder follows the WHATWG framing rules:
 * multi-line data joins with a newline, comments are ignored, and a blank line dispatches.
 */
const AIStream = {
    async post(url, body, onEvent, signal) {
        const response = await fetch(url, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
            body: JSON.stringify(body),
            signal,
        });
        if (!response.ok) {
            let message = response.statusText || ('HTTP ' + response.status);
            try {
                const payload = await response.json();
                message = payload.error || message;
            } catch (e) {
                /* a non-JSON error keeps the status text */
            }
            throw new Error(message);
        }
        if (!response.body || !response.headers.get('Content-Type')?.includes('text/event-stream')) {
            const separator = url.includes('?') ? '&' : '?';
            const fallback = await fetch(url + separator + 'stream=0', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(body),
                signal,
            });
            const payload = await fallback.json();
            if (!fallback.ok || payload.ok === false) throw new Error(payload.error || 'request failed');
            for (const event of payload.events || []) onEvent(event);
            return;
        }
        const reader = response.body.getReader();
        const decoder = new TextDecoder();
        let buffer = '';
        let dataLines = [];
        const dispatch = () => {
            if (!dataLines.length) return;
            const raw = dataLines.join('\n');
            dataLines = [];
            let event;
            try {
                event = JSON.parse(raw);
            } catch (e) {
                return;
            }
            onEvent(event);
        };
        for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buffer += decoder.decode(value, { stream: true });
            let lineStart = 0;
            for (let index = 0; index < buffer.length; index += 1) {
                if (buffer[index] !== '\n' && buffer[index] !== '\r') continue;
                const line = buffer.slice(lineStart, index);
                lineStart = index + 1;
                if (line === '') {
                    dispatch();
                } else if (line.startsWith('data:')) {
                    dataLines.push(line.slice(5).replace(/^ /, ''));
                }
            }
            buffer = buffer.slice(lineStart);
        }
        buffer += decoder.decode();
        if (buffer.startsWith('data:')) dataLines.push(buffer.slice(5).replace(/^ /, ''));
        dispatch();
    },
};
window.AIStream = AIStream;
