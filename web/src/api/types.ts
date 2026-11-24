// Shapes returned by the heos-home service (see src/heos_home/api/routes.py).

export type PlayState = "play" | "pause" | "stop";
export type Repeat = "off" | "on_all" | "on_one";
export type PowerState = "on" | "standby" | "unknown";

export interface NowPlaying {
  type?: "song" | "station" | string;
  song?: string;
  station?: string;
  album?: string;
  artist?: string;
  image_url?: string;
  mid?: string;
  qid?: number;
  sid?: number;
  input?: string | null;
}

export interface PlayerState {
  pid: number;
  name: string;
  model: string;
  version: string;
  ip: string | null;
  network: string | null;
  serial: string | null;
  gid: number | null;
  online: boolean;
  state: PlayState;
  volume: number;
  mute: boolean;
  repeat: Repeat;
  shuffle: boolean;
  now_playing: NowPlaying;
  progress: { cur_pos: number; duration: number };
  input: string | null;
  last_error: string | null;
}

export interface PowerInfo {
  driver: string;
  effective_driver: string | null;
  state: PowerState;
  error: string | null;
}

export interface Device {
  pid: number;
  name: string;
  model: string;
  ip: string | null;
  ip_override: string | null;
  firmware: string | null;
  network: string | null;
  serial: string | null;
  online: boolean;
  connection_host: boolean;
  default: boolean;
  power: PowerInfo;
}

export interface QueueItem {
  qid: number;
  song: string;
  album: string;
  artist: string;
  image_url: string;
  mid: string;
  album_id?: string;
}

export type SortKey = "title" | "artist" | "album" | "random";

export interface QueueSortProgress {
  state: "running" | "done" | "failed";
  done?: number;
  total?: number;
  error?: string;
}

// ------------------------------------------------------------------ library
export interface LibraryItem {
  sid: number;
  name: string;
  type: string;
  container: boolean;
  playable: boolean;
  cid: string | null;
  mid: string | null;
  artist: string;
  album: string;
  /** For tracks: the container they belong to (used to queue them, e.g. from search results). */
  album_id?: string | null;
  image_url: string;
  /**
   * How it plays: "queue" (add to queue modes), "stream" (Amazon albums,
   * playlists, stations: replaces what is playing), "favorite" (HEOS Favorite).
   */
  play: "queue" | "stream" | "favorite";
}

export interface LibrarySource {
  sid: number;
  name: string;
  kind: "favorites" | "service" | "dlna";
  image_url: string;
  account?: string | null;
}

export interface BrowsePage {
  sid: number;
  cid: string | null;
  start: number;
  count: number;
  total: number;
  /** The browsed container itself can be queued as a whole. */
  playable: boolean;
  items: LibraryItem[];
}

export interface PathStep {
  cid: string;
  name: string;
}

export interface Shortcut {
  id: number;
  name: string;
  sid: number;
  cid: string;
  path: PathStep[];
}

export type AddMode = "now" | "next" | "end" | "replace";

export interface QueueAddItem {
  sid: number;
  cid?: string | null;
  mid?: string | null;
}

export interface InputItem {
  input: string;
  name: string;
  image_url?: string | null;
}

export interface Account {
  signed_in: boolean;
  username: string | null;
}

export interface Health {
  status: string;
  version: string;
  heos: { connected: boolean; host: string | null; last_error: string | null };
}

// ----------------------------------------------------------- WebSocket events
export interface Snapshot {
  connection: { connected: boolean; host: string | null };
  players: PlayerState[];
  devices: Device[];
  account: Account;
}

export type ServerEvent =
  | { type: "snapshot"; data: Snapshot }
  | { type: "connection"; data: { connected: boolean; host: string | null } }
  | { type: "player_full"; pid: number; data: PlayerState }
  | { type: "player_state"; pid: number; data: { state: PlayState } }
  | { type: "volume"; pid: number; data: { level: number; mute: boolean } }
  | { type: "now_playing"; pid: number; data: NowPlaying }
  | { type: "progress"; pid: number; data: { cur_pos: number; duration: number } }
  | { type: "play_mode"; pid: number; data: { repeat: Repeat; shuffle: boolean } }
  | { type: "playback_error"; pid: number; data: { error: string } }
  | { type: "queue_changed"; pid: number }
  | { type: "queue_sort"; pid: number; data: QueueSortProgress }
  | { type: "power"; pid: number; data: { state: PowerState } }
  | { type: "device_online"; pid: number; data?: Partial<Device> }
  | { type: "device_offline"; pid: number }
  | { type: "account"; data: Account }
  | { type: "devices_changed" | "players_changed" | "sources_changed" | "pong" };
