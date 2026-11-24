import json

from starlette.testclient import TestClient

from heos_home.api.app import build_services, create_app
from tests.conftest import PID, fast_client, wait_for


async def test_health(app_env):
    _, _, http = app_env
    body = (await http.get("/health")).json()
    assert body["status"] == "ok"
    assert body["heos"]["connected"] is True


async def test_devices_persisted_to_config(app_env, settings):
    _, svc, http = app_env
    devices = (await http.get("/devices")).json()["devices"]
    assert devices[0]["pid"] == PID
    assert devices[0]["model"] == "Marantz PM7000N"
    assert devices[0]["online"] is True
    assert devices[0]["firmware"] == "3.84.410"
    saved = json.loads((settings.data_dir / "config.json").read_text())
    assert saved["default_pid"] == PID
    assert saved["devices"][0]["name"] == "Living room"
    state = json.loads((settings.data_dir / "state.json").read_text())
    assert state["last_host"] == "127.0.0.1"


async def test_patch_device_power_driver_validation(app_env):
    _, _, http = app_env
    r = await http.patch(f"/devices/{PID}", json={"power": {"driver": "bogus"}})
    assert r.status_code == 400
    r = await http.patch(f"/devices/{PID}", json={"power": {"driver": "none"}})
    assert r.json()["power"]["driver"] == "none"


async def test_player_state_and_volume(app_env, fake):
    _, svc, http = app_env
    state = (await http.get(f"/players/{PID}/state")).json()
    assert state["volume"] == 20 and state["state"] == "stop"

    r = await http.put(f"/players/{PID}/volume", json={"level": 35})
    assert r.status_code == 200 and r.json()["level"] == 35
    assert fake.players[PID].volume == 35

    await http.put(f"/players/{PID}/volume", json={"step": -5})
    await wait_for(lambda: svc.players.players[PID].volume == 30)

    assert (await http.put(f"/players/{PID}/volume", json={"level": 10, "step": 1})).status_code == 422
    assert (await http.put(f"/players/{PID}/volume", json={"level": 101})).status_code == 422


async def test_mute_and_play_mode(app_env, fake):
    _, svc, http = app_env
    await http.put(f"/players/{PID}/mute", json={"state": True})
    assert fake.players[PID].mute is True
    r = await http.put(f"/players/{PID}/play-mode", json={"repeat": "on_all"})
    assert r.json() == {"shuffle": False, "repeat": "on_all"}
    assert fake.players[PID].repeat == "on_all"


async def test_unknown_player_is_404(app_env):
    _, _, http = app_env
    assert (await http.get("/players/999/state")).status_code == 404


async def test_inputs_read_from_device_and_select(app_env, fake):
    _, svc, http = app_env
    body = (await http.get(f"/players/{PID}/inputs")).json()
    names = [i["input"] for i in body["inputs"]]
    assert "inputs/phono" in names and "inputs/coax_in_1" in names

    r = await http.put(f"/players/{PID}/input", json={"input": "inputs/phono"})
    assert r.status_code == 200
    await wait_for(lambda: svc.players.players[PID].input == "inputs/phono")
    assert svc.players.players[PID].state == "play"


async def test_queue_add_move_remove_clear(app_env, fake):
    _, svc, http = app_env
    r = await http.post(f"/players/{PID}/queue",
                        json={"items": [{"sid": 111, "cid": "64$1$3"}], "mode": "replace"})
    assert r.status_code == 200
    await wait_for(lambda: svc.players.players[PID].now_playing.get("song") == "Cantata BWV 140: I. Chorus")

    await http.post(f"/players/{PID}/queue",
                    json={"items": [{"sid": 111, "cid": "64$1$4", "mid": "64$1$4$1"}], "mode": "end"})
    queue = (await http.get(f"/players/{PID}/queue")).json()
    assert queue["count"] == 4
    assert [i["qid"] for i in queue["items"]] == [1, 2, 3, 4]
    assert queue["items"][3]["song"] == "So What"

    await http.post(f"/players/{PID}/queue/move", json={"qids": [4], "to": 1})
    queue = (await http.get(f"/players/{PID}/queue")).json()
    assert queue["items"][0]["song"] == "So What"

    r = await http.request("DELETE", f"/players/{PID}/queue", json={"qids": [1]})
    assert r.json() == {"removed": [1]}
    assert (await http.get(f"/players/{PID}/queue")).json()["count"] == 3

    r = await http.delete(f"/players/{PID}/queue")
    assert r.json() == {"cleared": True}
    assert (await http.get(f"/players/{PID}/queue")).json()["count"] == 0


