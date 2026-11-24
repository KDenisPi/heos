// Source (F5, F6): DLNA servers, streaming services (Amazon), HEOS Favorites, pinned folders, folder browsing with breadcrumb,
// paging, a filter for the loaded folder, and play / queue actions.

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CloseIcon from "@mui/icons-material/Close";
import ChevronRightIcon from "@mui/icons-material/ChevronRight";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import CloudIcon from "@mui/icons-material/Cloud";
import DnsIcon from "@mui/icons-material/Dns";
import FolderIcon from "@mui/icons-material/Folder";
import HistoryIcon from "@mui/icons-material/History";
import LibraryMusicIcon from "@mui/icons-material/LibraryMusic";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PushPinIcon from "@mui/icons-material/PushPin";
import PushPinOutlinedIcon from "@mui/icons-material/PushPinOutlined";
import RadioIcon from "@mui/icons-material/Radio";
import RefreshIcon from "@mui/icons-material/Refresh";
import StarIcon from "@mui/icons-material/Star";
import StarBorderIcon from "@mui/icons-material/StarBorder";
import SearchIcon from "@mui/icons-material/Search";
import {
  Avatar,
  Box,
  Breadcrumbs,
  Button,
  ButtonBase,
  CircularProgress,
  IconButton,
  InputAdornment,
  Link,
  List,
  ListItem,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  Radio,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { AddMode, LibraryItem, LibrarySource, PathStep, QueueAddItem, Shortcut } from "../api/types";
import { ActionButton, QueueActions } from "../components/ActionButton";
import { useDeviceClass } from "../hooks/useDeviceClass";
import { useFavorites } from "../hooks/useFavorites";
import { useSelectedPid } from "../hooks/useSelectedPlayer";
import { useAction, useNotify } from "../notify";
import { useAppState } from "../state/store";

const PAGE = 50;
const FAVORITES_SID = 1028;

interface Location {
  sid: number;
  server: string;
  path: PathStep[];
}

const MODE_LABEL: Record<AddMode, string> = {
  now: "Added and playing",
  next: "Plays next",
  end: "Added to end of queue",
  replace: "Queue replaced, playing",
};

/** Queue items from the library with a mode; reports the result in the snackbar. */
function useEnqueue() {
  const act = useAction();
  const pid = useSelectedPid();
  return useCallback(
    (items: QueueAddItem[], mode: AddMode) => {
      if (pid === null) return;
      act(() => api.addToQueue(pid, items, mode), MODE_LABEL[mode]);
    },
    [act, pid],
  );
}

/** Play a stream-like item (Amazon album / playlist / station) or a HEOS Favorite. */
function usePlayStream() {
  const act = useAction();
  const pid = useSelectedPid();
  return useCallback(
    (item: LibraryItem) => {
      if (pid === null || !item.mid) return;
      const mid = item.mid;
      act(
        () => (item.play === "favorite" ? api.playFavorite(pid, mid) : api.playStream(pid, { sid: item.sid, mid, name: item.name })),
        `Playing ${item.name}`,
      );
    },
    [act, pid],
  );
}

function queueItemFor(item: LibraryItem, folderCid: string | null): QueueAddItem {
  // A track is queued with its container's cid plus its mid; a folder with its own cid.
  return item.container
    ? { sid: item.sid, cid: item.cid }
    : { sid: item.sid, cid: item.album_id || folderCid, mid: item.mid };
}

// ------------------------------------------------------------------- home
const KIND_LABEL: Record<LibrarySource["kind"], string> = {
  favorites: "HEOS Favorites",
  service: "Streaming service",
  dlna: "DLNA server",
};

function SourceIcon({ source }: { source: LibrarySource }) {
  if (source.kind === "favorites") return <StarIcon color="primary" sx={{ fontSize: 40 }} />;
  if (source.kind === "dlna") return <DnsIcon color="primary" sx={{ fontSize: 40 }} />;
  return source.image_url ? (
    <Avatar variant="rounded" src={source.image_url} alt="" sx={{ width: 40, height: 40, bgcolor: "transparent" }} />
  ) : (
    <CloudIcon color="primary" sx={{ fontSize: 40 }} />
  );
}

function SourceHome({ onOpen }: { onOpen: (loc: Location) => void }) {
  const act = useAction();
  const heosConnected = useAppState((s) => s.heos.connected);
  const [sources, setSources] = useState<LibrarySource[] | null>(null);
  const [shortcuts, setShortcuts] = useState<Shortcut[]>([]);
  const [lastFolders, setLastFolders] = useState<Record<number, PathStep[]>>({});

  useEffect(() => {
    if (!heosConnected) return;
    act(() => api.librarySources()).then(async (res) => {
      if (!res) return;
      setSources(res.sources);
      const entries = await Promise.all(
        res.sources.map(async (s) => [s.sid, (await api.lastFolder(s.sid).catch(() => ({ path: [] }))).path] as const),
      );
      setLastFolders(Object.fromEntries(entries));
    });
    api.shortcuts().then((r) => setShortcuts(r.shortcuts)).catch(() => undefined);
  }, [act, heosConnected]);

  const sourceName = (sid: number) => sources?.find((s) => s.sid === sid)?.name ?? "Source";
  const unpin = async (id: number) => {
    await act(() => api.removeShortcut(id));
    const r = await act(() => api.shortcuts());
    if (r) setShortcuts(r.shortcuts);
  };

  return (
    <Stack spacing={3} sx={{ p: 3 }}>
      <Typography variant="h5">Source</Typography>

      <Box>
        <Typography variant="subtitle1" gutterBottom>Media servers and services</Typography>
        {sources === null ? (
          heosConnected ? <CircularProgress size={28} /> : <Typography color="text.secondary">Not connected</Typography>
        ) : sources.length === 0 ? (
          <Typography color="text.secondary">No music sources available. Sign in to HEOS or add a DLNA server.</Typography>
        ) : (
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
            {sources.map((s) => {
              const last = lastFolders[s.sid] ?? [];
              return (
                <Box key={s.sid} sx={{ border: 1, borderColor: "divider", borderRadius: 4, bgcolor: "background.paper", overflow: "hidden" }}>
                  <ButtonBase onClick={() => onOpen({ sid: s.sid, server: s.name, path: [] })} sx={{ width: "100%", justifyContent: "flex-start", gap: 2, p: 2 }}>
                    <SourceIcon source={s} />
                    <Box sx={{ textAlign: "left", minWidth: 0 }}>
                      <Typography variant="subtitle1" noWrap>{s.name}</Typography>
                      <Typography variant="caption" color="text.secondary" noWrap component="div">
                        {KIND_LABEL[s.kind]}{s.account ? ` · ${s.account}` : ""}
                      </Typography>
                    </Box>
                  </ButtonBase>
                  {last.length > 0 && (
                    <Button
                      fullWidth
                      startIcon={<HistoryIcon />}
                      onClick={() => onOpen({ sid: s.sid, server: s.name, path: last })}
                      sx={{ justifyContent: "flex-start", borderRadius: 0, px: 2 }}
                    >
                      <Typography variant="body2" noWrap>Continue in {last[last.length - 1].name}</Typography>
                    </Button>
                  )}
                </Box>
              );
            })}
          </Box>
        )}
      </Box>

      <Box>
        <Typography variant="subtitle1" gutterBottom>Pinned folders</Typography>
        {shortcuts.length === 0 ? (
          <Typography color="text.secondary">Pin a folder with the pin button while browsing.</Typography>
        ) : (
          <List disablePadding sx={{ maxWidth: 720 }}>
            {shortcuts.map((sc) => (
              <ListItem
                key={sc.id}
                disablePadding
                secondaryAction={
                  <IconButton edge="end" aria-label={`Unpin ${sc.name}`} onClick={() => unpin(sc.id)}>
                    <DeleteOutlineIcon />
                  </IconButton>
                }
              >
                <ListItemButton onClick={() => onOpen({ sid: sc.sid, server: sourceName(sc.sid), path: sc.path })}>
                  <ListItemAvatar>
                    <Avatar sx={{ bgcolor: "secondary.main", color: "secondary.contrastText" }}><PushPinIcon /></Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={sc.name} secondary={[sourceName(sc.sid), ...sc.path.map((p) => p.name)].join(" › ")} />
                </ListItemButton>
              </ListItem>
            ))}
          </List>
        )}
      </Box>
    </Stack>
  );
}

// ---------------------------------------------------------------- browser
type Target = { kind: "item"; item: LibraryItem } | { kind: "folder"; name: string; total: number | null } | null;

function itemKey(item: LibraryItem): string {
  return `${item.cid ?? ""}|${item.mid ?? ""}`;
}

/**
 * One row. Tapping a track selects it; tapping a folder opens it, and its
 * radio selects the folder itself. Nothing is queued until an action is chosen.
 */
function ItemRow({
  item,
  selected,
  onSelect,
  onOpen,
}: {
  item: LibraryItem;
  selected: boolean;
  onSelect: () => void;
  onOpen: () => void;
}) {
  const secondary = [item.artist, item.album].filter(Boolean).join(" · ");
  return (
    <ListItem disablePadding>
      <Radio
        checked={selected}
        onClick={onSelect}
        slotProps={{ input: { "aria-label": `Select ${item.name}` } }}
        sx={{ ml: 0.5 }}
      />
      <ListItemButton selected={selected} onClick={item.container ? onOpen : onSelect} sx={{ borderRadius: 3 }}>
        <ListItemAvatar>
          {item.image_url ? (
            <Avatar variant="rounded" src={item.image_url} alt="" slotProps={{ img: { loading: "lazy" } }} />
          ) : (
            <Avatar variant="rounded" sx={{ bgcolor: "action.hover", color: "text.secondary" }}>
              {item.container ? <FolderIcon /> : item.play === "queue" ? <MusicNoteIcon /> : <RadioIcon />}
            </Avatar>
          )}
        </ListItemAvatar>
        <ListItemText primary={item.name} secondary={secondary || undefined} slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }} />
        {item.container && <ChevronRightIcon sx={{ color: "text.disabled" }} />}
      </ListItemButton>
    </ListItem>
  );
}

