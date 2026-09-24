import os

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    DRIVER_PATH = r'C:\Program Files\Google\Chrome\Application\chromedriver.exe'

    SECRET_KEY = os.environ.get('SECRET_KEY', 'crawler-workflow-secret-key')

    # Paths
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    COOKIE_DIR = os.path.join(DATA_DIR, 'cookies')
    EXPORT_DIR = os.path.join(DATA_DIR, 'exports')
    WORKFLOW_DIR = os.path.join(DATA_DIR, 'workflows')
    LOG_DIR = os.path.join(BASE_DIR, 'logs')
    # The run log is written by every crawl, so it rotates instead of growing
    # without limit: app.log rolls at LOG_MAX_BYTES and the previous
    # LOG_BACKUP_COUNT rolls are kept as app.log.1 … app.log.N.
    LOG_MAX_BYTES = 5 * 1024 * 1024
    LOG_BACKUP_COUNT = 5
    # Per-row LLM checkpoints: every finished row of a cleaning / emotion /
    # tendency run is appended here, so an interrupted run resumes instead of
    # paying for the same rows twice. Used only when the run-state store is
    # unavailable (the DB cache in RUNS_DB is the primary one now).
    LLM_CHECKPOINT_DIR = os.path.join(DATA_DIR, 'checkpoints')
    # Where one Chrome profile per platform lives, so the crawl browser is the same
    # device twice in a row instead of a blank one replaying an old cookie snapshot
    # (see services-free module ``browser_profiles`` for why this exists).
    BROWSER_PROFILE_DIR = os.path.join(DATA_DIR, 'chrome_profile')

    # Durable run state: per-node output rows, crawl cursors, crawled-item
    # fingerprints and the LLM answer cache. This is what makes an interrupted
    # run continuable instead of a total loss.
    RUNS_DB = os.path.join(DATA_DIR, 'runs.db')
    # Uploaded / pasted files, plus which Upload node of which workflow reads
    # which one. Separate from RUNS_DB because these are inputs a saved
    # workflow must find again tomorrow, not the state of one execution.
    DATASETS_DB = os.path.join(DATA_DIR, 'datasets.db')
    # Housekeeping: keep the newest N runs per workflow, and never keep
    # anything older than this many days. Runs that finished cleanly are the
    # first to go; interrupted ones are kept to the end because they are the
    # ones a user may still want to continue.
    RUN_KEEP_PER_WORKFLOW = 20
    RUN_KEEP_DAYS = 30
    # How often the retention settings above are actually applied without
    # anybody asking (see services/housekeeping.py). Startup, then at most once
    # per this many minutes.
    HOUSEKEEPING_INTERVAL_MINUTES = 60
    # Hard ceiling on rows persisted per node: a runaway crawl must not fill
    # the disk. Hitting it is reported in the console rather than silently
    # truncating the data handed downstream.
    RUN_MAX_ROWS_PER_NODE = 500000
    # Same guard for a single uploaded file, which unlike a crawl is one
    # deliberate act — if it is this big it was almost certainly the wrong file.
    DATASET_MAX_ROWS = 300000

    # Housekeeping for stored files: a file no saved workflow points at and
    # nobody has read for this many days is an orphan and gets dropped. Files
    # still referenced are never touched — they are what makes a saved
    # workflow runnable.
    DATASET_KEEP_DAYS = 90

    # Ollama
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen3.5:9b')
    OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')

    # Crawler defaults
    DEFAULT_HEADLESS = True
    DEFAULT_MAX_WORKERS = 4
    PAGE_LOAD_TIMEOUT = 15
    SCROLL_WAIT = 2.5

    #: How long a crawl waits for its platform's browser profile to be free. A
    #: parallel canvas starts its workflows together, so two nodes of one platform
    #: reach for the same directory in the same instant — and a profile only carries
    #: one browser at a time (see ``browser_profiles``). The ceiling is a whole
    #: long crawl, because the honest alternative to waiting is failing a node that
    #: would have succeeded seconds later; it is not infinite so a browser that was
    #: killed without closing cannot park this platform forever.
    PROFILE_LOCK_TIMEOUT = 900

    #: Two crawls of one platform inside the same second look to the site like one
    #: client doing two searches at once, which is what weibo answers with a passport
    #: redirect and zhihu with risk code 40362 (both met with two parallel workflows
    #: on one account). When 同平台排队 is on, a crawl that had to wait for its
    #: predecessor backs off this many seconds (plus jitter) before opening its
    #: browser — the gap is only paid where there was real contention, so a serial
    #: canvas waits for nothing.
    SAME_PLATFORM_STAGGER = 12.0

    #: A wall met *before the first row* is that collision's shape, not a dead cookie:
    #: a cookie that dies mid-crawl leaves rows behind, and that path stays
    #: 判失败 → 续跑 rather than burning a second attempt. One bounded wait and one
    #: retry is the difference between a red node and a green one; 0 disables it.
    WALL_RETRY_BACKOFF = 45.0

    #: How long a crawl may wait for its platform's turn. Same reasoning as
    #: :attr:`PROFILE_LOCK_TIMEOUT`: longer than any single crawl, and finite so a
    #: browser that never closed cannot park the platform for the rest of the process.
    PLATFORM_GATE_TIMEOUT = 900

    #: How much of a 公众号 article body a row keeps. A long post runs past ten
    #: thousand characters, and the crawler used to cut it at a hardcoded 5000 —
    #: which silently dropped the ending of every analysis input. 0 keeps it all.
    WECHAT_BODY_MAX_CHARS = 5000

    for d in [COOKIE_DIR, EXPORT_DIR, WORKFLOW_DIR, LOG_DIR, LLM_CHECKPOINT_DIR, BROWSER_PROFILE_DIR]:
        os.makedirs(d, exist_ok=True)
