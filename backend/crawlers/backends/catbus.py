"""The second crawl backend: a node's CatBus session, driven one process per walk.

This class subclasses :class:`~crawlers.core.crawler.Crawler` on purpose. The streaming machinery it inherits
is where the run's correctness lives — :meth:`emit` is where 停止 is felt and where a broken sink
stays best-effort, :meth:`note_end` is where a licence to be short is refused, and
:meth:`watermark_boundary` is where a cross-run boundary is honoured. Re-declaring those on a
duck-typed object would be a second copy of rules this project has already paid for once. The browser
half costs it nothing: no profile is claimed, ``driver`` stays ``None``, and no cookie is planted.

**It is written for the backend as a whole, not for one platform.** Which cells exist, what columns a
cell returns and which of those columns identify a row are all read out of the adapter's own manifest
(:mod:`services.catbus_bridge`), so the day CatBus maps another site's search, comments or board, the
panel offers it, the node crawls it and the watermark keys it by that site's own identity column —
with no branch added in this file. The only per-platform fact here is the *method name* the comment
engine looks up, and even that is synthesised from the manifest.

Three things it does NOT pretend:

- **No position cursor.** CatBus walks a list from its own top and has no offset. A resumed node
  re-asks, and the row ledger drops everything already paid for; writing a cursor here would claim a
  position the backend cannot return to.
- **No Selenium wall flags.** ``login_wall`` / ``risk_blocked`` answer "this project's cookie died"
  and "back off", and the executor's sentences for them are written for a browser session. CatBus
  keeps its own account files, so an unauthenticated adapter raises its own line naming
  ``catbus … auth login`` and never latches either flag — otherwise the run would flip
  ``cookie_expired`` and send the user to re-save a cookie they never used.
- **A watermark that bounds the table, not the requests.** Under Selenium the boundary is checked
  *before* the fetch, so older items are never asked for. CatBus hands back a whole list, so the
  boundary can only stop older rows from being filed — which is said out loud, never left implicit.
"""

from __future__ import annotations

import logging
import uuid

from crawlers.commenting.protocol import DEAD, OK
from crawlers.core.crawler import UNDER_TARGET, Crawler, CrawlerStopped
from i18n import t
from services import catbus_bridge as bridge

logger = logging.getLogger(__name__)

#: The comment engine reaches an adapter by ``getattr(session, f'crawl_{platform}')``. That prefix is
# the one protocol fact this class knows about its caller.
_COMMENT_PREFIX = 'crawl_'

#: Fields that CHANGE WHAT IS COLLECTED. CatBus keeps unknown parameters on purpose (the adapter is
#: shared with other callers), so a stored condition it does not consume would run as if it had: a
#: time window on a search that has none, a comment preview on a backend that never expands them.
#: A value equal to the field's declared default is not a condition the user chose (the canvas seeds
#: every platform's defaults), so only a value that departs from it is refused.
_DATA_PARAMS = (
    'keyword',
    'author',
    'board',
    'urls',
    'comment_limit',
    'start_time',
    'end_time',
    'comment_preview',
    'with_facts',
    'full_body',
)


