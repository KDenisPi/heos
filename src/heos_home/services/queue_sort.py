"""Queue sort planning (F3.7).

HEOS has no sort command, so a sort is a series of ``player/move_queue_item``
calls. Semantics measured on a PM7000N (firmware 3.139.175):

* queue ids are positions 1..n and are renumbered after every change;
* moving one item to ``dqid`` takes it out and puts it at position ``dqid``
  (the same whether it moves up or down);
* several ``sqid`` values move as a block in their *queue* order, not in the
  order listed, so a whole sort cannot be done in one command.

``plan_moves`` therefore produces single-item moves. Items that already form
the longest run in the right relative order stay put; only the others move,
so an almost-sorted queue needs only a few commands.

``get_queue`` returns only song, artist, album and ids: no track number,
duration or date added. Ties are broken by the current position, so the
tracks of one album keep their current (usually track) order.
"""

from __future__ import annotations

import random
from bisect import bisect_left
from collections.abc import Callable, Sequence
from typing import Any

SORT_KEYS = ("title", "artist", "album", "random")
UNSUPPORTED_KEYS = {
    "track": "track numbers",
    "duration": "durations",
    "date_added": "the date added",
}


def _text(value: Any) -> tuple[int, str]:
    """Case-insensitive text key; empty values sort last."""
    text = str(value or "").strip().casefold()
    return (1, "") if not text else (0, text)


def sort_order(items: Sequence[dict[str, Any]], by: str, descending: bool = False,
               rng: random.Random | None = None) -> list[int]:
    """Return the indices of ``items`` in their new order."""
    if by in UNSUPPORTED_KEYS:
        raise ValueError(f"HEOS does not report {UNSUPPORTED_KEYS[by]} for queue items; "
                         f"sort by one of {', '.join(SORT_KEYS)}")
    if by not in SORT_KEYS:
        raise ValueError(f"sort key must be one of {', '.join(SORT_KEYS)}")
    indices = list(range(len(items)))
    if by == "random":
        (rng or random.Random()).shuffle(indices)
        return indices

    keyfuncs: dict[str, Callable[[dict[str, Any]], tuple[Any, ...]]] = {
        "title": lambda it: (_text(it.get("song")), _text(it.get("artist")), _text(it.get("album"))),
        "artist": lambda it: (_text(it.get("artist")), _text(it.get("album"))),
        "album": lambda it: (_text(it.get("album")), _text(it.get("artist"))),
    }
    keyfunc = keyfuncs[by]
    # Stable sort on the key, so ties keep their current order. Descending
    # reverses the key order but still keeps ties (album tracks) in order.
    groups = sorted(indices, key=lambda i: keyfunc(items[i]))
    if not descending:
        return groups
    result: list[int] = []
    run: list[int] = []
    for i in groups:
        if run and keyfunc(items[run[0]]) != keyfunc(items[i]):
            result[:0] = run
            run = []
        run.append(i)
    result[:0] = run
    return result


def _longest_increasing(seq: Sequence[int]) -> set[int]:
    """Positions in ``seq`` forming one longest strictly increasing subsequence."""
    tails: list[int] = []
    tails_at: list[int] = []
    parent = [-1] * len(seq)
    for i, value in enumerate(seq):
        k = bisect_left(tails, value)
        if k == len(tails):
            tails.append(value)
            tails_at.append(i)
        else:
            tails[k] = value
            tails_at[k] = i
        parent[i] = tails_at[k - 1] if k > 0 else -1
    keep: set[int] = set()
    i = tails_at[-1] if tails_at else -1
    while i != -1:
        keep.add(i)
        i = parent[i]
    return keep


def plan_moves(current: Sequence[Any], target: Sequence[Any]) -> list[tuple[int, int]]:
    """Single-item moves ``(sqid, dqid)`` that turn ``current`` into ``target``.

    Both are sequences of the same unique identifiers. Positions are 1-based and
    refer to the queue as it is right before each move, matching HEOS.
    """
    if len(current) != len(target) or set(current) != set(target) or len(set(current)) != len(current):
        raise ValueError("current and target must hold the same unique items")
    rank = {item: k for k, item in enumerate(target)}
    stay = {current[i] for i in _longest_increasing([rank[x] for x in current])}
    cur = list(current)
    moves: list[tuple[int, int]] = []
    for k, item in enumerate(target):
        if item in stay:
            continue
        src = cur.index(item)
        cur.pop(src)
        # Put it right after its predecessor in the target order (or first).
        dst = 0 if k == 0 else cur.index(target[k - 1]) + 1
        cur.insert(dst, item)
        if src != dst:
            moves.append((src + 1, dst + 1))
        stay.add(item)
    assert cur == list(target)
    return moves
