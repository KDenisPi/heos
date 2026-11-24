import { Button, Dialog, DialogActions, DialogContent, DialogTitle, TextField } from "@mui/material";
import { useEffect, useState } from "react";
import { ApiError, api } from "../api/client";
import { useNotify } from "../notify";

/** Save the current queue as a local playlist. Asks for the name only (F4.1). */
export function SavePlaylistDialog({ pid, open, onClose }: { pid: number; open: boolean; onClose: () => void }) {
  const notify = useNotify();
  const [name, setName] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (open) {
      setName("");
      setError(null);
    }
  }, [open]);

  const save = async () => {
    const trimmed = name.trim();
    if (!trimmed || saving) return;
    setSaving(true);
    try {
      const pl = await api.createPlaylist(trimmed, pid);
      onClose();
      notify(
        pl.unresolved
          ? `Saved "${pl.name}" (${pl.count} tracks). ${pl.unresolved} could not be traced to a source and will be skipped when loading.`
          : `Saved "${pl.name}" (${pl.count} tracks)`,
        pl.unresolved ? "warning" : "success",
      );
    } catch (err) {
      // A name clash stays in the dialog, so another name can be typed right away.
      setError(err instanceof ApiError || err instanceof Error ? err.message : String(err));
    } finally {
      setSaving(false);
    }
  };

  return (
    <Dialog open={open} onClose={onClose} fullWidth maxWidth="xs">
      <DialogTitle>Save queue as playlist</DialogTitle>
      <DialogContent>
        <TextField
          autoFocus
          fullWidth
          margin="dense"
          label="Playlist name"
          value={name}
          error={error !== null}
          helperText={error ?? " "}
          onChange={(e) => {
            setName(e.target.value);
            setError(null);
          }}
          onKeyDown={(e) => e.key === "Enter" && save()}
          slotProps={{ htmlInput: { maxLength: 120 } }}
        />
      </DialogContent>
      <DialogActions sx={{ px: 3, pb: 2 }}>
        <Button onClick={onClose}>Cancel</Button>
        <Button variant="contained" onClick={save} disabled={!name.trim() || saving}>Save</Button>
      </DialogActions>
    </Dialog>
  );
}