async def test_multi_item_play_next_keeps_order(app_env, fake):
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$3"}], "mode": "replace"})
    items = [{"sid": 111, "cid": "64$1$4", "mid": f"64$1$4${i}"} for i in (1, 2, 3)]
    await http.post(f"/players/{PID}/queue", json={"items": items, "mode": "next"})
    songs = [i["song"] for i in (await http.get(f"/players/{PID}/queue")).json()["items"]]
    assert songs[1:4] == ["So What", "Freddie Freeloader", "Blue in Green"]


async def test_transport(app_env, fake):
    _, svc, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$3"}], "mode": "replace"})
    await http.post(f"/players/{PID}/transport", json={"action": "next"})
    await wait_for(lambda: svc.players.players[PID].now_playing.get("song") == "Cantata BWV 140: II. Recitative")
    await http.post(f"/players/{PID}/transport", json={"action": "pause"})
    await wait_for(lambda: svc.players.players[PID].state == "pause")
    assert (await http.post(f"/players/{PID}/transport", json={"action": "rewind"})).status_code == 422


async def test_heos_failure_maps_to_502(app_env, fake):
    _, _, http = app_env
    fake.fail_next["player/set_mute"] = 7
    r = await http.put(f"/players/{PID}/mute", json={"state": True})
    assert r.status_code == 502
    assert r.json()["error"]["eid"] == 7


async def test_sources_and_account(app_env):
    _, _, http = app_env
    sources = (await http.get("/sources")).json()["sources"]
    assert {s["name"] for s in sources} >= {"Amazon Music", "Local Music", "AUX Input"}
    assert (await http.get("/account")).json() == {"signed_in": True, "username": "user@example.com"}


async def test_offline_returns_503(app_env, fake):
    _, svc, http = app_env
    await fake.stop()
    await wait_for(lambda: not svc.client.connected)
    r = await http.put(f"/players/{PID}/volume", json={"level": 10})
    assert r.status_code == 503
    devices = (await http.get("/devices")).json()["devices"]
    assert devices[0]["online"] is False


async def test_token_required_for_writes(fake, settings):
    settings.token = "s3cret"
    svc = build_services(settings, fast_client(fake.port, host=None))
    app = create_app(settings, svc)
    import httpx
    async with app.router.lifespan_context(app):
        await svc.client.wait_connected(3)
        await wait_for(lambda: PID in svc.players.players)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://t/api/v1") as http:
            assert (await http.get(f"/players/{PID}/state")).status_code == 200
            assert (await http.put(f"/players/{PID}/mute", json={"state": True})).status_code == 401
            r = await http.put(f"/players/{PID}/mute", json={"state": True},
                               headers={"Authorization": "Bearer s3cret"})
            assert r.status_code == 200


def test_websocket_snapshot_and_events(settings):
    """Uses Starlette's sync TestClient, which runs the app in its own loop."""
    import asyncio
    import threading

    # The fake device must live in a loop that keeps running: run it in a thread.
    loop = asyncio.new_event_loop()
    from heos_home.heos.fake import FakeHeosServer

    ready = threading.Event()
    holder = {}

    def run():
        asyncio.set_event_loop(loop)
        holder["srv"] = loop.run_until_complete(FakeHeosServer().start())
        ready.set()
        loop.run_forever()

    t = threading.Thread(target=run, daemon=True)
    t.start()
    ready.wait(3)
    srv = holder["srv"]
    try:
        svc = build_services(settings, fast_client(srv.port, host=None))
        app = create_app(settings, svc)
        with TestClient(app) as tc:
            with tc.websocket_connect("/api/v1/ws") as ws:
                first = ws.receive_json()
                assert first["type"] == "snapshot"
                # The snapshot may arrive before the first refresh; wait for player data.
                seen = [first]
                while not any(e["type"] == "player_full" for e in seen) and not first["data"]["players"]:
                    seen.append(ws.receive_json())
                r = tc.put(f"/api/v1/players/{PID}/volume", json={"level": 42})
                assert r.status_code == 200
                for _ in range(20):
                    ev = ws.receive_json()
                    if ev["type"] == "volume":
                        assert ev == {"type": "volume", "pid": PID, "data": {"level": 42, "mute": False}}
                        break
                else:
                    raise AssertionError("no volume event")
                ws.send_json({"type": "ping"})
                for _ in range(20):
                    if ws.receive_json()["type"] == "pong":
                        break
                else:
                    raise AssertionError("no pong")
    finally:
        asyncio.run_coroutine_threadsafe(srv.stop(), loop).result(3)
        loop.call_soon_threadsafe(loop.stop)
