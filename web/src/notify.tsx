// App-wide snackbar for errors and short confirmations.

import { Alert, Snackbar } from "@mui/material";
import { createContext, type ReactNode, useCallback, useContext, useState } from "react";
import { ApiError } from "./api/client";

type Severity = "error" | "success" | "info" | "warning";
interface Note {
  id: number;
  text: string;
  severity: Severity;
}

const NotifyContext = createContext<(text: string, severity?: Severity) => void>(() => undefined);

export function NotifyProvider({ children }: { children: ReactNode }) {
  const [note, setNote] = useState<Note | null>(null);
  const notify = useCallback((text: string, severity: Severity = "info") => {
    setNote({ id: Date.now(), text, severity });
  }, []);
  return (
    <NotifyContext.Provider value={notify}>
      {children}
      <Snackbar
        key={note?.id}
        open={note !== null}
        autoHideDuration={note?.severity === "error" ? 6000 : 3000}
        onClose={() => setNote(null)}
        anchorOrigin={{ vertical: "bottom", horizontal: "center" }}
      >
        <Alert severity={note?.severity ?? "info"} variant="filled" onClose={() => setNote(null)}>
          {note?.text}
        </Alert>
      </Snackbar>
    </NotifyContext.Provider>
  );
}

export function useNotify() {
  return useContext(NotifyContext);
}

/** Wrap an API call: show its error in the snackbar instead of throwing. */
export function useAction() {
  const notify = useNotify();
  return useCallback(
    async <T,>(fn: () => Promise<T>, success?: string): Promise<T | undefined> => {
      try {
        const result = await fn();
        if (success) notify(success, "success");
        return result;
      } catch (err) {
        notify(err instanceof ApiError || err instanceof Error ? err.message : String(err), "error");
        return undefined;
      }
    },
    [notify],
  );
}
