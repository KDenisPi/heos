"""Local cache for images the HEOS device points at (source logos, input icons, covers).

The device returns ``image_url`` values on Denon's cloud. The UI must not depend
on that cloud, so the service downloads each image once, keeps it on disk and
serves it at ``/api/v1/images/{key}``.

Only URLs that came from the device are fetched: an URL is *registered* when a
response is rewritten, and the endpoint serves registered keys only. That keeps
the endpoint from becoming an open proxy.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import mimetypes
import os
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import urlparse

import httpx

from ..storage import atomic_write

log = logging.getLogger(__name__)

API_PREFIX = "/api/v1/images/"
MAX_IMAGE_BYTES = 5 * 1024 * 1024
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}


class ImageError(Exception):
    """The image could not be fetched or is not an image."""


def image_key(url: str) -> str:
    """Stable file name for an URL: hash plus the URL's image extension, if any."""
    digest = hashlib.sha256(url.encode()).hexdigest()[:24]
    ext = PurePosixPath(urlparse(url).path).suffix.lower()
    return digest + (ext if ext in _EXTENSIONS else "")


class ImageCache:
    def __init__(
        self,
        directory: Path,
        *,
        max_bytes: int = 100 * 1024 * 1024,
        timeout: float = 10.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.directory = directory
        self.max_bytes = max_bytes
        self.timeout = timeout
        self._transport = transport
        self._http: httpx.AsyncClient | None = None
        self._locks: dict[str, asyncio.Lock] = {}
        self._index_path = directory / "index.json"
        self._index: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._tasks: set[asyncio.Task[None]] = set()
        directory.mkdir(parents=True, exist_ok=True)
        self._load_index()

    # ------------------------------------------------------------- lifecycle
    async def start(self) -> None:
        self._http = httpx.AsyncClient(
            timeout=self.timeout,
            follow_redirects=True,
            transport=self._transport,
            headers={"User-Agent": "heos-home"},
        )

    async def stop(self) -> None:
        for task in list(self._tasks):
            task.cancel()
        await asyncio.gather(*self._tasks, return_exceptions=True)
        self._save_index()
        if self._http:
            await self._http.aclose()
            self._http = None

    def _load_index(self) -> None:
        try:
            data = json.loads(self._index_path.read_text("utf-8"))
            self._index = {k: v for k, v in data.items() if isinstance(v, dict) and "url" in v}
        except FileNotFoundError:
            self._index = {}
        except (OSError, ValueError) as err:
            log.warning("image index unreadable (%s), starting empty", err)
            self._index = {}

    def _save_index(self) -> None:
        if not self._dirty:
            return
        atomic_write(self._index_path, json.dumps(self._index, indent=1).encode())
        self._dirty = False

    # ------------------------------------------------------------- registry
    def register(self, url: str | None) -> str | None:
        """Remember an URL from the device and return its local API path."""
        if not url or not url.startswith(("http://", "https://")):
            return None
        key = image_key(url)
        if self._index.get(key, {}).get("url") != url:
            self._index[key] = {"url": url}
            self._dirty = True
        return API_PREFIX + key

    def localize(self, item: dict[str, Any], field: str = "image_url") -> dict[str, Any]:
        """Copy of ``item`` with ``image_url`` pointing at the local cache.

        The original stays available as ``image_url_remote``.
        """
        remote = item.get(field)
        local = self.register(remote) if isinstance(remote, str) else None
        if local is None:
            return dict(item)
        return {**item, field: local, f"{field}_remote": remote}

    def localize_all(self, items: list[dict[str, Any]], prefetch: bool = True) -> list[dict[str, Any]]:
        result = [self.localize(item) for item in items]
        self._save_index()
        if prefetch:
            urls = [i["image_url_remote"] for i in result if "image_url_remote" in i]
            if urls:
                task = asyncio.get_running_loop().create_task(self.prefetch(urls))
                self._tasks.add(task)
                task.add_done_callback(self._tasks.discard)
        return result

    # --------------------------------------------------------------- access
    def known(self, key: str) -> bool:
        return key in self._index

    def media_type(self, key: str) -> str:
        stored = self._index.get(key, {}).get("type")
        return stored or mimetypes.guess_type(key)[0] or "application/octet-stream"

    async def get(self, key: str) -> Path:
        """Path of the cached file, downloading it first if needed.

        Raises ``KeyError`` for keys never registered, ``ImageError`` when the
        download fails.
        """
        entry = self._index.get(key)
        if entry is None:
            raise KeyError(key)
        path = self.directory / key
        if path.exists():
            _touch(path)
            return path
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:
            if not path.exists():
                await self._download(key, entry, path)
        self._locks.pop(key, None)
        return path

    async def prefetch(self, urls: list[str]) -> None:
        for url in urls:
            key = image_key(url)
            try:
                await self.get(key)
            except (KeyError, ImageError) as err:
                log.info("prefetch of %s failed: %s", url, err)

    async def _download(self, key: str, entry: dict[str, Any], path: Path) -> None:
        if self._http is None:
            raise ImageError("image cache not started")
        url = entry["url"]
        try:
            async with self._http.stream("GET", url) as resp:
                if resp.status_code != 200:
                    raise ImageError(f"HTTP {resp.status_code} for {url}")
                ctype = resp.headers.get("content-type", "").split(";")[0].strip().lower()
                if not ctype.startswith("image/"):
                    raise ImageError(f"not an image ({ctype or 'no content-type'}): {url}")
                chunks: list[bytes] = []
                size = 0
                async for chunk in resp.aiter_bytes():
                    size += len(chunk)
                    if size > MAX_IMAGE_BYTES:
                        raise ImageError(f"image larger than {MAX_IMAGE_BYTES} bytes: {url}")
                    chunks.append(chunk)
        except httpx.HTTPError as err:
            raise ImageError(f"download failed for {url}: {err}") from err
        atomic_write(path, b"".join(chunks))
        entry["type"] = ctype
        self._dirty = True
        self._save_index()
        log.info("cached image %s (%d bytes) from %s", key, size, url)
        self._evict()

    def _evict(self) -> None:
        """Drop the least recently used files while the cache is over its size limit."""
        files = [p for p in self.directory.iterdir() if p.is_file() and p.name != self._index_path.name
                 and not p.name.startswith(".")]
        total = sum(p.stat().st_size for p in files)
        if total <= self.max_bytes:
            return
        for p in sorted(files, key=lambda f: f.stat().st_mtime):
            if total <= self.max_bytes:
                break
            total -= p.stat().st_size
            p.unlink(missing_ok=True)
            log.info("evicted cached image %s", p.name)


def _touch(path: Path) -> None:
    try:
        os.utime(path)
    except OSError:
        pass
