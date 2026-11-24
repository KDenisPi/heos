import { useCallback, useEffect, useRef } from "react";

/**
 * Call `fn` at most every `ms` while values keep coming, and always with the
 * final value (spec 7: volume slider sends at most every 150 ms while dragging).
 */
export function useThrottled<T>(fn: (value: T) => void, ms: number): (value: T) => void {
  const fnRef = useRef(fn);
  fnRef.current = fn;
  const last = useRef(0);
  const pending = useRef<{ value: T } | null>(null);
  const timer = useRef<number | undefined>(undefined);

  useEffect(() => () => window.clearTimeout(timer.current), []);

  return useCallback(
    (value: T) => {
      const now = Date.now();
      const wait = last.current + ms - now;
      if (wait <= 0) {
        last.current = now;
        pending.current = null;
        fnRef.current(value);
        return;
      }
      pending.current = { value };
      if (timer.current === undefined) {
        timer.current = window.setTimeout(() => {
          timer.current = undefined;
          if (pending.current) {
            last.current = Date.now();
            fnRef.current(pending.current.value);
            pending.current = null;
          }
        }, wait);
      }
    },
    [ms],
  );
}
