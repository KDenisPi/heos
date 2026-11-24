// Local playlists (F4): list, open, load into the queue, edit without playing,
// sort, rename, duplicate, export, delete, import.

import { DndContext, type DragEndEvent, PointerSensor, TouchSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import ArrowBackIcon from "@mui/icons-material/ArrowBack";
import CloseIcon from "@mui/icons-material/Close";
import ContentCopyIcon from "@mui/icons-material/ContentCopy";
import DeleteOutlineIcon from "@mui/icons-material/DeleteOutlined";
import DownloadIcon from "@mui/icons-material/Download";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import EditIcon from "@mui/icons-material/Edit";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import QueueMusicIcon from "@mui/icons-material/QueueMusic";
import ShuffleIcon from "@mui/icons-material/Shuffle";
import SortByAlphaIcon from "@mui/icons-material/SortByAlpha";
import SwapVertIcon from "@mui/icons-material/SwapVert";
import UploadFileIcon from "@mui/icons-material/UploadFile";
import WarningAmberIcon from "@mui/icons-material/WarningAmber";
import {
  Avatar,
  Box,
  Button,
  CircularProgress,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemAvatar,
  ListItemButton,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  Stack,
  TextField,
  Tooltip,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api } from "../api/client";
import type { AddMode, Playlist, PlaylistEntry, PlaylistSummary, SortKey } from "../api/types";
import { useSelectedPid } from "../hooks/useSelectedPlayer";
import { useAction, useNotify } from "../notify";
import { useAppState } from "../state/store";

// ------------------------------------------------------------------ list
function PlaylistList({ onOpen }: { onOpen: (id: string) => void }) {
  const act = useAction();
  const notify = useNotify();
  const version = useAppState((s) => s.playlistsVersion);
  const [playlists, setPlaylists] = useState<PlaylistSummary[] | null>(null);
  const fileInput = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    act(() => api.playlists()).then((r) => r && setPlaylists(r.playlists));
  }, [act, version]);

  const importFile = async (file: File) => {
    const text = await file.text();
    try {
      const pl = await api.importPlaylist(text);
      notify(`Imported "${pl.name}" (${pl.count} tracks${pl.unresolved ? `, ${pl.unresolved} unresolved` : ""})`, "success");
    } catch (err) {
      notify(err instanceof ApiError || err instanceof Error ? err.message : String(err), "error");
    }
  };

  return (
    <Stack spacing={2} sx={{ p: 3, maxWidth: 900 }}>
      <Stack direction="row" sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flex: 1 }}>Playlists</Typography>
        <Button variant="outlined" startIcon={<UploadFileIcon />} onClick={() => fileInput.current?.click()}>
          Import .m3u8
        </Button>
        <input
          ref={fileInput}
          type="file"
          accept=".m3u8,.m3u,audio/x-mpegurl,text/plain"
          hidden
          onChange={(e) => {
            const file = e.target.files?.[0];
            if (file) importFile(file);
            e.target.value = "";
          }}
        />
      </Stack>
      {playlists === null ? (
        <CircularProgress />
      ) : playlists.length === 0 ? (
        <Typography color="text.secondary">
          No playlists yet. Build a queue, then use “Save as playlist…” in the queue menu on the Playing screen.
        </Typography>
      ) : (
        <List disablePadding>
          {playlists.map((p) => (
            <ListItem key={p.id} disablePadding>
              <ListItemButton onClick={() => onOpen(p.id)}>
                <ListItemAvatar>
                  <Avatar sx={{ bgcolor: "secondary.main", color: "secondary.contrastText" }}><QueueMusicIcon /></Avatar>
                </ListItemAvatar>
                <ListItemText
                  primary={p.name}
                  secondary={`${p.count} track${p.count === 1 ? "" : "s"}${p.unresolved ? ` · ${p.unresolved} unresolved` : ""}`}
                />
                {p.unresolved > 0 && (
                  <Tooltip title="Some tracks could not be traced to a source and will be skipped">
                    <WarningAmberIcon color="warning" />
                  </Tooltip>
                )}
              </ListItemButton>
            </ListItem>
          ))}
        </List>
      )}
    </Stack>
  );
}

