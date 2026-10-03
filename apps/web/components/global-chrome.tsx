"use client";

import { usePathname } from "next/navigation";

import { isChromelessRoute, useImmersiveActive } from "../lib/chrome-visibility";
import { BottomNav } from "./bottom-nav";
import { LoginNudge } from "./login-nudge";
import { MiniPlayer } from "./mini-player";

/**
 * The single, app-wide bottom navigation and mini player. Rendered once in the
 * root layout so page changes never rebuild them; hidden (not unmounted) on
 * the player route and during 开播中.
 */
export function GlobalChrome() {
  const pathname = usePathname();
  const overlay = useImmersiveActive();
  const hidden = isChromelessRoute(pathname) || overlay;
  return (
    <>
      <MiniPlayer hidden={hidden} />
      <LoginNudge hidden={hidden} />
      {hidden ? null : <BottomNav />}
    </>
  );
}
