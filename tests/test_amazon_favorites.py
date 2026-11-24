from tests.conftest import PID, wait_for

AMAZON, FAVORITES = 13, 1028


async def test_library_sources(app_env):
    _, _, http = app_env
    sources = (await http.get("/library/sources")).json()["sources"]
    kinds = [(s["kind"], s["sid"], s["name"]) for s in sources]
    assert kinds == [("service", AMAZON, "Amazon Music"), ("favorites", FAVORITES, "Favorites"), ("dlna", 111, "Fake NAS")]
    assert sources[0]["account"] == "user@example.com"


async def test_amazon_root_hides_upsell_banner(app_env):
    _, _, http = app_env
    root = (await http.get(f"/sources/{AMAZON}/browse")).json()
    assert [i["name"] for i in root["items"]] == ["Prime Stations", "My Music"]
    assert root["total"] == 2


async def test_amazon_albums_are_streams_not_queueable(app_env):
    _, _, http = app_env
    page = (await http.get(f"/sources/{AMAZON}/browse", params={"cid": "library/albums/#library_albums-NAME-Albums"})).json()
    album = page["items"][0]
    assert (album["type"], album["container"], album["play"]) == ("station", False, "stream")
    assert page["items"][1]["name"] == "Moods & Activities"  # decoded %26
    menus = (await http.get(f"/sources/{AMAZON}/browse", params={"cid": "library/#library_node_desc"})).json()
    assert menus["items"][0]["play"] == "queue" and menus["items"][0]["container"]


async def test_play_amazon_album(app_env, fake):
    _, svc, http = app_env
    r = await http.post(f"/players/{PID}/play-stream",
                        json={"sid": AMAZON, "mid": "catalog/albums/B0HRLGGK59/#chunk", "name": "Chopin: The Great Works"})
    assert r.status_code == 200
    assert fake.players[PID].station["name"] == "Chopin: The Great Works"
    await wait_for(lambda: svc.players.players[PID].now_playing.get("station") == "Chopin: The Great Works")
    sent = [c for c in fake.received if "play_stream" in c][-1]
    assert sent == f"heos://browse/play_stream?pid={PID}&sid=13&mid=catalog/albums/B0HRLGGK59/#chunk&name=Chopin: The Great Works"


async def test_amazon_search_not_supported(app_env):
    _, _, http = app_env
    assert (await http.get(f"/sources/{AMAZON}/search-criteria")).json()["criteria"] == []
    assert (await http.get(f"/sources/{AMAZON}/search", params={"q": "chopin"})).status_code == 501


async def test_favorites_list_and_play(app_env, fake):
    _, svc, http = app_env
    favs = (await http.get(f"/sources/{FAVORITES}/browse")).json()["items"]
    assert [f["name"] for f in favs] == ["Classical Piano", "All '80s"]
    assert all(f["play"] == "favorite" for f in favs)
    r = await http.post(f"/players/{PID}/play-favorite", json={"mid": favs[1]["mid"]})
    assert r.json() == {"preset": 2}
    assert fake.players[PID].station["name"] == "All '80s"


async def test_favorite_position_is_read_fresh(app_env, fake):
    """If favorites are reordered in another app, the right station still plays."""
    from heos_home.heos import fake as fake_mod
    _, _, http = app_env
    favs = (await http.get(f"/sources/{FAVORITES}/browse")).json()["items"]  # now cached
    fake_mod.FAVORITES.reverse()
    try:
        r = await http.post(f"/players/{PID}/play-favorite", json={"mid": favs[1]["mid"]})
        assert r.json() == {"preset": 1}
        assert fake.players[PID].station["name"] == "All '80s"
    finally:
        fake_mod.FAVORITES.reverse()


async def test_unknown_favorite_is_404(app_env):
    _, _, http = app_env
    assert (await http.post(f"/players/{PID}/play-favorite", json={"mid": "nope"})).status_code == 404


async def test_queue_after_stream_plays_queue(app_env, fake):
    _, _, http = app_env
    await http.post(f"/players/{PID}/play-stream", json={"sid": AMAZON, "mid": "library/tracks/#chunk", "name": "Tracks"})
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$4"}], "mode": "replace"})
    assert fake.players[PID].station is None


MY_ALBUM = "library/albums/77415132/#library_tracks-NAME-14 Weeks of Silence"


async def test_my_music_album_tracks_are_queueable(app_env):
    _, _, http = app_env
    page = (await http.get(f"/sources/{AMAZON}/browse", params={"cid": MY_ALBUM})).json()
    assert page["playable"] is False  # no option 21
    track = page["items"][1]
    assert (track["play"], track["album_id"]) == ("queue", None)  # Amazon sends album_id ""


