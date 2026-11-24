"""JSON files on disk: config.json and state.json (section 5 of the spec).

There is no database. Every write is atomic (temp file, fsync, rename), and the
service is the only writer while it runs.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field, ValidationError

log = logging.getLogger(__name__)


def atomic_write(path: Path, data: bytes, mode: int = 0o644) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
    with contextlib.suppress(OSError):  # make the rename durable
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)



# ---------------------------------------------------------------- models
class PowerConfig(BaseModel):
    driver: str = "auto"  # auto | upnp_act | none (F2.5), see services/power.py
    config: dict[str, Any] = Field(default_factory=dict)


class DeviceConfig(BaseModel):
    pid: int
    name: str = ""
    model: str = ""
    ip: str | None = None
    ip_override: str | None = None
    power: PowerConfig = Field(default_factory=PowerConfig)

    @property
    def address(self) -> str | None:
        return self.ip_override or self.ip


class PathStep(BaseModel):
    """One breadcrumb step: a container id and its display name."""

    cid: str
    name: str


class FolderShortcut(BaseModel):
    """A pinned folder (F5.7). ``path`` is the breadcrumb from the server root."""

    name: str
    sid: int
    cid: str
    path: list[PathStep] = Field(default_factory=list)


CONFIG_VERSION = 2


class VolumeConfig(BaseModel):
    """Volume limits applied by this service to every volume change it makes."""

    max: int = Field(50, ge=1, le=100)
    step: int = Field(1, ge=1, le=10)


class Config(BaseModel):
    version: int = CONFIG_VERSION
    default_pid: int | None = None
    volume: VolumeConfig = Field(default_factory=VolumeConfig)
    devices: list[DeviceConfig] = Field(default_factory=list)
    folder_shortcuts: list[FolderShortcut] = Field(default_factory=list)
    ui: dict[str, Any] = Field(default_factory=lambda: {"theme": "dark"})

    def device(self, pid: int) -> DeviceConfig | None:
        return next((d for d in self.devices if d.pid == pid), None)

    def migrate(self) -> bool:
        """Upgrade an older config in place; return True if anything changed."""
        if self.version >= CONFIG_VERSION:
            return False
        if self.version < 2:
            # v1 wrote driver "none" as a placeholder, before any power path
            # existed; nobody chose it, so switch those devices to "auto".
            for dev in self.devices:
                if dev.power.driver == "none" and not dev.power.config:
                    dev.power.driver = "auto"
        self.version = CONFIG_VERSION
        return True


class State(BaseModel):
    version: int = 1
    last_pid: int | None = None
    last_host: str | None = None
    # sid -> breadcrumb of the last folder browsed on that server (F5.7)
    last_folder: dict[str, list[PathStep]] = Field(default_factory=dict)


M = TypeVar("M", bound=BaseModel)


class JsonFile(Generic[M]):
    """A pydantic model persisted as a pretty-printed JSON file."""

    def __init__(self, path: Path, model: type[M]) -> None:
        self.path = path
        self.model = model
        self.data: M = self._load()

    def _load(self) -> M:
        if not self.path.exists():
            return self.model()
        try:
            return self.model.model_validate(json.loads(self.path.read_text("utf-8")))
        except (OSError, ValueError, ValidationError) as err:
            backup = self.path.with_suffix(self.path.suffix + ".bad")
            log.error("cannot read %s (%s); keeping it as %s and using defaults", self.path, err, backup)
            with contextlib.suppress(OSError):
                os.replace(self.path, backup)
            return self.model()

    def save(self) -> None:
        text = json.dumps(self.data.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
        atomic_write(self.path, text.encode("utf-8"))


class Storage:
    def __init__(self, data_dir: Path) -> None:
        self.data_dir = data_dir
        data_dir.mkdir(parents=True, exist_ok=True)
        (data_dir / "playlists").mkdir(exist_ok=True)
        self.config: JsonFile[Config] = JsonFile(data_dir / "config.json", Config)
        self.state: JsonFile[State] = JsonFile(data_dir / "state.json", State)
        if self.config.path.exists() and self.config.data.migrate():
            log.info("config.json migrated to version %d", self.config.data.version)
            self.config.save()

    @property
    def playlists_dir(self) -> Path:
        return self.data_dir / "playlists"

    @property
    def images_dir(self) -> Path:
        """Downloaded device images; a cache, safe to delete and not needed in backups."""
        return self.data_dir / "cache" / "images"
