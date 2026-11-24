// Library (F5): DLNA servers, pinned folders, folder browsing with breadcrumb,
// paging, a filter for the loaded folder, and play / queue actions.

import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import DnsIcon from "@mui/icons-material/Dns";
import FolderIcon from "@mui/icons-material/Folder";
import HistoryIcon from "@mui/icons-material/History";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import PlaylistPlayIcon from "@mui/icons-material/PlaylistPlay";
import PushPinIcon from "@mui/icons-material/PushPin";
import PushPinOutlinedIcon from "@mui/icons-material/PushPinOutlined";
import QueueMusicIcon from "@mui/icons-material/QueueMusic";
import RefreshIcon from "@mui/icons-material/Refresh";
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
  Menu,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { AddMode, LibraryItem, PathStep, QueueAddItem, Shortcut } from "../api/types";
import { useSelectedPid } from "../hooks/useSelectedPlayer";
import { useAction, useNotify } from "../notify";
import { useAppState } from "../state/store";

const PAGE = 50;

interface Location {
  sid: number;
  server: string;
  path: PathStep[];
}

const MODE_LABEL: Record<AddMode, string> = {
  now: "Playing now",
  next: "Plays next",
  end: "Added to queue",
  replace: "Queue replaced",
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

function queueItemFor(item: LibraryItem, folderCid: string | null): QueueAddItem {
  // A track is queued with its folder's cid plus its mid; a container with its own cid.
  return item.container ? { sid: item.sid, cid: item.cid } : { sid: item.sid, cid: folderCid, mid: item.mid };
}

// ------------------------------------------------------------------- home
function LibraryHome({ onOpen }: { onOpen: (loc: Location) => void }) {
  const act = useAction();
  const heosConnected = useAppState((s) => s.heos.connected);
  const [servers, setServers] = useState<LibraryItem[] | null>(null);
  const [shortcuts, setShortcuts] = useState<Shortcut[]>([]);
  const [lastFolders, setLastFolders] = useState<Record<number, PathStep[]>>({});

  useEffect(() => {
    if (!heosConnected) return;
    act(() => api.libraryServers()).then(async (res) => {
      if (!res) return;
      setServers(res.servers);
      const entries = await Promise.all(
        res.servers.map(async (s) => [s.sid, (await api.lastFolder(s.sid).catch(() => ({ path: [] }))).path] as const),
      );
      setLastFolders(Object.fromEntries(entries));
    });
    api.shortcuts().then((r) => setShortcuts(r.shortcuts)).catch(() => undefined);
  }, [act, heosConnected]);

  const serverName = (sid: number) => servers?.find((s) => s.sid === sid)?.name ?? "Server";
  const unpin = async (id: number) => {
    await act(() => api.removeShortcut(id));
    const r = await act(() => api.shortcuts());
    if (r) setShortcuts(r.shortcuts);
  };

  return (
    <Stack spacing={3} sx={{ p: 3 }}>
      <Typography variant="h5">Library</Typography>

      <Box>
        <Typography variant="subtitle1" gutterBottom>Media servers</Typography>
        {servers === null ? (
          heosConnected ? <CircularProgress size={28} /> : <Typography color="text.secondary">Not connected</Typography>
        ) : servers.length === 0 ? (
          <Typography color="text.secondary">The HEOS device sees no DLNA servers.</Typography>
        ) : (
          <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(240px, 1fr))" }}>
            {servers.map((s) => {
              const last = lastFolders[s.sid] ?? [];
              return (
                <Box key={s.sid} sx={{ border: 1, borderColor: "divider", borderRadius: 4, bgcolor: "background.paper", overflow: "hidden" }}>
                  <ButtonBase onClick={() => onOpen({ sid: s.sid, server: s.name, path: [] })} sx={{ width: "100%", justifyContent: "flex-start", gap: 2, p: 2 }}>
                    <DnsIcon color="primary" sx={{ fontSize: 40 }} />
                    <Box sx={{ textAlign: "left", minWidth: 0 }}>
                      <Typography variant="subtitle1" noWrap>{s.name}</Typography>
                      <Typography variant="caption" color="text.secondary">DLNA server</Typography>
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
                <ListItemButton onClick={() => onOpen({ sid: sc.sid, server: serverName(sc.sid), path: sc.path })}>
                  <ListItemAvatar>
                    <Avatar sx={{ bgcolor: "secondary.main", color: "secondary.contrastText" }}><PushPinIcon /></Avatar>
                  </ListItemAvatar>
                  <ListItemText primary={sc.name} secondary={[serverName(sc.sid), ...sc.path.map((p) => p.name)].join(" › ")} />
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
function ItemMenu({
  anchor,
  onClose,
  onAdd,
}: {
  anchor: HTMLElement | null;
  onClose: () => void;
  onAdd: (mode: AddMode) => void;
}) {
  const choose = (mode: AddMode) => {
    onClose();
    onAdd(mode);
  };
  return (
    <Menu anchorEl={anchor} open={anchor !== null} onClose={onClose}>
      <MenuItem onClick={() => choose("now")}><PlayArrowIcon fontSize="small" sx={{ mr: 1.5 }} /> Play now</MenuItem>
      <MenuItem onClick={() => choose("next")}><PlaylistPlayIcon fontSize="small" sx={{ mr: 1.5 }} /> Play next</MenuItem>
      <MenuItem onClick={() => choose("end")}><PlaylistAddIcon fontSize="small" sx={{ mr: 1.5 }} /> Add to queue</MenuItem>
      <MenuItem onClick={() => choose("replace")}><QueueMusicIcon fontSize="small" sx={{ mr: 1.5 }} /> Replace queue</MenuItem>
      <MenuItem disabled>Add to playlist… (phase 3)</MenuItem>
    </Menu>
  );
}

function ItemRow({ item, folderCid, onOpen }: { item: LibraryItem; folderCid: string | null; onOpen: () => void }) {
  const enqueue = useEnqueue();
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  const secondary = [item.artist, item.album].filter(Boolean).join(" · ");
  // Containers open; tracks play now. Everything else is in the ⋮ menu.
  const onClick = item.container ? onOpen : () => enqueue([queueItemFor(item, folderCid)], "now");
  return (
    <ListItem
      disablePadding
      secondaryAction={
        <IconButton edge="end" aria-label={`Actions for ${item.name}`} onClick={(e) => setMenu(e.currentTarget)}>
          <MoreVertIcon />
        </IconButton>
      }
    >
      <ListItemButton onClick={onClick} sx={{ pr: 7 }}>
        <ListItemAvatar>
          {item.image_url ? (
            <Avatar variant="rounded" src={item.image_url} alt="" slotProps={{ img: { loading: "lazy" } }} />
          ) : (
            <Avatar variant="rounded" sx={{ bgcolor: "action.hover", color: "text.secondary" }}>
              {item.container ? <FolderIcon /> : <MusicNoteIcon />}
            </Avatar>
          )}
        </ListItemAvatar>
        <ListItemText primary={item.name} secondary={secondary || undefined} slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }} />
      </ListItemButton>
      <ItemMenu anchor={menu} onClose={() => setMenu(null)} onAdd={(mode) => enqueue([queueItemFor(item, folderCid)], mode)} />
    </ListItem>
  );
}

function Browser({ loc, onNavigate, onHome }: { loc: Location; onNavigate: (path: PathStep[]) => void; onHome: () => void }) {
  const act = useAction();
  const notify = useNotify();
  const enqueue = useEnqueue();
  const cid = loc.path.length ? loc.path[loc.path.length - 1].cid : null;
  const [items, setItems] = useState<LibraryItem[]>([]);
  const [total, setTotal] = useState<number | null>(null);
  const [playable, setPlayable] = useState(false);
  const [loading, setLoading] = useState(false);
  const [filter, setFilter] = useState("");
  const [results, setResults] = useState<LibraryItem[] | null>(null);
  const [searchUnsupported, setSearchUnsupported] = useState(false);
  const [shortcuts, setShortcuts] = useState<Shortcut[]>([]);
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
    loadPage(0);
    if (loc.path.length) api.setLastFolder(loc.sid, loc.path).catch(() => undefined);
  }, [loadPage, loc.sid, loc.path]);

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

  return (
    <Stack sx={{ height: "100%", minHeight: 0 }}>
      <Stack spacing={1.5} sx={{ p: 2, pb: 1, borderBottom: 1, borderColor: "divider" }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <IconButton aria-label="Back" onClick={() => (loc.path.length ? onNavigate(loc.path.slice(0, -1)) : onHome())}>
            <ArrowBackIcon />
          </IconButton>
          <Breadcrumbs maxItems={5} itemsAfterCollapse={2} sx={{ flex: 1, minWidth: 0 }}>
            <Link component="button" underline="hover" color="inherit" onClick={onHome}>Library</Link>
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
          {playable && cid && (
            <Stack direction="row" spacing={1}>
              <Button variant="contained" startIcon={<PlayArrowIcon />} onClick={() => enqueue([{ sid: loc.sid, cid }], "replace")}>
                Play all
              </Button>
              <Button variant="outlined" startIcon={<PlaylistAddIcon />} onClick={() => enqueue([{ sid: loc.sid, cid }], "end")}>
                Add all
              </Button>
            </Stack>
          )}
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
              key={`${item.cid ?? ""}|${item.mid ?? ""}|${i}`}
              item={item}
              folderCid={cid}
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
    </Stack>
  );
}

export function LibraryView() {
  const [loc, setLoc] = useState<Location | null>(null);
  if (!loc) return <LibraryHome onOpen={setLoc} />;
  return <Browser loc={loc} onNavigate={(path) => setLoc({ ...loc, path })} onHome={() => setLoc(null)} />;
}
