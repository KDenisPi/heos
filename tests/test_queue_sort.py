import random

import pytest

from heos_home.services.queue_sort import plan_moves, sort_order
from tests.conftest import PID


def apply_heos_moves(items, moves):
    """Replay moves with the semantics measured on the PM7000N."""
    q = list(items)
    for sqid, dqid in moves:
        item = q.pop(sqid - 1)
        q.insert(dqid - 1, item)
    return q


@pytest.mark.parametrize("seed", range(200))
def test_plan_moves_reaches_target(seed):
    rng = random.Random(seed)
    n = rng.randint(0, 40)
    current = list(range(n))
    target = current[:]
    rng.shuffle(target)
    moves = plan_moves(current, target)
    assert apply_heos_moves(current, moves) == target
    assert len(moves) <= max(0, n - 1)


def test_sorted_queue_needs_no_moves():
    assert plan_moves([1, 2, 3, 4], [1, 2, 3, 4]) == []


def test_one_misplaced_item_needs_one_move():
    # The LIS keeps A..D in place; only E moves (a naive approach needs 4 moves).
    assert len(plan_moves(list("EABCD"), list("ABCDE"))) == 1
    assert len(plan_moves(list("BCDEA"), list("ABCDE"))) == 1


def test_plan_moves_rejects_mismatched_items():
    with pytest.raises(ValueError):
        plan_moves([1, 2], [1, 3])


ITEMS = [
    {"song": "So What", "artist": "Miles Davis", "album": "Kind of Blue"},
    {"song": "aria", "artist": "Bach", "album": "Cantatas"},
    {"song": "Chorus", "artist": "Bach", "album": "Cantatas"},
    {"song": "", "artist": "", "album": ""},
    {"song": "Blue in Green", "artist": "Miles Davis", "album": "Kind of Blue"},
]


def test_sort_by_title_is_case_insensitive_and_empty_last():
    order = sort_order(ITEMS, "title")
    assert [ITEMS[i]["song"] for i in order] == ["aria", "Blue in Green", "Chorus", "So What", ""]


def test_sort_by_album_keeps_track_order_within_album():
    order = sort_order(ITEMS, "album")
    assert [ITEMS[i]["song"] for i in order] == ["aria", "Chorus", "So What", "Blue in Green", ""]


def test_descending_reverses_groups_but_not_ties():
    order = sort_order(ITEMS, "artist", descending=True)
    assert [ITEMS[i]["song"] for i in order] == ["", "So What", "Blue in Green", "aria", "Chorus"]


def test_random_is_a_permutation():
    order = sort_order(ITEMS, "random", rng=random.Random(1))
    assert sorted(order) == list(range(len(ITEMS)))


@pytest.mark.parametrize("key", ["track", "duration", "date_added"])
def test_unavailable_keys_explain_why(key):
    with pytest.raises(ValueError, match="does not report"):
        sort_order(ITEMS, key)


# ----------------------------------------------------------------- API level
async def fill(http):
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$4"}], "mode": "replace"})
    await http.post(f"/players/{PID}/queue", json={"items": [{"sid": 111, "cid": "64$1$3"}], "mode": "end"})


async def songs(http):
    return [i["song"] for i in (await http.get(f"/players/{PID}/queue")).json()["items"]]


async def test_sort_by_title_on_device(app_env, fake):
    _, svc, http = app_env
    await fill(http)
    before_moves = sum(1 for c in fake.received if "move_queue_item" in c)
    queue = svc.bus.subscribe()
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["items"] == 6 and body["moves"] >= 1
    assert await songs(http) == sorted(await songs(http), key=str.casefold)
    assert sum(1 for c in fake.received if "move_queue_item" in c) - before_moves == body["moves"]

    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    # Many moves, but a single queue_changed for the UI.
    assert [e["type"] for e in events].count("queue_changed") == 1
    assert events[-2]["type"] == "queue_sort" and events[-2]["data"]["state"] == "done"


async def test_sort_by_album_desc_keeps_tracks_in_order(app_env):
    _, _, http = app_env
    await fill(http)
    await http.post(f"/players/{PID}/queue/sort", json={"by": "album", "order": "desc"})
    assert await songs(http) == [
        "So What", "Freddie Freeloader", "Blue in Green",
        "Cantata BWV 140: I. Chorus", "Cantata BWV 140: II. Recitative", "Cantata BWV 140: III. Aria",
    ]


