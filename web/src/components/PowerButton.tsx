import PowerSettingsNewIcon from "@mui/icons-material/PowerSettingsNew";
import { CircularProgress, IconButton, Tooltip } from "@mui/material";
import { useState } from "react";
import { api } from "../api/client";
import type { Device } from "../api/types";
import { useAction } from "../notify";

/**
 * Power toggle for one device: one tap switches between on and standby.
 * The service skips no-op switches and spaces real ones 10 s apart.
 */
export function PowerButton({ device, size = "large" }: { device: Device | null; size?: "large" | "small" }) {
  const act = useAction();
  const [busy, setBusy] = useState(false);
  const state = device?.power.state ?? "unknown";
  const supported = device !== null && device.power.effective_driver !== "none";
  const label = !supported
    ? "No power control for this device"
    : state === "on"
      ? `Switch ${device.name} to standby`
      : state === "standby"
        ? `Switch ${device.name} on`
        : "Power state unknown";

  const toggle = async (e: React.MouseEvent) => {
    e.stopPropagation(); // inside a menu item or card: don't also select the device
    if (!device || busy) return;
    setBusy(true);
    await act(() => api.setPower(device.pid, state !== "on"));
    setBusy(false);
  };

  return (
    <Tooltip title={label}>
      <span>
        <IconButton
          onClick={toggle}
          disabled={!supported || busy || state === "unknown"}
          aria-label={label}
          sx={{
            width: size === "large" ? 56 : 44,
            height: size === "large" ? 56 : 44,
            minWidth: 0,
            minHeight: 0,
            color: state === "on" ? "success.main" : "text.secondary",
            border: 2,
            borderColor: state === "on" ? "success.main" : "divider",
          }}
        >
          {busy ? <CircularProgress size={size === "large" ? 24 : 18} /> : <PowerSettingsNewIcon fontSize={size === "large" ? "medium" : "small"} />}
        </IconButton>
      </span>
    </Tooltip>
  );
}
