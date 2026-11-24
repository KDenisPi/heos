import {
  Alert,
  Button,
  Card,
  CardContent,
  Checkbox,
  Dialog,
  DialogActions,
  DialogContent,
  DialogContentText,
  DialogTitle,
  FormControlLabel,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import { useState } from "react";
import { ApiError, api } from "../api/client";
import { useAction } from "../notify";
import { useAppState } from "../state/store";

/**
 * HEOS account (F7): sign in / out on the amp. The password goes only to the
 * service, which can keep it encrypted for automatic re-sign-in after a reboot.
 */
export function AccountCard() {
  const act = useAction();
  const account = useAppState((s) => s.account);
  const heosConnected = useAppState((s) => s.heos.connected);
  const [username, setUsername] = useState(account.remembered_username ?? account.username ?? "");
  const [password, setPassword] = useState("");
  const [remember, setRemember] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [confirmSignOut, setConfirmSignOut] = useState(false);

  const signIn = async () => {
    if (!username.trim() || !password || busy) return;
    setBusy(true);
    setError(null);
    try {
      await api.signIn(username.trim(), password, remember);
      setPassword("");
    } catch (err) {
      setError(err instanceof ApiError || err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card variant="outlined">
      <CardContent>
        <Stack spacing={2}>
          <Typography variant="subtitle1">HEOS account</Typography>
          {account.error && <Alert severity="warning">{account.error}. Sign in again below.</Alert>}

          {account.signed_in ? (
            <>
              <Typography>
                Signed in as <strong>{account.username}</strong>
              </Typography>
              <Typography variant="body2" color="text.secondary">
                {account.auto_sign_in
                  ? "The password is saved encrypted on the server; the amp is signed in again automatically after a reboot."
                  : "The password is not saved; after an amp reboot you may need to sign in again here."}
              </Typography>
              <Stack direction="row" spacing={1} sx={{ flexWrap: "wrap", rowGap: 1 }}>
                {account.remembered && (
                  <Button variant="outlined" onClick={() => act(() => api.forgetCredentials(), "Saved password forgotten")}>
                    Forget saved password
                  </Button>
                )}
                <Button color="error" variant="outlined" disabled={!heosConnected} onClick={() => setConfirmSignOut(true)}>
                  Sign out
                </Button>
              </Stack>
            </>
          ) : (
            <>
              <Typography variant="body2" color="text.secondary">
                The amp is signed out. Streaming services such as Amazon Music work only while it is signed in to the HEOS
                account that holds their logins.
              </Typography>
              <TextField
                label="HEOS account (e-mail)"
                type="email"
                value={username}
                onChange={(e) => setUsername(e.target.value)}
                autoComplete="off"
                size="small"
              />
              <TextField
                label="Password"
                type="password"
                value={password}
                onChange={(e) => {
                  setPassword(e.target.value);
                  setError(null);
                }}
                onKeyDown={(e) => e.key === "Enter" && signIn()}
                autoComplete="off"
                size="small"
                error={error !== null}
                helperText={error ?? " "}
              />
              <FormControlLabel
                control={<Checkbox checked={remember} onChange={(e) => setRemember(e.target.checked)} />}
                label="Remember on the server (encrypted) and sign in again after an amp reboot"
              />
              <Stack direction="row">
                <Button variant="contained" onClick={signIn} disabled={!heosConnected || busy || !username.trim() || !password}>
                  {busy ? "Signing in…" : "Sign in"}
                </Button>
              </Stack>
            </>
          )}
        </Stack>
      </CardContent>

      <Dialog open={confirmSignOut} onClose={() => setConfirmSignOut(false)}>
        <DialogTitle>Sign out of HEOS?</DialogTitle>
        <DialogContent>
          <DialogContentText>
            Amazon Music and HEOS Favorites stop working until the amp is signed in again. The saved password is forgotten.
          </DialogContentText>
        </DialogContent>
        <DialogActions sx={{ px: 3, pb: 2 }}>
          <Button onClick={() => setConfirmSignOut(false)}>Cancel</Button>
          <Button
            color="error"
            variant="contained"
            onClick={() => {
              setConfirmSignOut(false);
              act(() => api.signOut(), "Signed out of HEOS");
            }}
          >
            Sign out
          </Button>
        </DialogActions>
      </Dialog>
    </Card>
  );
}
