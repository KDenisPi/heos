import PowerSettingsNewIcon from "@mui/icons-material/PowerSettingsNew";
import { CircularProgress, IconButton, Tooltip } from "@mui/material";
import { useState } from "react";
import { api } from "../api/client";
import type { Device } from "../api/types";
import { useAction } from "../notify";

/** One tap toggles on/standby. The service skips no-op switches and spaces real ones 10 s apart. */
export function PowerButton({ device }: { device: Device | null }) {
  const act = useAction();
  const [busy, setBusy] = useState(false);
  const state = device?.power.state ?? "unknown";
  const supported = device !== null && device.power.effective_driver !== "none";
  const label = !supported
    ? "No power control for this device"
    : state === "on"
      ? "Switch to standby"
      : state === "standby"
        ? "Switch on"
        : "Power state unknown";

  const toggle = async () => {
    if (!device || busy) return;
    setBusy(true);
    await act(() => api.setPower(device.pid, state !== "on"));
    setBusy(false);
  };

  return (
    <Tooltip title={label} placement="right">
      <span>
        <IconButton
          onClick={toggle}
          disabled={!supported || busy || state === "unknown"}
          aria-label={label}
          sx={{
            width: 56,
            height: 56,
            color: state === "on" ? "success.main" : "text.secondary",
            border: 2,
            borderColor: state === "on" ? "success.main" : "divider",
          }}
        >
          {busy ? <CircularProgress size={24} /> : <PowerSettingsNewIcon />}
        </IconButton>
      </span>
    </Tooltip>
  );
}
