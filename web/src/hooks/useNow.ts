import { useEffect, useState } from "react";

/** Re-render every `ms` while `active`, returning the current time. */
export function useNow(active: boolean, ms = 500): number {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!active) return;
    const id = window.setInterval(() => setNow(Date.now()), ms);
    return () => window.clearInterval(id);
  }, [active, ms]);
  return active ? now : Date.now();
}
