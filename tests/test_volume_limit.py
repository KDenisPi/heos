import json

from tests.conftest import PID, wait_for


async def test_default_limit_is_50(app_env, settings):
    _, _, http = app_env
    assert (await http.get("/settings")).json() == {"volume_max": 50, "volume_step": 1}


async def test_set_volume_is_capped(app_env, fake):
    _, _, http = app_env
    r = await http.put(f"/players/{PID}/volume", json={"level": 80})
    assert r.json() == {"level": 50, "mute": False, "max": 50, "limited": True}
    assert fake.players[PID].volume == 50
    r = await http.put(f"/players/{PID}/volume", json={"level": 30})
    assert r.json()["limited"] is False and fake.players[PID].volume == 30


async def test_step_up_stops_at_the_limit(app_env, fake):
    _, svc, http = app_env
    await http.put(f"/players/{PID}/volume", json={"level": 48})
    await http.put(f"/players/{PID}/volume", json={"step": 5})
    assert fake.players[PID].volume == 50  # not 53
    sent = sum("set_volume" in c for c in fake.received)
    await http.put(f"/players/{PID}/volume", json={"step": 1})
    assert fake.players[PID].volume == 50
    assert sum("set_volume" in c for c in fake.received) == sent  # nothing sent at the limit


async def test_step_down_always_works(app_env, fake):
    _, svc, http = app_env
    fake.players[PID].volume = 70  # e.g. turned up with the amp's own remote
    svc.players.players[PID].volume = 70
    r = await http.put(f"/players/{PID}/volume", json={"step": -1})
    assert r.json()["level"] == 69 and fake.players[PID].volume == 69


async def test_change_limit_persists_and_is_pushed(app_env, settings, fake):
    _, svc, http = app_env
    events = svc.bus.subscribe()
    r = await http.patch("/settings", json={"volume_max": 35, "volume_step": 2})
    assert r.json() == {"volume_max": 35, "volume_step": 2}
    saved = json.loads((settings.data_dir / "config.json").read_text())
    assert saved["volume"] == {"max": 35, "step": 2}
    pushed = []
    while not events.empty():
        pushed.append(events.get_nowait())
    assert {"type": "settings", "data": {"volume_max": 35, "volume_step": 2}} in pushed
    await http.put(f"/players/{PID}/volume", json={"level": 40})
    assert fake.players[PID].volume == 35


async def test_invalid_limits_rejected(app_env):
    _, _, http = app_env
    assert (await http.patch("/settings", json={"volume_max": 0})).status_code == 422
    assert (await http.patch("/settings", json={"volume_max": 101})).status_code == 422
    assert (await http.patch("/settings", json={"volume_step": 11})).status_code == 422