/** What the actions apply to, and the three ways to add it to the queue. */
function ActionBar({
  target,
  isFavorite,
  onAdd,
  onPlay,
  onToggleFavorite,
  onClear,
}: {
  target: Target;
  isFavorite: boolean;
  onAdd: (mode: AddMode) => void;
  onPlay: () => void;
  onToggleFavorite: () => void;
  onClear: () => void;
}) {
  // Phones: one row with icon buttons (labels as tooltips); tablets: labelled buttons.
  const { phone: compact } = useDeviceClass();
  const stream = target?.kind === "item" && target.item.play !== "queue";
  const label =
    target === null
      ? "Select a track or folder"
      : target.kind === "item"
        ? target.item.name
        : compact
          ? `${target.name}${target.total !== null ? ` · ${target.total}` : ""}`
          : `Whole folder: ${target.name}${target.total !== null ? ` · ${target.total} items` : ""}`;
  const disabled = target === null;
  const streamNote =
    target?.kind === "item" && target.item.play === "favorite"
      ? "HEOS Favorite: replaces what is playing, not added to the queue"
      : "Plays as a stream: replaces what is playing, not added to the queue";
  return (
    <Stack
      direction={compact ? "row" : { xs: "column", md: "row" }}
      spacing={compact ? 1 : 1.5}
      sx={{ p: compact ? 1 : 1.5, px: compact ? 1.5 : 2, borderTop: 1, borderColor: "divider", bgcolor: "background.paper", alignItems: compact ? "center" : { md: "center" } }}
    >
      <Stack direction="row" spacing={1} sx={{ flex: 1, minWidth: 0, alignItems: "center" }}>
        {target?.kind === "item" ? (
          target.item.container ? <FolderIcon color="primary" /> : stream ? <RadioIcon color="primary" /> : <MusicNoteIcon color="primary" />
        ) : (
          <LibraryMusicIcon color={disabled ? "disabled" : "primary"} />
        )}
        <Typography noWrap variant={compact ? "body2" : "body1"} color={disabled ? "text.secondary" : "text.primary"} title={label}>
          {label}
        </Typography>
        {target?.kind === "item" &&
          (compact ? (
            <IconButton size="small" aria-label="Clear selection" onClick={onClear} sx={{ flexShrink: 0, minWidth: 32, minHeight: 32 }}>
              <CloseIcon fontSize="small" />
            </IconButton>
          ) : (
            <Button size="small" onClick={onClear} sx={{ flexShrink: 0 }}>Clear</Button>
          ))}
      </Stack>
      {stream ? (
        <Stack direction="row" spacing={compact ? 1 : 1.5} sx={{ alignItems: "center", flexShrink: 0 }}>
          {!compact && (
            <Typography variant="caption" color="text.secondary" sx={{ maxWidth: 260 }}>{streamNote}</Typography>
          )}
          {target.item.can_favorite && (
            <ActionButton
              compact={compact}
              icon={isFavorite ? <StarIcon /> : <StarBorderIcon />}
              label={isFavorite ? "Remove from Favorites" : "Add to Favorites"}
              onClick={onToggleFavorite}
            />
          )}
          <ActionButton compact={compact} primary icon={<PlayArrowIcon />} label={compact ? `Play (${streamNote.split(":")[1].trim()})` : "Play"} onClick={onPlay} />
        </Stack>
      ) : (
        <QueueActions compact={compact} disabled={disabled} onAdd={onAdd} />
      )}
    </Stack>
  );
}

