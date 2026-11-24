import json
import os

import pytest

from heos_home.services.account import SecretStore
from tests.conftest import wait_for

USER, PASSWORD = "user@example.com", "s3cret & =%"  # special characters must survive HEOS escaping


async def sign_in(http, password=PASSWORD, remember=True, username=USER):
    return await http.post("/account/sign-in", json={"username": username, "password": password, "remember": remember})


# ------------------------------------------------------------ secret store
def test_secrets_are_encrypted_and_private(tmp_path):
    store = SecretStore(tmp_path / "data" / "secrets.json", tmp_path / "etc" / "key", tmp_path / "data" / "fallback.key")
    store.save(USER, PASSWORD)
    raw = (tmp_path / "data" / "secrets.json").read_text()
    assert PASSWORD not in raw and USER not in raw
    assert oct(os.stat(tmp_path / "data" / "secrets.json").st_mode & 0o777) == "0o600"
    assert oct(os.stat(tmp_path / "etc" / "key").st_mode & 0o777) == "0o600"
    assert SecretStore(store.path, store.key_file, store.fallback_key_file).load() == {"username": USER, "password": PASSWORD}


def test_wrong_key_means_no_credentials(tmp_path):
    store = SecretStore(tmp_path / "secrets.json", tmp_path / "key", tmp_path / "fb.key")
    store.save(USER, PASSWORD)
    (tmp_path / "key").unlink()  # key lost: a new one is made and the old token cannot be read
    assert SecretStore(tmp_path / "secrets.json", tmp_path / "key", tmp_path / "fb.key").load() is None


def test_key_falls_back_when_primary_not_writable(tmp_path):
    blocked = tmp_path / "ro"
    blocked.mkdir()
    blocked.chmod(0o500)
    try:
        store = SecretStore(tmp_path / "secrets.json", blocked / "sub" / "key", tmp_path / "fb.key")
        store.save(USER, PASSWORD)
        assert (tmp_path / "fb.key").exists()
    finally:
        blocked.chmod(0o700)


# --------------------------------------------------------------- endpoints
async def test_sign_out_and_in(app_env, fake, settings):
    _, svc, http = app_env
    r = await http.post("/account/sign-out")
    assert r.json()["signed_in"] is False and fake.signed_in is None
    r = await sign_in(http)
    assert r.status_code == 200
    body = r.json()
    assert (body["signed_in"], body["username"], body["remembered"], body["remembered_username"]) == (True, USER, True, USER)
    assert fake.signed_in == USER
    assert PASSWORD not in (settings.data_dir / "secrets.json").read_text()
    sent = [c for c in fake.received if c.startswith("heos://system/sign_in")][-1]
    assert sent == "heos://system/sign_in?un=user@example.com&pw=s3cret %26 %3D%25"


async def test_wrong_password_is_401_and_not_saved(app_env, fake, settings):
    _, _, http = app_env
    await http.post("/account/sign-out")
    r = await sign_in(http, password="nope")
    assert r.status_code == 401
    assert r.json()["error"] == {"code": "sign_in_failed", "message": "HEOS sign-in failed: Invalid credentials", "eid": 6}
    assert not (settings.data_dir / "secrets.json").exists()
    r = await sign_in(http, username="nobody@example.com")
    assert "User not found" in r.json()["error"]["message"]


async def test_password_is_not_logged(app_env, caplog):
    _, _, http = app_env
    import logging
    caplog.set_level(logging.DEBUG)
    await sign_in(http)
    assert PASSWORD not in caplog.text and "s3cret" not in caplog.text


async def test_sign_in_without_remember(app_env, settings):
    _, _, http = app_env
    await sign_in(http)  # remembered
    body = (await sign_in(http, remember=False)).json()
    assert body["remembered"] is False
    assert not (settings.data_dir / "secrets.json").exists()


async def test_signs_in_again_after_amp_reboot(app_env, fake):
    """F7.3: the amp comes back signed out; the service signs in again with the saved credentials."""
    _, svc, http = app_env
    await sign_in(http)
    await fake.reboot()
    await wait_for(lambda: fake.signed_in == USER, timeout=5)
    await wait_for(lambda: svc.players.account["signed_in"])
    assert (await http.get("/account")).json()["signed_in"] is True


async def test_no_auto_sign_in_after_explicit_sign_out(app_env, fake):
    _, svc, http = app_env
    await sign_in(http)
    r = await http.post("/account/sign-out")
    assert r.json()["remembered"] is False
    await fake.reboot()
    await wait_for(lambda: svc.client.connected, timeout=5)
    await wait_for(lambda: svc.players.account.get("signed_in") is False)
    assert fake.signed_in is None


async def test_rejected_saved_password_stops_retrying(app_env, fake):
    _, svc, http = app_env
    await sign_in(http)
    fake.accounts[USER] = "changed elsewhere"
    await fake.reboot()
    await wait_for(lambda: svc.account.last_error is not None, timeout=5)
    status = (await http.get("/account")).json()
    assert status["signed_in"] is False and status["auto_sign_in"] is False
    assert "Invalid credentials" in status["error"]
    attempts = sum(c.startswith("heos://system/sign_in") for c in fake.received)
    transitions = []

    async def on_conn(connected):
        transitions.append(connected)

    svc.client.add_connection_listener(on_conn)
    await fake.drop_connections()  # another reconnect: must not try the bad password again
    await wait_for(lambda: transitions[-2:] == [False, True], timeout=5)
    assert sum(c.startswith("heos://system/sign_in") for c in fake.received) == attempts
    # Signing in by hand with the new password clears the error and re-enables it.
    body = (await sign_in(http, password="changed elsewhere")).json()
    assert body["auto_sign_in"] is True and body["error"] is None


async def test_forget_credentials_keeps_signed_in(app_env, fake, settings):
    _, _, http = app_env
    await sign_in(http)
    body = (await http.delete("/account/credentials")).json()
    assert body["signed_in"] is True and body["remembered"] is False
    assert fake.signed_in == USER


async def test_signed_out_elsewhere_signs_in_again(app_env, fake):
    """Signed out by another app (user_changed event): saved credentials sign it back in."""
    _, svc, http = app_env
    await sign_in(http)
    svc.account._last_auto_attempt = 0
    fake.signed_in = None
    fake.emit("user_changed", "signed_out")
    await wait_for(lambda: fake.signed_in == USER, timeout=5)


async def test_account_status_in_websocket_snapshot(app_env):
    _, svc, _ = app_env
    snap_account = svc.account.status()
    assert set(snap_account) >= {"signed_in", "username", "remembered", "auto_sign_in", "error"}
