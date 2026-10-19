"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, type ComponentType } from "react";

import { rememberTabPath } from "../lib/nav-memory";
import { useLibraryTabState } from "./full-version-watcher";

import { HomeIcon, LibraryIcon, TuneIcon } from "./icons";

const ITEMS: Array<{ href: string; label: string; Icon: ComponentType<{ size?: number }>; guide?: string }> = [
  { href: "/", label: "首页", Icon: HomeIcon },
  { href: "/tune", label: "调频", Icon: TuneIcon, guide: "nav-tune" },
  { href: "/library", label: "节目库", Icon: LibraryIcon },
];

export function BottomNav() {
  const pathname = usePathname();
  useEffect(() => rememberTabPath(pathname), [pathname]);
  const libraryState = useLibraryTabState();

  return (
    <nav className="bottom-nav" aria-label="主导航">
      {ITEMS.map(({ href, label, Icon, guide }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            href={href}
            className={active ? "bottom-nav-item active" : "bottom-nav-item"}
            aria-current={active ? "page" : undefined}
            data-guide={guide}
            key={href}
          >
            <Icon size={26} />
            <span>{label}</span>
            {href === "/library" && libraryState === "ready" ? <i className="nav-dot" role="img" aria-label="有新的完整版" /> : null}
            {href === "/library" && libraryState === "busy" ? <i className="nav-dot is-busy" role="img" aria-label="正在准备完整版" /> : null}
          </Link>
        );
      })}
    </nav>
  );
}
