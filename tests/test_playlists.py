import json

from heos_home.services.playlists import PlaylistItem, parse_m3u8, render_m3u8, slugify
from tests.conftest import PID

DLNA, AMAZON = 111, 13
MY_ALBUM = "library/albums/77415132/#library_tracks-NAME-14 Weeks of Silence"


# ----------------------------------------------------------- file format
def test_m3u8_round_trip():
    items = [
        PlaylistItem("Cantata BWV 140: I. Chorus", "J.S. Bach", "Cantatas Vol. 1", 111, "64$1$3", "64$1$3$1", "http://x/c.jpg"),
        PlaylistItem("Lost track", "Someone", "", None, None, "A0$9"),
    ]
    text = render_m3u8("Bach & Friends", items)
    assert text.startswith("#EXTM3U\n#PLAYLIST:Bach & Friends\n#EXTINF:-1,J.S. Bach - Cantata BWV 140: I. Chorus\n")
    assert "heos://111/64%241%243/64%241%243%241" in text
    assert "heos://unresolved/A0%249" in text
    name, parsed = parse_m3u8(text, "x")
    assert name == "Bach & Friends"
    assert parsed == items
    assert [p.resolved for p in parsed] == [True, False]


def test_parse_plain_m3u_from_another_player():
    name, items = parse_m3u8("#EXTM3U\n#EXTINF:200,Miles Davis - So What\n/music/so_what.flac\nother.mp3\n", "Imported")
    assert name == "Imported"
    assert [(i.artist, i.title, i.resolved) for i in items] == [("Miles Davis", "So What", False), ("", "other", False)]


def test_slugify_keeps_unicode():
    assert slugify("Bach Cantatas") == "bach-cantatas"
    assert slugify("Лучшие песни!") == "лучшие-песни"
    assert slugify("  ***  ") == "playlist"


# ------------------------------------------------------------ save queue
async def build_queue(http):
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$4"}], "mode": "replace"})
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$3", "mid": "64$1$3$2"}], "mode": "end"})


async def test_save_queue_with_name_only(app_env, settings):
    _, _, http = app_env
    await build_queue(http)
    r = await http.post("/playlists", json={"name": "Evening Jazz", "from_queue": PID})
    assert r.status_code == 200, r.text
    assert r.json()["count"] == 4 and r.json()["unresolved"] == 0 and r.json()["id"] == "evening-jazz"
    text = (settings.data_dir / "playlists" / "evening-jazz.m3u8").read_text()
    assert "#PLAYLIST:Evening Jazz" in text and text.count("#EXTHEOS:") == 4
    pl = (await http.get("/playlists/evening-jazz")).json()
    assert [i["title"] for i in pl["items"]] == ["So What", "Freddie Freeloader", "Blue in Green", "Cantata BWV 140: II. Recitative"]
    assert pl["items"][3] == {"title": "Cantata BWV 140: II. Recitative", "artist": "J.S. Bach", "album": "Cantatas Vol. 1",
                              "sid": DLNA, "cid": "64$1$3", "mid": "64$1$3$2", "image_url": "", "resolved": True}


async def test_queue_from_other_app_resolved_via_album(app_env, fake):
    """Tracks queued by the official app: traced through their album_id on the DLNA server."""
    _, svc, http = app_env
    pl = fake.players[PID]
    pl.queue = [dict(t) for t in fake._tracks_for("64$1$3", None)]
    pl.renumber()
    assert svc.playlists.sources.get("64$1$3$1") is None
    r = await http.post("/playlists", json={"name": "From the app", "from_queue": PID})
    assert r.json()["unresolved"] == 0


async def test_untraceable_tracks_are_saved_unresolved_and_skipped(app_env, fake):
    _, _, http = app_env
    await build_queue(http)
    fake.players[PID].queue.append({"song": "Mystery", "album": "", "artist": "X", "image_url": "",
                                    "mid": "B00UNKNOWN", "qid": 0, "album_id": "", "duration": 1})
    fake.players[PID].renumber()
    body = (await http.post("/playlists", json={"name": "Mixed", "from_queue": PID})).json()
    assert body["unresolved"] == 1
    await http.delete(f"/players/{PID}/queue")
    r = await http.post("/playlists/mixed/load", json={"pid": PID, "mode": "replace"})
    assert r.json()["tracks"] == 4 and r.json()["skipped"] == 1
    assert len(fake.players[PID].queue) == 4


async def test_amazon_tracks_remembered_when_queued_here(app_env, fake):
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": AMAZON, "cid": MY_ALBUM}], "mode": "replace"})
    for it in fake.players[PID].queue:  # the real amp reports album_id "" for Amazon tracks
        it["album_id"] = ""
    body = (await http.post("/playlists", json={"name": "Zemfira", "from_queue": PID})).json()
    assert body["count"] == 3 and body["unresolved"] == 0


