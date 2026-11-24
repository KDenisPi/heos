import asyncio
import json

import httpx
import pytest

from heos_home.services.power import UpnpActDriver
from heos_home.storage import Storage
from tests.conftest import PID, FakeAct, wait_for


async def test_driver_reads_and_sets():
    act = FakeAct("OFF")
    async with httpx.AsyncClient(transport=act.transport()) as http:
        drv = UpnpActDriver("192.0.2.1", http)
        assert await drv.get_state() == "standby"
        await drv.set_state(True)
        assert act.set_calls == ["ON"]
        assert await drv.get_state() == "on"


async def test_state_is_read_at_startup_and_shown(app_env, act):
    _, svc, http = app_env
    await wait_for(lambda: svc.power.state(PID) == "on")
    power = (await http.get("/devices")).json()["devices"][0]["power"]
    assert power == {"driver": "auto", "effective_driver": "upnp_act", "state": "on", "error": None}
    assert act.set_calls == []


async def test_get_power_is_read_only(app_env, act):
    _, _, http = app_env
    r = await http.get(f"/devices/{PID}/power")
    assert r.json()["state"] == "on"
    assert act.set_calls == []


async def test_switch_off_publishes_event(app_env, act):
    _, svc, http = app_env
    await wait_for(lambda: svc.power.state(PID) == "on")
    queue = svc.bus.subscribe()
    r = await http.post(f"/devices/{PID}/power", json={"state": "off"})
    assert r.json() == {"state": "standby", "changed": True}
    assert act.set_calls == ["OFF"]
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert {"type": "power", "pid": PID, "data": {"state": "standby"}} in events


async def test_already_in_state_does_not_switch(app_env, act):
    _, _, http = app_env
    r = await http.post(f"/devices/{PID}/power", json={"state": "on"})
    assert r.json() == {"state": "on", "changed": False}
    assert act.set_calls == []


async def test_second_switch_too_soon_is_refused(app_env, act):
    _, _, http = app_env
    await http.post(f"/devices/{PID}/power", json={"state": "off"})
    r = await http.post(f"/devices/{PID}/power", json={"state": "on"})
    assert r.status_code == 429
    assert int(r.headers["Retry-After"]) >= 1
    assert act.set_calls == ["OFF"]


async def test_driver_none_refuses(app_env, act):
    _, _, http = app_env
    await http.patch(f"/devices/{PID}", json={"power": {"driver": "none"}})
    r = await http.post(f"/devices/{PID}/power", json={"state": "off"})
    assert r.status_code == 501
    assert act.set_calls == []


async def test_unreachable_power_path_stays_auto(app_env, act):
    _, svc, http = app_env
    await wait_for(lambda: svc.power.state(PID) == "on")
    svc.power._resolved.clear()
    act.reachable = False
    body = (await http.get(f"/devices/{PID}/power")).json()
    assert body["state"] == "unknown"
    assert body["effective_driver"] == "auto"
    assert "refused" in body["error"]
    act.reachable = True
    assert (await http.get(f"/devices/{PID}/power")).json()["state"] == "on"


async def test_remote_power_change_detected_via_volume_event(app_env, act, fake):
    """Standby by remote: the CLI emits a volume event, which triggers a re-read."""
    _, svc, http = app_env
    await wait_for(lambda: svc.power.state(PID) == "on")
    svc.power.poll_interval = 3600  # only the event can wake it
    await asyncio.sleep(0.05)
    act.power = "OFF"
    await http.put(f"/players/{PID}/mute", json={"state": True})  # causes a volume event
    await wait_for(lambda: svc.power.state(PID) == "standby")
    assert act.set_calls == []


def test_config_v1_none_migrates_to_auto(tmp_path):
    (tmp_path / "config.json").write_text(json.dumps({
        "version": 1, "default_pid": PID,
        "devices": [
            {"pid": PID, "power": {"driver": "none", "config": {}}},
            {"pid": 7, "power": {"driver": "none", "config": {"note": "keep"}}},
        ],
    }))
    storage = Storage(tmp_path)
    devs = storage.config.data.devices
    assert storage.config.data.version == 2
    assert devs[0].power.driver == "auto"
    assert devs[1].power.driver == "none"
    assert json.loads((tmp_path / "config.json").read_text())["version"] == 2
