# Marantz PM7000N – Local Control Project (HEOS)

**Goal:** Replace the unreliable Denon HEOS Android app with a self-built local controller (Pi 4 touchscreen / GB10), no cloud.
**Status (2026-11-12):** Research done. Next step: find the undocumented power on/off path (probe endpoints, then sniff the HEOS app).

---

## 1. Protocols on Denon/Marantz gear

| Protocol | Port | Format | Used by |
|---|---|---|---|
| HEOS CLI | TCP 1255 | ASCII cmd + `\r\n`, JSON response, no auth | All HEOS devices incl. PM7000N |
| Denon/Marantz AVR telnet | TCP 23 | ASCII cmd + `\r` (`PWON`, `MV45`, `SICD`) | AVRs (SR/Cinema/NR), Model 30/40n, some players. **Likely NOT PM7000N** |
| Legacy HTTP (goform) | 80 / 8080 | `/goform/formiPhoneAppPower.xml?1+PowerOn` | AVRs (e.g. SR5014) |
| Newer HTTPS web-UI API | 10443 | `/ajax/general/set_config?type=4&data=<MainZone><Power>3</Power></MainZone>` | 2020+ AVRs; untested on PM7000N |

- Discovery: SSDP `ST: urn:schemas-denon-com:device:ACT-Denon:1` (or use a static IP / DHCP reservation).
- AVR telnet accepts **one connection only**.
- Amp setting: **Network Control = On** (keeps network alive in standby; needed for remote wake).

## 2. PM7000N findings

- Not on Home Assistant's `denonavr` supported list.
- HEOS CLI: **source select + volume confirmed working** (HA community).
- Gladys Assistant integration marks PM7000N as "Power: Not controllable (HEOS)".
- **But the HEOS Android app CAN power it off/on**, so there is an undocumented path. Find it.

## 3. HEOS CLI command reference (port 1255)

```
heos://system/register_for_change_events?enable=on
heos://system/heart_beat                          # keepalive every ~30 s
heos://player/get_players                         # -> pid
heos://player/get_volume?pid=PID
heos://player/set_volume?pid=PID&level=0-100
heos://player/volume_up?pid=PID&step=1-10
heos://player/set_mute?pid=PID&state=on|off
heos://player/get_now_playing_media?pid=PID
heos://browse/get_music_sources                   # find AUX/inputs sid, browse to list valid input names
heos://browse/play_input?pid=PID&input=inputs/phono
   # others: inputs/cd, inputs/aux_in_1, inputs/optical_in_1, inputs/optical_in_2, inputs/coax_in_1
```

Quick test:
```bash
printf 'heos://player/get_players\r\n' | nc -w2 <IP> 1255
```

Spec PDF (v1.10 mirror): https://cdn.hackaday.io/files/1869467998297664/HEOS_CLI_ProtocolSpecification.pdf
(Newer v1.14+ revisions are published under Marantz model names.)

## 4. TODO – find the power command

### Step 1: probe ports / candidate endpoints
```bash
nmap -p 23,80,1255,8080,10443,60006 <IP>
printf 'PW?\r' | nc -w2 <IP> 23

curl -s  "http://<IP>:8080/goform/formMainZone_MainZoneXmlStatusLite.xml"
curl -s  "http://<IP>:8080/goform/formiPhoneAppPower.xml?1+PowerStandby"
curl -sk "https://<IP>:10443/ajax/globals/get_config?type=4"
curl -sk "https://<IP>:10443/ajax/general/set_config?type=4&data=%3CMainZone%3E%3CPower%3E3%3C%2FPower%3E%3C%2FMainZone%3E"   # 3=standby, 1=on
```

### Step 2: sniff the HEOS Android app
- **A (phone, no root):** PCAPdroid, filter on the HEOS app, press power off/on, export pcap.
  - Port 1255 is plaintext, so the exact `heos://...` command will be visible.
  - HTTPS (10443) needs the PCAPdroid TLS decryption add-on; if the app pins certificates, use mitmproxy + Frida unpinning.
- **B (laptop hotspot):**
  ```bash
  sudo tcpdump -i <hotspot_if> -w heos.pcap host <AMP_IP>
  tshark -r heos.pcap -Y 'tcp.port==1255' -T fields -e tcp.payload | xxd -r -p
  ```
- Check **all** TCP streams to the amp's IP, not just 1255.

### Fallback for power
- Broadlink RM4 Mini IR blaster + `python-broadlink` (PM7000N remote codes), or
- Drive the amp's wired remote IN jack from Pi GPIO.
- Power-on alternative: start HEOS playback / `play_input` while Network Control = On (to be verified).

## 5. Minimal Python HEOS client (asyncio, no deps)

```python
import asyncio, json

class Heos:
    def __init__(s, host): s.host = host
    async def connect(s):
        s.r, s.w = await asyncio.open_connection(s.host, 1255)
    async def cmd(s, c):
        s.w.write(f"heos://{c}\r\n".encode()); await s.w.drain()
        while True:
            m = json.loads(await s.r.readuntil(b"\r\n"))
            if m["heos"]["command"] == c.split("?")[0] and \
               "command under process" not in m["heos"].get("message", ""):
                return m

async def main():
    h = Heos("192.168.1.50"); await h.connect()
    pid = (await h.cmd("player/get_players"))["payload"][0]["pid"]
    await h.cmd(f"browse/play_input?pid={pid}&input=inputs/phono")
    await h.cmd(f"player/set_volume?pid={pid}&level=25")
    print(await h.cmd(f"player/get_volume?pid={pid}"))

asyncio.run(main())
```

Libraries: `pyheos` (HA's HEOS backend), `denonavr` (AVR telnet/HTTP, likely not for PM7000N), `aiomadeavr`.

## 6. Planned architecture

```
Pi 4 touchscreen UI / MCP / MQTT
          |
   control service (asyncio)
     |-- persistent HEOS socket :1255 (heartbeat 30 s, change events)
     |-- power: discovered endpoint  OR  Broadlink IR
          |
   Marantz PM7000N (static IP, Network Control = On)
```

## Sources
- HEOS CLI spec: https://cdn.hackaday.io/files/1869467998297664/HEOS_CLI_ProtocolSpecification.pdf
- HA community – PM7000N + HEOS: https://community.home-assistant.io/t/anyone-know-if-the-denon-heos-integrations-work-with-the-marantz-pm7000n/599703/5
- HA community – HEOS power off: https://community.home-assistant.io/t/heos-integration-of-power-off-button/367181
- Gladys Denon/Marantz integration: https://gladysassistant.com/docs/integrations/external/denon-marantz-avr/
- Node-RED Marantz HTTP API flow: https://flows.nodered.org/flow/8fe5add4451c2c3bc95ce02fb4a0dfc7
- denonavr: https://github.com/ol-iver/denonavr
