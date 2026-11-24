import {
  Button,
  Card,
  CardContent,
  FormControlLabel,
  Stack,
  Switch,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { api, getToken, setToken } from "../api/client";
import type { Health } from "../api/types";
import { useNotify } from "../notify";
import { type ThemeMode, setPrefs, usePrefs } from "../state/prefs";
import { useAppState } from "../state/store";

export function SettingsView() {
  const prefs = usePrefs();
  const notify = useNotify();
  const account = useAppState((s) => s.account);
  const [token, setTokenInput] = useState(getToken());
  const [health, setHealth] = useState<Health | null>(null);

  useEffect(() => {
    api.health().then(setHealth).catch(() => setHealth(null));
  }, []);

  return (
    <Stack spacing={2} sx={{ p: 3, maxWidth: 720 }}>
      <Typography variant="h5">Settings</Typography>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" gutterBottom>HEOS account</Typography>
          <Typography color="text.secondary">
            {account.signed_in ? `Signed in as ${account.username}` : "Signed out"}. Sign-in from this app comes later (F7.2).
          </Typography>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="subtitle1">Display</Typography>
            <ToggleButtonGroup
              exclusive
              value={prefs.theme}
              onChange={(_, v: ThemeMode | null) => v && setPrefs({ theme: v })}
              size="small"
            >
              <ToggleButton value="dark">Dark</ToggleButton>
              <ToggleButton value="light">Light</ToggleButton>
              <ToggleButton value="system">System</ToggleButton>
            </ToggleButtonGroup>
            <FormControlLabel
              control={<Switch checked={prefs.wakeLock} onChange={(e) => setPrefs({ wakeLock: e.target.checked })} />}
              label="Keep the screen on (wall-mounted tablet)"
            />
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Stack spacing={2}>
            <Typography variant="subtitle1">Access token</Typography>
            <Typography variant="body2" color="text.secondary">
              Only needed if the service runs with HEOS_HOME_TOKEN. Stored in this browser only.
            </Typography>
            <Stack direction="row" spacing={1}>
              <TextField size="small" type="password" label="Token" value={token} onChange={(e) => setTokenInput(e.target.value)} sx={{ flex: 1 }} />
              <Button variant="outlined" onClick={() => { setToken(token.trim()); notify("Token saved", "success"); }}>Save</Button>
            </Stack>
          </Stack>
        </CardContent>
      </Card>

      <Card variant="outlined">
        <CardContent>
          <Typography variant="subtitle1" gutterBottom>About</Typography>
          <Typography variant="body2" color="text.secondary">
            HEOS Home {health ? `service ${health.version}` : ""} · HEOS {health?.heos.connected ? `connected to ${health.heos.host}` : "not connected"}
          </Typography>
        </CardContent>
      </Card>
    </Stack>
  );
}
