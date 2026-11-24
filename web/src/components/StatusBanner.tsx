import { Alert, Button } from "@mui/material";
import { store, useAppState } from "../state/store";

/** Shown when the service is unreachable, or when it has lost the HEOS device. */
export function StatusBanner() {
  const online = useAppState((s) => s.online);
  const heos = useAppState((s) => s.heos);
  if (!online) {
    return (
      <Alert severity="warning" square action={<Button color="inherit" onClick={() => store.reconnectNow()}>Retry</Button>}>
        HEOS Home service is offline. Reconnecting…
      </Alert>
    );
  }
  if (!heos.connected) {
    return (
      <Alert severity="info" square>
        Not connected to a HEOS device{heos.host ? ` (${heos.host})` : ""}. Retrying…
      </Alert>
    );
  }
  return null;
}