async def test_sort_already_sorted_sends_no_moves(app_env, fake):
    _, _, http = app_env
    await fill(http)
    await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    assert r.json()["moves"] == 0


async def test_sort_unavailable_key_is_400(app_env):
    _, _, http = app_env
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "duration"})
    assert r.status_code == 400
    assert "does not report durations" in r.json()["error"]["message"]


async def test_sort_detects_concurrent_change(app_env, fake, monkeypatch):
    _, svc, http = app_env
    await fill(http)
    original = svc.players._cmd

    async def meddling(command, **params):
        result = await original(command, **params)
        if command == "player/move_queue_item":
            fake.players[PID].queue.pop()  # someone removes a track mid-sort
            fake.players[PID].renumber()
        return result

    monkeypatch.setattr(svc.players, "_cmd", meddling)
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    assert r.status_code in (409, 502)


async def test_sort_recovers_from_rejected_move(app_env, fake):
    """The PM7000N once answered eid 12 to a move mid-sort; the sort must re-plan and finish."""
    _, _, http = app_env
    await fill(http)
    fake.fail_next["player/move_queue_item"] = 12  # one rejection: retried, not a failure
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    assert r.status_code == 200, r.text
    assert await songs(http) == sorted(await songs(http), key=str.casefold)


async def test_sort_survives_a_busy_amp(app_env, fake, monkeypatch):
    """The PM7000N rejects a move (eid 12) that arrives while it is still applying the previous one."""
    import heos_home.services.players as players_mod
    monkeypatch.setattr(players_mod, "MOVE_GAP", 0.0)  # no pacing: every move after the first hits "busy"
    monkeypatch.setattr(players_mod, "MOVE_RETRY_DELAYS", (0.06, 0.06, 0.06, 0.06, 0.06))
    _, _, http = app_env
    await fill(http)
    fake.move_busy_seconds = 0.05
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    assert r.status_code == 200, r.text
    assert await songs(http) == sorted(await songs(http), key=str.casefold)
    assert fake.busy_rejections >= 1  # it really was busy, and the sort still finished


async def test_pacing_avoids_busy_rejections(app_env, fake, monkeypatch):
    import heos_home.services.players as players_mod
    monkeypatch.setattr(players_mod, "MOVE_GAP", 0.06)
    _, _, http = app_env
    await fill(http)
    fake.move_busy_seconds = 0.05
    assert (await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})).status_code == 200
    assert fake.busy_rejections == 0


async def test_drag_move_retries_when_busy(app_env, fake, monkeypatch):
    import heos_home.services.players as players_mod
    monkeypatch.setattr(players_mod, "MOVE_RETRY_DELAYS", (0.06,) * 5)
    _, _, http = app_env
    await fill(http)
    fake.move_busy_seconds = 0.05
    assert (await http.post(f"/players/{PID}/queue/move", json={"qids": [6], "to": 1})).status_code == 200
    assert (await http.post(f"/players/{PID}/queue/move", json={"qids": [6], "to": 2})).status_code == 200
    assert fake.busy_rejections == 1


async def test_sort_gives_up_after_repeated_rejections(app_env, fake, monkeypatch):
    _, svc, http = app_env
    await fill(http)
    before = await songs(http)
    original = fake._dispatch

    async def always_fail_moves(text, writer):
        if "move_queue_item" in text:
            fake.fail_next["player/move_queue_item"] = 12
        await original(text, writer)

    monkeypatch.setattr(fake, "_dispatch", always_fail_moves)
    import heos_home.services.players as players_mod
    monkeypatch.setattr(players_mod, "MOVE_RETRY_DELAYS", (0.01,) * 5)
    queue = svc.bus.subscribe()
    r = await http.post(f"/players/{PID}/queue/sort", json={"by": "title"})
    assert r.status_code == 502
    assert await songs(http) == before  # nothing moved
    events = []
    while not queue.empty():
        events.append(queue.get_nowait())
    assert any(e["type"] == "queue_sort" and e["data"]["state"] == "failed" for e in events)