// ---------------------------------------------------------------- detail
function EntryRow({ id, entry, onRemove }: { id: string; entry: PlaylistEntry; onRemove: () => void }) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({ id });
  return (
    <ListItem
      ref={setNodeRef}
      disablePadding
      style={{ transform: CSS.Transform.toString(transform), transition }}
      sx={{ opacity: isDragging ? 0.6 : 1, zIndex: isDragging ? 1 : "auto", bgcolor: isDragging ? "background.paper" : undefined }}
      secondaryAction={
        <IconButton edge="end" aria-label={`Remove ${entry.title}`} onClick={onRemove}>
          <CloseIcon fontSize="small" />
        </IconButton>
      }
    >
      <Box
        ref={setActivatorNodeRef}
        {...attributes}
        {...listeners}
        sx={{ display: "grid", placeItems: "center", width: 40, minHeight: 56, cursor: "grab", touchAction: "none", color: "text.disabled" }}
        aria-label="Drag to reorder"
      >
        <DragIndicatorIcon fontSize="small" />
      </Box>
      <ListItemText
        sx={{ pr: 6, opacity: entry.resolved ? 1 : 0.6 }}
        primary={entry.title}
        secondary={[entry.artist, entry.album].filter(Boolean).join(" · ") || undefined}
        slotProps={{ primary: { noWrap: true }, secondary: { noWrap: true } }}
      />
      {!entry.resolved && (
        <Tooltip title="Source unknown: skipped when loading">
          <WarningAmberIcon color="warning" fontSize="small" sx={{ mr: 6 }} />
        </Tooltip>
      )}
    </ListItem>
  );
}

const LOAD_LABEL: Record<AddMode, string> = {
  now: "Added and playing",
  next: "Plays next",
  end: "Added to end of queue",
  replace: "Queue replaced, playing",
};

