import InputIcon from "@mui/icons-material/Input";
import LibraryMusicIcon from "@mui/icons-material/LibraryMusic";
import PlayCircleIcon from "@mui/icons-material/PlayCircle";
import QueueMusicIcon from "@mui/icons-material/QueueMusic";
import SettingsIcon from "@mui/icons-material/Settings";
import SpeakerIcon from "@mui/icons-material/Speaker";
import { Box, ButtonBase, Menu, MenuItem, Stack, Typography } from "@mui/material";
import { useState } from "react";
import { selectPid, useSelectedDevice } from "../hooks/useSelectedPlayer";
import { useAppState } from "../state/store";
import { PowerButton } from "./PowerButton";

export type View = "now" | "library" | "playlists" | "inputs" | "devices" | "settings";

const ITEMS: { view: View; label: string; icon: React.ReactNode; narrowOnly?: boolean }[] = [
  { view: "now", label: "Playing", icon: <PlayCircleIcon />, narrowOnly: true },
  { view: "library", label: "Library", icon: <LibraryMusicIcon /> },
  { view: "playlists", label: "Playlists", icon: <QueueMusicIcon /> },
  { view: "inputs", label: "Inputs", icon: <InputIcon /> },
  { view: "devices", label: "Devices", icon: <SpeakerIcon /> },
  { view: "settings", label: "Settings", icon: <SettingsIcon /> },
];

function RailItem({ active, label, icon, onClick }: { active: boolean; label: string; icon: React.ReactNode; onClick: () => void }) {
  return (
    <ButtonBase onClick={onClick} aria-current={active ? "page" : undefined} sx={{ flexDirection: "column", py: 0.75, borderRadius: 3, width: 72 }}>
      <Box sx={{ px: 2, py: 0.5, borderRadius: 4, bgcolor: active ? "secondary.main" : "transparent", color: active ? "secondary.contrastText" : "text.secondary", display: "flex" }}>
        {icon}
      </Box>
      <Typography variant="caption" sx={{ mt: 0.5, color: active ? "text.primary" : "text.secondary", fontWeight: active ? 600 : 400 }}>
        {label}
      </Typography>
    </ButtonBase>
  );
}

export function NavRail({ view, onView, narrow }: { view: View; onView: (v: View) => void; narrow: boolean }) {
  const device = useSelectedDevice();
  const devices = useAppState((s) => s.devices);
  const [anchor, setAnchor] = useState<HTMLElement | null>(null);

  return (
    <Stack role="navigation" spacing={1} sx={{ alignItems: "center", width: 80, py: 2, bgcolor: "background.paper", borderRight: 1, borderColor: "divider", overflowY: "auto" }}>
      <ButtonBase
        onClick={(e) => setAnchor(e.currentTarget)}
        sx={{ flexDirection: "column", width: 72, py: 1, borderRadius: 3 }}
        aria-label="Choose device"
      >
        <SpeakerIcon color={device?.online ? "primary" : "disabled"} />
        <Typography variant="caption" noWrap sx={{ maxWidth: 68 }}>
          {device?.name ?? "No device"}
        </Typography>
      </ButtonBase>
      <Menu anchorEl={anchor} open={anchor !== null} onClose={() => setAnchor(null)}>
        {devices.length === 0 && <MenuItem disabled>No devices found</MenuItem>}
        {devices.map((d) => (
          <MenuItem
            key={d.pid}
            selected={d.pid === device?.pid}
            onClick={() => {
              selectPid(d.pid);
              setAnchor(null);
            }}
          >
            {d.name} {d.online ? "" : "(offline)"}
          </MenuItem>
        ))}
      </Menu>
      <PowerButton device={device} />
      <Box sx={{ height: 8 }} />
      {ITEMS.filter((i) => narrow || !i.narrowOnly).map((i) => (
        <RailItem key={i.view} active={view === i.view} label={i.label} icon={i.icon} onClick={() => onView(i.view)} />
      ))}
    </Stack>
  );
}
