import logging
import logging.handlers
import os

# A crawl writes tens of thousands of lines; an unbounded app.log eventually
# turns every "open the log folder" action into a hang, so the file rotates.
DEFAULT_MAX_BYTES = 5 * 1024 * 1024
DEFAULT_BACKUP_COUNT = 5


def setup_logger(
    log_dir: str,
    name: str = 'app',
    max_bytes: int = DEFAULT_MAX_BYTES,
    backup_count: int = DEFAULT_BACKUP_COUNT,
) -> logging.Logger:
    """Configure and return a logger instance.

    The file handler rotates; callers that need a plain file (a test asserting
    on exact contents) can pass ``max_bytes=0``, which keeps the append-only
    behaviour.
    """
    os.makedirs(log_dir, exist_ok=True)
    log_path = os.path.join(log_dir, f'{name}.log')

    logger = logging.getLogger(name)
    logger.setLevel(logging.INFO)

    if max_bytes:
        fh = logging.handlers.RotatingFileHandler(
            log_path,
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding='utf-8',
        )
    else:
        fh = logging.FileHandler(log_path, encoding='utf-8')
    fh.setLevel(logging.INFO)

    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)

    fmt = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(fmt)
    ch.setFormatter(fmt)

    logger.addHandler(fh)
    logger.addHandler(ch)

    return logger
