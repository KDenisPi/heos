import RefreshIcon from "@mui/icons-material/Refresh";
import {
  Button,
  Card,
  CardActions,
  CardContent,
  Chip,
  MenuItem,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useEffect, useState } from "react";
import { api } from "../api/client";
import type { Device } from "../api/types";
import { PowerButton } from "../components/PowerButton";
import { useAction } from "../notify";
import { store, useAppState } from "../state/store";

const DRIVERS = [
  { value: "auto", label: "Auto (UPnP if available)" },
  { value: "upnp_act", label: "UPnP ACT" },
  { value: "none", label: "None (use the amp's remote)" },
];

function Field({ label, value }: { label: string; value: string | null | undefined }) {
  return (
    <Stack direction="row" spacing={1}>
      <Typography variant="body2" color="text.secondary" sx={{ width: 110, flexShrink: 0 }}>{label}</Typography>
      <Typography variant="body2" sx={{ wordBreak: "break-all" }}>{value || "—"}</Typography>
    </Stack>
  );
}

function DeviceCard({ device }: { device: Device }) {
  const act = useAction();
  const [ip, setIp] = useState(device.ip_override ?? "");
  const [firmware, setFirmware] = useState<string | null>(null);

  useEffect(() => setIp(device.ip_override ?? ""), [device.ip_override]);

  const saveIp = () =>
    act(() => api.patchDevice(device.pid, { ip_override: ip.trim() || null }), "IP override saved");
  const setDriver = (driver: string) => act(() => api.patchDevice(device.pid, { power: { driver } }), "Power driver saved");
  const testPower = async () => {
    const p = await act(() => api.readPower(device.pid));
    if (p) {
      store.setDevices(store.get().devices.map((d) => (d.pid === device.pid ? { ...d, power: p } : d)));
    }
  };
  const checkFirmware = async () => {
    const f = await act(() => api.firmware(device.pid));
    if (f) setFirmware(f.update_available ? `Update available. ${f.how_to_install}` : "Firmware is up to date.");
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack direction="row" spacing={1} useFlexGap sx={{ mb: 1.5, alignItems: "center", flexWrap: "wrap" }}>
          <PowerButton device={device} size="small" />
          <Typography variant="h6" sx={{ mr: 1 }}>{device.name}</Typography>
          <Chip size="small" label={device.online ? "Online" : "Offline"} color={device.online ? "success" : "default"} />
          <Chip size="small" variant="outlined" label={`Power: ${device.power.state}`} color={device.power.state === "on" ? "success" : "default"} />
          {device.default && <Chip size="small" variant="outlined" label="Default" />}
          {device.connection_host && <Chip size="small" variant="outlined" label="CLI connection" />}
        </Stack>
        <Stack spacing={0.5}>
          <Field label="Model" value={device.model} />
          <Field label="IP" value={device.ip} />
          <Field label="Firmware" value={device.firmware} />
          <Field label="Network" value={device.network} />
          <Field label="Serial" value={device.serial} />
          <Field label="Player id" value={String(device.pid)} />
          <Field label="Power driver" value={`${device.power.driver}${device.power.effective_driver && device.power.effective_driver !== device.power.driver ? ` → ${device.power.effective_driver}` : ""}`} />
          {device.power.error && <Field label="Power error" value={device.power.error} />}
        </Stack>
        <Stack direction={{ xs: "column", sm: "row" }} spacing={2} sx={{ mt: 2 }}>
          <TextField
            size="small"
            label="IP override"
            placeholder={device.ip ?? "192.168.1.50"}
            value={ip}
            onChange={(e) => setIp(e.target.value)}
            onKeyDown={(e) => e.key === "Enter" && saveIp()}
            helperText="Used when discovery fails"
          />
          <TextField
            select
            size="small"
            label="Power driver"
            value={device.power.driver}
            onChange={(e) => setDriver(e.target.value)}
            sx={{ minWidth: 240 }}
          >
            {DRIVERS.map((d) => (
              <MenuItem key={d.value} value={d.value}>{d.label}</MenuItem>
            ))}
          </TextField>
        </Stack>
        {firmware && <Typography variant="body2" sx={{ mt: 2 }}>{firmware}</Typography>}
      </CardContent>
      <CardActions sx={{ px: 2, pb: 2, flexWrap: "wrap", gap: 1 }}>
        <Button variant="outlined" onClick={saveIp}>Save IP</Button>
        <Button variant="outlined" onClick={testPower}>Test power</Button>
        <Button variant="outlined" onClick={checkFirmware} disabled={!device.online}>Check firmware</Button>
        {!device.default && (
          <Button onClick={() => act(() => api.patchDevice(device.pid, { default: true }), "Default device set")}>Make default</Button>
        )}
      </CardActions>
    </Card>
  );
}

export function DevicesView() {
  const act = useAction();
  const devices = useAppState((s) => s.devices);
  const version = useAppState((s) => s.devicesVersion);
  const [discovering, setDiscovering] = useState(false);

  // The snapshot carries devices; refetch when the service says they changed.
  useEffect(() => {
    act(() => api.devices()).then((res) => res && store.setDevices(res.devices));
  }, [act, version]);

  const discover = async () => {
    setDiscovering(true);
    const res = await act(() => api.discover());
    setDiscovering(false);
    if (res) store.setDevices(res.devices);
  };

  return (
    <Stack spacing={2} sx={{ p: 3, maxWidth: 900 }}>
      <Stack direction="row" sx={{ alignItems: "center" }}>
        <Typography variant="h5" sx={{ flex: 1 }}>Devices</Typography>
        <Button variant="contained" startIcon={<RefreshIcon />} onClick={discover} disabled={discovering}>
          {discovering ? "Searching…" : "Re-discover"}
        </Button>
      </Stack>
      {devices.length === 0 && <Typography color="text.secondary">No HEOS devices yet. Try Re-discover, or set the IP with HEOS_HOME_HOSTS.</Typography>}
      {devices.map((d) => <DeviceCard key={d.pid} device={d} />)}
    </Stack>
  );
}
