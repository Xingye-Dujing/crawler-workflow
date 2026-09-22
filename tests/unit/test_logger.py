"""The run log rotates: a crawl writes far more lines than a disk should keep."""

import logging
import logging.handlers

import pytest

from engine.logger import DEFAULT_BACKUP_COUNT, DEFAULT_MAX_BYTES, setup_logger

pytestmark = pytest.mark.unit


def _rotating_handlers(logger: logging.Logger):
    return [h for h in logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]


@pytest.fixture
def make_logger(tmp_path):
    """Build loggers under unique names and always detach them afterwards —
    ``logging`` keys its loggers globally, so leftover handlers would keep
    writing into another test's temporary directory."""
    made = []

    def _make(name, **kwargs):
        logger = setup_logger(str(tmp_path), name=name, **kwargs)
        made.append(logger)
        return logger

    yield _make
    for logger in made:
        for handler in list(logger.handlers):
            logger.removeHandler(handler)
            handler.close()


class TestFilePlacement:
    def test_log_lands_under_the_named_file_and_the_dir_is_created(self, make_logger, tmp_path):
        logger = make_logger('placement')
        target = tmp_path / 'placement.log'
        assert target.exists()
        logger.info('written')
        for handler in logger.handlers:
            handler.flush()
        assert 'written' in target.read_text(encoding='utf-8')

    def test_console_handler_stays_attached(self, make_logger):
        logger = make_logger('console')
        kinds = [type(h) for h in logger.handlers]
        assert logging.StreamHandler in kinds


class TestRotation:
    def test_default_handler_rotates_instead_of_growing_forever(self, make_logger):
        assert _rotating_handlers(make_logger('defaults'))

    def test_defaults_are_a_rollover_and_five_kept_rolls(self):
        assert DEFAULT_MAX_BYTES == 5 * 1024 * 1024
        assert DEFAULT_BACKUP_COUNT == 5

    def test_rolling_produces_numbered_backups_and_stops_at_backup_count(self, make_logger, tmp_path):
        logger = make_logger('rolling', max_bytes=200, backup_count=3)
        for i in range(60):
            logger.info('line %03d %s', i, 'x' * 20)
        for handler in _rotating_handlers(logger):
            handler.flush()
        assert (tmp_path / 'rolling.log').exists()
        rolls = sorted(p.name for p in tmp_path.glob('rolling.log.*'))
        assert rolls == ['rolling.log.1', 'rolling.log.2', 'rolling.log.3']

    def test_the_current_file_never_exceeds_its_ceiling_by_more_than_a_line(self, make_logger, tmp_path):
        logger = make_logger('bounded', max_bytes=400, backup_count=2)
        for i in range(50):
            logger.info('entry %03d %s', i, 'y' * 10)
        for handler in _rotating_handlers(logger):
            handler.flush()
        assert (tmp_path / 'bounded.log').stat().st_size < 1000

    def test_max_bytes_zero_keeps_a_plain_append_only_file(self, make_logger, tmp_path):
        """A caller that must assert on exact contents (or ship one whole log)
        opts out of rolling — the behaviour before rotation existed."""
        logger = make_logger('plain', max_bytes=0)
        assert _rotating_handlers(logger) == []
        for i in range(200):
            logger.info('row %03d %s', i, 'z' * 30)
        for handler in logger.handlers:
            handler.flush()
        text = (tmp_path / 'plain.log').read_text(encoding='utf-8')
        assert 'row 000' in text and 'row 199' in text

    def test_utf8_survives_rollover(self, make_logger, tmp_path):
        logger = make_logger('unicode', max_bytes=300, backup_count=2)
        for i in range(30):
            logger.info('采集节点开始 关键词=%s', i)
        for handler in _rotating_handlers(logger):
            handler.flush()
        bodies = [(tmp_path / name).read_text(encoding='utf-8') for name in ('unicode.log', 'unicode.log.1')]
        assert any('采集节点开始' in body for body in bodies)


class TestBackupCount:
    def test_zero_keeps_only_the_current_file(self, make_logger, tmp_path):
        logger = make_logger('single', max_bytes=200, backup_count=0)
        for i in range(20):
            logger.info('line %03d %s', i, 'x' * 20)
        for handler in _rotating_handlers(logger):
            handler.flush()
        assert list(tmp_path.glob('single.log.*')) == []
        assert (tmp_path / 'single.log').exists()


class TestProductionWiring:
    def test_the_app_logger_uses_the_configured_ceiling(self):
        """The rotation is only real if app.py asks for Config's numbers —
        otherwise these are library defaults nobody installed."""
        import app as app_module

        from config import Config

        assert app_module.logger is logging.getLogger('app')
        handlers = _rotating_handlers(app_module.logger)
        assert handlers, 'the production logger must rotate'
        assert {h.maxBytes for h in handlers} == {Config.LOG_MAX_BYTES}
        assert {h.backupCount for h in handlers} == {Config.LOG_BACKUP_COUNT}
