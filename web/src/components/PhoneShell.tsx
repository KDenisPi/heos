import ScreenRotationIcon from "@mui/icons-material/ScreenRotation";
import SettingsIcon from "@mui/icons-material/Settings";
import SpeakerIcon from "@mui/icons-material/Speaker";
import {
  AppBar,
  BottomNavigation,
  BottomNavigationAction,
  Box,
  ButtonBase,
  IconButton,
  Stack,
  Toolbar,
  Typography,
} from "@mui/material";
import { type ReactNode, useState } from "react";
import { useSelectedDevice } from "../hooks/useSelectedPlayer";
import { DeviceMenu } from "./DeviceMenu";
import { MiniPlayer } from "./MiniPlayer";
import { NAV_ITEMS, type View } from "./NavRail";

/** The five screens in the phone's bottom navigation; Devices and Settings are in the top bar. */
const BOTTOM: View[] = ["now", "queue", "source", "playlists", "inputs"];

/**
 * Phone layout (portrait): top bar with the device switcher, the current
 * screen, a mini-player (except on Playing) and the bottom navigation.
 */
export function PhoneShell({
  view,
  onView,
  landscape,
  children,
}: {
  view: View;
  onView: (v: View) => void;
  landscape: boolean;
  children: ReactNode;
}) {
  const device = useSelectedDevice();
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);
  const items = NAV_ITEMS.filter((i) => BOTTOM.includes(i.view));

  if (landscape) {
    // Phones are portrait only. An installed PWA is locked; a browser tab shows this instead.
    return (
      <Stack spacing={2} sx={{ height: "100%", alignItems: "center", justifyContent: "center", p: 3, textAlign: "center" }}>
        <ScreenRotationIcon sx={{ fontSize: 56, color: "text.secondary" }} />
        <Typography>Turn your phone upright to use HEOS Home.</Typography>
      </Stack>
    );
  }

  return (
    <Box sx={{ flex: 1, minHeight: 0, display: "flex", flexDirection: "column" }}>
      <AppBar position="static" color="default" elevation={0} sx={{ bgcolor: "background.paper", borderBottom: 1, borderColor: "divider" }}>
        <Toolbar variant="dense" sx={{ gap: 1, minHeight: 56 }}>
          <ButtonBase
            onClick={(e) => setAnchor(e.currentTarget)}
            aria-label="Choose device"
            sx={{ gap: 1, borderRadius: 2, px: 1, py: 0.5, minWidth: 0, flex: 1, justifyContent: "flex-start" }}
          >
            <SpeakerIcon color={!device?.online ? "disabled" : device.power.state === "on" ? "success" : "primary"} />
            <Typography variant="subtitle1" noWrap>{device?.name ?? "No device"}</Typography>
          </ButtonBase>
          <IconButton aria-label="Devices" color={view === "devices" ? "primary" : "default"} onClick={() => onView("devices")}>
            <SpeakerIcon />
          </IconButton>
          <IconButton aria-label="Settings" color={view === "settings" ? "primary" : "default"} onClick={() => onView("settings")}>
            <SettingsIcon />
          </IconButton>
        </Toolbar>
      </AppBar>
      <DeviceMenu anchor={anchor} onClose={() => setAnchor(null)} />

      <Box component="main" sx={{ flex: 1, minHeight: 0, overflowY: view === "queue" ? "hidden" : "auto" }}>
        {children}
      </Box>

      {view !== "now" && <MiniPlayer onOpen={() => onView("now")} />}
      <BottomNavigation
        component="nav"
        showLabels
        value={BOTTOM.includes(view) ? view : false}
        onChange={(_, v: View) => onView(v)}
        sx={{ borderTop: 1, borderColor: "divider", pb: "env(safe-area-inset-bottom)" }}
      >
        {items.map((i) => (
          <BottomNavigationAction key={i.view} value={i.view} label={i.label} icon={i.icon} sx={{ minWidth: 0, px: 0.5 }} />
        ))}
      </BottomNavigation>
    </Box>
  );
}
