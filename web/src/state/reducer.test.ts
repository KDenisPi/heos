import { describe, expect, it } from "vitest";
import type { Device, PlayerState } from "../api/types";
import { initialState, livePosition, reduce } from "./reducer";

const player: PlayerState = {
  pid: -1, name: "Living room", model: "PM7000N", version: "1", ip: null, network: null, serial: null, gid: null,
  online: true, state: "stop", volume: 20, mute: false, repeat: "off", shuffle: false,
  now_playing: { song: "A" }, progress: { cur_pos: 0, duration: 0 }, input: null, last_error: null,
};
const device: Device = {
  pid: -1, name: "Living room", model: "PM7000N", ip: null, ip_override: null, firmware: null, network: null,
  serial: null, online: true, connection_host: true, default: true,
  power: { driver: "auto", effective_driver: "upnp_act", state: "on", error: null },
};
const snap = reduce(initialState, {
  type: "snapshot",
  data: { connection: { connected: true, host: "h" }, players: [player], devices: [device], account: { signed_in: false, username: null } },
});

describe("reduce", () => {
  it("loads a snapshot", () => {
    expect(snap.players[-1].volume).toBe(20);
    expect(snap.heos.connected).toBe(true);
    expect(snap.devices).toHaveLength(1);
  });

  it("applies volume and mute", () => {
    const s = reduce(snap, { type: "volume", pid: -1, data: { level: 42, mute: true } });
    expect(s.players[-1]).toMatchObject({ volume: 42, mute: true });
  });

  it("ignores events for unknown players", () => {
    expect(reduce(snap, { type: "volume", pid: 99, data: { level: 1, mute: false } })).toBe(snap);
  });

  it("splits input out of now_playing and resets progress", () => {
    const s = reduce(snap, { type: "now_playing", pid: -1, data: { song: "Phono", input: "inputs/phono" } });
    expect(s.players[-1].input).toBe("inputs/phono");
    expect(s.players[-1].now_playing).toEqual({ song: "Phono" });
    expect(s.players[-1].progress).toEqual({ cur_pos: 0, duration: 0 });
  });

  it("bumps the queue version", () => {
    const s = reduce(reduce(snap, { type: "queue_changed", pid: -1 }), { type: "queue_changed", pid: -1 });
    expect(s.queueVersion[-1]).toBe(2);
  });

  it("updates power state on the device", () => {
    const s = reduce(snap, { type: "power", pid: -1, data: { state: "standby" } });
    expect(s.devices[0].power.state).toBe("standby");
  });

  it("tracks offline devices", () => {
    const s = reduce(snap, { type: "device_offline", pid: -1 });
    expect(s.players[-1].online).toBe(false);
    expect(s.devices[0].online).toBe(false);
  });
});

describe("livePosition", () => {
  const playing = { ...player, state: "play" as const, progress: { cur_pos: 10_000, duration: 60_000 } };
  it("interpolates while playing", () => {
    expect(livePosition(playing, 1_000, 3_500)).toBe(12_500);
  });
  it("stops at the duration", () => {
    expect(livePosition(playing, 0, 999_999)).toBe(60_000);
  });
  it("does not move when paused", () => {
    expect(livePosition({ ...playing, state: "pause" }, 1_000, 9_000)).toBe(10_000);
  });
});

describe("queue sort progress", () => {
  it("tracks the latest progress per player", () => {
    let s = reduce(snap, { type: "queue_sort", pid: -1, data: { state: "running", done: 10, total: 40 } });
    expect(s.queueSort[-1]).toEqual({ state: "running", done: 10, total: 40 });
    s = reduce(s, { type: "queue_sort", pid: -1, data: { state: "done", done: 40, total: 40 } });
    expect(s.queueSort[-1].state).toBe("done");
  });
});

describe("playlists", () => {
  it("bumps the version on playlists_changed and tracks load progress", () => {
    let s = reduce(snap, { type: "playlists_changed", data: { id: "jazz" } });
    expect(s.playlistsVersion).toBe(1);
    s = reduce(s, { type: "playlist_load", pid: -1, data: { id: "jazz", done: 10, total: 40 } });
    expect(s.playlistLoad[-1]).toEqual({ id: "jazz", done: 10, total: 40 });
  });
});
