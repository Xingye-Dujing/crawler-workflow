"""The one declaration of every runtime setting.

``runtime.settings`` used to keep a flat ``DEFAULTS`` dict plus a hand-written
``if key == ...`` chain in ``save_settings``. Every new key then had to be added in
four places (the dict, the validator, the panel markup and the browser catalogue),
and forgetting the validator made the key silently unsaveable. This module makes the
declaration itself the single source of truth:

* :data:`SETTINGS` — one :class:`Setting` per key, with its type, default, bounds,
  group, i18n label keys, who reads it and whether it may travel in an export.
* :data:`GROUPS` — the panel's section order and titles.
* :data:`PRESETS` — named bundles such as 慢速采集, applied as concrete values with a
  snapshot so they can be restored exactly.

The metadata is deliberately data (no imports beyond the standard library), so the
schema endpoint, the export/import validator, the panel renderer and the coverage
gate all read the same table.
"""

from dataclasses import dataclass, field

from core.config import Config


@dataclass(frozen=True)
class Setting:
    """One runtime setting.

    ``consumer`` is what the coverage gate audits:

    * ``server``  — read by :func:`runtime.settings.get_setting` in backend code;
    * ``browser`` — read by the page (``app-settings.js`` / ``workflow.js``);
    * ``both``    — read on both sides;
    * ``startup`` — read before/at import (a change needs a restart);
    * ``internal``— written by a preset, never edited directly.

    ``portable`` is False for values that name something on *this* machine. An
    export leaves them out unless the caller explicitly asks for them, and an import
    skips them unless the same opt-in is given.

    ``presets`` names the presets whose bundle includes this key.
    """

    key: str
    kind: str
    default: object
    group: str
    label: str
    hint: str = ''
    minimum: float | None = None
    maximum: float | None = None
    choices: tuple = ()
    validator: str = ''
    consumer: str = 'server'
    portable: bool = True
    restart: bool = False
    secret: bool = False
    presets: tuple = field(default_factory=tuple)


# ─── Groups (panel order) ────────────────────────────────────────────────────
GROUPS = (
    ('components', 'set.groupComponents'),
    ('browser', 'set.groupBrowser'),
    ('pace', 'set.groupPace'),
    ('safety', 'set.groupSafety'),
    ('limits', 'set.groupLimits'),
    ('data', 'set.groupData'),
    ('defaults', 'set.groupDefaults'),
)

