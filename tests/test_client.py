import asyncio

import pytest

from heos_home.heos.protocol import HeosCommandError, HeosConnectionError, HeosTimeoutError
from tests.conftest import PID, fast_client, wait_for


async def test_registers_for_events_on_connect(fake, client):
    assert "heos://system/register_for_change_events?enable=on" in fake.received


async def test_command_and_response(client):
    msg = await client.command("player/get_players")
    assert msg.payload[0]["pid"] == PID
    assert msg.payload[0]["model"] == "Marantz PM7000N"


async def test_under_process_reply_is_skipped(fake, client):
    msg = await client.command("browse/browse", {"sid": 1024})
    assert msg.payload[0]["type"] == "dlna_server"


async def test_failure_raises(client):
    with pytest.raises(HeosCommandError) as info:
        await client.command("player/set_volume", {"pid": PID, "level": 150})
    assert info.value.eid == 9


async def test_busy_is_retried(fake, client):
    fake.fail_next["player/get_volume"] = 13
    msg = await client.command("player/get_volume", {"pid": PID})
    assert msg.params["level"] == "20"


async def test_timeout(fake, client):
    fake.silent.add("player/get_mute")
    with pytest.raises(HeosTimeoutError):
        await client.command("player/get_mute", {"pid": PID}, timeout=0.2)
    # The connection stays usable afterwards.
    fake.silent.clear()
    assert (await client.command("player/get_mute", {"pid": PID})).params["state"] == "off"


async def test_events_are_dispatched(client):
    events = []

    async def listener(msg):
        events.append(msg)

    client.add_event_listener(listener)
    await client.command("player/set_volume", {"pid": PID, "level": 33})
    await wait_for(lambda: any(e.command == "event/player_volume_changed" for e in events))
    vol = next(e for e in events if e.command == "event/player_volume_changed")
    assert vol.params == {"pid": str(PID), "level": "33", "mute": "off"}


async def test_reconnects_and_reregisters(fake, client):
    states = []

    async def on_conn(connected):
        states.append(connected)

    client.add_connection_listener(on_conn)
    before = fake.received.count("heos://system/register_for_change_events?enable=on")
    await fake.drop_connections()
    await wait_for(lambda: states[-2:] == [False, True])
    assert fake.received.count("heos://system/register_for_change_events?enable=on") == before + 1
    assert (await client.command("system/heart_beat")).result == "success"


async def test_heartbeat_detects_dead_device(fake, client):
    fake.silent.add("system/heart_beat")
    await wait_for(lambda: not client.connected, timeout=4)
    fake.silent.clear()
    await wait_for(lambda: client.connected, timeout=4)


async def test_not_connected_raises():
    c = fast_client(1, host=None)
    with pytest.raises(HeosConnectionError):
        await c.command("system/heart_beat")


async def test_set_host_switches_device(fake):
    c = fast_client(fake.port, host="127.0.0.2")  # nothing listens on .2 for this port
    await c.start()
    try:
        assert not await c.wait_connected(0.3)
        await c.set_host("127.0.0.1")
        assert await c.wait_connected(3)
    finally:
        await c.stop()
