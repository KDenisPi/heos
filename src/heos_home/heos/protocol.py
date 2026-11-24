"""HEOS CLI wire format: command encoding and response parsing.

Commands are ASCII lines ``heos://group/command?a=1&b=2\\r\\n``; responses are
JSON objects terminated by ``\\r\\n``. In both directions only the characters
``&``, ``=`` and ``%`` are escaped (``%26``, ``%3D``, ``%25``), so we decode
every string we receive and re-encode every value we send. That round trip is
lossless, and the rest of the code base works with plain, decoded strings.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

DELIMITER = b"\r\n"
UNDER_PROCESS = "command under process"

_ENCODE = (("%", "%25"), ("&", "%26"), ("=", "%3D"))
_DECODE = (("%26", "&"), ("%3D", "="), ("%3d", "="), ("%25", "%"))


def encode_value(value: Any) -> str:
    """Escape a single attribute value for a HEOS command."""
    if isinstance(value, bool):
        value = "on" if value else "off"
    text = str(value)
    for char, escaped in _ENCODE:
        text = text.replace(char, escaped)
    return text


def decode_value(text: str) -> str:
    """Undo HEOS escaping of a string received from the device."""
    if "%" not in text:
        return text
    for escaped, char in _DECODE:
        text = text.replace(escaped, char)
    return text


def _decode_tree(obj: Any) -> Any:
    if isinstance(obj, str):
        return decode_value(obj)
    if isinstance(obj, list):
        return [_decode_tree(item) for item in obj]
    if isinstance(obj, dict):
        return {key: _decode_tree(val) for key, val in obj.items()}
    return obj


def build_command(command: str, params: dict[str, Any] | None = None) -> str:
    """Build the wire text of a command, without the trailing delimiter.

    ``None`` values are skipped, so optional attributes can be passed directly.
    Per the spec, ``url`` must be the last attribute; it is moved to the end.
    """
    text = f"heos://{command}"
    if params:
        items = [(k, v) for k, v in params.items() if v is not None]
        items.sort(key=lambda kv: kv[0] == "url")
        if items:
            text += "?" + "&".join(f"{k}={encode_value(v)}" for k, v in items)
    return text


def parse_message(message: str) -> dict[str, str]:
    """Parse the ``heos.message`` field (``pid=1&state=play``) into a dict.

    Bare words such as ``signed_in`` become keys with an empty value.
    """
    result: dict[str, str] = {}
    if not message:
        return result
    for part in message.split("&"):
        if not part:
            continue
        key, sep, value = part.partition("=")
        result[decode_value(key.strip())] = decode_value(value.strip()) if sep else ""
    return result


ERROR_CODES = {
    1: "Unrecognized command",
    2: "Invalid ID",
    3: "Wrong number of command arguments",
    4: "Requested data not available",
    5: "Resource currently not available",
    6: "Invalid credentials",
    7: "Command could not be executed",
    8: "User not logged in",
    9: "Parameter out of range",
    10: "User not found",
    11: "Internal error",
    12: "System error",
    13: "Processing previous command",
    14: "Media can't be played",
    15: "Option not supported",
    16: "Too many commands in message queue to process",
    17: "Reached skip limit",
}


class HeosError(Exception):
    """Base error for HEOS communication."""


class HeosConnectionError(HeosError):
    """The CLI socket is not connected or was lost."""


class HeosTimeoutError(HeosError):
    """No response arrived in time."""


class HeosCommandError(HeosError):
    """The device answered ``result=fail``."""

    def __init__(self, command: str, eid: int | None, text: str, syserrno: str | None = None):
        self.command = command
        self.eid = eid
        self.text = text
        self.syserrno = syserrno
        label = ERROR_CODES.get(eid or 0, "Unknown error")
        super().__init__(f"{command}: {label} (eid={eid}): {text}")


@dataclass(slots=True)
class HeosMessage:
    """One decoded JSON object received from the CLI."""

    command: str
    result: str | None
    message: str
    params: dict[str, str]
    payload: Any = None
    options: Any = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def is_event(self) -> bool:
        return self.command.startswith("event/")

    @property
    def is_under_process(self) -> bool:
        return UNDER_PROCESS in self.message

    @property
    def failed(self) -> bool:
        return self.result == "fail"

    def raise_for_error(self) -> None:
        if not self.failed:
            return
        eid_text = self.params.get("eid")
        try:
            eid = int(eid_text) if eid_text is not None else None
        except ValueError:
            eid = None
        raise HeosCommandError(
            self.command, eid, self.params.get("text", self.message), self.params.get("syserrno")
        )

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> "HeosMessage":
        heos = data.get("heos") or {}
        # Real devices (and the spec) sometimes pad command names with spaces.
        command = str(heos.get("command", "")).strip()
        message = str(heos.get("message", "") or "")
        return cls(
            command=command,
            result=(str(heos["result"]).strip() if "result" in heos else None),
            message=message,
            params=parse_message(message),
            payload=_decode_tree(data.get("payload")),
            options=data.get("options"),
            raw=data,
        )
