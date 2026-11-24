import { DndContext, type DragEndEvent, PointerSensor, TouchSensor, closestCenter, useSensor, useSensors } from "@dnd-kit/core";
import { SortableContext, arrayMove, useSortable, verticalListSortingStrategy } from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import ClearAllIcon from "@mui/icons-material/ClearAll";
import CloseIcon from "@mui/icons-material/Close";
import DragIndicatorIcon from "@mui/icons-material/DragIndicator";
import EqualizerIcon from "@mui/icons-material/Equalizer";
import MoreVertIcon from "@mui/icons-material/MoreVert";
import {
  Box,
  CircularProgress,
  IconButton,
  List,
  ListItem,
  ListItemButton,
  ListItemText,
  Menu,
  MenuItem,
  Stack,
  Typography,
} from "@mui/material";
import { useCallback, useEffect, useState } from "react";
import { api } from "../api/client";
import type { QueueItem } from "../api/types";
import { useAction } from "../notify";
import { useAppState } from "../state/store";

function Row({
  item,
  current,
  onPlay,
  onRemove,
}: {
  item: QueueItem;
  current: boolean;
  onPlay: () => void;
  onRemove: () => void;
}) {
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: item.qid,
  });
  return (
    <ListItem
      ref={setNodeRef}
      disablePadding
      style={{ transform: CSS.Transform.toString(transform), transition }}
      sx={{ opacity: isDragging ? 0.6 : 1, zIndex: isDragging ? 1 : "auto", bgcolor: isDragging ? "background.paper" : undefined }}
      secondaryAction={
        <IconButton edge="end" aria-label={`Remove ${item.song}`} onClick={onRemove}>
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
          <MenuItem disabled>Sort… (coming next)</MenuItem>
          <MenuItem disabled>Save as playlist… (phase 3)</MenuItem>
        </Menu>
      </Stack>
      <Box sx={{ flex: 1, overflowY: "auto", px: 1, pb: 2 }}>
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
                    onPlay={() => act(() => api.playQueueItem(pid, item.qid))}
                    onRemove={() => remove(item.qid)}
                  />
                ))}
              </List>
            </SortableContext>
          </DndContext>
        )}
      </Box>
    </Stack>
  );
}
