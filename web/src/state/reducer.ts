// Pure state transitions for WebSocket events. Kept free of React and the
// browser so it can be unit-tested.

import type { Account, Device, PlayerState, QueueSortProgress, ServerEvent } from "../api/types";

export interface AppState {
  /** WebSocket to the heos-home service is open. */
  online: boolean;
  /** heos-home is connected to a HEOS device. */
  heos: { connected: boolean; host: string | null };
  players: Record<number, PlayerState>;
  devices: Device[];
  account: Account;
  /** Bumped on every queue_changed event; views refetch when it changes. */
  queueVersion: Record<number, number>;
  /** Progress of a running queue sort, per pid. */
  queueSort: Record<number, QueueSortProgress>;
  /** Bumped when HEOS Favorites change (added or removed from this app). */
  favoritesVersion: number;
  /** Bumped when local playlists change (saved, renamed, edited, deleted). */
  playlistsVersion: number;
  /** Progress of loading a playlist into the queue, per pid. */
  playlistLoad: Record<number, { id: string; done: number; total: number }>;
  /** Bumped when the device list should be refetched. */
  devicesVersion: number;
  /** Wall-clock ms when the last progress event arrived, per pid (for interpolation). */
  progressAt: Record<number, number>;
  lastPlaybackError: { pid: number; error: string; at: number } | null;
}

export const initialState: AppState = {
  online: false,
  heos: { connected: false, host: null },
  players: {},
  devices: [],
  account: { signed_in: false, username: null },
  queueVersion: {},
  queueSort: {},
  favoritesVersion: 0,
  playlistsVersion: 0,
  playlistLoad: {},
  devicesVersion: 0,
  progressAt: {},
  lastPlaybackError: null,
};

function patchPlayer(state: AppState, pid: number, patch: Partial<PlayerState>): AppState {
  const player = state.players[pid];
  if (!player) return state;
  return { ...state, players: { ...state.players, [pid]: { ...player, ...patch } } };
}

function patchDevice(state: AppState, pid: number, patch: (d: Device) => Device): AppState {
  if (!state.devices.some((d) => d.pid === pid)) return state;
  return { ...state, devices: state.devices.map((d) => (d.pid === pid ? patch(d) : d)) };
}

export function reduce(state: AppState, ev: ServerEvent, now = Date.now()): AppState {
  switch (ev.type) {
    case "snapshot": {
      const players: Record<number, PlayerState> = {};
      for (const p of ev.data.players) players[p.pid] = p;
      return {
        ...state,
        heos: ev.data.connection,
        players,
        devices: ev.data.devices,
        account: ev.data.account,
        devicesVersion: state.devicesVersion + 1,
      };
    }
    case "connection":
      return { ...state, heos: ev.data };
    case "player_full":
      return {
        ...state,
        players: { ...state.players, [ev.pid]: ev.data },
        progressAt: { ...state.progressAt, [ev.pid]: now },
      };
    case "player_state": {
      const next = patchPlayer(state, ev.pid, { state: ev.data.state });
      // Restart interpolation from the current position when play resumes.
      return { ...next, progressAt: { ...next.progressAt, [ev.pid]: now } };
    }
    case "volume":
      return patchPlayer(state, ev.pid, { volume: ev.data.level, mute: ev.data.mute });
    case "now_playing": {
      const { input = null, ...media } = ev.data;
      return patchPlayer(state, ev.pid, {
        now_playing: media,
        input,
        progress: { cur_pos: 0, duration: 0 },
      });
    }
    case "progress": {
      const next = patchPlayer(state, ev.pid, { progress: ev.data });
      return { ...next, progressAt: { ...next.progressAt, [ev.pid]: now } };
    }
    case "play_mode":
      return patchPlayer(state, ev.pid, ev.data);
    case "playback_error":
      return { ...patchPlayer(state, ev.pid, { last_error: ev.data.error }), lastPlaybackError: { pid: ev.pid, error: ev.data.error, at: now } };
    case "queue_changed":
      return { ...state, queueVersion: { ...state.queueVersion, [ev.pid]: (state.queueVersion[ev.pid] ?? 0) + 1 } };
    case "favorites_changed":
      return { ...state, favoritesVersion: state.favoritesVersion + 1 };
    case "playlists_changed":
      return { ...state, playlistsVersion: state.playlistsVersion + 1 };
    case "playlist_load":
      return { ...state, playlistLoad: { ...state.playlistLoad, [ev.pid]: ev.data } };
    case "queue_sort":
      return { ...state, queueSort: { ...state.queueSort, [ev.pid]: ev.data } };
    case "power":
      return patchDevice(state, ev.pid, (d) => ({ ...d, power: { ...d.power, state: ev.data.state } }));
    case "device_online": {
      const next = patchPlayer(state, ev.pid, { online: true });
      return { ...patchDevice(next, ev.pid, (d) => ({ ...d, online: true })), devicesVersion: next.devicesVersion + 1 };
    }
    case "device_offline": {
      const next = patchPlayer(state, ev.pid, { online: false });
      return patchDevice(next, ev.pid, (d) => ({ ...d, online: false }));
    }
    case "account":
      // Player events carry only signed_in/username; the account service adds the rest.
      return { ...state, account: { ...state.account, ...ev.data } };
    case "devices_changed":
    case "players_changed":
      return { ...state, devicesVersion: state.devicesVersion + 1 };
    default:
      return state;
  }
}

/** Current playback position in ms, interpolated since the last progress event. */
export function livePosition(player: PlayerState, progressAt: number | undefined, now = Date.now()): number {
  const { cur_pos, duration } = player.progress;
  if (player.state !== "play" || progressAt === undefined) return cur_pos;
  const pos = cur_pos + (now - progressAt);
  return duration > 0 ? Math.min(pos, duration) : pos;
}
