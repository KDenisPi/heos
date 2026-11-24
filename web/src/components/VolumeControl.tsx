import VolumeDownIcon from "@mui/icons-material/VolumeDown";
import VolumeOffIcon from "@mui/icons-material/VolumeOff";
import VolumeUpIcon from "@mui/icons-material/VolumeUp";
import { IconButton, Slider, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PlayerState } from "../api/types";
import { useThrottled } from "../hooks/useThrottled";
import { useAction } from "../notify";
import { store } from "../state/store";

export function VolumeControl({ player }: { player: PlayerState }) {
  const act = useAction();
  const pid = player.pid;
  // While dragging, the slider shows the local value; server events take over after release.
  const [dragValue, setDragValue] = useState<number | null>(null);
  const send = useThrottled((level: number) => {
    act(() => api.setVolume(pid, level));
  }, 150);

  useEffect(() => setDragValue(null), [pid]);

  const value = dragValue ?? player.volume;
  const toggleMute = () => {
    store.patchPlayer(pid, { mute: !player.mute });
    act(() => api.setMute(pid, !player.mute));
  };

  return (
    <Stack direction="row" spacing={1} sx={{ alignItems: "center" }}>
      <IconButton onClick={toggleMute} aria-label={player.mute ? "Unmute" : "Mute"} color={player.mute ? "error" : "default"}>
        {player.mute ? <VolumeOffIcon /> : value < 40 ? <VolumeDownIcon /> : <VolumeUpIcon />}
      </IconButton>
      <Slider
        value={value}
        min={0}
        max={100}
        aria-label="Volume"
        onChange={(_, v) => {
          const level = v as number;
          setDragValue(level);
          send(level);
        }}
        onChangeCommitted={(_, v) => {
          const level = v as number;
          store.patchPlayer(pid, { volume: level });
          send(level); // the throttle always delivers the final value
          setDragValue(null);
        }}
        sx={{ flex: 1 }}
      />
      <Typography variant="body2" sx={{ width: 32, textAlign: "right" }} color={player.mute ? "text.disabled" : "text.primary"}>
        {value}
      </Typography>
    </Stack>
  );
}
