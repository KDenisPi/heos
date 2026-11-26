"""Process settings, read from environment variables (all optional).

| Variable                 | Default              | Meaning                                       |
| ------------------------ | -------------------- | --------------------------------------------- |
| HEOS_HOME_DATA_DIR       | /var/lib/heos-home   | config.json, state.json, playlists/           |
| HEOS_HOME_BIND           | 0.0.0.0              | HTTP bind address                             |
| HEOS_HOME_PORT           | 8080                 | HTTP port                                     |
| HEOS_HOME_HOSTS          | (empty)              | Comma-separated manual device IPs (F1.2)      |
| HEOS_HOME_DISCOVERY      | on                   | SSDP discovery at startup (on/off)            |
| HEOS_HOME_TOKEN          | (empty)              | If set, write requests need this bearer token |
| HEOS_HOME_STATIC_DIR     | web/dist if built    | Built PWA to serve at /                       |
| HEOS_HOME_LOG_LEVEL      | INFO                 | DEBUG also logs raw CLI traffic               |
| HEOS_HOME_LOG_JSON       | off                  | JSON lines instead of plain text              |
| HEOS_HOME_LOG_FILE       | (empty)              | Also log to this file, rotated daily          |
| HEOS_HOME_LOG_BACKUP_COUNT | 7                  | Rotated log files kept (days)                 |
| HEOS_HOME_HEOS_PORT      | 1255                 | HEOS CLI port (change only for the fake)      |
| HEOS_HOME_KEY_FILE       | /etc/heos-home/key   | Key for saved HEOS credentials (mode 600)     |
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


# Repo checkout layout: src/heos_home/settings.py -> <repo>/web/dist
_REPO_WEB_DIST = Path(__file__).resolve().parents[2] / "web" / "dist"


def _flag(value: str | None, default: bool) -> bool:
    if value is None or value == "":
        return default
    return value.strip().lower() in {"1", "on", "true", "yes"}


@dataclass(slots=True)
class Settings:
    data_dir: Path = Path("/var/lib/heos-home")
    bind: str = "0.0.0.0"
    port: int = 8080
    hosts: list[str] = field(default_factory=list)
    discovery: bool = True
    discovery_timeout: float = 3.0
    token: str | None = None
    static_dir: Path | None = None
    log_level: str = "INFO"
    log_json: bool = False
    log_file: Path | None = None
    log_backup_count: int = 7
    heos_port: int = 1255
    key_file: Path = Path("/etc/heos-home/key")

    @classmethod
    def from_env(cls, env: dict[str, str] | None = None) -> "Settings":
        env = dict(os.environ if env is None else env)
        static = env.get("HEOS_HOME_STATIC_DIR")
        return cls(
            data_dir=Path(env.get("HEOS_HOME_DATA_DIR") or "/var/lib/heos-home"),
            bind=env.get("HEOS_HOME_BIND") or "0.0.0.0",
            port=int(env.get("HEOS_HOME_PORT") or 8080),
            hosts=[h.strip() for h in (env.get("HEOS_HOME_HOSTS") or "").split(",") if h.strip()],
            discovery=_flag(env.get("HEOS_HOME_DISCOVERY"), True),
            token=env.get("HEOS_HOME_TOKEN") or None,
            static_dir=Path(static) if static else (_REPO_WEB_DIST if _REPO_WEB_DIST.is_dir() else None),
            log_level=(env.get("HEOS_HOME_LOG_LEVEL") or "INFO").upper(),
            log_json=_flag(env.get("HEOS_HOME_LOG_JSON"), False),
            log_file=Path(env["HEOS_HOME_LOG_FILE"]) if env.get("HEOS_HOME_LOG_FILE") else None,
            log_backup_count=int(env.get("HEOS_HOME_LOG_BACKUP_COUNT") or 7),
            heos_port=int(env.get("HEOS_HOME_HEOS_PORT") or 1255),
            key_file=Path(env.get("HEOS_HOME_KEY_FILE") or "/etc/heos-home/key"),
        )
