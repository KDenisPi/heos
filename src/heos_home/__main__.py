"""Entry point: ``python -m heos_home`` or the ``heos-home`` script."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone
from logging.handlers import TimedRotatingFileHandler

import uvicorn

from .api.app import create_app
from .settings import Settings


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry = {
            "ts": datetime.fromtimestamp(record.created, timezone.utc).isoformat(timespec="milliseconds"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }
        if record.exc_info:
            entry["exc"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


LOG_FORMAT = "%(asctime)s %(levelname)s %(name)s: %(message)s"


def setup_logging(settings: Settings) -> None:
    """Console always; with HEOS_HOME_LOG_FILE also a file rotated daily, kept log_backup_count days."""
    formatter: logging.Formatter = JsonFormatter() if settings.log_json else logging.Formatter(LOG_FORMAT)
    handlers: list[logging.Handler] = [logging.StreamHandler(sys.stdout)]
    if settings.log_file:
        settings.log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(
            TimedRotatingFileHandler(
                settings.log_file, when="D", interval=1, backupCount=settings.log_backup_count, encoding="utf-8"
            )
        )
    for handler in handlers:
        handler.setFormatter(formatter)
    root = logging.getLogger()
    for old in root.handlers[:]:
        root.removeHandler(old)
        old.close()
    for handler in handlers:
        root.addHandler(handler)
    root.setLevel(settings.log_level)
    # The power poll makes an HTTP request every 30 s; keep httpx quiet unless debugging.
    for name in ("httpx", "httpcore"):
        logging.getLogger(name).setLevel(logging.DEBUG if settings.log_level == "DEBUG" else logging.WARNING)
    # Raw CLI traffic only at DEBUG (NFR Logging).
    logging.getLogger("heos_home.wire").setLevel(
        logging.DEBUG if settings.log_level == "DEBUG" else logging.WARNING
    )


def main() -> None:
    settings = Settings.from_env()
    setup_logging(settings)
    app = create_app(settings)
    uvicorn.run(app, host=settings.bind, port=settings.port, log_config=None)


if __name__ == "__main__":
    main()
