import { Box, Typography } from "@mui/material";
import { QueuePanel } from "../components/QueuePanel";
import { useSelectedPid } from "../hooks/useSelectedPlayer";

/** Queue: the current HEOS queue on its own screen (reorder, remove, sort, save as playlist). */
export function QueueView() {
  const pid = useSelectedPid();
  if (pid === null) {
    return (
      <Typography color="text.secondary" sx={{ p: 3 }}>
        No player yet. Check the Devices screen.
      </Typography>
    );
  }
  return (
    <Box sx={{ height: "100%", display: "flex", flexDirection: "column", maxWidth: 960, mx: "auto", pt: 1 }}>
      <QueuePanel pid={pid} />
    </Box>
  );
}