async def test_duplicate_name_is_409(app_env):
    _, _, http = app_env
    await http.post("/playlists", json={"name": "Jazz"})
    r = await http.post("/playlists", json={"name": "jazz"})
    assert r.status_code == 409
    assert "already exists" in r.json()["error"]["message"]


# ------------------------------------------------------------------ load
async def test_load_modes(app_env, fake):
    _, _, http = app_env
    await build_queue(http)
    await http.post("/playlists", json={"name": "Four", "from_queue": PID})
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$9$1$1", "mid": "64$9$1$1$1"}], "mode": "replace"})
    r = await http.post("/playlists/four/load", json={"pid": PID, "mode": "append"})
    assert r.json()["mode"] == "end"
    songs = [i["song"] for i in fake.players[PID].queue]
    assert songs == ["Track 001", "So What", "Freddie Freeloader", "Blue in Green", "Cantata BWV 140: II. Recitative"]
    await http.post("/playlists/four/load", json={"pid": PID, "mode": "replace"})
    assert [i["song"] for i in fake.players[PID].queue] == songs[1:]
    assert fake.players[PID].queue[fake.players[PID].current]["song"] == "So What"


async def test_whole_folder_loads_as_one_command(app_env, fake):
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$9$1$1"}], "mode": "replace"})
    await http.post("/playlists", json={"name": "Big", "from_queue": PID})
    before = sum("add_to_queue" in c for c in fake.received)
    r = await http.post("/playlists/big/load", json={"pid": PID, "mode": "replace"})
    assert r.json() == {"id": "big", "mode": "replace", "tracks": 120, "skipped": 0, "commands": 1, "moves": 0}
    assert sum("add_to_queue" in c for c in fake.received) - before == 1
    assert len(fake.players[PID].queue) == 120


async def test_load_reports_progress(app_env):
    _, svc, http = app_env
    await build_queue(http)
    await http.post("/playlists", json={"name": "Four", "from_queue": PID})
    queue = svc.bus.subscribe()
    await http.post("/playlists/four/load", json={"pid": PID, "mode": "end"})
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    progress = [e["data"] for e in events if e["type"] == "playlist_load"]
    assert progress[0]["done"] == 0 and progress[-1]["done"] == progress[-1]["total"]


# ------------------------------------------------------------ management
async def test_rename_duplicate_delete(app_env, settings):
    _, _, http = app_env
    await http.post("/playlists", json={"name": "Old Name"})
    r = await http.patch("/playlists/old-name", json={"name": "New Name"})
    assert r.json()["id"] == "new-name" and r.json()["name"] == "New Name"
    files = sorted(p.name for p in (settings.data_dir / "playlists").iterdir())
    assert files == ["new-name.m3u8"]
    dup = (await http.post("/playlists/new-name/duplicate")).json()
    assert dup["name"] == "New Name (copy)"
    assert [p["name"] for p in (await http.get("/playlists")).json()["playlists"]] == ["New Name", "New Name (copy)"]
    assert (await http.delete("/playlists/new-name")).json() == {"deleted": "new-name"}
    assert (await http.get("/playlists/new-name")).status_code == 404


async def test_edit_items_and_sort(app_env):
    _, _, http = app_env
    await build_queue(http)
    await http.post("/playlists", json={"name": "Edit", "from_queue": PID})
    pl = (await http.get("/playlists/edit")).json()
    items = pl["items"][1:][::-1]  # remove the first, reverse the rest
    r = await http.patch("/playlists/edit", json={"items": items})
    assert [i["title"] for i in r.json()["items"]] == ["Cantata BWV 140: II. Recitative", "Blue in Green", "Freddie Freeloader"]
    r = await http.post("/playlists/edit/sort", json={"by": "title"})
    assert [i["title"] for i in r.json()["items"]] == ["Blue in Green", "Cantata BWV 140: II. Recitative", "Freddie Freeloader"]


async def test_export_and_import(app_env):
    _, _, http = app_env
    await build_queue(http)
    await http.post("/playlists", json={"name": "Евгений Онегин", "from_queue": PID})
    r = await http.get("/playlists/евгений-онегин/export")
    assert r.status_code == 200
    assert "filename*=UTF-8''%D0%B5" in r.headers["content-disposition"]
    text = r.text
    r = await http.post("/playlists/import", params={"name": "Imported copy"}, content=text.encode())
    assert r.json()["count"] == 4 and r.json()["unresolved"] == 0


async def test_files_copied_in_by_hand_appear(app_env, settings):
    _, _, http = app_env
    (settings.data_dir / "playlists" / "hand-made.m3u8").write_text("#EXTM3U\n#PLAYLIST:Hand Made\n#EXTINF:-1,A - B\nb.mp3\n")
    assert {p["name"] for p in (await http.get("/playlists")).json()["playlists"]} == {"Hand Made"}


async def test_path_traversal_rejected(app_env):
    _, _, http = app_env
    assert (await http.get("/playlists/..%2Fconfig")).status_code == 404


