/* The AI workspace is ONE object with ONE state record.
 *
 * The shell, the composer, the transcript, the studios and the stream reducer all read and write the
 * same fields (`_messages`, `_sending`, `_conversationId`, …). Copying that record into each file
 * would make "the open conversation" depend on which module answered, so the record lives here and
 * every declared key is exposed on `AIWorkspace` as an ACCESSOR onto it: `this._sending = true` in
 * any companion writes the one field, and `AIWorkspace._sending` in the console reads it back.
 *
 * The record is observable: a write notifies the subscribers with the key, which is how a surface
 * that must not poll (the live line, a future inspector) hears about a turn's state instead of
 * re-reading the DOM. Nothing subscribes today; `subscribe` exists so a consumer has a door that is
 * not a private peek at a field, and `tests/frontend/harness_ai_workspace.mjs` pins the mechanism.
 */

/* The object every companion extends with `Object.assign(AIWorkspace, { … })`. Declared here, in the
 * first script the page loads, because a later script's `const` is in its temporal dead zone. */
const AIWorkspace = {};

/* Every field of the workspace, with the value a fresh page starts from. A field declared here is
 * bound as an accessor; a name a companion writes without declaring it here would become a second
 * hidden copy, so this table is the whole state — a new `this._name` belongs here in the same change. */
const AI_STATE = {
    _init: false,
    _open: false,
    _full: false,
    /* Transient width override for a demo deep link; never persisted (see setRunWidth). */
    _runWidth: 0,
    _sessionsOpen: false,
    _pinned: false,
    _sending: false,
    /* The live turn's clock: when it opened, when the last byte arrived, and whether an ENDING event
       (done / question / paused / error / stop) was seen. A stream that closes without one was cut,
       and a cut has to say so — otherwise a half answer is indistinguishable from a finished one. */
    _turnStartedAt: 0,
    _lastEventAt: 0,
    _turnEnded: false,
    _turnClock: null,
    /* The conversation the OPEN turn belongs to; `''` on a new chat until its first `meta`. */
    _streamConversation: '',
    _streamTurnId: '',
    _mode: 'chat',
    _conversationId: '',
    _bootstrap: null,
    /* Bumped per bootstrap request so an older answer cannot revert the picker. */
    _bootstrapSeq: 0,
    _loading: false,
    _provider: 'deepseek',
    _model: '',
    _skill: 'auto',
    _agentMode: 'build',
    _scope: 'summary',
    _messages: [],
    _current: null,
    _plan: [],
    /* The conversation's live recipe run, as the server last reported it (never guessed). */
    _recipe: null,
    _usage: null,
    _contextMeta: null,
    /* Row grants this conversation holds: the server's answer, never a browser preference. A
       revoked grant is removed from this list before the request, then re-read from the answer. */
    _grants: [],
    _attachments: [],
    /* Things named with `@` in this draft: datasets, export files, workflow files and files
       uploaded in an earlier conversation. Sent as ids; the server resolves them. */
    _refs: [],
    _refResults: [],
    _refIndex: 0,
    _refOpen: false,
    _refQuery: '',
    _refTarget: '',
    _refTimer: null,
    /* The "what will be sent" text while it is open; one preview, toggled by its own button. */
    _contextPreview: '',
    /* The slash-command menu's own draft: open flag, query, rows and the highlighted index. */
    _cmdOpen: false,
    _cmdQuery: '',
    _cmdRows: [],
    _cmdIndex: 0,
    _uploading: false,
    _studioTab: 'skills',
    _editingSkill: null,
    _pythonScript: null,
    _abort: null,
    _renderTimer: null,
    /* Which disclosures the READER opened, keyed by `data-ai-detail`. A streaming repaint rebuilds
       the block stream; without this, every delta closed the thinking block or tool result the user
       had just opened. */
    _openDetails: new Set(),
    _balance: null,
    _convoUsage: null,
    _conversationModel: '',
    /* Sessions list: the search box, the archived switch and the debounce timer. */
    _sessionQuery: '',
    _showArchived: false,
    _sessionSearchTimer: null,
    /* The folder dialog's server answer. */
    _folderState: null,
    /* The delegated click handler's bookkeeping: which column grip is down, and which selection
       token a late answer belongs to. */
    _pointerDown: false,
    _selectToken: 0,
    /* Artifact and monitor cards painted inside a turn, keyed by their id. */
    _artifactsById: {},
    _inlineToolCalls: {},
    _monitorFailed: false,
    /* Run feedback (a failed-node card) so a streamed repaint does not re-announce it. */
    _feedbackTurn: '',
    _feedbackCount: 0,
    _dom: {},
    /* The ResizeObserver the dock binds once, so a painted width is measured, not remembered. */
    _widthObserver: null,
};

const AIStore = {
    /** The one record every companion reads and writes through its host's accessors. */
    state: AI_STATE,

    _listeners: new Set(),

    subscribe(listener) {
        this._listeners.add(listener);
        return () => this._listeners.delete(listener);
    },

    notify(key, value) {
        for (const listener of this._listeners) {
            try {
                listener(key, value);
            } catch (e) {
                /* a listener is a reader: its failure must not undo the write that told it */
            }
        }
    },

    /** Expose every declared key on `host` as an accessor onto the one record. */
    bind(host) {
        for (const key of Object.keys(this.state)) {
            Object.defineProperty(host, key, {
                configurable: true,
                enumerable: true,
                get() {
                    return AIStore.state[key];
                },
                set(value) {
                    AIStore.state[key] = value;
                    AIStore.notify(key, value);
                },
            });
        }
        return host;
    },
};

AIStore.bind(AIWorkspace);
window.AIStore = AIStore;
