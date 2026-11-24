import json

from tests.conftest import PID

DLNA = 111


async def test_servers(app_env):
    _, _, http = app_env
    servers = (await http.get("/library/servers")).json()["servers"]
    assert servers == [{"sid": DLNA, "name": "Fake NAS", "type": "dlna_server", "container": True, "playable": False,
                        "cid": None, "mid": None, "artist": "", "album": "", "album_id": None, "image_url": "", "play": "queue"}]


async def test_browse_root_and_folder_tree(app_env):
    _, _, http = app_env
    root = (await http.get(f"/sources/{DLNA}/browse")).json()
    assert [i["name"] for i in root["items"]] == ["Music", "Folder"]
    assert root["playable"] is False
    folder = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9"})).json()
    assert [i["name"] for i in folder["items"]] == ["classic", "empty"]
    assert all(i["container"] and not i["playable"] for i in folder["items"])


async def test_folder_with_tracks_is_playable_via_option_21(app_env):
    """Listed as playable=no by its parent, but browsing it says it can be queued."""
    _, _, http = app_env
    parent = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9$1"})).json()
    assert parent["items"][0]["playable"] is False
    box = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9$1$1"})).json()
    assert box["playable"] is True


async def test_paging_reports_total(app_env):
    _, _, http = app_env
    p1 = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9$1$1", "count": 50})).json()
    p3 = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9$1$1", "start": 100, "count": 50})).json()
    assert (p1["total"], p1["count"], p1["items"][0]["name"]) == (120, 50, "Track 001")
    assert (p3["start"], p3["count"], p3["items"][-1]["name"]) == (100, 20, "Track 120")
    assert (await http.get(f"/sources/{DLNA}/browse", params={"count": 500})).status_code == 422


async def test_empty_folder(app_env):
    _, _, http = app_env
    body = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9$2"})).json()
    assert body["items"] == [] and body["total"] == 0


async def test_browse_is_cached(app_env, fake):
    _, _, http = app_env
    params = {"cid": "64$9$1$1", "count": 10}
    await http.get(f"/sources/{DLNA}/browse", params=params)
    sent = len(fake.received)
    await http.get(f"/sources/{DLNA}/browse", params=params)
    assert len(fake.received) == sent  # served from cache
    await http.get(f"/sources/{DLNA}/browse", params={**params, "refresh": True})
    assert len(fake.received) == sent + 1


async def test_cache_cleared_on_sources_changed(app_env, fake):
    _, svc, http = app_env
    params = {"cid": "64$9", "count": 10}
    await http.get(f"/sources/{DLNA}/browse", params=params)
    fake.emit("sources_changed")
    from tests.conftest import wait_for
    await wait_for(lambda: not svc.library._cache)


async def test_track_cover_points_at_local_cache(app_env):
    _, svc, http = app_env
    box = (await http.get(f"/sources/{DLNA}/browse", params={"cid": "64$9$1$1", "count": 2})).json()
    track = box["items"][0]
    assert track["image_url"].startswith("/api/v1/images/")
    assert track["image_url_remote"] == "http://192.0.2.11:8200/cover/bigbox.jpg"


async def test_queue_whole_folder_and_single_track(app_env, fake):
    _, _, http = app_env
    r = await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$9$1$1"}], "mode": "replace"})
    assert r.status_code == 200
    assert (await http.get(f"/players/{PID}/queue")).json()["count"] == 120
    await http.post(f"/players/{PID}/queue",
                    json={"items": [{"sid": DLNA, "cid": "64$1$4", "mid": "64$1$4$2"}], "mode": "end"})
    items = (await http.get(f"/players/{PID}/queue")).json()["items"]
    assert len(items) == 121 and items[-1]["song"] == "Freddie Freeloader"


