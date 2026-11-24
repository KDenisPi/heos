import { Card, CardContent, Slider, Stack, ToggleButton, ToggleButtonGroup, Typography } from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import { useAction } from "../notify";
import { useAppState } from "../state/store";

/** Maximum volume (default 50) and the step of the - / + buttons; stored on the server for all clients. */
export function VolumeSettingsCard() {
  const act = useAction();
  const settings = useAppState((s) => s.settings);
  const [max, setMax] = useState(settings.volume_max);
  useEffect(() => setMax(settings.volume_max), [settings.volume_max]);

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="subtitle1">Volume</Typography>
          <Stack spacing={0.5}>
            <Typography variant="body2">Maximum volume: {max}</Typography>
            <Slider
              value={max}
              min={5}
              max={100}
              step={5}
              marks={[{ value: 50, label: "50" }, { value: 100, label: "100" }]}
              aria-label="Maximum volume"
              onChange={(_, v) => setMax(v as number)}
              onChangeCommitted={(_, v) => act(() => api.patchSettings({ volume_max: v as number }), `Maximum volume set to ${v}`)}
              sx={{ maxWidth: 480 }}
            />
            <Typography variant="caption" color="text.secondary">
              This app (and every client of this server) never sets the volume above this level. The amp's own remote and the
              official HEOS app are not limited.
            </Typography>
          </Stack>
          <Stack direction="row" spacing={2} sx={{ alignItems: "center" }}>
            <Typography variant="body2">Step of − / +</Typography>
            <ToggleButtonGroup
              exclusive
              size="small"
              value={settings.volume_step}
              onChange={(_, v: number | null) => v && act(() => api.patchSettings({ volume_step: v }))}
            >
              {[1, 2, 5].map((n) => (
                <ToggleButton key={n} value={n}>{n}</ToggleButton>
              ))}
            </ToggleButtonGroup>
          </Stack>
        </Stack>
      </CardContent>
    </Card>
  );
}
