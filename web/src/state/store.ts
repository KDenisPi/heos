// Global app state, fed by the /api/v1/ws WebSocket. Clients never poll:
// the service sends a snapshot on connect, then events.

import { useSyncExternalStore } from "react";
import type { Device, PlayerState, ServerEvent } from "../api/types";
import { type AppState, initialState, reduce } from "./reducer";

type Listener = () => void;

class Store {
  private state: AppState = initialState;
  private listeners = new Set<Listener>();
  private ws: WebSocket | null = null;
  private retry = 1000;
  private timer: number | undefined;
  private pinger: number | undefined;

  get = (): AppState => this.state;

  subscribe = (fn: Listener): (() => void) => {
    this.listeners.add(fn);
    return () => this.listeners.delete(fn);
  };

  dispatch(ev: ServerEvent): void {
    const next = reduce(this.state, ev);
    if (next !== this.state) {
      this.state = next;
      this.listeners.forEach((fn) => fn());
    }
  }

  /** Optimistic local change, reconciled by the next server event. */
  patchPlayer(pid: number, patch: Partial<PlayerState>): void {
    const player = this.state.players[pid];
    if (!player) return;
    this.state = { ...this.state, players: { ...this.state.players, [pid]: { ...player, ...patch } } };
    this.listeners.forEach((fn) => fn());
  }

  setDevices(devices: Device[]): void {
    this.state = { ...this.state, devices };
    this.listeners.forEach((fn) => fn());
  }

  private setOnline(online: boolean): void {
    if (this.state.online === online) return;
    this.state = { ...this.state, online };
    this.listeners.forEach((fn) => fn());
  }

  connect(): void {
    if (this.ws) return;
    const proto = location.protocol === "https:" ? "wss" : "ws";
    const ws = new WebSocket(`${proto}://${location.host}/api/v1/ws`);
    this.ws = ws;
    ws.onopen = () => {
      this.retry = 1000;
      this.setOnline(true);
      this.pinger = window.setInterval(() => ws.readyState === ws.OPEN && ws.send('{"type":"ping"}'), 25000);
    };
    ws.onmessage = (msg) => {
      try {
        this.dispatch(JSON.parse(msg.data) as ServerEvent);
      } catch (err) {
        console.warn("bad event", err);
      }
    };
    ws.onclose = () => {
      window.clearInterval(this.pinger);
      this.ws = null;
      this.setOnline(false);
      // Reconnect with exponential backoff, 1 s to 30 s.
      this.timer = window.setTimeout(() => this.connect(), this.retry);
      this.retry = Math.min(this.retry * 2, 30000);
    };
    ws.onerror = () => ws.close();
  }

  /** Reconnect now (e.g. when the tablet wakes up), skipping the backoff wait. */
  reconnectNow(): void {
    if (this.ws) return;
    window.clearTimeout(this.timer);
    this.retry = 1000;
    this.connect();
  }
}

export const store = new Store();

export function useAppState<T>(selector: (s: AppState) => T): T {
  return useSyncExternalStore(store.subscribe, () => selector(store.get()));
}
