// Thin REST client for /api/v1. Errors carry the service's {error:{code,message}}.

import type {
  Account,
  AddMode,
  BrowsePage,
  Device,
  Health,
  InputItem,
  LibraryItem,
  LibrarySource,
  PathStep,
  Playlist,
  PlaylistEntry,
  PlaylistSummary,
  PlayerState,
  PowerInfo,
  QueueAddItem,
  QueueItem,
  Shortcut,
  SortKey,
} from "./types";

const BASE = "/api/v1";
const TOKEN_KEY = "heos-home.token";

export class ApiError extends Error {
  constructor(
    public status: number,
    public code: string,
    message: string,
    public extra: Record<string, unknown> = {},
  ) {
    super(message);
  }
}

export function getToken(): string {
  try {
    return localStorage.getItem(TOKEN_KEY) ?? "";
  } catch {
    return "";
  }
}

export function setToken(token: string): void {
  try {
    if (token) localStorage.setItem(TOKEN_KEY, token);
    else localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* storage unavailable: token lives only for this page */
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const headers: Record<string, string> = {};
  if (body !== undefined) headers["Content-Type"] = "application/json";
  const token = getToken();
  if (token && method !== "GET") headers["Authorization"] = `Bearer ${token}`;
  let resp: Response;
  try {
    resp = await fetch(BASE + path, {
      method,
      headers,
      body: body === undefined ? undefined : JSON.stringify(body),
    });
  } catch {
    throw new ApiError(0, "network", "The HEOS Home service is not reachable");
  }
  const text = await resp.text();
  const data = text ? JSON.parse(text) : null;
  if (!resp.ok) {
    const err = data?.error;
    const detail = typeof data?.detail === "string" ? data.detail : undefined;
    throw new ApiError(resp.status, err?.code ?? "http_error", err?.message ?? detail ?? `HTTP ${resp.status}`, err ?? {});
  }
  return data as T;
}

const json = { get: <T>(p: string) => request<T>("GET", p) };

export const api = {
  health: () => json.get<Health>("/health"),
  account: () => json.get<Account>("/account"),

  devices: () => json.get<{ devices: Device[]; last_discovery: number | null }>("/devices"),
  discover: () => request<{ found: string[]; devices: Device[] }>("POST", "/devices/discover"),
  patchDevice: (pid: number, body: { ip_override?: string | null; power?: { driver: string }; default?: boolean }) =>
    request<Device>("PATCH", `/devices/${pid}`, body),
  deviceInfo: (pid: number) => json.get<Device & { raw?: Record<string, unknown> }>(`/devices/${pid}/info`),
  firmware: (pid: number) =>
    json.get<{ installed: string; update_available: boolean; how_to_install: string }>(`/devices/${pid}/firmware`),
  readPower: (pid: number) => json.get<PowerInfo>(`/devices/${pid}/power`),
  setPower: (pid: number, on: boolean) =>
    request<{ state: string; changed: boolean }>("POST", `/devices/${pid}/power`, { state: on ? "on" : "off" }),

  player: (pid: number) => json.get<PlayerState>(`/players/${pid}/state`),
  transport: (pid: number, action: "play" | "pause" | "stop" | "next" | "prev") =>
    request("POST", `/players/${pid}/transport`, { action }),
  setVolume: (pid: number, level: number) => request("PUT", `/players/${pid}/volume`, { level }),
  stepVolume: (pid: number, step: number) => request("PUT", `/players/${pid}/volume`, { step }),
  setMute: (pid: number, state: boolean) => request("PUT", `/players/${pid}/mute`, { state }),
  setPlayMode: (pid: number, mode: { shuffle?: boolean; repeat?: string }) =>
    request("PUT", `/players/${pid}/play-mode`, mode),
  inputs: (pid: number) => json.get<{ current: string | null; inputs: InputItem[] }>(`/players/${pid}/inputs`),
  selectInput: (pid: number, input: string) => request("PUT", `/players/${pid}/input`, { input }),

  queue: (pid: number) => json.get<{ count: number; items: QueueItem[] }>(`/players/${pid}/queue`),
  playQueueItem: (pid: number, qid: number) => request("POST", `/players/${pid}/queue/play`, { qid }),
  removeFromQueue: (pid: number, qids: number[]) => request("DELETE", `/players/${pid}/queue`, { qids }),
  clearQueue: (pid: number) => request("DELETE", `/players/${pid}/queue`),
  addToQueue: (pid: number, items: QueueAddItem[], mode: AddMode) =>
    request<{ added: number; mode: AddMode }>("POST", `/players/${pid}/queue`, { items, mode }),
  sortQueue: (pid: number, by: SortKey, order: "asc" | "desc" = "asc") =>
    request<{ by: string; order: string; items: number; moves: number }>("POST", `/players/${pid}/queue/sort`, { by, order }),
  moveQueue: (pid: number, qids: number[], to: number) =>
    request("POST", `/players/${pid}/queue/move`, { qids, to }),

  libraryServers: () => json.get<{ servers: LibraryItem[] }>("/library/servers"),
  librarySources: () => json.get<{ sources: LibrarySource[] }>("/library/sources"),
  playStream: (pid: number, item: { sid: number; mid: string; name: string }) =>
    request("POST", `/players/${pid}/play-stream`, item),
  playFavorite: (pid: number, mid: string) => request<{ preset: number }>("POST", `/players/${pid}/play-favorite`, { mid }),
  browse: (sid: number, cid: string | null, start = 0, count = 50, refresh = false) => {
    const q = new URLSearchParams({ start: String(start), count: String(count) });
    if (cid) q.set("cid", cid);
    if (refresh) q.set("refresh", "true");
    return json.get<BrowsePage>(`/sources/${sid}/browse?${q}`);
  },
  search: (sid: number, q: string, criteria = 3) =>
    json.get<{ items: LibraryItem[]; total: number }>(
      `/sources/${sid}/search?${new URLSearchParams({ q, criteria: String(criteria) })}`,
    ),
  shortcuts: () => json.get<{ shortcuts: Shortcut[] }>("/library/shortcuts"),
  addShortcut: (sid: number, path: PathStep[]) => request<Shortcut>("POST", "/library/shortcuts", { sid, path }),
  removeShortcut: (id: number) => request("DELETE", `/library/shortcuts/${id}`),
  lastFolder: (sid: number) => json.get<{ path: PathStep[] }>(`/library/last-folder/${sid}`),
  setLastFolder: (sid: number, path: PathStep[]) => request("PUT", `/library/last-folder/${sid}`, { path }),

  playlists: () => json.get<{ playlists: PlaylistSummary[] }>("/playlists"),
  playlist: (id: string) => json.get<Playlist>(`/playlists/${encodeURIComponent(id)}`),
  createPlaylist: (name: string, fromQueue?: number) =>
    request<PlaylistSummary>("POST", "/playlists", fromQueue === undefined ? { name } : { name, from_queue: fromQueue }),
  renamePlaylist: (id: string, name: string) => request<Playlist>("PATCH", `/playlists/${encodeURIComponent(id)}`, { name }),
  setPlaylistItems: (id: string, items: PlaylistEntry[]) =>
    request<Playlist>("PATCH", `/playlists/${encodeURIComponent(id)}`, { items }),
  deletePlaylist: (id: string) => request("DELETE", `/playlists/${encodeURIComponent(id)}`),
  duplicatePlaylist: (id: string) => request<PlaylistSummary>("POST", `/playlists/${encodeURIComponent(id)}/duplicate`, {}),
  sortPlaylist: (id: string, by: SortKey, order: "asc" | "desc") =>
    request<Playlist>("POST", `/playlists/${encodeURIComponent(id)}/sort`, { by, order }),
  loadPlaylist: (id: string, pid: number, mode: AddMode) =>
    request<{ tracks: number; skipped: number; commands: number }>("POST", `/playlists/${encodeURIComponent(id)}/load`, { pid, mode }),
  importPlaylist: async (text: string, name?: string) => {
    const token = getToken();
    const resp = await fetch(`${BASE}/playlists/import${name ? `?name=${encodeURIComponent(name)}` : ""}`, {
      method: "POST",
      headers: { "Content-Type": "audio/x-mpegurl", ...(token ? { Authorization: `Bearer ${token}` } : {}) },
      body: text,
    });
    const data = await resp.json().catch(() => null);
    if (!resp.ok) throw new ApiError(resp.status, data?.error?.code ?? "http_error", data?.error?.message ?? `HTTP ${resp.status}`);
    return data as PlaylistSummary;
  },
  exportUrl: (id: string) => `${BASE}/playlists/${encodeURIComponent(id)}/export`,
};
