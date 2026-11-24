from heos_home.heos.protocol import (
    HeosCommandError,
    HeosMessage,
    build_command,
    decode_value,
    encode_value,
    parse_message,
)
import pytest


def test_encode_round_trip():
    text = "Rock & Roll = 100%"
    assert encode_value(text) == "Rock %26 Roll %3D 100%25"
    assert decode_value(encode_value(text)) == text


def test_ids_with_dollar_signs_pass_through():
    assert encode_value("64$1$3") == "64$1$3"


def test_build_command_skips_none_and_puts_url_last():
    assert build_command("player/get_players") == "heos://player/get_players"
    cmd = build_command("browse/play_stream", {"url": "http://x/a?b=1&c=2", "pid": 1, "sid": None})
    assert cmd == "heos://browse/play_stream?pid=1&url=http://x/a?b%3D1%26c%3D2"


def test_bool_values_become_on_off():
    assert build_command("player/set_mute", {"pid": 1, "state": True}) == "heos://player/set_mute?pid=1&state=on"


def test_parse_message_handles_bare_words_and_spaces():
    assert parse_message("signed_in&un=a%26b@x.com") == {"signed_in": "", "un": "a&b@x.com"}
    assert parse_message("eid=2&text=ID not valid&pid=1") == {"eid": "2", "text": "ID not valid", "pid": "1"}
    assert parse_message("") == {}


def test_message_from_json_strips_command_and_decodes_payload():
    msg = HeosMessage.from_json({
        "heos": {"command": " event/player_now_playing_changed ", "message": "pid=5"},
    })
    assert msg.is_event and msg.command == "event/player_now_playing_changed"
    assert msg.params == {"pid": "5"}

    msg = HeosMessage.from_json({
        "heos": {"command": "browse/browse", "result": "success", "message": "sid=1"},
        "payload": [{"name": "Simon %26 Garfunkel", "cid": "a%3Db"}],
    })
    assert msg.payload == [{"name": "Simon & Garfunkel", "cid": "a=b"}]


def test_failure_raises_with_eid():
    msg = HeosMessage.from_json({
        "heos": {"command": "player/set_volume", "result": "fail", "message": "eid=9&text=Out of range&pid=1"},
    })
    with pytest.raises(HeosCommandError) as info:
        msg.raise_for_error()
    assert info.value.eid == 9
