import type { ReactNode } from "react";

import { BottomNav } from "./bottom-nav";
import { MiniPlayer } from "./mini-player";

export function AppShell({ children }: { children: ReactNode }) {
  return (
    <div className="app-frame">
      <main className="app-content page-enter">{children}</main>
      <MiniPlayer />
      <BottomNav />
    </div>
  );
}
