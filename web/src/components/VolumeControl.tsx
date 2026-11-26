import AddIcon from "@mui/icons-material/Add";
import RemoveIcon from "@mui/icons-material/Remove";
import VolumeDownIcon from "@mui/icons-material/VolumeDown";
import VolumeOffIcon from "@mui/icons-material/VolumeOff";
import VolumeUpIcon from "@mui/icons-material/VolumeUp";
import { Box, IconButton, Slider, Stack, Typography } from "@mui/material";
import { useEffect, useState, type SyntheticEvent } from "react";
import { api } from "../api/client";
import type { PlayerState } from "../api/types";
import { useDeviceClass } from "../hooks/useDeviceClass";
import { useThrottled } from "../hooks/useThrottled";
import { useAction } from "../notify";
import { store, useAppState } from "../state/store";

/**
 * Mute, "-", slider, "+". The slider ends at the configured maximum (Settings);
 * the service caps every change too, so no client can go past it.
 *
 * On phones a touch on the slider's bar does nothing: only dragging the handle
 * (or - / +) changes the volume, so a tap meant for the bottom navigation or a
 * swipe across the screen cannot make the volume jump.
 */
export function VolumeControl({ player }: { player: PlayerState }) {
  const act = useAction();
  const pid = player.pid;
  const { volume_max: max, volume_step: step } = useAppState((s) => s.settings);
  const { phone } = useDeviceClass();
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

  // Runs in the capture phase, before the slider's own touch/mouse handlers see the press.
  const blockBarPress = (e: SyntheticEvent) => {
    if (!phone) return;
    const target = e.target as Element | null;
    if (!target?.closest?.(".MuiSlider-thumb")) e.stopPropagation();
  };

  return (
    <Stack spacing={0} sx={{ pb: phone ? 2 : 0 }}>
      <Stack direction="row" spacing={0.5} sx={{ alignItems: "center" }}>
        <IconButton onClick={toggleMute} aria-label={player.mute ? "Unmute" : "Mute"} color={player.mute ? "error" : "default"}>
          {player.mute ? <VolumeOffIcon /> : value < max * 0.4 ? <VolumeDownIcon /> : <VolumeUpIcon />}
        </IconButton>
        <IconButton onClick={() => stepBy(-step)} disabled={player.volume <= 0} aria-label="Volume down">
          <RemoveIcon />
        </IconButton>
        <Box sx={{ flex: 1, mx: 1, display: "flex", alignItems: "center" }}
          onTouchStartCapture={blockBarPress} onMouseDownCapture={blockBarPress}>
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
            // A bigger handle on phones, since only the handle can be dragged there.
            sx={phone ? { "& .MuiSlider-thumb": { width: 26, height: 26 } } : undefined}
          />
        </Box>
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
