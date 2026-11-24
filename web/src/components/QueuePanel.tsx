import { DndContext, type DragEndEvent, PointerSensor, TouchSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import ClearAllIcon from "@mui/icons-material/ClearAll";
import CloseIcon from "@mui/icons-material/Close";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import EqualizerIcon from "@mui/icons-material/Equalizer";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import SaveIcon from "@mui/icons-material/Save";
import ShuffleIcon from "@mui/icons-material/Shuffle";
import SortByAlphaIcon from "@mui/icons-material/SortByAlpha";
import SwapVertIcon from "@mui/icons-material/SwapVert";
import {
  Box,
  CircularProgress,
  Divider,
  IconButton,
  LinearProgress,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  ListSubheader,
  Menu,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { QueueItem, SortKey } from "../api/types";
import { useAction } from "../notify";
import { useAppState } from "../state/store";
import { SavePlaylistDialog } from "./SavePlaylistDialog";

function Row({
  item,
  current,
  locked,
  onPlay,
  onRemove,
}: {
  item: QueueItem;
  current: boolean;
  locked: boolean;
  onPlay: () => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: item.qid,
    disabled: locked,
  });
  return (
    <ListItem
      ref={setNodeRef}
      disablePadding
      style={{ transform: CSS.Transform.toString(transform), transition }}
      sx={{ opacity: isDragging ? 0.6 : 1, zIndex: isDragging ? 1 : "auto", bgcolor: isDragging ? "background.paper" : undefined }}
      secondaryAction={
        <IconButton edge="end" aria-label={`Remove ${item.song}`} onClick={onRemove} disabled={locked}>
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
      <ListItemButton onClick={onPlay} selected={current} sx={{ pr: 6 }}>
        <ListItemText
          primary={item.song}
          secondary={[item.artist, item.album].filter(Boolean).join(" · ")}
          slotProps={{
            primary: { noWrap: true, color: current ? "primary" : undefined },
            secondary: { noWrap: true },
          }}
        />
        {current && <EqualizerIcon color="primary" fontSize="small" sx={{ ml: 1 }} />}
      </ListItemButton>
    </ListItem>
  );
}

export function QueuePanel({ pid }: { pid: number }) {
  const act = useAction();
  const version = useAppState((s) => s.queueVersion[pid] ?? 0);
  const currentQid = useAppState((s) => s.players[pid]?.now_playing.qid);
  const heosConnected = useAppState((s) => s.heos.connected);
  const [items, setItems] = useState<QueueItem[] | null>(null);
  const [menu, setMenu] = useState<HTMLElement | null>(null);
  const [descending, setDescending] = useState(false);
  const [saving, setSaving] = useState(false);
  const sort = useAppState((s) => s.queueSort[pid]);
  const sorting = sort?.state === "running";

  const sortBy = (by: SortKey) => {
    setMenu(null);
    const order = descending ? "desc" : "asc";
    act(() => api.sortQueue(pid, by, order), by === "random" ? "Queue shuffled" : "Queue sorted");
  };

  const load = useCallback(async () => {
    const res = await act(() => api.queue(pid));
    if (res) setItems(res.items);
  }, [act, pid]);

  useEffect(() => {
    if (heosConnected) load();
  }, [load, version, heosConnected]);

  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(TouchSensor, { activationConstraint: { delay: 150, tolerance: 6 } }),
  );

  const onDragEnd = (ev: DragEndEvent) => {
    if (!items || !ev.over || ev.active.id === ev.over.id) return;
    const from = items.findIndex((i) => i.qid === ev.active.id);
    const to = items.findIndex((i) => i.qid === ev.over!.id);
    const moved = items[from];
    // Optimistic reorder; the queue_changed event brings the authoritative order.
    setItems(arrayMove(items, from, to));
    act(() => api.moveQueue(pid, [moved.qid], to + 1));
  };

  const remove = (qid: number) => {
    setItems((cur) => cur?.filter((i) => i.qid !== qid) ?? cur);
    act(() => api.removeFromQueue(pid, [qid]));
  };

  return (
    <Stack sx={{ minHeight: 0, flex: 1 }}>
      <Stack direction="row" sx={{ px: 2, py: 1, alignItems: "center" }}>
        <Typography variant="subtitle1" sx={{ flex: 1 }}>
          Queue {items ? <Typography component="span" color="text.secondary">· {items.length}</Typography> : null}
        </Typography>
        <IconButton aria-label="Queue actions" onClick={(e) => setMenu(e.currentTarget)}>
          <MoreVertIcon />
        </IconButton>
        <Menu anchorEl={menu} open={menu !== null} onClose={() => setMenu(null)}>
          <MenuItem
            disabled={!items?.length}
            onClick={() => {
              setMenu(null);
              setItems([]);
              act(() => api.clearQueue(pid));
            }}
          >
            <ClearAllIcon fontSize="small" sx={{ mr: 1.5 }} /> Clear queue
          </MenuItem>
          <Divider />
          <ListSubheader sx={{ lineHeight: "36px", bgcolor: "transparent" }}>Sort queue</ListSubheader>
          {(["title", "artist", "album"] as const).map((key) => (
            <MenuItem key={key} disabled={!items || items.length < 2 || sorting} onClick={() => sortBy(key)}>
              <SortByAlphaIcon fontSize="small" sx={{ mr: 1.5 }} /> By {key}
            </MenuItem>
          ))}
          <MenuItem onClick={() => setDescending((d) => !d)}>
            <SwapVertIcon fontSize="small" sx={{ mr: 1.5 }} /> Order: {descending ? "Z → A" : "A → Z"}
          </MenuItem>
          <MenuItem disabled={!items || items.length < 2 || sorting} onClick={() => sortBy("random")}>
            <ShuffleIcon fontSize="small" sx={{ mr: 1.5 }} /> Random order
          </MenuItem>
          <Divider />
          <MenuItem
            disabled={!items?.length || sorting}
            onClick={() => {
              setMenu(null);
              setSaving(true);
            }}
          >
            <SaveIcon fontSize="small" sx={{ mr: 1.5 }} /> Save as playlist…
          </MenuItem>
        </Menu>
      </Stack>
      {sorting && (
        <Box sx={{ px: 2, pb: 1 }}>
          <LinearProgress
            variant={sort.total ? "determinate" : "indeterminate"}
            value={sort.total ? ((sort.done ?? 0) / sort.total) * 100 : 0}
            aria-label="Sorting queue"
          />
          <Typography variant="caption" color="text.secondary">
            Sorting… {sort.total ? `${sort.done ?? 0} / ${sort.total} moves` : ""}
          </Typography>
        </Box>
      )}
      <Box sx={{ flex: 1, overflowY: "auto", px: 1, pb: 2, opacity: sorting ? 0.6 : 1 }}>
        {items === null ? (
          <Box sx={{ display: "grid", placeItems: "center", py: 4 }}>
            {heosConnected ? <CircularProgress size={28} /> : <Typography color="text.secondary">Not connected</Typography>}
          </Box>
        ) : items.length === 0 ? (
          <Typography color="text.secondary" sx={{ px: 2, py: 3 }}>
            The queue is empty. Add music from the Library.
          </Typography>
        ) : (
          <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={onDragEnd}>
            <SortableContext items={items.map((i) => i.qid)} strategy={verticalListSortingStrategy}>
              <List dense disablePadding>
                {items.map((item) => (
                  <Row
                    key={item.qid}
                    item={item}
                    current={item.qid === currentQid}
                    locked={sorting}
                    onPlay={() => !sorting && act(() => api.playQueueItem(pid, item.qid))}
                    onRemove={() => remove(item.qid)}
                  />
                ))}
              </List>
            </SortableContext>
          </DndContext>
        )}
      </Box>
      <SavePlaylistDialog pid={pid} open={saving} onClose={() => setSaving(false)} />
    </Stack>
  );
}
