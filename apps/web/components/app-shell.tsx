import type { ReactNode } from "react";

import { BottomNav } from "./bottom-nav";
import { MiniPlayer } from "./mini-player";

/**
 * Tab-level frame: a single scrolling content region, the floating mini player
 * and the frosted bottom navigation. `fixed` screens (tuner) never scroll.
 */
export function AppShell({
  children,
  fixed = false,
  background,
}: {
  children: ReactNode;
  fixed?: boolean;
  background?: ReactNode;
}) {
  return (
    <div className="app-frame">
      {background}
      <main className={fixed ? "app-fixed" : "app-scroll page-enter"}>{children}</main>
      {fixed ? null : <MiniPlayer />}
      <BottomNav />
    </div>
  );
}
