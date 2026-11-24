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
    driver: str = "none"  # none | heos_hidden | http_8080 | https_10443 (F2.5)
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


class FolderShortcut(BaseModel):
    name: str
    sid: int
    cid: str


class Config(BaseModel):
    version: int = 1
    default_pid: int | None = None
    devices: list[DeviceConfig] = Field(default_factory=list)
    folder_shortcuts: list[FolderShortcut] = Field(default_factory=list)
    ui: dict[str, Any] = Field(default_factory=lambda: {"theme": "dark"})

    def device(self, pid: int) -> DeviceConfig | None:
        return next((d for d in self.devices if d.pid == pid), None)


class State(BaseModel):
    version: int = 1
    last_pid: int | None = None
    last_host: str | None = None
    last_folder: dict[str, str] = Field(default_factory=dict)  # sid -> cid


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

    @property
    def playlists_dir(self) -> Path:
        return self.data_dir / "playlists"
