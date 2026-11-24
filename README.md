# HEOS Home Controller

Local-only controller for HEOS devices (Marantz PM7000N first). One Python
service on the Raspberry Pi holds the only HEOS CLI connection and serves a
REST + WebSocket API (and, later, the PWA). See
[HEOS-Home-Controller-Specification.md](HEOS-Home-Controller-Specification.md).

## Status

Phase 1 backend (core):

| Area | Done | Spec |
| --- | --- | --- |
| HEOS CLI client: one socket, serialized commands, "command under process", events, heartbeat 30 s, reconnect 1–30 s backoff, re-register | ✅ | §8 |
| SSDP discovery, manual IPs, device list, IP override, re-discover | ✅ | F1 |
| Transport, volume (level/step), mute, shuffle/repeat | ✅ | F3.1, F3.2 |
| Inputs read from the device, input select | ✅ | F3.3 |
| Now playing + progress, pushed over WebSocket | ✅ | F3.4 |
| Queue: list, add (now/next/end/replace), move, remove, clear, play item | ✅ | F3.5, F3.6 |
| Power driver interface (`none` only; power is on the amp's remote for v1) | ✅ | F2.5 |
| Device info, firmware check, HEOS account status | ✅ | F7.1, F8.1, F8.2 |
| Queue sort, DLNA/Amazon browse + search, playlists, sign-in, PWA | next | F3.7, F4–F7 |

## Tested devices

HEOS firmware updates can change CLI behaviour (risk R5). Record each device
and firmware the service is checked against here.

| Model | Firmware | Network | Checked | What was checked |
| --- | --- | --- | --- | --- |
| Marantz PM7000N | 3.139.175 | Wi-Fi | 2026-11-23 | SSDP discovery, CLI connect, `player/get_players` |

The fake device (`heos_home/heos/fake.py`) reports firmware 3.84.410; that is a
placeholder, not a tested real version.

## Development

Requires Python 3.11+ (Raspberry Pi OS Bookworm ships 3.11).

```bash
python3 -m venv .venv
.venv/bin/pip install -e '.[dev]'
.venv/bin/pytest
```

Run against the fake HEOS device (no amp needed):

```bash
.venv/bin/python -m heos_home.heos.fake --port 21255 &
HEOS_HOME_DATA_DIR=./data HEOS_HOME_HOSTS=127.0.0.1 HEOS_HOME_HEOS_PORT=21255 \
HEOS_HOME_DISCOVERY=off HEOS_HOME_LOG_JSON=off .venv/bin/heos-home
# API docs: http://localhost:8080/docs
```

Run against the real amp:

```bash
HEOS_HOME_DATA_DIR=./data HEOS_HOME_HOSTS=192.168.1.50 HEOS_HOME_LOG_LEVEL=DEBUG \
HEOS_HOME_LOG_JSON=off .venv/bin/heos-home
```

`DEBUG` logs every raw CLI line (`heos_home.wire`), which is useful for the
phase-0 protocol checks.

All settings are environment variables; see `src/heos_home/settings.py`.

## API quick reference

Base path `/api/v1`. Full OpenAPI at `/docs`.

```bash
curl localhost:8080/api/v1/health
curl localhost:8080/api/v1/devices
curl -X PUT  localhost:8080/api/v1/players/-1234/volume    -H 'content-type: application/json' -d '{"level":25}'
curl -X PUT  localhost:8080/api/v1/players/-1234/input     -H 'content-type: application/json' -d '{"input":"inputs/phono"}'
curl -X POST localhost:8080/api/v1/players/-1234/transport -H 'content-type: application/json' -d '{"action":"pause"}'
```

WebSocket `/api/v1/ws` sends a `snapshot` first, then events:
`player_state`, `volume`, `now_playing`, `progress`, `queue_changed`,
`play_mode`, `playback_error`, `player_full`, `device_online`,
`device_offline`, `devices_changed`, `players_changed`, `sources_changed`,
`account`, `connection`. Send `{"type":"ping"}` to get a `pong`.

Errors are JSON `{"error":{"code","message",…}}`: 404 unknown id, 400 bad
value, 503 amp not connected, 504 amp timeout, 502 HEOS `fail` (with `eid`),
501 power not supported.

## Deployment (Pi 4, venv + systemd)

```bash
sudo useradd --system --home /opt/heos-home heos-home
sudo mkdir -p /opt/heos-home /etc/heos-home
sudo cp -r . /opt/heos-home && cd /opt/heos-home
sudo python3 -m venv .venv && sudo .venv/bin/pip install .
sudo install -m 600 deploy/env.example /etc/heos-home/env    # edit it
sudo cp deploy/heos-home.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now heos-home
```

## Layout

```text
src/heos_home/
  heos/protocol.py    wire format, escaping, errors
  heos/client.py      the single CLI connection
  heos/discovery.py   SSDP M-SEARCH
  heos/fake.py        fake HEOS device for tests and UI work
  services/players.py player state cache, events, player and queue commands
  services/devices.py discovery, overrides, choice of CLI host
  services/power.py   power driver interface
  api/                FastAPI app, REST routes, WebSocket
  storage.py          config.json / state.json, atomic writes
tests/                protocol, client and API tests against the fake device
```
