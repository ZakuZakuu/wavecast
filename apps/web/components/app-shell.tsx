import type { ReactNode } from "react";

/**
 * Tab-level frame: a single scrolling content region. The bottom navigation
 * and mini player live once in the root layout (GlobalChrome); bottom spacing
 * for them is applied centrally in CSS. `fixed` screens (tuner) never scroll.
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
    </div>
  );
}