# ------------------------------------------------- loading on a slow amp
def amp_like(fake, apply=0.02, backlog=5):
    """Make the fake behave like the PM7000N: adds applied later, small backlog (eid 9 beyond it)."""
    fake.add_apply_seconds = apply
    fake.add_backlog = backlog


async def sorted_big_box(http, n=12):
    """A playlist of n tracks from the 120-track folder, in a different order (not a whole container)."""
    items = [{"title": f"Track {i:03d}", "artist": "Various", "album": "Big Box", "sid": DLNA,
              "cid": "64$9$1$1", "mid": f"64$9$1$1${i}", "image_url": "", "resolved": True}
             for i in range(n, 0, -1)]
    await http.post("/playlists", json={"name": "Reverse"})
    await http.patch("/playlists/reverse", json={"items": items})
    return [i["title"] for i in items]


async def test_load_many_single_tracks_on_a_slow_amp(app_env, fake, monkeypatch):
    """Regression: 48 single adds overran the amp's backlog (eid 9) and the load stopped at 15."""
    import heos_home.services.playlists as pl_mod
    monkeypatch.setattr(pl_mod, "ADD_GAP", 0.03)
    amp_like(fake)
    _, _, http = app_env
    titles = await sorted_big_box(http)
    r = await http.post("/playlists/reverse/load", json={"pid": PID, "mode": "replace"})
    assert r.status_code == 200, r.text
    assert [i["song"] for i in fake.players[PID].queue] == titles
    assert fake.players[PID].queue[fake.players[PID].current]["song"] == titles[0]
    assert fake.backlog_rejections == 0


async def test_whole_container_in_other_order_is_one_add_plus_moves(app_env, fake, monkeypatch):
    """The Zauberflöte case: all tracks of one NAS container, sorted differently."""
    import heos_home.services.playlists as pl_mod
    import heos_home.services.players as players_mod
    monkeypatch.setattr(players_mod, "MOVE_GAP", 0.0)
    _, _, http = app_env
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$4"}], "mode": "replace"})
    await http.post("/playlists", json={"name": "Blue", "from_queue": PID})
    pl = (await http.get("/playlists/blue")).json()
    await http.patch("/playlists/blue", json={"items": pl["items"][::-1]})  # reversed: not container order
    amp_like(fake)  # from here on the fake applies adds late, like the amp
    before = sum("add_to_queue" in c for c in fake.received)
    r = await http.post("/playlists/blue/load", json={"pid": PID, "mode": "replace"})
    assert r.status_code == 200, r.text
    assert sum("add_to_queue" in c for c in fake.received) - before == 1
    assert r.json()["moves"] >= 1
    assert [i["song"] for i in fake.players[PID].queue] == ["Blue in Green", "Freddie Freeloader", "So What"]


async def test_add_and_play_puts_the_playlist_after_the_current_track(app_env, fake, monkeypatch):
    import heos_home.services.playlists as pl_mod
    import heos_home.services.players as players_mod
    monkeypatch.setattr(pl_mod, "ADD_GAP", 0.0)
    monkeypatch.setattr(players_mod, "MOVE_GAP", 0.0)
    _, _, http = app_env
    titles = await sorted_big_box(http, n=4)
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$4"}], "mode": "replace"})
    await http.post(f"/players/{PID}/queue/play", json={"qid": 2})  # Freddie Freeloader is playing
    r = await http.post("/playlists/reverse/load", json={"pid": PID, "mode": "now"})
    assert r.status_code == 200, r.text
    pl = fake.players[PID]
    assert [i["song"] for i in pl.queue] == ["So What", "Freddie Freeloader", *titles, "Blue in Green"]
    assert pl.queue[pl.current]["song"] == titles[0]


async def test_load_end_does_not_start_playback(app_env, fake, monkeypatch):
    import heos_home.services.playlists as pl_mod
    monkeypatch.setattr(pl_mod, "ADD_GAP", 0.0)
    _, _, http = app_env
    titles = await sorted_big_box(http, n=3)
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": DLNA, "cid": "64$1$4"}], "mode": "end"})
    await http.post(f"/players/{PID}/transport", json={"action": "stop"})
    state_before = fake.players[PID].state
    await http.post("/playlists/reverse/load", json={"pid": PID, "mode": "end"})
    assert [i["song"] for i in fake.players[PID].queue][-3:] == titles
    assert fake.players[PID].state == state_before


async def test_load_sends_one_queue_changed(app_env, fake, monkeypatch):
    import heos_home.services.playlists as pl_mod
    monkeypatch.setattr(pl_mod, "ADD_GAP", 0.0)
    _, svc, http = app_env
    await sorted_big_box(http, n=5)
    events = svc.bus.subscribe()
    await http.post("/playlists/reverse/load", json={"pid": PID, "mode": "replace"})
    from tests.conftest import wait_for
    import asyncio
    await asyncio.sleep(0.2)  # let late amp events arrive
    types = []
    while not events.empty():
        types.append(events.get_nowait()["type"])
    assert types.count("queue_changed") == 1
