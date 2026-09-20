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
    # Per-row LLM checkpoints: every finished row of a cleaning / emotion /
    # tendency run is appended here, so an interrupted run resumes instead of
    # paying for the same rows twice. Used only when the run-state store is
    # unavailable (the DB cache in RUNS_DB is the primary one now).
    LLM_CHECKPOINT_DIR = os.path.join(DATA_DIR, 'checkpoints')

    # Durable run state: per-node output rows, crawl cursors, crawled-item
    # fingerprints and the LLM answer cache. This is what makes an interrupted
    # run continuable instead of a total loss.
    RUNS_DB = os.path.join(DATA_DIR, 'runs.db')
    # Housekeeping: keep the newest N runs per workflow, and never keep
    # anything older than this many days. Runs that finished cleanly are the
    # first to go; interrupted ones are kept to the end because they are the
    # ones a user may still want to continue.
    RUN_KEEP_PER_WORKFLOW = 20
    RUN_KEEP_DAYS = 30
    # Hard ceiling on rows persisted per node: a runaway crawl must not fill
    # the disk. Hitting it is reported in the console rather than silently
    # truncating the data handed downstream.
    RUN_MAX_ROWS_PER_NODE = 500000

    # Ollama
    OLLAMA_MODEL = os.environ.get('OLLAMA_MODEL', 'qwen3.5:9b')
    OLLAMA_HOST = os.environ.get('OLLAMA_HOST', 'http://localhost:11434')

    # Crawler defaults
    DEFAULT_HEADLESS = True
    DEFAULT_MAX_WORKERS = 4
    PAGE_LOAD_TIMEOUT = 15
    SCROLL_WAIT = 2.5

    for d in [COOKIE_DIR, EXPORT_DIR, WORKFLOW_DIR, LOG_DIR, LLM_CHECKPOINT_DIR]:
        os.makedirs(d, exist_ok=True)
