import { ListItemText, Menu, MenuItem } from "@mui/material";
import { selectPid, useSelectedPid } from "../hooks/useSelectedPlayer";
import { useAppState } from "../state/store";
import { PowerButton } from "./PowerButton";

/** Device switcher: every device with its state and its own power button. Used by the rail and the phone's top bar. */
export function DeviceMenu({ anchor, onClose }: { anchor: HTMLElement | null; onClose: () => void }) {
  const devices = useAppState((s) => s.devices);
  const selected = useSelectedPid();
  return (
    <Menu anchorEl={anchor} open={anchor !== null} onClose={onClose}>
      {devices.length === 0 && <MenuItem disabled>No devices found</MenuItem>}
      {devices.map((d) => (
        <MenuItem
          key={d.pid}
          selected={d.pid === selected}
          onClick={() => {
            selectPid(d.pid);
            onClose();
          }}
          sx={{ gap: 2, minWidth: 260 }}
        >
          <ListItemText
            primary={d.name}
            secondary={!d.online ? "Offline" : d.power.state === "on" ? "On" : d.power.state === "standby" ? "Standby" : d.model}
          />
          <PowerButton device={d} size="small" />
        </MenuItem>
      ))}
    </Menu>
  );
}
