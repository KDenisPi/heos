import MusicNoteIcon from "@mui/icons-material/MusicNote";
import InputIcon from "@mui/icons-material/Input";
import PauseIcon from "@mui/icons-material/Pause";
import PlayArrowIcon from "@mui/icons-material/PlayArrow";
import RepeatIcon from "@mui/icons-material/Repeat";
import RepeatOneIcon from "@mui/icons-material/RepeatOne";
import ShuffleIcon from "@mui/icons-material/Shuffle";
import SkipNextIcon from "@mui/icons-material/SkipNext";
import SkipPreviousIcon from "@mui/icons-material/SkipPrevious";
import StarIcon from "@mui/icons-material/Star";
import StarBorderIcon from "@mui/icons-material/StarBorder";
import StopIcon from "@mui/icons-material/Stop";
import { Box, IconButton, LinearProgress, Stack, Tooltip, Typography } from "@mui/material";
import { api } from "../api/client";
import type { PlayerState, Repeat } from "../api/types";
import { useFavorites } from "../hooks/useFavorites";
import { useNow } from "../hooks/useNow";
import { useAction } from "../notify";
import { livePosition } from "../state/reducer";
import { store, useAppState } from "../state/store";
import { formatTime } from "../theme";
import { VolumeControl } from "./VolumeControl";

const NEXT_REPEAT: Record<Repeat, Repeat> = { off: "on_all", on_all: "on_one", on_one: "off" };

