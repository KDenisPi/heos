// Thin REST client for /api/v1. Errors carry the service's {error:{code,message}}.

import type { Account, Device, Health, InputItem, PlayerState, PowerInfo, QueueItem } from "./types";

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
  moveQueue: (pid: number, qids: number[], to: number) =>
    request("POST", `/players/${pid}/queue/move`, { qids, to }),
};