SETTINGS = (
    # ── Components and machine paths ────────────────────────────────────────
    Setting(
        'driver_path',
        'path',
        Config.DRIVER_PATH,
        'components',
        'set.driver',
        validator='driver',
        consumer='both',
        portable=False,
    ),
    Setting(
        'browser_binary',
        'path',
        '',
        'components',
        'set.binary',
        validator='browser',
        consumer='both',
        portable=False,
    ),
    Setting(
        'component_source',
        'enum',
        'bundled',
        'components',
        'set.componentSource',
        hint='set.componentSourceHint',
        choices=('bundled', 'system'),
        validator='enum',
        consumer='startup',
        restart=True,
    ),
    Setting(
        'latex_binary',
        'path',
        '',
        'components',
        'set.latexBinary',
        validator='latex',
        portable=False,
    ),
    Setting(
        'catbus_cli',
        'path',
        Config.CATBUS_CLI,
        'components',
        'set.catbusCli',
        hint='set.catbusNote',
        validator='catbus',
        portable=False,
    ),
    Setting(
        'catbus_node',
        'path',
        Config.CATBUS_NODE,
        'components',
        'set.catbusNode',
        hint='set.catbusNote',
        validator='catbus_node',
        portable=False,
    ),
    # ── Browser and profile ─────────────────────────────────────────────────
    Setting('window_size', 'str', '960x920', 'browser', 'set.window', validator='window'),
    Setting(
        'page_load_timeout',
        'int',
        40,
        'browser',
        'set.pageLoad',
        hint='set.pageLoadHint',
        minimum=5,
        maximum=300,
    ),
    Setting(
        'element_timeout',
        'int',
        15,
        'browser',
        'set.elementWait',
        hint='set.elementWaitHint',
        minimum=3,
        maximum=600,
    ),
    Setting('ollama_host', 'str', Config.OLLAMA_HOST, 'browser', 'set.ollamaHost', validator='url', consumer='both'),
    Setting(
        'use_browser_profile',
        'bool',
        True,
        'browser',
        'set.useProfile',
        hint='set.useProfileInline',
        consumer='server',
    ),
    Setting(
        'browser_profile_dir',
        'path',
        '',
        'browser',
        'set.profileDir',
        hint='set.profileDirHint',
        validator='absdir',
        portable=False,
    ),
    Setting(
        'max_visible_browsers',
        'int',
        int(Config.DEFAULT_MAX_WORKERS),
        'browser',
        'set.maxVisible',
        hint='set.maxVisibleHint',
        minimum=1,
        maximum=16,
        presets=('slow',),
    ),
    Setting(
        'max_headless_browsers',
        'int',
        int(Config.DEFAULT_MAX_WORKERS),
        'browser',
        'set.maxHeadless',
        hint='set.maxHeadlessHint',
        minimum=1,
        maximum=16,
        presets=('slow',),
    ),
    # ── Pace / waits ────────────────────────────────────────────────────────
    Setting(
        'crawl_pace_scale',
        'float',
        1.0,
        'pace',
        'set.crawlPaceScale',
        hint='set.crawlPaceScaleHint',
        minimum=0.25,
        maximum=10.0,
        presets=('slow',),
    ),
    Setting(
        'crawl_scroll_scale',
        'float',
        1.0,
        'pace',
        'set.crawlScrollScale',
        hint='set.crawlScrollScaleHint',
        minimum=0.25,
        maximum=10.0,
        presets=('slow',),
    ),
    Setting(
        'crawl_expand_scale',
        'float',
        1.0,
        'pace',
        'set.crawlExpandScale',
        hint='set.crawlExpandScaleHint',
        minimum=0.25,
        maximum=10.0,
        presets=('slow',),
    ),
    Setting(
        'crawl_click_scale',
        'float',
        1.0,
        'pace',
        'set.crawlClickScale',
        hint='set.crawlClickScaleHint',
        minimum=0.25,
        maximum=10.0,
        presets=('slow',),
    ),
    Setting(
        'crawl_wait_scale',
        'float',
        1.0,
        'pace',
        'set.crawlWaitScale',
        hint='set.crawlWaitScaleHint',
        minimum=0.5,
        maximum=5.0,
        presets=('slow',),
    ),
    Setting(
        'crawl_arrival_scale',
        'float',
        1.0,
        'pace',
        'set.crawlArrivalScale',
        hint='set.crawlArrivalScaleHint',
        minimum=0.5,
        maximum=5.0,
        presets=('slow',),
    ),
    Setting(
        'crawl_patience_scale',
        'float',
        1.0,
        'pace',
        'set.crawlPatienceScale',
        hint='set.crawlPatienceScaleHint',
        minimum=1.0,
        maximum=5.0,
        presets=('slow',),
    ),
    Setting(
        'page_wait_timeout',
        'int',
        int(Config.PAGE_WAIT_TIMEOUT),
        'pace',
        'set.pageWait',
        hint='set.pageWaitHint',
        minimum=30,
        maximum=1800,
    ),
    Setting(
        'same_platform_stagger',
        'int',
        int(Config.SAME_PLATFORM_STAGGER),
        'pace',
        'set.stagger',
        hint='set.staggerHint',
        minimum=0,
        maximum=600,
    ),
    # ── Anti-bot, validation and retries ────────────────────────────────────
    Setting(
        'cookie_preflight_before_run',
        'bool',
        False,
        'safety',
        'set.cookiePreflight',
        hint='set.cookiePreflightInline',
        consumer='both',
        presets=('slow',),
    ),
    Setting(
        'ask_overseas_network',
        'bool',
        True,
        'safety',
        'set.overseasAsk',
        hint='set.overseasAskInline',
        consumer='browser',
    ),
    Setting(
        'same_platform_queue',
        'bool',
        False,
        'safety',
        'set.sameQueue',
        hint='set.sameQueueInline',
        consumer='both',
        presets=('slow',),
    ),
    Setting(
        'clear_console_before_run',
        'bool',
        True,
        'safety',
        'set.clearConsole',
        hint='set.clearConsoleInline',
        consumer='browser',
    ),
    Setting(
        'wall_retry_backoff',
        'float',
        float(Config.WALL_RETRY_BACKOFF),
        'safety',
        'set.wallRetryBackoff',
        hint='set.wallRetryBackoffHint',
        minimum=0.0,
        maximum=600.0,
    ),
    # ── Account/exit pool ───────────────────────────────────────────────────
    # A platform's control lasts hours or days, so the expensive thing is trying again too
    # soon. These keys are the pool's only user-facing knobs: the rest of its behaviour is
    # the failure attribution table in ``services.pool.health``, which is a rule, not a dial.
    Setting(
        'pool_enabled',
        'bool',
        False,
        'safety',
        'set.poolEnabled',
        hint='set.poolEnabledInline',
        consumer='server',
    ),
    Setting(
        'pool_cooldown_seconds',
        'int',
        7200,
        'safety',
        'set.poolCooldown',
        hint='set.poolCooldownHint',
        minimum=60,
        maximum=604800,
    ),
    Setting(
        'pool_network_cooldown_seconds',
        'int',
        300,
        'safety',
        'set.poolNetworkCooldown',
        hint='set.poolNetworkCooldownHint',
        minimum=0,
        maximum=86400,
    ),
    Setting(
        'pool_max_attempts',
        'int',
        3,
        'safety',
        'set.poolMaxAttempts',
        hint='set.poolMaxAttemptsHint',
        minimum=1,
        maximum=10,
    ),
    Setting(
        'pool_escalate',
        'bool',
        False,
        'safety',
        'set.poolEscalate',
        hint='set.poolEscalateHint',
        consumer='server',
    ),
    Setting(
        'pool_allow_direct_fallback',
        'bool',
        False,
        'safety',
        'set.poolDirectFallback',
        hint='set.poolDirectFallbackHint',
        consumer='server',
    ),
    Setting(
        'pool_skip_wall_backoff',
        'bool',
        True,
        'safety',
        'set.poolSkipBackoff',
        hint='set.poolSkipBackoffHint',
        consumer='server',
    ),
    Setting(
        'pool_preflight_live',
        'bool',
        False,
        'safety',
        'set.poolPreflightLive',
        hint='set.poolPreflightLiveHint',
        consumer='server',
    ),
    Setting(
        'wall_proofs',
        'int',
        5,
        'safety',
        'set.wallProofs',
        hint='set.wallProofsHint',
        minimum=1,
        maximum=20,
    ),
    Setting(
        'wall_poll',
        'float',
        0.3,
        'safety',
        'set.wallPoll',
        hint='set.wallPollHint',
        minimum=0.05,
        maximum=5.0,
    ),
    Setting(
        'nav_retry',
        'int',
        1,
        'safety',
        'set.navRetry',
        hint='set.navRetryHint',
        minimum=0,
        maximum=5,
    ),
    Setting(
        'nav_settle',
        'float',
        0.4,
        'safety',
        'set.navSettle',
        hint='set.navSettleHint',
        minimum=0.0,
        maximum=10.0,
    ),
    Setting(
        'max_pending_waits',
        'int',
        2,
        'safety',
        'set.maxPendingWaits',
        hint='set.maxPendingWaitsHint',
        minimum=1,
        maximum=10,
    ),
    Setting(
        'profile_lock_timeout',
        'int',
        int(Config.PROFILE_LOCK_TIMEOUT),
        'safety',
        'set.profileLockTimeout',
        hint='set.profileLockTimeoutHint',
        minimum=30,
        maximum=7200,
    ),
    Setting(
        'platform_gate_timeout',
        'int',
        int(Config.PLATFORM_GATE_TIMEOUT),
        'safety',
        'set.platformGateTimeout',
        hint='set.platformGateTimeoutHint',
        minimum=30,
        maximum=7200,
    ),
    Setting(
        'renderer_probe_timeout',
        'int',
        int(Config.RENDERER_PROBE_TIMEOUT),
        'safety',
        'set.rendererProbeTimeout',
        hint='set.rendererProbeTimeoutHint',
        minimum=5,
        maximum=120,
    ),
    Setting(
        'renderer_close_timeout',
        'int',
        int(Config.RENDERER_CLOSE_TIMEOUT),
        'safety',
        'set.rendererCloseTimeout',
        hint='set.rendererCloseTimeoutHint',
        minimum=1,
        maximum=120,
    ),
    Setting(
        'cookie_preflight_timeout',
        'int',
        int(Config.COOKIE_PREFLIGHT_TIMEOUT),
        'safety',
        'set.preflightTimeout',
        hint='set.preflightTimeoutHint',
        minimum=5,
        maximum=300,
    ),
    Setting(
        'cookie_preflight_ttl',
        'int',
        int(Config.COOKIE_PREFLIGHT_TTL),
        'safety',
        'set.preflightTtl',
        hint='set.preflightTtlHint',
        minimum=0,
        maximum=3600,
    ),
    Setting(
        'cookie_preflight_max_parallel',
        'int',
        int(Config.COOKIE_PREFLIGHT_MAX_PARALLEL),
        'safety',
        'set.preflightParallel',
        hint='set.preflightParallelHint',
        minimum=1,
        maximum=16,
    ),
    # ── Limits and retention ────────────────────────────────────────────────
    Setting(
        'run_max_rows_per_node',
        'int',
        int(Config.RUN_MAX_ROWS_PER_NODE),
        'limits',
        'set.runMaxRows',
        hint='set.runMaxRowsHint',
        minimum=1000,
        maximum=10000000,
    ),
    Setting(
        'dataset_max_rows',
        'int',
        int(Config.DATASET_MAX_ROWS),
        'limits',
        'set.datasetMaxRows',
        hint='set.datasetMaxRowsHint',
        minimum=1000,
        maximum=5000000,
    ),
    Setting(
        'max_upload_mb',
        'int',
        64,
        'limits',
        'set.maxUploadMb',
        hint='set.maxUploadMbHint',
        minimum=1,
        maximum=10240,
    ),
    # ── Data retention ──────────────────────────────────────────────────────
    Setting(
        'run_keep_per_workflow',
        'int',
        int(Config.RUN_KEEP_PER_WORKFLOW),
        'data',
        'set.runKeepPerWorkflow',
        hint='set.runKeepPerWorkflowHint',
        minimum=1,
        maximum=1000,
    ),
    Setting(
        'run_keep_days',
        'int',
        int(Config.RUN_KEEP_DAYS),
        'data',
        'set.runKeepDays',
        hint='set.runKeepDaysHint',
        minimum=1,
        maximum=3650,
    ),
    Setting(
        'dataset_keep_days',
        'int',
        int(Config.DATASET_KEEP_DAYS),
        'data',
        'set.datasetKeepDays',
        hint='set.datasetKeepDaysHint',
        minimum=1,
        maximum=3650,
    ),
    Setting(
        'housekeeping_interval_minutes',
        'int',
        int(Config.HOUSEKEEPING_INTERVAL_MINUTES),
        'data',
        'set.housekeepingInterval',
        hint='set.housekeepingIntervalHint',
        minimum=5,
        maximum=1440,
    ),
    Setting(
        'log_max_mb',
        'int',
        max(1, int(Config.LOG_MAX_BYTES // (1024 * 1024))),
        'data',
        'set.logMaxMb',
        hint='set.logMaxMbHint',
        minimum=1,
        maximum=1024,
        restart=True,
    ),
    Setting(
        'log_backup_count',
        'int',
        int(Config.LOG_BACKUP_COUNT),
        'data',
        'set.logBackupCount',
        hint='set.logBackupCountHint',
        minimum=1,
        maximum=50,
        restart=True,
    ),
    # ── Run and node defaults ───────────────────────────────────────────────
    Setting(
        'default_run_mode',
        'enum',
        'parallel',
        'defaults',
        'set.defaultRunMode',
        hint='set.defaultRunModeHint',
        choices=('parallel', 'serial'),
        consumer='browser',
    ),
    Setting(
        'default_headless',
        'bool',
        True,
        'defaults',
        'set.defaultHeadless',
        hint='set.defaultHeadlessHint',
        consumer='browser',
    ),
    Setting(
        'default_target_count',
        'int',
        50,
        'defaults',
        'set.defaultTargetCount',
        hint='set.defaultTargetCountHint',
        minimum=1,
        maximum=100000,
        consumer='server',
    ),
    Setting(
        'default_comment_limit',
        'int',
        0,
        'defaults',
        'set.defaultCommentLimit',
        hint='set.defaultCommentLimitHint',
        minimum=0,
        maximum=100000,
        consumer='browser',
    ),
    Setting(
        'default_comment_part_size',
        'int',
        50,
        'defaults',
        'set.defaultCommentPartSize',
        hint='set.defaultCommentPartSizeHint',
        minimum=0,
        maximum=100000,
        consumer='browser',
    ),
    Setting(
        'default_source_part_size',
        'int',
        0,
        'defaults',
        'set.defaultSourcePartSize',
        hint='set.defaultSourcePartSizeHint',
        minimum=0,
        maximum=100000,
        consumer='server',
    ),
    Setting(
        'default_per_article_file',
        'bool',
        True,
        'defaults',
        'set.defaultPerArticleFile',
        hint='set.defaultPerArticleFileHint',
        consumer='browser',
    ),
    Setting(
        'default_keep_parts',
        'bool',
        False,
        'defaults',
        'set.defaultKeepParts',
        hint='set.defaultKeepPartsHint',
        consumer='browser',
    ),
    Setting(
        'default_live_export',
        'bool',
        False,
        'defaults',
        'set.defaultLiveExport',
        hint='set.defaultLiveExportHint',
        consumer='server',
    ),
    # ── Hongguo harvest (Windows-only capability, still settings) ────────────
    Setting(
        'hongguo_player_path',
        'path',
        '',
        'components',
        'set.hgPlayer',
        validator='harvest',
        portable=False,
    ),
    Setting('mitmdump_path', 'path', '', 'components', 'set.mitmdump', validator='harvest', portable=False),
    Setting(
        'harvest_proxy_port',
        'int',
        8860,
        'components',
        'set.harvestPort',
        hint='set.harvestPortHint',
        minimum=1024,
        maximum=65535,
    ),
    Setting(
        'harvest_auto_install_ca',
        'bool',
        True,
        'components',
        'set.harvestCA',
        hint='set.harvestCAInline',
    ),
)

#: ``key -> Setting``, built once. A duplicate key is a bug caught at import.
BY_KEY = {spec.key: spec for spec in SETTINGS}
if len(BY_KEY) != len(SETTINGS):  # pragma: no cover - a declaration mistake
    raise RuntimeError('duplicate setting key in runtime.settings_schema')

#: The compatibility view the rest of the code already imports. Derived, never typed.
DEFAULTS = {spec.key: spec.default for spec in SETTINGS}

#: Machine-local values: never in a portable export, never visible to a non-admin.
MACHINE_KEYS = tuple(spec.key for spec in SETTINGS if not spec.portable)

#: Keys that need a process restart before the new value is used.
RESTART_KEYS = tuple(spec.key for spec in SETTINGS if spec.restart)

#: The settings that decide how the crawl *behaves*, not where its tools live.
CRAWL_KEYS = tuple(spec.key for spec in SETTINGS if spec.group in ('pace', 'safety', 'limits', 'data', 'defaults'))


# ─── Presets ────────────────────────────────────────────────────────────────
#: Named bundles applied as concrete values. ``slow`` is the one-click
#: 慢速采集 template: it raises patience and spacing together, serially queues a
#: platform and verifies the session first. Applying it snapshots the previous values
#: (see ``runtime.settings.apply_preset``) so restoring is exact, and the values are
#: written rather than layered, so no multiplier can stack twice.
PRESETS = {
    'slow': {
        'label': 'set.presetSlow',
        'hint': 'set.presetSlowHint',
        'values': {
            'crawl_pace_scale': 4.0,
            'crawl_scroll_scale': 3.0,
            'crawl_expand_scale': 3.0,
            'crawl_click_scale': 3.0,
            'crawl_wait_scale': 2.0,
            'crawl_arrival_scale': 1.6,
            'crawl_patience_scale': 2.0,
            'same_platform_queue': True,
            'cookie_preflight_before_run': True,
            'max_headless_browsers': 2,
            'max_visible_browsers': 1,
        },
    },
}


def schema_payload() -> dict:
    """The browser's view of the declaration: groups, fields and preset metadata."""
    return {
        'groups': [{'id': gid, 'label': label} for gid, label in GROUPS],
        'settings': [
            {
                'key': s.key,
                'kind': s.kind,
                'default': s.default,
                'group': s.group,
                'label': s.label,
                'hint': s.hint,
                'minimum': s.minimum,
                'maximum': s.maximum,
                'choices': list(s.choices),
                'consumer': s.consumer,
                'portable': s.portable,
                'restart': s.restart,
                'secret': s.secret,
                'presets': list(s.presets),
            }
            for s in SETTINGS
        ],
        'presets': {
            pid: {
                'label': p['label'],
                'hint': p['hint'],
                'keys': sorted(p['values']),
            }
            for pid, p in PRESETS.items()
        },
    }