class CatbusCrawler(Crawler):
    """One node's CatBus crawl: the source handlers and the comment adapter in one object."""

    def __init__(
        self,
        platform: str = '',
        params: dict | None = None,
        account: str = '',
        abort=None,
        log=None,
        headless: bool = True,
    ):
        # No cookie path and no profile directory: those are the two arguments that buy a browser and
        # its lock. ``login_wall`` / ``risk_blocked`` arrive False from the base and are never latched
        # here — see the module docstring.
        super().__init__(headless=headless, cookie_path=None, for_login=False, profile_dir=None, abort=abort)
        self.params = dict(params or {})
        self.platform = str(platform or self.params.get('platform') or '').strip()
        #: The node's Selenium account, remembered only so a refusal can say it was not used.
        self.node_account = str(account or '')
        self._log = log or logger.info
        # The key this session's live child is registered under, so 停止 can aim the reaper at
        # exactly this process while the worker sits blocked reading its stdout.
        self._token = uuid.uuid4().hex
        # U1 and watermark facts the executors read after the walk, BY ATTRIBUTE.
        self.target_total = 0
        self.shortfall = 0
        self.skipped_targets: list[str] = []
        #: Which column the recorded boundary belongs to. The store keeps it next to the value, and a
        #: backend that names its identity differently per site must not have that spelled for it.
        self.watermark_column = ''

    # ─── the base class's browser half, answered with nothing ────────────────────────────────

    def _create_driver(self):
        """No Chrome: this session crawls by starting an adapter process per walk.

        :meth:`crawlers.core.crawler.Crawler.__init__` builds the driver, so this override is what makes the
        inheritance affordable — every streaming rule comes along for free and the one step that would
        buy a browser answers with nothing. The child belongs to one crawl, not to the session: it is
        created in :meth:`_run` and reaped by :meth:`close`, which is why ``driver`` stays ``None``.
        """
        return None

    # ─── the source node's handlers ───────────────────────────────────────────────────────────

    def search(self, keyword: str = '', target_count: int = 50, **_kwargs):
        """Keyword search: the adapter resolves each hit into this project's row shape."""
        return self._collect('posts', {'keyword': keyword}, target_count)

    def author(self, author: str = '', target_count: int = 50, **_kwargs):
        """One creator's uploads, newest-first, so the watermark bounds the table."""
        return self._collect('author', {'author': author}, target_count)

    def hot(self, board: str = '', target_count: int = 50, **_kwargs):
        """A board. A board the manifest does not list refuses itself there, never here.

        ``_kwargs`` is the executor's ``resume`` blob, and this backend has nothing to resume from:
        CatBus walks a list from its own top, so the row ledger is what makes a replay cheap rather
        than a cursor being what makes it correct.
        """
        return self._collect('hot', {'board': board}, target_count)

    def catbus(self, mode_key: str = '', target_count: int = 0, **kwargs):
        """One CatBus-only read mode (``user.followers``, ``keyword.hot`` …).

        The command is the mode: which arguments it takes, which columns it returns and whether it is
        paged all come from the manifest through the bridge. A non-paged cell (a single item's detail,
        a keyword board) declares no ``target_count``, so it is not measured against one — asking a
        one-row answer to reach fifty and calling the gap 「采得不足」 would be a conviction for a
        promise the cell never made.
        """
        self._guard(mode_key)
        extra = {key: value for key, value in kwargs.items() if key not in ('resume', 'mode_key')}
        if not target_count:
            self._log(t('catbus.startOnce', mode=mode_key))
        return self._collect(mode_key, extra, int(target_count or 0))

    def get_detail(self, url: str) -> dict | None:
        """Not this backend's job: the adapter resolves every card itself.

        ``Crawler`` declares the method abstract. The honest body is a refusal that says so, not a
        browser fetch pretending to be one thing while the crawl is another.
        """
        raise ValueError(t('catbus.noDetail', url=url))

    def _collect(self, mode: str, extra: dict, target_count: int) -> list:
        """One adapter run for a whole list, filed into the node's ledger row by row.

        ``target_count`` is passed through as the *list* size, never as "how many rows this node still
        needs": a resumed run already holds rows, and a shorter list would drop candidates the ledger
        has never seen rather than skip the ones it has.
        """
        self._guard(mode)
        if target_count and self.collected() >= target_count:
            self._log(t('catbus.targetReached', n=target_count))
            return self.results()
        self._unsupported_params(mode)
        if target_count:
            self._log(t('catbus.start', mode=mode, n=target_count))
        identity = self._identity_column(mode)
        if self.watermark and not identity:
            # A boundary compared against a column nobody declared would bound nothing while the
            # panel still shows a saved one, so the walk says the cell cannot carry the feature
            # instead of running it wrong.
            raise ValueError(t('catbus.noIdentity', platform=self.platform, mode=mode))
        if self.watermark:
            # Said out loud because the difference is money: under Selenium the boundary saves the
            # request; here it only bounds which rows are filed. A degradation this quiet must be
            # printed, never left for the user to infer from a slower-than-expected run.
            self._log(t('catbus.watermarkNote'))
        counts = {'scanned': 0, 'kept': 0, 'refused': 0, 'halted': False}

        def _file(row: dict) -> None:
            counts['scanned'] += 1
            if counts['halted']:
                return
            key = str(row.get(identity) or '') if identity else ''
            if key and self.watermark_boundary(key):
                self._log(t('catbus.watermarkHit', i=key))
                counts['halted'] = True
                return
            if self.emit(row):
                counts['kept'] += 1
                if key:
                    self.note_watermark(key)
            else:
                counts['refused'] += 1

        outcome = self._run(mode, {**extra, 'target_count': target_count}, on_row=_file)
        # The refusal comes AFTER the rows were filed. A run stopped, walled or column-drifted at row
        # 30 of 50 has 30 rows the site already gave, and the streaming this backend exists for is
        # worth nothing if they are dropped on the way to the message about them.
        self._warn(outcome)
        self._refuse(outcome, mode)
        kept = counts['kept']
        refused = counts['refused'] + len(outcome.warnings)
        self.target_total = target_count
        if target_count and self.collected() < target_count:
            # Convicted, not excused: an adapter list that stopped growing is not proof the site ran
            # out — a soft throttle looks exactly the same — so a short table says 「采得不足」 with the
            # funnel instead of settling clean. The warnings are counted as refused because that is
            # what they are: cards the adapter asked for and did not bring back.
            self.note_end(UNDER_TARGET, scanned=counts['scanned'], kept=kept, refused=refused)
        if target_count:
            self._log(t('catbus.finished', n=kept, want=target_count))
        else:
            self._log(t('catbus.finishedOnce', mode=mode, n=kept))
        return self.results()

    # ─── the comment engine's adapter ─────────────────────────────────────────────────────────

    def __getattr__(self, name: str):
        """Synthesise ``crawl_<platform>``, the name the comment engine looks an adapter up by.

        Declaring one method per platform would put a list of sites in this file — a second opinion
        about what the backend supports, and the kind that falls behind. So the name is answered from
        the manifest: a platform CatBus has mapped for comments walks through here, and one it has not
        raises ``AttributeError`` exactly as a missing method would, which lands on the engine's named
        ``comment.noAdapter`` refusal rather than a silent fallback.
        """
        if name.startswith(_COMMENT_PREFIX):
            platform = name[len(_COMMENT_PREFIX) :]
            if platform and bridge.supports(platform, 'comments'):
                return lambda url, limit=0: self.crawl_comments(platform, url, limit)
        raise AttributeError(f'{type(self).__name__} object has no attribute {name!r}')

    def crawl_comments(self, platform: str, url: str, limit: int = 0) -> tuple[list, str]:
        """One article's comments, in its own process.

        One child per link is the design: the engine advances ``url_index`` only over the unbroken
        leading links it *proved*, and a per-link process is what makes a row count, a refusal and a
        cursor all mean the same thing per link.
        """
        self._guard('comments', platform=platform)
        rows: list[dict] = []
        outcome = self._run(
            'comments',
            {'urls': [url], 'comment_limit': limit},
            on_row=rows.append,
            platform=platform,
        )
        self._refuse(outcome, 'comments', url=url, platform=platform)
        if outcome.status == 'dead':
            # The page answered and there was nothing behind it: DEAD is the engine's own word for
            # that, and the link is named so the node cannot settle as if it had read everything.
            self.skipped_targets.append(url)
            return rows, DEAD
        if outcome.status == 'partial':
            # Some pages of this thread did not come back. The rows stand, but the link is not
            # proven, which pins the cursor before it — advancing over a hole is the laundering
            # this rule exists to stop.
            self.skipped_targets.append(url)
            self.shortfall += 1
        self._warn(outcome)
        return rows, OK

    # ─── the boundary with the adapter ────────────────────────────────────────────────────────

    def _guard(self, mode: str, platform: str = '') -> None:
        """Refuse a cell this machine cannot crawl BEFORE anything is bought for it.

        The adapter owns the answer and refuses with it too, but the walk asks first so two things
        hold: no child process starts for a combination that cannot work, and the line the user reads
        is the manifest's own reason for that cell rather than a machine-level fact about Node or a
        child's exit code.
        """
        site = platform or self.platform
        runnable, why = bridge.crawlability(site, mode)
        if not runnable:
            raise ValueError(t('catbus.refused', platform=site, mode=mode, detail=why))

    def _identity_column(self, mode: str) -> str:
        """The column this cell's rows identify themselves by, in the adapter's own words.

        Read from the manifest, never guessed from the row: a comment ledger keys on (平台, 评论ID)
        while a video walk keys on its link, and the watermark has to store the one its site actually
        promised — a boundary compared against the wrong column reads as "nothing is old" forever.
        """
        for name in bridge.identity_for(self.platform, mode):
            if name and name != '平台':
                self.watermark_column = str(name)
                return str(name)
        return ''

    def _unsupported_params(self, mode: str) -> None:
        """Refuse a stored data condition this cell's adapter does not consume.

        The adapter documents that unknown keys are kept and ignored, which is the right behaviour
        for a shared subprocess boundary — but for a node it means a time window or a comment preview
        the user asked for would produce a table that LOOKS like the condition ran. The manifest's
        ``params`` list is the adapter's own answer to what it consumes; anything else that departs
        from its declared default is refused here, before a child process is bought.
        """
        import crawl_capabilities as capabilities

        accepted = set(bridge.declared_params(self.platform, mode))
        defaults = capabilities.declared_defaults(self.platform)
        ignored = [
            key
            for key in _DATA_PARAMS
            if key not in accepted
            and str(self.params.get(key) or '').strip()
            and str(self.params.get(key)) != str(defaults.get(key))
        ]
        if ignored:
            raise ValueError(t('catbus.paramUnsupported', platform=self.platform, mode=mode, params='、'.join(ignored)))

    def _run(self, mode: str, extra: dict, on_row, platform: str = '') -> bridge.Outcome:
        """One ``catbus-crawler-workflow run``, carrying the node's form plus this walk's arguments.

        Nothing is filtered out on the way. The manifest's ``params`` list says what a cell *takes as
        an argument*, not what the user asked for; a stored condition the cell does not consume is
        refused by name before this call (:meth:`_unsupported_params`), never dropped on the way to a
        table that would look like it ran.

        ``catbus_account`` is the only account the adapter may see: the node's ``account`` names a
        Selenium session this crawl never opens, and the bridge drops it (:func:`_params_payload`).
        """
        site = platform or self.platform
        params = dict(self.params)
        params.update(extra)
        return bridge.run(
            site,
            mode,
            params,
            on_row=on_row,
            abort=self.may_stop,
            account=str(params.get('catbus_account') or ''),
            token=self._token,
        )

    def _warn(self, outcome: bridge.Outcome) -> None:
        """The adapter's own words about what it refused. A short table with no such line is the
        silent under-collect this project was convicted for before."""
        for warning in outcome.warnings:
            self._log(t('catbus.warning', text=warning))

    def _refuse(self, outcome: bridge.Outcome, mode: str, url: str = '', platform: str = '') -> None:
        """Turn a non-row answer into one line that says what to do next.

        Raising rather than returning is the rule: a refusal that answers with an empty list lets the
        node settle DONE over a table with nothing in it.
        """
        site = platform or self.platform
        if outcome.status == 'stopped':
            # The user's own 停止: a ``BaseException``, so no ``except Exception`` in a walk can fold
            # it into "the site sent nothing".
            raise CrawlerStopped(t('crawl.stopped'))
        if outcome.status in (OK, 'partial', 'dead'):
            return
        # 'blocked' (the whole list walled), 'error' and 'unavailable' all refuse. The advice is the
        # adapter's own hint — 「catbus bilibili auth login」 — never 「重新保存 Cookie」.
        message = str(outcome.message or '') or f'exit={outcome.exit_code}'
        hint = f' — {outcome.hint}' if outcome.hint else ''
        where = f' [{url}]' if url else ''
        raise ValueError(t('catbus.refused', platform=site, mode=mode, detail=f'{message}{hint}{where}'))

    def close(self) -> None:
        """Stop this session's child, if it is still running.

        The run-control thread calls this while the worker sits blocked in the stdout read, so it
        cannot wait for the ``abort`` predicate between rows: the reaper has to be aimed here instead.
        """
        bridge.kill_running(self._token)
        super().close()