function inputLabel(input: string): string {
  return input.replace(/^inputs\//, "").replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}

export function NowPlaying({ player, compact = false }: { player: PlayerState; compact?: boolean }) {
  const act = useAction();
  const progressAt = useAppState((s) => s.progressAt[player.pid]);
  const now = useNow(player.state === "play");
  const np = player.now_playing;
  const { duration } = player.progress;
  const position = livePosition(player, progressAt, now);
  const isInput = Boolean(player.input);
  const title = np.song || np.station || (isInput ? inputLabel(player.input!) : "Nothing playing");
  const subtitle = isInput ? "External input" : [np.artist, np.album].filter(Boolean).join(" · ");
  const pid = player.pid;
  const favorites = useFavorites();
  // Stations (Amazon, favorites) can be starred; external inputs and queue songs cannot.
  const isStation = np.type === "station" && !isInput && Boolean(np.mid);
  const isFavorite = isStation && favorites.mids.has(np.mid!);
  const stationName = np.station || np.song || "station";

  const transport = (action: "play" | "pause" | "stop" | "next" | "prev") => {
    if (action === "play" || action === "pause" || action === "stop") store.patchPlayer(pid, { state: action });
    act(() => api.transport(pid, action));
  };
  const toggleShuffle = () => {
    store.patchPlayer(pid, { shuffle: !player.shuffle });
    act(() => api.setPlayMode(pid, { shuffle: !player.shuffle }));
  };
  const cycleRepeat = () => {
    const repeat = NEXT_REPEAT[player.repeat];
    store.patchPlayer(pid, { repeat });
    act(() => api.setPlayMode(pid, { repeat }));
  };

  const coverSize = compact ? 96 : "100%";
  return (
    <Stack spacing={2} sx={{ p: 2 }}>
      <Stack direction={compact ? "row" : "column"} spacing={2} sx={{ alignItems: compact ? "center" : "stretch" }}>
        <Box
          sx={{
            width: coverSize,
            maxWidth: compact ? 96 : 420,
            aspectRatio: "1 / 1",
            alignSelf: "center",
            borderRadius: 3,
            overflow: "hidden",
            bgcolor: "action.hover",
            display: "grid",
            placeItems: "center",
            flexShrink: 0,
          }}
        >
          {np.image_url ? (
            <Box component="img" src={np.image_url} alt="" sx={{ width: "100%", height: "100%", objectFit: "cover" }} />
          ) : isInput ? (
            <InputIcon sx={{ fontSize: compact ? 40 : 96, color: "text.secondary" }} />
          ) : (
            <MusicNoteIcon sx={{ fontSize: compact ? 40 : 96, color: "text.secondary" }} />
          )}
        </Box>
        <Box sx={{ minWidth: 0, textAlign: compact ? "left" : "center" }}>
          <Stack direction="row" spacing={0.5} sx={{ alignItems: "center", justifyContent: compact ? "flex-start" : "center" }}>
            <Typography variant={compact ? "subtitle1" : "h6"} noWrap title={title}>
              {title}
            </Typography>
            {isStation && (
              <Tooltip title={isFavorite ? "Remove from HEOS Favorites" : "Add to HEOS Favorites"}>
                <IconButton
                  size="small"
                  color={isFavorite ? "primary" : "default"}
                  aria-pressed={isFavorite}
                  aria-label={isFavorite ? "Remove from HEOS Favorites" : "Add to HEOS Favorites"}
                  onClick={() => (isFavorite ? favorites.remove(np.mid!, stationName) : favorites.addNowPlaying(pid, stationName))}
                  sx={{ minWidth: 40, minHeight: 40 }}
                >
                  {isFavorite ? <StarIcon /> : <StarBorderIcon />}
                </IconButton>
              </Tooltip>
            )}
          </Stack>
          {np.type === "station" && np.station && np.station !== title && (
            <Typography variant="body2" color="text.secondary" noWrap>{np.station}</Typography>
          )}
          <Typography variant="body2" color="text.secondary" noWrap title={subtitle}>
            {subtitle || " "}
          </Typography>
        </Box>
      </Stack>

      {/* HEOS has no seek command, so the bar only displays progress. */}
      {!isInput && (
        <Box>
          <LinearProgress
            variant="determinate"
            value={duration > 0 ? (position / duration) * 100 : 0}
            sx={{ height: 6, borderRadius: 3 }}
            aria-label="Playback progress"
          />
          <Stack direction="row" sx={{ mt: 0.5, justifyContent: "space-between" }}>
            <Typography variant="caption" color="text.secondary">{formatTime(position)}</Typography>
            <Typography variant="caption" color="text.secondary">{formatTime(duration)}</Typography>
          </Stack>
        </Box>
      )}

      <Stack direction="row" spacing={0.5} sx={{ justifyContent: "center", alignItems: "center" }}>
        <Tooltip title="Shuffle">
          <IconButton onClick={toggleShuffle} color={player.shuffle ? "primary" : "default"} aria-pressed={player.shuffle}>
            <ShuffleIcon />
          </IconButton>
        </Tooltip>
        <IconButton onClick={() => transport("prev")} aria-label="Previous">
          <SkipPreviousIcon fontSize="large" />
        </IconButton>
        {player.state === "play" ? (
          <IconButton onClick={() => transport(isInput ? "stop" : "pause")} aria-label="Pause"
            sx={{ bgcolor: "primary.main", color: "primary.contrastText", width: 64, height: 64, "&:hover": { bgcolor: "primary.dark" } }}>
            {isInput ? <StopIcon fontSize="large" /> : <PauseIcon fontSize="large" />}
          </IconButton>
        ) : (
          <IconButton onClick={() => transport("play")} aria-label="Play"
            sx={{ bgcolor: "primary.main", color: "primary.contrastText", width: 64, height: 64, "&:hover": { bgcolor: "primary.dark" } }}>
            <PlayArrowIcon fontSize="large" />
          </IconButton>
        )}
        <IconButton onClick={() => transport("next")} aria-label="Next">
          <SkipNextIcon fontSize="large" />
        </IconButton>
        <Tooltip title={`Repeat: ${player.repeat.replace("_", " ")}`}>
          <IconButton onClick={cycleRepeat} color={player.repeat === "off" ? "default" : "primary"}>
            {player.repeat === "on_one" ? <RepeatOneIcon /> : <RepeatIcon />}
          </IconButton>
        </Tooltip>
      </Stack>

      <VolumeControl player={player} />
    </Stack>
  );
}
