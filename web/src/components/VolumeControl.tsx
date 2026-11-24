import AddIcon from "@mui/icons-material/Add";
import RemoveIcon from "@mui/icons-material/Remove";
import VolumeDownIcon from "@mui/icons-material/VolumeDown";
import VolumeOffIcon from "@mui/icons-material/VolumeOff";
import VolumeUpIcon from "@mui/icons-material/VolumeUp";
import { IconButton, Slider, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { PlayerState } from "../api/types";
import { useThrottled } from "../hooks/useThrottled";
import { useAction } from "../notify";
import { store, useAppState } from "../state/store";

/**
 * Mute, "-", slider, "+". The slider ends at the configured maximum (Settings);
 * the service caps every change too, so no client can go past it.
 */
export function VolumeControl({ player }: { player: PlayerState }) {
  const act = useAction();
  const pid = player.pid;
  const { volume_max: max, volume_step: step } = useAppState((s) => s.settings);
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
  const stepBy = (delta: number) => {
    const target = Math.max(0, delta > 0 ? Math.min(max, player.volume + delta) : player.volume + delta);
    if (target === player.volume) return;
    store.patchPlayer(pid, { volume: target });
    act(() => api.stepVolume(pid, delta));
  };

  return (
    <Stack spacing={0}>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
        <IconButton onClick={toggleMute} aria-label={player.mute ? "Unmute" : "Mute"} color={player.mute ? "error" : "default"}>
          {player.mute ? <VolumeOffIcon /> : value < max * 0.4 ? <VolumeDownIcon /> : <VolumeUpIcon />}
        </IconButton>
        <IconButton onClick={() => stepBy(-step)} disabled={player.volume <= 0} aria-label="Volume down">
          <RemoveIcon />
        </IconButton>
        <Slider
          value={Math.min(value, max)}
          min={0}
          max={max}
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
          sx={{ flex: 1, mx: 1 }}
        />
        <IconButton onClick={() => stepBy(step)} disabled={player.volume >= max} aria-label="Volume up">
          <AddIcon />
        </IconButton>
        <Typography
          variant="body2"
          sx={{ width: 32, textAlign: "right" }}
          color={player.mute ? "text.disabled" : value > max ? "warning.main" : "text.primary"}
        >
          {value}
        </Typography>
      </Stack>
      <Typography variant="caption" color="text.secondary" sx={{ textAlign: "right", pr: 0.5 }}>
        {value > max ? `above the app's limit (${max}), set elsewhere` : `max ${max}`}
      </Typography>
    </Stack>
  );
}
