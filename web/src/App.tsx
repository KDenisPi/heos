import { Box, CssBaseline, Divider, Stack, Typography, useMediaQuery } from "@mui/material";
import { ThemeProvider } from "@mui/material/styles";
import { useEffect, useMemo, useState } from "react";
import { NavRail, type View } from "./components/NavRail";
import { NowPlaying } from "./components/NowPlaying";
import { QueuePanel } from "./components/QueuePanel";
import { StatusBanner } from "./components/StatusBanner";
import { useSelectedPlayer } from "./hooks/useSelectedPlayer";
import { useWakeLock } from "./hooks/useWakeLock";
import { NotifyProvider, useNotify } from "./notify";
import { usePrefs } from "./state/prefs";
import { store, useAppState } from "./state/store";
import { makeTheme } from "./theme";
import { DevicesView } from "./views/DevicesView";
import { InputsView } from "./views/InputsView";
import { PlaceholderView } from "./views/PlaceholderView";
import { SettingsView } from "./views/SettingsView";

/** Now playing above the queue: the tablet's right panel, or a full view on narrow screens. */
function PlayerPanel() {
  const player = useSelectedPlayer();
  if (!player) {
    return (
      <Typography color="text.secondary" sx={{ p: 3 }}>
        No player yet. Check the Devices screen.
      </Typography>
    );
  }
  return (
    <Stack sx={{ height: "100%", minHeight: 0 }}>
      <NowPlaying player={player} />
      <Divider />
      <QueuePanel pid={player.pid} />
    </Stack>
  );
}

function MainView({ view }: { view: View }) {
  switch (view) {
    case "now":
      return <PlayerPanel />;
    case "inputs":
      return <InputsView />;
    case "devices":
      return <DevicesView />;
    case "settings":
      return <SettingsView />;
    case "library":
      return <PlaceholderView title="Library" text="DLNA servers, Amazon Music and HEOS Favorites arrive in phase 2." />;
    case "playlists":
      return <PlaceholderView title="Playlists" text="Local playlists (M3U8 on the server) arrive in phase 3." />;
  }
}

function PlaybackErrors() {
  const err = useAppState((s) => s.lastPlaybackError);
  const notify = useNotify();
  useEffect(() => {
    if (err) notify(`Playback error: ${err.error}`, "error");
  }, [err, notify]);
  return null;
}

function Shell() {
  // Tablet landscape (≈1280 dp) gets three panes; narrower screens fold the player into a view.
  const wide = useMediaQuery("(min-width: 1000px)");
  const [view, setView] = useState<View>("inputs");
  const shown: View = wide && view === "now" ? "inputs" : view;

  return (
    <Box sx={{ height: "100dvh", display: "flex", flexDirection: "column" }}>
      <StatusBanner />
      <PlaybackErrors />
      <Box sx={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: wide ? "80px minmax(0,1fr) 420px" : "80px minmax(0,1fr)" }}>
        <NavRail view={shown} onView={setView} narrow={!wide} />
        <Box component="main" sx={{ minWidth: 0, minHeight: 0, overflowY: shown === "now" ? "hidden" : "auto" }}>
          <MainView view={shown} />
        </Box>
        {wide && (
          <Box component="aside" sx={{ borderLeft: 1, borderColor: "divider", bgcolor: "background.paper", minHeight: 0 }}>
            <PlayerPanel />
          </Box>
        )}
      </Box>
    </Box>
  );
}

export function App() {
  const prefs = usePrefs();
  const systemDark = useMediaQuery("(prefers-color-scheme: dark)");
  const mode = prefs.theme === "system" ? (systemDark ? "dark" : "light") : prefs.theme;
  const theme = useMemo(() => makeTheme(mode), [mode]);
  useWakeLock(prefs.wakeLock);

  useEffect(() => {
    store.connect();
    // Tablets suspend the page; reconnect at once when it becomes visible again.
    const onVisible = () => document.visibilityState === "visible" && store.reconnectNow();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, []);

  return (
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <NotifyProvider>
        <Shell />
      </NotifyProvider>
    </ThemeProvider>
  );
}
