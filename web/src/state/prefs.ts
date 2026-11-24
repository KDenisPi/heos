// Per-viewer preferences kept in localStorage (selected player, theme, wake lock).
// Every access is guarded: storage can be unavailable (private mode, kiosk resets).

import { useSyncExternalStore } from "react";

export type ThemeMode = "dark" | "light" | "system";

export interface Prefs {
  selectedPid: number | null;
  theme: ThemeMode;
  wakeLock: boolean;
}

const KEY = "heos-home.prefs";
const defaults: Prefs = { selectedPid: null, theme: "dark", wakeLock: false };

function load(): Prefs {
  try {
    return { ...defaults, ...JSON.parse(localStorage.getItem(KEY) ?? "{}") };
  } catch {
    return defaults;
  }
}

let prefs = load();
const listeners = new Set<() => void>();

export function setPrefs(patch: Partial<Prefs>): void {
  prefs = { ...prefs, ...patch };
  try {
    localStorage.setItem(KEY, JSON.stringify(prefs));
  } catch {
    /* keep in memory only */
  }
  listeners.forEach((fn) => fn());
}

export function usePrefs(): Prefs {
  return useSyncExternalStore(
    (fn) => {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    () => prefs,
  );
}
