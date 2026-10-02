// Full-screen overlays that are not their own route (e.g. 开播中 inside /tune)
// register here so the global nav and mini player can step aside.
import { useEffect, useSyncExternalStore } from "react";

const active = new Set<string>();
const listeners = new Set<() => void>();
let snapshot = false;

function emit() {
  snapshot = active.size > 0;
  listeners.forEach((listener) => listener());
}

export function useImmersiveOverlay(key: string, on = true): void {
  useEffect(() => {
    if (!on) return;
    active.add(key);
    emit();
    return () => {
      active.delete(key);
      emit();
    };
  }, [key, on]);
}

export function useImmersiveActive(): boolean {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => snapshot,
    () => false,
  );
}

/** Routes that own the whole screen (player). */
export function isImmersiveRoute(pathname: string | null): boolean {
  return Boolean(pathname && /^\/episode(\/|$)/.test(pathname));
}