async def test_whole_amazon_album_is_one_command(app_env, fake):
    """The PM7000N accepts an Amazon My Music album by cid, although it lacks option 21."""
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$4"}], "mode": "replace"})
    before = sum("add_to_queue" in c for c in fake.received)
    r = await http.post(f"/players/{PID}/queue", json={"items": [{"sid": AMAZON, "cid": MY_ALBUM}], "mode": "end"})
    assert r.json() == {"added": 1, "mode": "end"}
    assert sum("add_to_queue" in c for c in fake.received) - before == 1
    assert [i["song"] for i in fake.players[PID].queue][-3:] == ["Паранойя", "Трафик", "Знак бесконечность"]


async def test_rejected_container_falls_back_to_tracks(app_env, fake):
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$4"}], "mode": "replace"})
    fake.fail_next["browse/add_to_queue"] = 7  # the amp rejects the whole album
    r = await http.post(f"/players/{PID}/queue", json={"items": [{"sid": AMAZON, "cid": MY_ALBUM}], "mode": "end"})
    assert r.json() == {"added": 3, "mode": "end"}
    assert [i["song"] for i in fake.players[PID].queue][-3:] == ["Паранойя", "Трафик", "Знак бесконечность"]


async def test_fallback_add_and_play_keeps_order(app_env, fake):
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$4"}], "mode": "replace"})
    fake.fail_next["browse/add_to_queue"] = 7
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": AMAZON, "cid": MY_ALBUM}], "mode": "now"})
    pl = fake.players[PID]
    assert pl.queue[pl.current]["song"] == "Паранойя"
    assert [i["song"] for i in pl.queue[pl.current:pl.current + 3]] == ["Паранойя", "Трафик", "Знак бесконечность"]


async def test_folder_without_tracks_gives_clear_error(app_env):
    _, _, http = app_env
    r = await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$9"}], "mode": "end"})
    assert r.status_code == 400
    assert "nothing in this folder" in r.json()["error"]["message"]


async def test_playable_dlna_folder_is_still_one_command(app_env, fake):
    _, _, http = app_env
    before = sum("add_to_queue" in c for c in fake.received)
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$9$1$1"}], "mode": "replace"})
    assert sum("add_to_queue" in c for c in fake.received) - before == 1


# ------------------------------------------------------------ add / remove
import pytest  # noqa: E402

from heos_home.heos import fake as fake_mod  # noqa: E402


@pytest.fixture
def restore_favorites():
    saved = [dict(f) for f in fake_mod.FAVORITES]
    yield
    fake_mod.FAVORITES[:] = saved


async def test_stations_can_be_favorites(app_env):
    _, _, http = app_env
    page = (await http.get(f"/sources/{AMAZON}/browse", params={"cid": "library/albums/#library_albums-NAME-Albums"})).json()
    assert all(i["can_favorite"] for i in page["items"])  # Amazon albums are stations
    menus = (await http.get(f"/sources/{AMAZON}/browse")).json()
    assert not any(i["can_favorite"] for i in menus["items"])  # menus are not


async def test_add_and_remove_favorite(app_env, fake, restore_favorites):
    _, svc, http = app_env
    events = svc.bus.subscribe()
    mid, name = "catalog/albums/B0HRLGGK59/#chunk", "Chopin: The Great Works"
    assert mid not in (await http.get("/favorites")).json()["mids"]
    r = await http.post("/favorites", json={"sid": AMAZON, "mid": mid, "name": name})
    assert r.json() == {"added": name}
    sent = [c for c in fake.received if "set_service_option" in c][-1]
    assert sent == f"heos://browse/set_service_option?sid=13&option=19&mid={mid}&name={name}"
    assert mid in (await http.get("/favorites")).json()["mids"]  # cache refreshed
    favs = (await http.get(f"/sources/{FAVORITES}/browse")).json()["items"]
    assert favs[-1]["name"] == name
    r = await http.delete("/favorites", params={"mid": mid})
    assert r.json() == {"removed": mid}
    assert mid not in (await http.get("/favorites")).json()["mids"]
    types = []
    while not events.empty():
        types.append(events.get_nowait()["type"])
    assert types.count("favorites_changed") == 2


async def test_favorite_the_playing_station(app_env, fake, restore_favorites):
    _, _, http = app_env
    await http.post(f"/players/{PID}/play-stream", json={"sid": AMAZON, "mid": "library/tracks/#chunk", "name": "Tracks"})
    r = await http.post(f"/players/{PID}/favorite-now-playing")
    assert r.status_code == 200
    assert "library/tracks/#chunk" in (await http.get("/favorites")).json()["mids"]


async def test_favorite_now_playing_without_station_fails_cleanly(app_env):
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$4"}], "mode": "replace"})
    r = await http.post(f"/players/{PID}/favorite-now-playing")
    assert r.status_code == 502 and r.json()["error"]["eid"] == 15


async def test_remove_unknown_favorite_is_404(app_env):
    _, _, http = app_env
    assert (await http.delete("/favorites", params={"mid": "nope"})).status_code == 404
