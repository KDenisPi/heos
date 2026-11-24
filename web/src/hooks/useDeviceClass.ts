import { useEffect, useState } from "react";

/** Phones have a shortest screen side under 600 dp; tablets use both orientations, phones portrait only. */
export const PHONE_MAX_SHORT_SIDE = 600;

/** Phone or tablet, from the viewport size in CSS px (dp). */
export function classify(w: number, h: number): { phone: boolean; landscape: boolean } {
  return { phone: Math.min(w, h) < PHONE_MAX_SHORT_SIDE, landscape: w > h };
}

function measure() {
  return classify(window.innerWidth, window.innerHeight);
}

export function useDeviceClass(): { phone: boolean; landscape: boolean } {
  const [cls, setCls] = useState(measure);
  useEffect(() => {
    const update = () => setCls((cur) => {
      const next = measure();
      return next.phone === cur.phone && next.landscape === cur.landscape ? cur : next;
    });
    window.addEventListener("resize", update);
    window.addEventListener("orientationchange", update);
    return () => {
      window.removeEventListener("resize", update);
      window.removeEventListener("orientationchange", update);
    };
  }, []);
  return cls;
}

/**
 * Keep phones in portrait. Browsers allow the lock only for an installed,
 * full-screen PWA (Android Chrome); elsewhere it fails quietly and the phone
 * shell shows a "turn upright" hint in landscape instead.
 */
export function usePortraitLock(phone: boolean): void {
  useEffect(() => {
    if (!phone) return;
    const orientation = screen.orientation as ScreenOrientation & { lock?: (o: string) => Promise<void> };
    if (!orientation?.lock) return;
    const lock = () => {
      orientation.lock?.("portrait").catch(() => undefined);
    };
    lock();
    const onVisible = () => document.visibilityState === "visible" && lock();
    document.addEventListener("visibilitychange", onVisible);
    return () => document.removeEventListener("visibilitychange", onVisible);
  }, [phone]);
}
