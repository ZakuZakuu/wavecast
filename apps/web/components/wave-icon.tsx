import type { SVGProps } from "react";

export type WaveIconName =
  | "home"
  | "tune"
  | "library"
  | "play"
  | "pause"
  | "back"
  | "heart"
  | "share"
  | "list"
  | "more"
  | "sparkle"
  | "search"
  | "chevron"
  | "skipBack"
  | "skipForward"
  | "close";

type Props = SVGProps<SVGSVGElement> & {
  name: WaveIconName;
  size?: number;
};

export function WaveIcon({ name, size = 22, ...props }: Props) {
  const common = {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.8,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    ...props,
  };

  switch (name) {
    case "home":
      return <svg {...common}><path d="m3 10 9-7 9 7"/><path d="M5 9.5V21h14V9.5"/><path d="M9.5 21v-7h5v7"/></svg>;
    case "tune":
      return <svg {...common}><circle cx="12" cy="12" r="8"/><path d="M12 4v3M12 17v3M4 12h3M17 12h3"/><path d="M8.5 15.5 15.6 8.4"/><circle cx="14.8" cy="9.2" r="1.4"/></svg>;
    case "library":
      return <svg {...common}><rect x="4" y="4" width="16" height="5" rx="1.5"/><rect x="4" y="11" width="16" height="9" rx="1.5"/><path d="M8 15h8"/></svg>;
    case "play":
      return <svg {...common} fill="currentColor" stroke="none"><path d="M8.2 5.3a1 1 0 0 1 1.5-.85l8.1 6.7a1.1 1.1 0 0 1 0 1.7l-8.1 6.7a1 1 0 0 1-1.5-.85Z"/></svg>;
    case "pause":
      return <svg {...common} fill="currentColor" stroke="none"><rect x="7" y="5" width="3.5" height="14" rx="1.2"/><rect x="13.5" y="5" width="3.5" height="14" rx="1.2"/></svg>;
    case "back":
      return <svg {...common}><path d="m15 18-6-6 6-6"/></svg>;
    case "heart":
      return <svg {...common}><path d="M20.8 4.7a5.3 5.3 0 0 0-7.5 0L12 6l-1.3-1.3a5.3 5.3 0 0 0-7.5 7.5L12 21l8.8-8.8a5.3 5.3 0 0 0 0-7.5Z"/></svg>;
    case "share":
      return <svg {...common}><path d="M12 16V3"/><path d="m8 7 4-4 4 4"/><path d="M5 11v8a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-8"/></svg>;
    case "list":
      return <svg {...common}><path d="M8 6h12M8 12h12M8 18h12"/><circle cx="4" cy="6" r=".7" fill="currentColor"/><circle cx="4" cy="12" r=".7" fill="currentColor"/><circle cx="4" cy="18" r=".7" fill="currentColor"/></svg>;
    case "more":
      return <svg {...common}><circle cx="5" cy="12" r="1" fill="currentColor"/><circle cx="12" cy="12" r="1" fill="currentColor"/><circle cx="19" cy="12" r="1" fill="currentColor"/></svg>;
    case "sparkle":
      return <svg {...common}><path d="M12 3c.7 4.2 2.8 6.3 7 7-4.2.7-6.3 2.8-7 7-.7-4.2-2.8-6.3-7-7 4.2-.7 6.3-2.8 7-7Z"/><path d="M19 16c.25 1.5 1 2.25 2.5 2.5C20 18.75 19.25 19.5 19 21c-.25-1.5-1-2.25-2.5-2.5C18 18.25 18.75 17.5 19 16Z"/></svg>;
    case "search":
      return <svg {...common}><circle cx="11" cy="11" r="6.5"/><path d="m16 16 4 4"/></svg>;
    case "chevron":
      return <svg {...common}><path d="m9 18 6-6-6-6"/></svg>;
    case "skipBack":
      return <svg {...common}><path d="M9 8H5V4"/><path d="M5.5 8A8 8 0 1 1 4 14"/><path d="M9 12h1.5v5M13 12h2.5a1.5 1.5 0 0 1 0 3H13v2h3"/></svg>;
    case "skipForward":
      return <svg {...common}><path d="M15 8h4V4"/><path d="M18.5 8A8 8 0 1 0 20 14"/><path d="M8 12h2.5a1.5 1.5 0 0 1 0 3H8v2h3M14 12v5M14 12h2"/></svg>;
    case "close":
      return <svg {...common}><path d="m6 6 12 12M18 6 6 18"/></svg>;
  }
}
