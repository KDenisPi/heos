import logging
from logging.handlers import TimedRotatingFileHandler

import pytest

from heos_home.__main__ import JsonFormatter, setup_logging
from heos_home.settings import Settings


@pytest.fixture(autouse=True)
def restore_root_logger():
    root = logging.getLogger()
    handlers, level = root.handlers[:], root.level
    yield
    for h in root.handlers[:]:
        if h not in handlers:
            root.removeHandler(h)
            h.close()
    root.handlers[:] = handlers
    root.setLevel(level)


def test_settings_log_defaults():
    s = Settings.from_env({})
    assert s.log_file is None and s.log_backup_count == 7 and s.log_json is False


def test_settings_log_from_env(tmp_path):
    s = Settings.from_env({"HEOS_HOME_LOG_FILE": str(tmp_path / "a.log"), "HEOS_HOME_LOG_BACKUP_COUNT": "3",
                           "HEOS_HOME_LOG_JSON": "on"})
    assert s.log_file == tmp_path / "a.log" and s.log_backup_count == 3 and s.log_json is True


def test_console_only_without_log_file():
    setup_logging(Settings())
    assert [type(h) for h in logging.getLogger().handlers] == [logging.StreamHandler]


def test_file_rotated_daily_keeps_seven(tmp_path):
    path = tmp_path / "logs" / "heos-home.log"
    setup_logging(Settings(log_file=path))
    files = [h for h in logging.getLogger().handlers if isinstance(h, TimedRotatingFileHandler)]
    assert len(files) == 1
    handler = files[0]
    assert handler.when == "D" and handler.interval == 86400 and handler.backupCount == 7
    logging.getLogger("heos_home.test").info("hello")
    handler.flush()
    line = path.read_text("utf-8").strip()
    assert line.endswith(" INFO heos_home.test: hello")


def test_json_format_on_both_handlers(tmp_path):
    setup_logging(Settings(log_file=tmp_path / "x.log", log_json=True))
    assert all(isinstance(h.formatter, JsonFormatter) for h in logging.getLogger().handlers)
