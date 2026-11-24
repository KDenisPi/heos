"""Entry point: ``python -m heos_home`` or the ``heos-home`` script."""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone

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


def setup_logging(settings: Settings) -> None:
    handler = logging.StreamHandler(sys.stdout)
    if settings.log_json:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
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
