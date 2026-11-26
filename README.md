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
| Transport, volume (slider, − / +, maximum from Settings, default 50), mute, shuffle/repeat | ✅ | F3.1, F3.2 |
| Inputs read from the device, input select | ✅ | F3.3 |
| Now playing + progress, pushed over WebSocket | ✅ | F3.4 |
| Queue: list, add (now/next/end/replace), move, remove, clear, play item | ✅ | F3.5, F3.6 |
| Power on/standby and power state via UPnP ACT (`auto` / `upnp_act` / `none` drivers) | ✅ | F2.1, F2.4, F2.5 |
| Device info, firmware check, HEOS account status | ✅ | F7.1, F8.1, F8.2 |
| Local cache for source logos and input icons | ✅ | §1 (no cloud dependency) |
| Tablet PWA (React + MUI): now playing, volume, transport, queue with drag reorder, inputs, devices, power, settings | ✅ | §7 |
| Queue sort: title / artist / album / random, asc/desc, fewest moves, retry on rejected moves | ✅ | F3.7 |
| DLNA library: servers, folder browsing with paging and breadcrumb, play/queue tracks and folders, search where supported (filter fallback), 10 min cache, pinned folders, last folder | ✅ | F5.1–F5.5, F5.7 |
| Amazon Music (browse, play streams, queue My Music tracks and albums) and HEOS Favorites (play, add, remove) | ✅ | F6.1–F6.5 |
| Local playlists: save queue (name only), list, load (3 modes), edit, sort, rename, duplicate, delete, import/export .m3u8 | ✅ | F4.1–F4.5 |
| HEOS account: sign in / out from Settings, password saved encrypted (optional), automatic re-sign-in after an amp reboot | ✅ | F7.1–F7.3 |
| Re-match unresolved playlist items, phone layout | next | F4.6, phase 4 |

## Tested devices

HEOS firmware updates can change CLI behaviour (risk R5). Record each device
and firmware the service is checked against here.

| Model | Firmware | Network | Checked | What was checked |
| --- | --- | --- | --- | --- |
| Marantz PM7000N | 3.139.175 | Wi-Fi | 2026-11-23 | SSDP discovery, CLI connect, `player/get_players`; power state read and on/off switch via UPnP ACT (port 60006); `move_queue_item` semantics and queue sort; DLNA browse, paging, add folder/track to queue (NAS: search unsupported, eid 12); Amazon browse, Favorites, queue Amazon track and album; station playback confirmed by ear; add/remove HEOS Favorite |

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
HEOS_HOME_DISCOVERY=off .venv/bin/heos-home
# API docs: http://localhost:8080/docs
```

Run against the real amp:

```bash
HEOS_HOME_DATA_DIR=./data HEOS_HOME_HOSTS=192.168.1.50 HEOS_HOME_LOG_LEVEL=DEBUG \
.venv/bin/heos-home
```

`DEBUG` logs every raw CLI line (`heos_home.wire`), which is useful for the
phase-0 protocol checks.

All settings are environment variables; see `src/heos_home/settings.py`.

## Frontend (web/)

React + MUI (Material 3 look), TypeScript, Vite, installable PWA. Needs
Node 20+ (here: Node 22 in `~/.local/node`, so `export PATH=$HOME/.local/node/bin:$PATH`).

```bash
cd web
npm ci
npm run dev        # http://localhost:5173, proxies /api to heos-home on :8080
                   # (another API: HEOS_API=http://127.0.0.1:18081 npm run dev)
