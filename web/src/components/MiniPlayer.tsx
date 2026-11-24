import InputIcon from "@mui/icons-material/Input";
import MusicNoteIcon from "@mui/icons-material/MusicNote";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import { Avatar, Box, ButtonBase, IconButton, LinearProgress, Stack, Typography } from "@mui/material";
import { api } from "../api/client";
import { useNow } from "../hooks/useNow";
import { useSelectedPlayer } from "../hooks/useSelectedPlayer";
import { useAction } from "../notify";
import { livePosition } from "../state/reducer";
import { store, useAppState } from "../state/store";

/** Phone: a slim now-playing bar above the bottom navigation; tapping the title opens Playing. */
export function MiniPlayer({ onOpen }: { onOpen: () => void }) {
  const act = useAction();
  const player = useSelectedPlayer();
  const progressAt = useAppState((s) => (player ? s.progressAt[player.pid] : undefined));
  const now = useNow(player?.state === "play", 1000);
  if (!player) return null;
  const np = player.now_playing;
  const isInput = Boolean(player.input);
  const title = np.song || np.station || (isInput ? player.input!.replace(/^inputs\//, "") : "Nothing playing");
  const subtitle = isInput ? "External input" : np.artist || np.album || np.station || "";
  const playing = player.state === "play";
  const { duration } = player.progress;
  const position = livePosition(player, progressAt, now);

  const toggle = () => {
    const action = playing ? (isInput ? "stop" : "pause") : "play";
    store.patchPlayer(player.pid, { state: action });
    act(() => api.transport(player.pid, action));
  };

  return (
    <Box sx={{ bgcolor: "background.paper", borderTop: 1, borderColor: "divider" }}>
      {!isInput && duration > 0 && (
        <LinearProgress variant="determinate" value={(position / duration) * 100} sx={{ height: 2 }} aria-hidden />
      )}
      <Stack direction="row" spacing={0.5} sx={{ alignItems: "center", px: 1, py: 0.5 }}>
        <ButtonBase
          onClick={onOpen}
          aria-label="Open Playing"
          sx={{ flex: 1, minWidth: 0, justifyContent: "flex-start", borderRadius: 2, p: 0.5, gap: 1.5 }}
        >
          {np.image_url ? (
            <Avatar variant="rounded" src={np.image_url} alt="" sx={{ width: 44, height: 44 }} />
          ) : (
            <Avatar variant="rounded" sx={{ width: 44, height: 44, bgcolor: "action.hover", color: "text.secondary" }}>
              {isInput ? <InputIcon /> : <MusicNoteIcon />}
            </Avatar>
          )}
          <Box sx={{ flex: 1, minWidth: 0, textAlign: "left" }}>
            <Typography variant="body2" noWrap>{title}</Typography>
            <Typography variant="caption" color="text.secondary" noWrap component="div">{subtitle || " "}</Typography>
          </Box>
        </ButtonBase>
        <IconButton onClick={toggle} aria-label={playing ? "Pause" : "Play"}>
          {playing ? <PauseIcon /> : <PlayArrowIcon />}
        </IconButton>
        {!isInput && (
          <IconButton onClick={() => act(() => api.transport(player.pid, "next"))} aria-label="Next">
            <SkipNextIcon />
          </IconButton>
        )}
      </Stack>
    </Box>
  );
}