function PlaylistDetail({ id, onBack, onRenamed }: { id: string; onBack: () => void; onRenamed: (id: string) => void }) {
  const act = useAction();
  const notify = useNotify();
  const pid = useSelectedPid();
  const version = useAppState((s) => s.playlistsVersion);
  const loadProgress = useAppState((s) => (pid === null ? undefined : s.playlistLoad[pid]));
  const [playlist, setPlaylist] = useState<Playlist | null>(null);
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  const [descending, setDescending] = useState(false);
  const [renaming, setRenaming] = useState(false);
  const [newName, setNewName] = useState("");
  const [renameError, setRenameError] = useState<string | null>(null);
  const [confirmDelete, setConfirmDelete] = useState(false);
  const [loading, setLoading] = useState(false);

  const reload = useCallback(() => act(() => api.playlist(id)).then((p) => p && setPlaylist(p)), [act, id]);
  useEffect(() => {
    reload();
  }, [reload, version]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
  );
  // Rows need stable ids for drag and drop; positions are fine because the list is saved whole.
  const rowIds = playlist ? playlist.items.map((_, i) => `row-${i}`) : [];

  const saveItems = async (items: PlaylistEntry[]) => {
    if (!playlist) return;
    setPlaylist({ ...playlist, items, count: items.length, unresolved: items.filter((i) => !i.resolved).length });
    const saved = await act(() => api.setPlaylistItems(id, items));
    if (saved) setPlaylist(saved);
  };

  const onDragEnd = (ev: DragEndEvent) => {
    if (!playlist || !ev.over || ev.active.id === ev.over.id) return;
    const from = rowIds.indexOf(String(ev.active.id));
    const to = rowIds.indexOf(String(ev.over.id));
    saveItems(arrayMove(playlist.items, from, to));
  };

  const load = async (mode: AddMode) => {
    if (pid === null || loading) return;
    setLoading(true);
    const res = await act(() => api.loadPlaylist(id, pid, mode));
    setLoading(false);
    if (res) {
      notify(
        res.skipped ? `${LOAD_LABEL[mode]}: ${res.tracks} tracks, ${res.skipped} unresolved skipped` : `${LOAD_LABEL[mode]}: ${res.tracks} tracks`,
        res.skipped ? "warning" : "success",
      );
    }
  };

  const sortBy = async (by: SortKey) => {
    setMenu(null);
    const res = await act(() => api.sortPlaylist(id, by, descending ? "desc" : "asc"), by === "random" ? "Playlist shuffled" : "Playlist sorted");
    if (res) setPlaylist(res);
  };

  const rename = async () => {
    const name = newName.trim();
    if (!name) return;
    try {
      const res = await api.renamePlaylist(id, name);
      setRenaming(false);
      notify("Playlist renamed", "success");
      if (res.id !== id) onRenamed(res.id);
      else setPlaylist(res);
    } catch (err) {
      setRenameError(err instanceof Error ? err.message : String(err));
    }
  };

  if (!playlist) {
    return (
      <Box sx={{ p: 3 }}>
        <CircularProgress />
      </Box>
    );
  }

  const playable = playlist.count - playlist.unresolved;
  const showProgress = loading && loadProgress && loadProgress.id === id && loadProgress.total > 1;

  return (
    <Stack sx={{ height: "100%", minHeight: 0 }}>
      <Stack spacing={1} sx={{ p: 2, borderBottom: 1, borderColor: "divider" }}>
        <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
          <IconButton aria-label="Back to playlists" onClick={onBack}>
            <ArrowBackIcon />
          </IconButton>
          <Box sx={{ flex: 1, minWidth: 0 }}>
            <Typography variant="h6" noWrap>{playlist.name}</Typography>
            <Typography variant="caption" color="text.secondary">
              {playlist.count} tracks{playlist.unresolved ? ` · ${playlist.unresolved} unresolved (skipped when loading)` : ""}
            </Typography>
          </Box>
          <IconButton aria-label="Playlist actions" onClick={(e) => setMenu(e.currentTarget)}>
            <MoreVertIcon />
          </IconButton>
          <Menu anchorEl={menu} open={menu !== null} onClose={() => setMenu(null)}>
            <MenuItem
              onClick={() => {
                setMenu(null);
                setNewName(playlist.name);
                setRenameError(null);
                setRenaming(true);
              }}
            >
              <EditIcon fontSize="small" sx={{ mr: 1.5 }} /> Rename…
            </MenuItem>
            <MenuItem
              onClick={async () => {
                setMenu(null);
                await act(() => api.duplicatePlaylist(id), "Playlist duplicated");
              }}
            >
              <ContentCopyIcon fontSize="small" sx={{ mr: 1.5 }} /> Duplicate
            </MenuItem>
            <MenuItem component="a" href={api.exportUrl(id)} download onClick={() => setMenu(null)}>
              <DownloadIcon fontSize="small" sx={{ mr: 1.5 }} /> Export .m3u8
            </MenuItem>
            <Divider />
            <ListSubheader sx={{ lineHeight: "36px", bgcolor: "transparent" }}>Sort playlist</ListSubheader>
            {(["title", "artist", "album"] as const).map((key) => (
              <MenuItem key={key} disabled={playlist.count < 2} onClick={() => sortBy(key)}>
                <SortByAlphaIcon fontSize="small" sx={{ mr: 1.5 }} /> By {key}
              </MenuItem>
            ))}
            <MenuItem onClick={() => setDescending((d) => !d)}>
              <SwapVertIcon fontSize="small" sx={{ mr: 1.5 }} /> Order: {descending ? "Z → A" : "A → Z"}
            </MenuItem>
            <MenuItem disabled={playlist.count < 2} onClick={() => sortBy("random")}>
              <ShuffleIcon fontSize="small" sx={{ mr: 1.5 }} /> Random order
            </MenuItem>
            <Divider />
            <MenuItem
              onClick={() => {
                setMenu(null);
                setConfirmDelete(true);
              }}
              sx={{ color: "error.main" }}
            >
              <DeleteOutlineIcon fontSize="small" sx={{ mr: 1.5 }} /> Delete…
            </MenuItem>
          </Menu>
        </Stack>
        {showProgress && (
          <LinearProgress variant="determinate" value={(loadProgress.done / loadProgress.total) * 100} aria-label="Loading playlist" />
        )}
      </Stack>

      <Box sx={{ flex: 1, overflowY: "auto", px: 1 }}>
        {playlist.items.length === 0 ? (
          <Typography color="text.secondary" sx={{ p: 2 }}>This playlist is empty.</Typography>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={rowIds} strategy={verticalListSortingStrategy}>
              <List dense disablePadding>
                {playlist.items.map((entry, i) => (
                  <EntryRow
                    key={rowIds[i]}
                    id={rowIds[i]}
                    entry={entry}
                    onRemove={() => saveItems(playlist.items.filter((_, j) => j !== i))}
                  />
                ))}
              </List>
            </SortableContext>
          </DndContext>
        )}
      </Box>

      {/* The same three actions as on the Source screen. */}
      <Stack
        direction={{ xs: "column", md: "row" }}
        spacing={1.5}
        sx={{ p: 1.5, px: 2, borderTop: 1, borderColor: "divider", bgcolor: "background.paper", alignItems: { md: "center" } }}
      >
        <Typography color="text.secondary" sx={{ flex: 1 }} noWrap>
          {loading ? "Loading into the queue…" : `Whole playlist · ${playable} playable tracks`}
        </Typography>
        <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
          <Button variant="contained" startIcon={<PlayArrowIcon />} disabled={!playable || loading} onClick={() => load("now")}>
            Add and play
          </Button>
          <Button variant="outlined" startIcon={<QueueMusicIcon />} disabled={!playable || loading} onClick={() => load("replace")}>
            Replace queue and play
          </Button>
          <Button variant="outlined" startIcon={<PlaylistAddIcon />} disabled={!playable || loading} onClick={() => load("end")}>
            Add to end of queue
          </Button>
        </Stack>
      </Stack>

      <Dialog open={renaming} onClose={() => setRenaming(false)} fullWidth maxWidth="xs">
        <DialogTitle>Rename playlist</DialogTitle>
        <DialogContent>
          <TextField
            autoFocus
            fullWidth
            margin="dense"
            label="Playlist name"
            value={newName}
            error={renameError !== null}
            helperText={renameError ?? " "}
            onChange={(e) => {
              setNewName(e.target.value);
              setRenameError(null);
            }}
            onKeyDown={(e) => e.key === "Enter" && rename()}
          />
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setRenaming(false)}>Cancel</Button>
          <Button variant="contained" onClick={rename} disabled={!newName.trim()}>Rename</Button>
        </DialogActions>
      </Dialog>

      <Dialog open={confirmDelete} onClose={() => setConfirmDelete(false)}>
        <DialogTitle>Delete “{playlist.name}”?</DialogTitle>
        <DialogContent>
          <DialogContentText>The .m3u8 file is removed from the server. This cannot be undone.</DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setConfirmDelete(false)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={async () => {
              setConfirmDelete(false);
              const ok = await act(() => api.deletePlaylist(id), "Playlist deleted");
              if (ok !== undefined) onBack();
            }}
          >
            Delete
          </Button>
        </DialogActions>
      </Dialog>
    </Stack>
  );
}

export function PlaylistsView() {
  const [open, setOpen] = useState<string | null>(null);
  if (open === null) return <PlaylistList onOpen={setOpen} />;
  return <PlaylistDetail id={open} onBack={() => setOpen(null)} onRenamed={setOpen} />;
}
