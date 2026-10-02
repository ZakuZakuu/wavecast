// Frost line icons (24 grid, 1.7–1.8 stroke, round caps) — HANDOFF §4.6.
import type { SVGProps } from "react";

type IconProps = { size?: number } & Omit<SVGProps<SVGSVGElement>, "width" | "height">;

function stroke({ size = 24, ...rest }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "none",
    stroke: "currentColor",
    strokeWidth: 1.7,
    strokeLinecap: "round" as const,
    strokeLinejoin: "round" as const,
    "aria-hidden": true,
    focusable: false,
    ...rest,
  };
}

function solid({ size = 24, ...rest }: IconProps) {
  return {
    width: size,
    height: size,
    viewBox: "0 0 24 24",
    fill: "currentColor",
    "aria-hidden": true,
    focusable: false,
    ...rest,
  };
}

export const HomeIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M4 10.5 12 4l8 6.5V20a1 1 0 0 1-1 1h-4.5v-6h-5v6H5a1 1 0 0 1-1-1z" /></svg>
);

export const TuneIcon = (p: IconProps) => (
  <svg {...stroke(p)}><rect x="2.5" y="8" width="19" height="9" rx="4.5" /><path d="M6.5 12.5h.01M9.5 12.5h.01M17.5 12.5h.01" /><path d="M13.5 5.5v13" /></svg>
);

export const LibraryIcon = (p: IconProps) => (
  <svg {...stroke(p)}><rect x="4" y="4" width="4" height="16" rx="1" /><rect x="10" y="4" width="4" height="16" rx="1" /><path d="m16 5.4 3.4-0.9 2.9 13.9-3.4 0.9z" /></svg>
);

export const PlayIcon = (p: IconProps) => (
  <svg {...solid(p)}><path d="M7 4.9v14.2a1 1 0 0 0 1.5.86l11.6-7.1a1 1 0 0 0 0-1.72L8.5 4.04A1 1 0 0 0 7 4.9z" /></svg>
);

export const PauseIcon = (p: IconProps) => (
  <svg {...solid(p)}><rect x="6" y="4.5" width="4" height="15" rx="1.2" /><rect x="14" y="4.5" width="4" height="15" rx="1.2" /></svg>
);

export const SkipIcon = (p: IconProps) => (
  <svg {...solid(p)}><path d="M4 5.8v12.4a.8.8 0 0 0 1.2.7l9.4-6.2a.8.8 0 0 0 0-1.4L5.2 5.1a.8.8 0 0 0-1.2.7z" /><rect x="16.8" y="5" width="2.6" height="14" rx="1" /></svg>
);

/** Back 15 seconds. The numeral is drawn as text so it reads as "15", not "12". */
export const Back15Icon = ({ size = 32, ...rest }: IconProps) => (
  <svg width={size} height={size} viewBox="0 0 32 32" fill="none" aria-hidden focusable={false} {...rest}>
    <path d="M9.2 8.6A10.6 10.6 0 1 1 5.6 17" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" />
    <path d="M9.6 3.8v5.2h5.2" stroke="currentColor" strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round" />
    <text x="16.4" y="21.3" textAnchor="middle" fontSize="10.5" fontWeight="700" fill="currentColor" fontFamily="-apple-system, 'Helvetica Neue', Arial, sans-serif" style={{ fontVariantNumeric: "tabular-nums" }}>15</text>
  </svg>
);

export const ChevronDownIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="m6 9.5 6 6 6-6" /></svg>
);

export const ChevronLeftIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="m14.5 5.5-6.5 6.5 6.5 6.5" /></svg>
);

export const MoreIcon = (p: IconProps) => (
  <svg {...solid(p)}><circle cx="5.5" cy="12" r="1.8" /><circle cx="12" cy="12" r="1.8" /><circle cx="18.5" cy="12" r="1.8" /></svg>
);

export const CloseIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M6.5 6.5l11 11M17.5 6.5l-11 11" /></svg>
);

export const ThumbDownIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M16.5 4.5h2.2a1.3 1.3 0 0 1 1.3 1.3v6.4a1.3 1.3 0 0 1-1.3 1.3h-2.2z" /><path d="M16.5 13.5 12.8 20a2 2 0 0 1-2.9-2.2l.8-3.3H5.6a1.8 1.8 0 0 1-1.8-2.1l1.2-6.3a1.8 1.8 0 0 1 1.8-1.5h9.7" /></svg>
);

export const CaptionsIcon = (p: IconProps) => (
  <svg {...stroke(p)}><rect x="3" y="5" width="18" height="14" rx="3" /><path d="M7 11h4M13 11h4M7 15h7" /></svg>
);

export const RouteIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M8 6h12M8 12h12M8 18h12" /><path d="M4 6h.01M4 12h.01M4 18h.01" strokeWidth={2.4} /></svg>
);

export const ShareIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M12 3.5v11M8 7.5l4-4 4 4" /><path d="M6.5 11H6a1.5 1.5 0 0 0-1.5 1.5v6A1.5 1.5 0 0 0 6 20h12a1.5 1.5 0 0 0 1.5-1.5v-6A1.5 1.5 0 0 0 18 11h-.5" /></svg>
);

export const PlusSquareIcon = (p: IconProps) => (
  <svg {...stroke(p)}><rect x="4" y="4" width="16" height="16" rx="4" /><path d="M12 8.5v7M8.5 12h7" /></svg>
);

export const SaveIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M7 4h10a1 1 0 0 1 1 1v15l-6-4-6 4V5a1 1 0 0 1 1-1z" /></svg>
);

export const DownloadIcon = (p: IconProps) => (
  <svg {...stroke(p)}><path d="M12 4v11M7.5 10.5 12 15l4.5-4.5M5 19.5h14" /></svg>
);

export const StopIcon = (p: IconProps) => (
  <svg {...stroke(p)}><rect x="6" y="6" width="12" height="12" rx="2.5" /></svg>
);
