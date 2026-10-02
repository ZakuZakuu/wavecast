"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ComponentType } from "react";

import { HomeIcon, LibraryIcon, TuneIcon } from "./icons";

const ITEMS: Array<{ href: string; label: string; Icon: ComponentType<{ size?: number }> }> = [
  { href: "/", label: "首页", Icon: HomeIcon },
  { href: "/tune", label: "调频", Icon: TuneIcon },
  { href: "/library", label: "节目库", Icon: LibraryIcon },
];

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="bottom-nav" aria-label="主导航">
      {ITEMS.map(({ href, label, Icon }) => {
        const active = href === "/" ? pathname === "/" : pathname.startsWith(href);
        return (
          <Link
            href={href}
            className={active ? "bottom-nav-item active" : "bottom-nav-item"}
            aria-current={active ? "page" : undefined}
            key={href}
          >
            <Icon size={26} />
            <span>{label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
