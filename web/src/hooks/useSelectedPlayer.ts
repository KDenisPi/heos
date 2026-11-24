import type { Device, PlayerState } from "../api/types";
import { setPrefs, usePrefs } from "../state/prefs";
import { useAppState } from "../state/store";

/** The player the UI controls: the remembered choice, else the default device, else the first. */
export function useSelectedPid(): number | null {
  const { selectedPid } = usePrefs();
  const devices = useAppState((s) => s.devices);
  const players = useAppState((s) => s.players);
  if (selectedPid !== null && (players[selectedPid] || devices.some((d) => d.pid === selectedPid))) return selectedPid;
  const fallback = devices.find((d) => d.default) ?? devices[0];
  if (fallback) return fallback.pid;
  const first = Object.keys(players)[0];
  return first !== undefined ? Number(first) : null;
}

export function selectPid(pid: number): void {
  setPrefs({ selectedPid: pid });
}

export function useSelectedPlayer(): PlayerState | null {
  const pid = useSelectedPid();
  return useAppState((s) => (pid === null ? null : s.players[pid] ?? null));
}

export function useSelectedDevice(): Device | null {
  const pid = useSelectedPid();
  return useAppState((s) => s.devices.find((d) => d.pid === pid) ?? null);
}