function Browser({ loc, onNavigate, onHome }: { loc: Location; onNavigate: (path: PathStep[]) => void; onHome: () => void }) {
  const act = useAction();
  const notify = useNotify();
  const enqueue = useEnqueue();
  const playStream = usePlayStream();
  const favorites = useFavorites();
  const favoritesVersion = useAppState((s) => s.favoritesVersion);
  const cid = loc.path.length ? loc.path[loc.path.length - 1].cid : null;
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [playable, setPlayable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [results, setResults] = useState<LibraryItem[] | null>(null);
  const [searchUnsupported, setSearchUnsupported] = useState(false);
  const [shortcuts, setShortcuts] = useState<Shortcut[]>([]);
  const [selected, setSelected] = useState<LibraryItem | null>(null);
  const sentinel = useRef<HTMLDivElement | null>(null);
  const loadingRef = useRef(false);

  const loadPage = useCallback(
    async (start: number, refresh = false) => {
      if (loadingRef.current) return;
      loadingRef.current = true;
      setLoading(true);
      const page = await act(() => api.browse(loc.sid, cid, start, PAGE, refresh));
      loadingRef.current = false;
      setLoading(false);
      if (!page) return;
      setItems((cur) => (start === 0 ? page.items : [...cur, ...page.items]));
      setTotal(page.total);
      setPlayable(page.playable);
    },
    [act, loc.sid, cid],
  );

  // New folder: reset and load the first page; remember it as the last folder (F5.7).
  useEffect(() => {
    setItems([]);
    setTotal(null);
    setFilter("");
    setResults(null);
    setSelected(null);
    loadPage(0);
    if (loc.path.length) api.setLastFolder(loc.sid, loc.path).catch(() => undefined);
  }, [loadPage, loc.sid, loc.path]);

  // The Favorites list itself changes when a favorite is added or removed here.
  useEffect(() => {
    if (loc.sid === FAVORITES_SID && favoritesVersion > 0) {
      setSelected(null);
      loadPage(0, true);
    }
  }, [favoritesVersion, loc.sid, loadPage]);

  useEffect(() => {
    api.shortcuts().then((r) => setShortcuts(r.shortcuts)).catch(() => undefined);
  }, []);

  // Infinite scroll: load the next page when the sentinel becomes visible.
  const hasMore = total !== null && items.length < total;
  useEffect(() => {
    const el = sentinel.current;
    if (!el || !hasMore || filter) return;
    const obs = new IntersectionObserver((entries) => entries[0].isIntersecting && loadPage(items.length), { rootMargin: "400px" });
    obs.observe(el);
    return () => obs.disconnect();
  }, [hasMore, items.length, loadPage, filter]);

  const pinned = shortcuts.find((s) => s.sid === loc.sid && s.cid === cid);
  const togglePin = async () => {
    if (pinned) await act(() => api.removeShortcut(pinned.id), "Unpinned");
    else await act(() => api.addShortcut(loc.sid, loc.path), "Folder pinned");
    const r = await act(() => api.shortcuts());
    if (r) setShortcuts(r.shortcuts);
  };

  const runSearch = async () => {
    const q = filter.trim();
    if (!q || searchUnsupported) return;
    try {
      const res = await api.search(loc.sid, q);
      setResults(res.items);
    } catch (err) {
      if (err instanceof ApiError && err.code === "search_not_supported") {
        setSearchUnsupported(true);
        notify("This server does not support search; the box filters this folder instead.", "info");
      } else notify(err instanceof Error ? err.message : String(err), "error");
    }
  };

  const shown = useMemo(() => {
    if (results) return results;
    const q = filter.trim().toLocaleLowerCase();
    if (!q) return items;
    return items.filter((i) => [i.name, i.artist, i.album].some((t) => t.toLocaleLowerCase().includes(q)));
  }, [items, filter, results]);

  const folderName = loc.path.length ? loc.path[loc.path.length - 1].name : loc.server;
  // With nothing selected, the actions apply to the whole folder, if the amp says it can be queued.
  // A folder the amp can queue whole, or one holding queueable tracks (e.g. an Amazon album).
  const folderQueueable = Boolean(cid) && (playable || items.some((i) => !i.container && i.play === "queue"));
  const target: Target = selected
    ? { kind: "item", item: selected }
    : folderQueueable
      ? { kind: "folder", name: folderName, total }
      : null;

  return (
    <Stack sx={{ height: "100%", minHeight: 0 }}>
      <Stack spacing={1.5} sx={{ p: 2, pb: 1, borderBottom: 1, borderColor: "divider" }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <IconButton aria-label="Back" onClick={() => (loc.path.length ? onNavigate(loc.path.slice(0, -1)) : onHome())}>
            <ArrowBackIcon />
          </IconButton>
          <Breadcrumbs maxItems={5} itemsAfterCollapse={2} sx={{ flex: 1, minWidth: 0 }}>
            <Link component="button" underline="hover" color="inherit" onClick={onHome}>Source</Link>
            {loc.path.length > 0 ? (
              <Link component="button" underline="hover" color="inherit" onClick={() => onNavigate([])}>{loc.server}</Link>
            ) : (
              <Typography color="text.primary">{loc.server}</Typography>
            )}
            {loc.path.map((step, i) =>
              i === loc.path.length - 1 ? (
                <Typography key={step.cid} color="text.primary" noWrap>{step.name}</Typography>
              ) : (
                <Link key={step.cid} component="button" underline="hover" color="inherit" onClick={() => onNavigate(loc.path.slice(0, i + 1))}>
                  {step.name}
                </Link>
              ),
            )}
          </Breadcrumbs>
          <Tooltip title="Reload this folder">
            <IconButton onClick={() => loadPage(0, true)} aria-label="Reload">
              <RefreshIcon />
            </IconButton>
          </Tooltip>
          {loc.path.length > 0 && (
            <Tooltip title={pinned ? "Unpin folder" : "Pin folder"}>
              <IconButton onClick={togglePin} color={pinned ? "primary" : "default"} aria-pressed={Boolean(pinned)}>
                {pinned ? <PushPinIcon /> : <PushPinOutlinedIcon />}
              </IconButton>
            </Tooltip>
          )}
        </Stack>
        <Stack direction={{ xs: "column", md: "row" }} spacing={1.5} sx={{ alignItems: { md: "center" } }}>
          <TextField
            size="small"
            placeholder={searchUnsupported ? `Filter ${folderName}` : `Filter ${folderName} · Enter searches the server`}
            value={filter}
            onChange={(e) => {
              setFilter(e.target.value);
              setResults(null);
            }}
            onKeyDown={(e) => e.key === "Enter" && runSearch()}
            sx={{ flex: 1, maxWidth: 480 }}
            slotProps={{ input: { startAdornment: <InputAdornment position="start"><SearchIcon fontSize="small" /></InputAdornment> } }}
          />
        </Stack>
        <Typography variant="caption" color="text.secondary">
          {results
            ? `${results.length} search results`
            : total === null
              ? "Loading…"
              : filter
                ? `${shown.length} of ${items.length} loaded${hasMore ? ` (folder has ${total})` : ""}`
                : `${total} item${total === 1 ? "" : "s"}`}
        </Typography>
      </Stack>
      <Box sx={{ flex: 1, overflowY: "auto", px: 1 }}>
        {total === 0 && <Typography color="text.secondary" sx={{ p: 2 }}>This folder is empty.</Typography>}
        <List dense disablePadding>
          {shown.map((item, i) => (
            <ItemRow
              key={`${itemKey(item)}|${i}`}
              item={item}
              selected={selected !== null && itemKey(selected) === itemKey(item)}
              onSelect={() => setSelected((cur) => (cur && itemKey(cur) === itemKey(item) ? null : item))}
              onOpen={() => item.cid && onNavigate([...loc.path, { cid: item.cid, name: item.name }])}
            />
          ))}
        </List>
        <Box ref={sentinel} sx={{ display: "grid", placeItems: "center", py: 2 }}>
          {loading && <CircularProgress size={24} />}
          {hasMore && filter && !results && (
            <Button size="small" onClick={() => loadPage(items.length)}>Load more to filter ({items.length} of {total})</Button>
          )}
        </Box>
      </Box>
      <ActionBar
        target={target}
        isFavorite={Boolean(selected?.mid && (selected.play === "favorite" || favorites.mids.has(selected.mid)))}
        onToggleFavorite={() => {
          if (!selected?.mid) return;
          const isFav = selected.play === "favorite" || favorites.mids.has(selected.mid);
          if (isFav) favorites.remove(selected.mid, selected.name);
          else favorites.add({ sid: selected.sid, mid: selected.mid, name: selected.name });
        }}
        onClear={() => setSelected(null)}
        onPlay={() => selected && playStream(selected)}
        onAdd={(mode) => {
          if (selected) enqueue([queueItemFor(selected, cid)], mode);
          else if (folderQueueable && cid) enqueue([{ sid: loc.sid, cid }], mode);
        }}
      />
    </Stack>
  );
}

export function SourceView() {
  const [loc, setLoc] = useState<Location | null>(null);
  if (!loc) return <SourceHome onOpen={setLoc} />;
  return <Browser loc={loc} onNavigate={(path) => setLoc({ ...loc, path })} onHome={() => setLoc(null)} />;
}
