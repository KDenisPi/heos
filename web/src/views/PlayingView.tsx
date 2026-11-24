import { Box, Typography } from "@mui/material";
import { NowPlaying } from "../components/NowPlaying";
import { useSelectedPlayer } from "../hooks/useSelectedPlayer";

/**
 * Playing: now playing and the controls only, in one centred column.
 * The queue has its own screen, so both fit a phone as they are.
 */
export function PlayingView() {
  const player = useSelectedPlayer();
  if (!player) {
    return (
      <Typography color="text.secondary" sx={{ p: 3 }}>
        No player yet. Check the Devices screen.
      </Typography>
    );
  }
  return (
    <Box sx={{ minHeight: "100%", display: "flex", alignItems: "center", justifyContent: "center", py: 2 }}>
      <Box sx={{ width: "100%", maxWidth: 560 }}>
        <NowPlaying player={player} />
      </Box>
    </Box>
  );
}
