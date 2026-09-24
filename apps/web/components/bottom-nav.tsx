"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { WaveIcon, type WaveIconName } from "./wave-icon";

const ITEMS: Array<{ href: string; label: string; icon: WaveIconName }> = [
  { href: "/", label: "为你", icon: "home" },
  { href: "/tune", label: "调频", icon: "tune" },
  { href: "/library", label: "节目库", icon: "library" },
];

export function BottomNav() {
  const pathname = usePathname();

  return (
    <nav className="bottom-nav" aria-label="主导航">
      {ITEMS.map((item) => {
        const active = item.href === "/" ? pathname === "/" : pathname.startsWith(item.href);
        return (
          <Link
            href={item.href}
            className={active ? "bottom-nav-item active" : "bottom-nav-item"}
            aria-current={active ? "page" : undefined}
            key={item.href}
          >
            <WaveIcon name={item.icon} size={21} />
            <span>{item.label}</span>
          </Link>
        );
      })}
    </nav>
  );
}
