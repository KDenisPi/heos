import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import { useAction } from "../notify";
import { useAppState } from "../state/store";

/**
 * HEOS Favorites as a set of media ids, refreshed when this app changes them,
 * plus add / remove actions. Favorites live in the HEOS account.
 */
export function useFavorites() {
  const act = useAction();
  const version = useAppState((s) => s.favoritesVersion);
  const heosConnected = useAppState((s) => s.heos.connected);
  const [mids, setMids] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!heosConnected) return;
    api.favoriteMids().then((r) => setMids(new Set(r.mids))).catch(() => undefined);
  }, [version, heosConnected]);

  const add = useCallback(
    (item: { sid: number; mid: string; name: string }) => act(() => api.addFavorite(item), `Added "${item.name}" to Favorites`),
    [act],
  );
  const addNowPlaying = useCallback(
    (pid: number, name: string) => act(() => api.favoriteNowPlaying(pid), `Added "${name}" to Favorites`),
    [act],
  );
  const remove = useCallback(
    (mid: string, name: string) => act(() => api.removeFavorite(mid), `Removed "${name}" from Favorites`),
    [act],
  );
  return { mids, add, addNowPlaying, remove };
}