npm test           # reducer unit tests (vitest)
npm run build      # -> web/dist, served by heos-home at / automatically
```

Layout: tablet landscape (>= 1000 px) shows three panes: navigation rail,
current view, and now playing + queue. Narrower screens fold now playing into
a "Playing" view. State comes only from the WebSocket (snapshot, then events);
the UI updates optimistically and reconciles with the next event. The volume
slider sends at most every 150 ms while dragging, plus the final value.

## API quick reference

Base path `/api/v1`. Full OpenAPI at `/docs`.

```bash
curl localhost:8080/api/v1/health
curl localhost:8080/api/v1/devices
curl -X PUT  localhost:8080/api/v1/players/-1234/volume    -H 'content-type: application/json' -d '{"level":25}'
curl -X PUT  localhost:8080/api/v1/players/-1234/input     -H 'content-type: application/json' -d '{"input":"inputs/phono"}'
curl -X POST localhost:8080/api/v1/players/-1234/transport -H 'content-type: application/json' -d '{"action":"pause"}'
```

Power (F2): the HEOS CLI keeps answering in standby, so power uses the UPnP
"ACT" service the HEOS app uses (port 60006). `GET /devices/{pid}/power` only
reads; `POST` switches, but does nothing if the amp is already in that state
and refuses (429) a second switch within 10 s, to spare the hardware.

```bash
curl localhost:8080/api/v1/devices/-1234/power
curl -X POST localhost:8080/api/v1/devices/-1234/power -H 'content-type: application/json' -d '{"state":"off"}'
```

Queue sort (F3.7) runs on the service as single `move_queue_item` calls; the
request returns when done, with progress pushed as `queue_sort` events:

```bash
curl -X POST localhost:8080/api/v1/players/-1234/queue/sort -H 'content-type: application/json' -d '{"by":"album","order":"asc"}'
```

WebSocket `/api/v1/ws` sends a `snapshot` first, then events:
`player_state`, `volume`, `now_playing`, `progress`, `queue_changed`,
`play_mode`, `playback_error`, `power`, `queue_sort`, `playlists_changed`, `playlist_load`, `favorites_changed`, `settings`, `player_full`, `device_online`,
`device_offline`, `devices_changed`, `players_changed`, `sources_changed`,
`account`, `connection`. Send `{"type":"ping"}` to get a `pong`.

Images: `image_url` values from the device (source logos, input icons) point
at Denon's cloud. The service rewrites them to `/api/v1/images/{key}`, keeps the
original as `image_url_remote`, downloads each image once into
`<data dir>/cache/images/` and serves it from there (LRU, 100 MB cap). Only URLs
the device returned can be fetched, so the endpoint is not an open proxy. The
cache is safe to delete and does not need backing up.

Errors are JSON `{"error":{"code","message",…}}`: 404 unknown id, 400 bad
value, 503 amp not connected, 504 amp timeout, 502 HEOS `fail` (with `eid`)
or power request failed, 501 no power driver, 429 power switched too recently.

## HEOS account and saved password

Settings → HEOS account signs the amp in or out (`system/sign_in`). With
"Remember", username and password are stored encrypted (Fernet) in
`<data dir>/secrets.json` (mode 600) with the key in a separate file,
`/etc/heos-home/key` (`HEOS_HOME_KEY_FILE`). If that file cannot be created
(development), the key goes to `<data dir>/heos-home.key` and a warning is
logged; then a copy of the data folder contains both, so keep backups private.
After an amp reboot, or a sign-out by another app, the service signs in again;
a rejected password stops the retries until you sign in by hand. Signing out
in this app forgets the saved password. Amazon logins are never handled here:
they live in the HEOS account.

## Deployment (Pi 4, venv + systemd)

```bash
sudo useradd --system --home /opt/heos-home heos-home
sudo mkdir -p /opt/heos-home /etc/heos-home
sudo cp -r . /opt/heos-home && cd /opt/heos-home
sudo python3 -m venv .venv && sudo .venv/bin/pip install .
sudo install -m 600 deploy/env.example /etc/heos-home/env    # edit it
# Key for the saved HEOS password (F7.2). /etc is read-only for the service
# (ProtectSystem=strict), so create it here, readable only by the service user:
sudo sh -c 'umask 077; /opt/heos-home/.venv/bin/python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())" > /etc/heos-home/key'
sudo chown heos-home:heos-home /etc/heos-home/key
sudo cp deploy/heos-home.service /etc/systemd/system/
sudo systemctl daemon-reload && sudo systemctl enable --now heos-home
```

Logs: plain text (`time level logger: message`) to the journal and to
`/var/log/heos-home/heos-home.log`. The file is rotated once a day
(`heos-home.log.2026-11-25`, ...) and 7 days are kept. Change it with
`HEOS_HOME_LOG_FILE` / `HEOS_HOME_LOG_BACKUP_COUNT` in `/etc/heos-home/env`;
`HEOS_HOME_LOG_JSON=on` writes JSON lines instead.

```bash
tail -f /var/log/heos-home/heos-home.log     # or: journalctl -u heos-home -f
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
  services/power.py   power drivers (UPnP ACT) and power state polling
  services/library.py DLNA / Amazon / Favorites browsing
  services/playlists.py local M3U8 playlists and track-source memory
  api/                FastAPI app, REST routes, WebSocket
  storage.py          config.json / state.json, atomic writes
tests/                protocol, client and API tests against the fake device
```
