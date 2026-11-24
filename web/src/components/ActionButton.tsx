import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import PlaylistAddIcon from "@mui/icons-material/PlaylistAdd";
import QueueMusicIcon from "@mui/icons-material/QueueMusic";
import { Button, IconButton, Stack, Tooltip } from "@mui/material";
import type { ReactNode } from "react";
import type { AddMode } from "../api/types";

/**
 * A labelled button on tablets; on phones (``compact``) an icon button whose
 * label is a tooltip (long press on touch) and its accessible name.
 */
export function ActionButton({
  icon,
  label,
  onClick,
  disabled = false,
  primary = false,
  compact,
}: {
  icon: ReactNode;
  label: string;
  onClick: () => void;
  disabled?: boolean;
  primary?: boolean;
  compact: boolean;
}) {
  if (!compact) {
    return (
      <Button variant={primary ? "contained" : "outlined"} startIcon={icon} disabled={disabled} onClick={onClick}>
        {label}
      </Button>
    );
  }
  return (
    <Tooltip title={label} enterTouchDelay={400}>
      {/* span: a tooltip needs an element that still receives events when the button is disabled */}
      <span>
        <IconButton
          aria-label={label}
          disabled={disabled}
          onClick={onClick}
          sx={
            primary
              ? {
                  bgcolor: "primary.main",
                  color: "primary.contrastText",
                  "&:hover": { bgcolor: "primary.dark" },
                  "&.Mui-disabled": { bgcolor: "action.disabledBackground" },
                }
              : { border: 1, borderColor: "divider" }
          }
        >
          {icon}
        </IconButton>
      </span>
    </Tooltip>
  );
}

/** The three ways to put music into the queue, used on Source and in playlists. */
export function QueueActions({
  onAdd,
  disabled = false,
  compact,
}: {
  onAdd: (mode: AddMode) => void;
  disabled?: boolean;
  compact: boolean;
}) {
  return (
    <Stack direction="row" spacing={1} sx={{ flexWrap: compact ? "nowrap" : "wrap", rowGap: 1, flexShrink: 0 }}>
      <ActionButton compact={compact} primary icon={<PlayArrowIcon />} label="Add and play" disabled={disabled} onClick={() => onAdd("now")} />
      <ActionButton compact={compact} icon={<QueueMusicIcon />} label="Replace queue and play" disabled={disabled} onClick={() => onAdd("replace")} />
      <ActionButton compact={compact} icon={<PlaylistAddIcon />} label="Add to end of queue" disabled={disabled} onClick={() => onAdd("end")} />
    </Stack>
  );
}
