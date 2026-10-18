import { logoDrawState } from "../lib/brand/logo-line";
import { LOGO_ACCENT } from "../lib/brand/logo-mark";

const GRILLE = [46, 55, 64].flatMap((cy) => [27, 35, 43].map((cx) => [cx, cy] as const));

/**
 * The line-art logo drawn out from a dot as `progress` goes 0 → 1 (pull-to-refresh). `swing` plays
 * the antenna swing and the needle sweep; `bump` is the single pop when the pull becomes ready.
 * Same size throughout: it is drawn in place, not scaled up.
 */
export function LogoLine({ progress = 1, swing = false, bump = false }: { progress?: number; swing?: boolean; bump?: boolean }) {
  const s = logoDrawState(progress);
  const dash = (draw: { offset: number; visible: boolean }) => ({ strokeDasharray: 1, strokeDashoffset: draw.offset, opacity: draw.visible ? 1 : 0 });
  const scaled = (value: number, x: number, y: number) => ({ transformOrigin: `${x}px ${y}px`, transform: `scale(${value})` });
  return (
    <svg viewBox="0 0 100 100" aria-hidden="true" className={bump ? "logo-line is-bump" : "logo-line"} data-swing={swing || undefined}>
      <defs>
        {/* The needle cuts a small gap out of the window, so it stays readable where they cross. */}
        <mask id="logo-line-window-cut" maskUnits="userSpaceOnUse" x="0" y="0" width="100" height="100">
          <rect width="100" height="100" fill="#FFFFFF" />
          <g className="logo-line-sweep"><path d="M66 38V57" pathLength="1" className="logo-line-stroke" stroke="#000000" strokeWidth="6.8" style={dash(s.needle)} /></g>
        </mask>
      </defs>
      <path d="M27 32h46a12 12 0 0 1 12 12v22a12 12 0 0 1-12 12H27a12 12 0 0 1-12-12V44a12 12 0 0 1 12-12Z" pathLength="1" className="logo-line-stroke" stroke="currentColor" strokeWidth="4.2" style={dash(s.body)} />
      {GRILLE.map(([cx, cy], index) => <circle key={index} cx={cx} cy={cy} r="2.5" fill="currentColor" style={scaled(s.dots[index], cx, cy)} />)}
      <g mask="url(#logo-line-window-cut)"><rect x="51" y="41" width="26" height="13" rx="4" fill="currentColor" style={scaled(s.window, 64, 47.5)} /></g>
      <circle cx="64" cy="66.5" r="5.5" fill="currentColor" style={scaled(s.knob, 64, 66.5)} />
      <g className="logo-line-sweep"><path d="M66 38V57" pathLength="1" className="logo-line-stroke" stroke={LOGO_ACCENT} strokeWidth="3.4" style={dash(s.needle)} /></g>
      <g className="logo-line-swing">
        <path d="M42 20 27 32" pathLength="1" className="logo-line-stroke" stroke="currentColor" strokeWidth="4.2" style={{ ...dash(s.antenna), strokeLinecap: "butt" }} />
        <circle cx="42" cy="20" r="4.4" fill={LOGO_ACCENT} style={scaled(s.tip, 42, 20)} />
      </g>
    </svg>
  );
}
