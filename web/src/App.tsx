import { Box, CssBaseline, useMediaQuery } from "@mui/material";
import { ThemeProvider } from "@mui/material/styles";
import { useEffect, useMemo, useState } from "react";
import { NavRail, type View } from "./components/NavRail";
import { PhoneShell } from "./components/PhoneShell";
import { StatusBanner } from "./components/StatusBanner";
import { useDeviceClass, usePortraitLock } from "./hooks/useDeviceClass";
import { useWakeLock } from "./hooks/useWakeLock";
import { NotifyProvider, useNotify } from "./notify";
import { usePrefs } from "./state/prefs";
import { store, useAppState } from "./state/store";
import { makeTheme } from "./theme";
import { DevicesView } from "./views/DevicesView";
import { InputsView } from "./views/InputsView";
import { SourceView } from "./views/SourceView";
import { PlayingView } from "./views/PlayingView";
import { PlaylistsView } from "./views/PlaylistsView";
import { QueueView } from "./views/QueueView";
import { SettingsView } from "./views/SettingsView";

function MainView({ view }: { view: View }) {
  switch (view) {
    case "now":
      return <PlayingView />;
    case "queue":
      return <QueueView />;
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
  // Tablet (shortest side >= 600 dp, either orientation): navigation rail + one view.
  // Phone: portrait only, top bar + view + mini-player + bottom navigation.
  const [view, setView] = useState<View>("now");
  const { phone, landscape } = useDeviceClass();
  usePortraitLock(phone);

  if (phone) {
    return (
      <Box sx={{ height: "100dvh", display: "flex", flexDirection: "column" }}>
        <StatusBanner />
        <PlaybackErrors />
        <PhoneShell view={view} onView={setView} landscape={landscape}>
          <MainView view={view} />
        </PhoneShell>
      </Box>
    );
  }

  return (
    <Box sx={{ height: "100dvh", display: "flex", flexDirection: "column" }}>
      <StatusBanner />
      <PlaybackErrors />
      <Box sx={{ flex: 1, minHeight: 0, display: "grid", gridTemplateColumns: "80px minmax(0,1fr)" }}>
        <NavRail view={view} onView={setView} />
        <Box component="main" sx={{ minWidth: 0, minHeight: 0, overflowY: view === "queue" ? "hidden" : "auto", height: "100%" }}>
          <MainView view={view} />
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
