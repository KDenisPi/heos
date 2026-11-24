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
import { SourceView } from "./views/SourceView";
import { PlaylistsView } from "./views/PlaylistsView";
import { SettingsView } from "./views/SettingsView";

/**
 * The Playing screen: now playing and the queue side by side on wide screens
 * (tablet landscape), stacked on narrow ones (phone).
 */
function PlayingView({ wide }: { wide: boolean }) {
  const player = useSelectedPlayer();
  if (!player) {
    return (
      <Typography color="text.secondary" sx={{ p: 3 }}>
        No player yet. Check the Devices screen.
      </Typography>
    );
  }
  if (wide) {
    return (
      <Box sx={{ height: "100%", minHeight: 0, display: "grid", gridTemplateColumns: "minmax(360px, 480px) minmax(0, 1fr)" }}>
        <Box sx={{ overflowY: "auto", borderRight: 1, borderColor: "divider", display: "flex", flexDirection: "column", justifyContent: "center" }}>
          <NowPlaying player={player} />
        </Box>
        <Stack sx={{ minHeight: 0 }}>
          <QueuePanel pid={player.pid} />
        </Stack>
      </Box>
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

function MainView({ view, wide }: { view: View; wide: boolean }) {
  switch (view) {
    case "now":
      return <PlayingView wide={wide} />;
    case "inputs":
      return <InputsView />;
    case "devices":
      return <DevicesView />;
    case "settings":
      return <SettingsView />;
    case "source":
      return <SourceView />;
    case "playlists":
      return <PlaylistsView />;
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
  // Navigation rail + one view. Playing is a view of its own, so other screens
  // get the full width, and the same layout works on a phone.
  const wide = useMediaQuery("(min-width: 900px)");
  const [view, setView] = useState<View>("now");

  return (
    <Box sx={{ height: "100dvh", display: "flex", flexDirection: "column" }}>
      <StatusBanner />
      <PlaybackErrors />
      <Box sx={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "80px minmax(0,1fr)" }}>
        <NavRail view={view} onView={setView} />
        <Box component="main" sx={{ minWidth: 0, minHeight: 0, overflowY: view === "now" ? "hidden" : "auto", height: "100%" }}>
          <MainView view={view} wide={wide} />
        </Box>
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
