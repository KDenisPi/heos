"""HEOS account (F7): status, sign in / out, encrypted credentials, re-sign-in.

* Sign-in and sign-out use the amp's own ``system/sign_in`` / ``system/sign_out``.
  The HEOS account holds the streaming logins (Amazon), so it must stay signed in.
* "Remember" stores username and password encrypted (Fernet: AES-128-CBC +
  HMAC-SHA256) in ``<data dir>/secrets.json`` (mode 600). The key is a separate
  file, ``/etc/heos-home/key`` by default (mode 600), created on first use.
  Nothing is kept in the browser and the password is never logged.
* After an amp reboot, or when the amp reports a sign-out this service did not
  ask for, it signs in again with the saved credentials (F7.3). If the amp
  rejects them, it stops retrying and reports the error until new ones are saved.
* An explicit sign-out forgets the saved credentials, so it is not undone.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any

from cryptography.fernet import Fernet, InvalidToken

from ..heos.client import HeosClient
from ..heos.protocol import HeosCommandError, HeosMessage
from ..storage import atomic_write
from .events import EventBus
from .players import PlayerService

log = logging.getLogger(__name__)

SIGN_IN_TIMEOUT = 30.0
RESIGN_MIN_INTERVAL = 60.0  # at most one automatic sign-in attempt per minute
_CREDENTIAL_ERRORS = {6: "Invalid credentials", 10: "User not found"}


class SignInFailed(Exception):
    def __init__(self, message: str, eid: int | None = None) -> None:
        super().__init__(message)
        self.eid = eid


# ---------------------------------------------------------------- secrets
class SecretStore:
    """Credentials encrypted with a key kept in a separate file."""

    def __init__(self, path: Path, key_file: Path, fallback_key_file: Path) -> None:
        self.path = path
        self.key_file = key_file
        self.fallback_key_file = fallback_key_file
        self._fernet: Fernet | None = None

    def _key(self) -> Fernet:
        if self._fernet:
            return self._fernet
        for candidate in (self.key_file, self.fallback_key_file):
            if candidate.exists():
                self._fernet = Fernet(candidate.read_bytes().strip())
                return self._fernet
        key = Fernet.generate_key()
        for candidate in (self.key_file, self.fallback_key_file):
            try:
                candidate.parent.mkdir(parents=True, exist_ok=True)
                atomic_write(candidate, key + b"\n", mode=0o600)
                if candidate != self.key_file:
                    log.warning("cannot write %s; credentials key created at %s instead", self.key_file, candidate)
                else:
                    log.info("credentials key created at %s", candidate)
                self._fernet = Fernet(key)
                return self._fernet
            except OSError:
                continue
        raise OSError(f"cannot create a credentials key at {self.key_file} or {self.fallback_key_file}")

    def load(self) -> dict[str, str] | None:
        """Decrypted {"username", "password"}, or None if nothing usable is stored."""
        try:
            data = json.loads(self.path.read_text("utf-8"))
            token = data["heos"]["token"].encode()
        except FileNotFoundError:
            return None
        except (OSError, ValueError, KeyError, TypeError) as err:
            log.warning("secrets.json unreadable (%s); ignoring it", err)
            return None
        try:
            creds = json.loads(self._key().decrypt(token))
            return {"username": str(creds["username"]), "password": str(creds["password"])}
        except (InvalidToken, ValueError, KeyError, TypeError, OSError) as err:
            log.warning("saved HEOS credentials cannot be decrypted (%s); ignoring them", type(err).__name__)
            return None

    def save(self, username: str, password: str) -> None:
        token = self._key().encrypt(json.dumps({"username": username, "password": password}).encode())
        doc = {"version": 1, "heos": {"token": token.decode(), "saved": time.time()}}
        atomic_write(self.path, json.dumps(doc, indent=1).encode(), mode=0o600)

    def clear(self) -> None:
        try:
            self.path.unlink()
        except FileNotFoundError:
            pass


# ---------------------------------------------------------------- service
class AccountService:
    def __init__(self, client: HeosClient, players: PlayerService, secrets: SecretStore, bus: EventBus) -> None:
        self.client = client
        self.players = players
        self.secrets = secrets
        self.bus = bus
        self.last_error: str | None = None
        self.auto_sign_in_disabled = False  # saved credentials were rejected
        self._last_auto_attempt = 0.0
        self._lock = asyncio.Lock()
        self._expect_sign_out = False
        # Registered after PlayerService, so its account state is fresh.
        client.add_connection_listener(self._on_connection)
        client.add_event_listener(self._on_event)

    # ------------------------------------------------------------ status
    def status(self) -> dict[str, Any]:
        saved = self.secrets.load()
        return {
            **self.players.account,
            "remembered": saved is not None,
            "remembered_username": saved["username"] if saved else None,
            "auto_sign_in": saved is not None and not self.auto_sign_in_disabled,
            "error": self.last_error,
        }

    def _publish(self) -> None:
        self.bus.publish("account", data=self.status())

    # ----------------------------------------------------------- actions
    async def sign_in(self, username: str, password: str, remember: bool = True) -> dict[str, Any]:
        username = username.strip()
        if not username or not password:
            raise ValueError("username and password are required")
        async with self._lock:
            await self._sign_in(username, password)
            if remember:
                self.secrets.save(username, password)
            else:
                self.secrets.clear()
            self.auto_sign_in_disabled = False
            self.last_error = None
        self._publish()
        return self.status()

    async def _sign_in(self, username: str, password: str) -> None:
        try:
            msg = await self.client.command(
                "system/sign_in", {"un": username, "pw": password}, timeout=SIGN_IN_TIMEOUT, retries=1
            )
        except HeosCommandError as err:
            text = _CREDENTIAL_ERRORS.get(err.eid or 0, err.text)
            raise SignInFailed(f"HEOS sign-in failed: {text}", err.eid) from err
        self.players._set_account(msg.params)

    async def sign_out(self) -> dict[str, Any]:
        """Sign out on the amp and forget saved credentials (so it is not undone automatically)."""
        async with self._lock:
            self.secrets.clear()
            self._expect_sign_out = True
            try:
                msg = await self.client.command("system/sign_out", timeout=SIGN_IN_TIMEOUT)
                self.players._set_account(msg.params)
            finally:
                self._expect_sign_out = False
            self.last_error = None
        self._publish()
        return self.status()

    def forget(self) -> dict[str, Any]:
        """Drop saved credentials but stay signed in."""
        self.secrets.clear()
        self.auto_sign_in_disabled = False
        self._publish()
        return self.status()

    # ------------------------------------------------------ re-sign-in (F7.3)
    async def _on_connection(self, connected: bool) -> None:
        if connected:
            await self.ensure_signed_in("connected")

    async def _on_event(self, msg: HeosMessage) -> None:
        if msg.command == "event/user_changed" and "signed_out" in msg.params and not self._expect_sign_out:
            await self.ensure_signed_in("signed out by the device")

    async def ensure_signed_in(self, reason: str) -> bool:
        """Sign in with saved credentials if the amp is signed out. Returns True if it signed in."""
        if self.players.account.get("signed_in") or self.auto_sign_in_disabled or self._lock.locked():
            return False
        saved = self.secrets.load()
        if saved is None:
            return False
        now = time.monotonic()
        if now - self._last_auto_attempt < RESIGN_MIN_INTERVAL:
            return False
        self._last_auto_attempt = now
        log.info("HEOS account signed out (%s); signing in again as saved", reason)
        async with self._lock:
            try:
                await self._sign_in(saved["username"], saved["password"])
                self.last_error = None
                log.info("signed in to HEOS again")
                return True
            except SignInFailed as err:
                self.last_error = str(err)
                if err.eid in _CREDENTIAL_ERRORS:
                    self.auto_sign_in_disabled = True  # do not hammer the account with a wrong password
                log.warning("automatic HEOS sign-in failed: %s", err)
                return False
            except Exception as err:  # noqa: BLE001 - e.g. connection lost; retried on next connect
                self.last_error = f"automatic sign-in failed: {err}"
                log.warning("automatic HEOS sign-in failed: %s", err)
                return False
            finally:
                self._publish()
