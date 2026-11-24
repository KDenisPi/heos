import AlbumIcon from "@mui/icons-material/Album";
import CableIcon from "@mui/icons-material/Cable";
import DiscFullIcon from "@mui/icons-material/DiscFull";
import InputIcon from "@mui/icons-material/Input";
import LightModeIcon from "@mui/icons-material/LightMode";
import SettingsInputComponentIcon from "@mui/icons-material/SettingsInputComponent";
import TvIcon from "@mui/icons-material/Tv";
import { Box, ButtonBase, CircularProgress, Stack, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { InputItem } from "../api/types";
import { useSelectedDevice, useSelectedPid } from "../hooks/useSelectedPlayer";
import { useAction } from "../notify";
import { useAppState } from "../state/store";

function iconFor(input: string) {
  if (input.includes("phono")) return <AlbumIcon fontSize="inherit" />;
  if (input.includes("cd")) return <DiscFullIcon fontSize="inherit" />;
  if (input.includes("optical")) return <LightModeIcon fontSize="inherit" />;
  if (input.includes("coax")) return <CableIcon fontSize="inherit" />;
  if (input.includes("hdmi") || input.includes("tv")) return <TvIcon fontSize="inherit" />;
  if (input.includes("aux") || input.includes("line")) return <SettingsInputComponentIcon fontSize="inherit" />;
  return <InputIcon fontSize="inherit" />;
}

export function InputsView() {
  const act = useAction();
  const pid = useSelectedPid();
  const device = useSelectedDevice();
  const current = useAppState((s) => (pid === null ? null : s.players[pid]?.input ?? null));
  const heosConnected = useAppState((s) => s.heos.connected);
  const [inputs, setInputs] = useState<InputItem[] | null>(null);
  const [busy, setBusy] = useState<string | null>(null);

  useEffect(() => {
    if (pid === null || !heosConnected) return;
    setInputs(null);
    act(() => api.inputs(pid)).then((res) => res && setInputs(res.inputs));
  }, [act, pid, heosConnected]);

  const choose = async (input: string) => {
    if (pid === null || busy) return;
    setBusy(input);
    // One tap: power on first if the amp is in standby (spec 7, Inputs screen).
    if (device?.power.state === "standby") {
      const ok = await act(() => api.setPower(pid, true));
      if (!ok) {
        setBusy(null);
        return;
      }
    }
    await act(() => api.selectInput(pid, input));
    setBusy(null);
  };

  return (
    <Stack spacing={2} sx={{ p: 3 }}>
      <Typography variant="h5">Inputs</Typography>
      {inputs === null ? (
        <CircularProgress />
      ) : inputs.length === 0 ? (
        <Typography color="text.secondary">This device reports no external inputs.</Typography>
      ) : (
        <Box sx={{ display: "grid", gap: 2, gridTemplateColumns: "repeat(auto-fill, minmax(180px, 1fr))" }}>
          {inputs.map((i) => {
            const active = i.input === current;
            return (
              <ButtonBase
                key={i.input}
                onClick={() => choose(i.input)}
                aria-pressed={active}
                sx={{
                  flexDirection: "column",
                  gap: 1,
                  height: 160,
                  borderRadius: 4,
                  border: 2,
                  borderColor: active ? "primary.main" : "divider",
                  bgcolor: active ? "action.selected" : "background.paper",
                  fontSize: 56,
                  color: active ? "primary.main" : "text.secondary",
                }}
              >
                {busy === i.input ? <CircularProgress /> : iconFor(i.input)}
                <Typography variant="subtitle1" color={active ? "primary" : "text.primary"}>
                  {i.name}
                </Typography>
              </ButtonBase>
            );
          })}
        </Box>
      )}
    </Stack>
  );
}