async def test_search(app_env):
    _, _, http = app_env
    crit = (await http.get(f"/sources/{DLNA}/search-criteria")).json()["criteria"]
    assert [c["name"] for c in crit] == ["Artist", "Album", "Track"]
    res = (await http.get(f"/sources/{DLNA}/search", params={"q": "blue", "criteria": 3})).json()
    assert [i["name"] for i in res["items"]] == ["Blue in Green"]
    res = (await http.get(f"/sources/{DLNA}/search", params={"q": "miles", "criteria": 1})).json()
    assert res["total"] == 3


async def test_search_not_supported_like_the_real_nas(app_env, fake):
    _, _, http = app_env
    fake.search_supported = False
    r = await http.get(f"/sources/{DLNA}/search", params={"q": "chopin"})
    assert r.status_code == 501
    assert r.json()["error"]["code"] == "search_not_supported"


async def test_shortcuts_persist(app_env, settings):
    _, _, http = app_env
    path = [{"cid": "64$9", "name": "Folder"}, {"cid": "64$9$1", "name": "classic"}]
    r = await http.post("/library/shortcuts", json={"sid": DLNA, "path": path})
    assert r.json()["name"] == "classic" and r.json()["id"] == 0
    # Pinning the same folder again does not duplicate it.
    await http.post("/library/shortcuts", json={"sid": DLNA, "path": path})
    shortcuts = (await http.get("/library/shortcuts")).json()["shortcuts"]
    assert len(shortcuts) == 1 and shortcuts[0]["path"] == path
    saved = json.loads((settings.data_dir / "config.json").read_text())
    assert saved["folder_shortcuts"][0]["cid"] == "64$9$1"
    assert (await http.delete("/library/shortcuts/0")).json() == {"removed": 0}
    assert (await http.get("/library/shortcuts")).json()["shortcuts"] == []
    assert (await http.delete("/library/shortcuts/5")).status_code == 404


async def test_last_folder_persists(app_env, settings):
    _, _, http = app_env
    assert (await http.get(f"/library/last-folder/{DLNA}")).json()["path"] == []
    path = [{"cid": "64$9", "name": "Folder"}, {"cid": "64$9$1", "name": "classic"}]
    await http.put(f"/library/last-folder/{DLNA}", json={"path": path})
    assert (await http.get(f"/library/last-folder/{DLNA}")).json()["path"] == path
    saved = json.loads((settings.data_dir / "state.json").read_text())
    assert saved["last_folder"][str(DLNA)][1]["name"] == "classic"


async def test_tracks_carry_their_container_for_queueing(app_env):
    """A track's album_id lets the UI queue it from search results, not only from its folder."""
    _, _, http = app_env
    res = (await http.get(f"/sources/{DLNA}/search", params={"q": "freddie", "criteria": 3})).json()
    track = res["items"][0]
    assert track["album_id"] == "64$1$4"
    r = await http.post(f"/players/{PID}/queue",
                        json={"items": [{"sid": DLNA, "cid": track["album_id"], "mid": track["mid"]}], "mode": "end"})
    assert r.status_code == 200
    assert (await http.get(f"/players/{PID}/queue")).json()["items"][-1]["song"] == "Freddie Freeloader"


async def test_three_add_modes(app_env, fake):
    """The library offers: add and play (now), replace queue and play, add to end."""
    _, svc, http = app_env
    folder = {"sid": DLNA, "cid": "64$1$3"}  # 3 tracks
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$4"}], "mode": "replace"})
    assert fake.players[PID].current == 0
    await http.post(f"/players/{PID}/queue", json={"items": [folder], "mode": "end"})
    q = fake.players[PID].queue
    assert len(q) == 6 and q[-1]["song"].endswith("III. Aria") and fake.players[PID].current == 0
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$3", "mid": "64$1$3$2"}], "mode": "now"})
    assert fake.players[PID].queue[fake.players[PID].current]["song"].endswith("II. Recitative")
    await http.post(f"/players/{PID}/queue", json={"items": [folder], "mode": "replace"})
    assert [i["song"][-9:] for i in fake.players[PID].queue] == ["I. Chorus", "ecitative", "III. Aria"]
