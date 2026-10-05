import { HOME_CARDS, HOST, PROGRAMMES, RECO, TYPED } from "../content";
import { SANS } from "../fonts";
import { clamp, ei, eio, eo, lerp, p } from "../lib/math";
import { AFTERNOON, MORNING, NEXT, NIGHT, END } from "../timeline";
import { tuneFreq } from "./afternoonCurve";
import {
  cardRect,
  Finger,
  HOME_LAYOUT,
  HomeScreen,
  Layer,
  MiniBar,
  PlayerScreen,
  RouteSheet,
  TabBar,
  TuneScreen,
  TuningScreen,
  type Gesture,
  type PlayerState,
} from "../components/PhoneScreens";
import { Cover } from "../components/Cover";
import { stationById } from "../stations";

/* ---------------- rig & camera ---------------- */

export const RIG = { left: 975, top: 108, w: 410, h: 864 };
const ANCHOR = { x: RIG.left + RIG.w / 2, y: RIG.top + RIG.h / 2 };

// [t, scale, focus x, focus y] in phone coordinates; eased between keys.
const KEYS: Array<[number, number, number, number]> = [
  [0, 1, 205, 432],
  [AFTERNOON.pushIn[0], 1, 205, 432],
  [AFTERNOON.pushIn[1], 1.45, 205, 323],
  [AFTERNOON.pushOut[0], 1.45, 205, 323],
  [AFTERNOON.pushOut[1], 1, 205, 432],
  [NIGHT.pushIn[0], 1, 205, 432],
  [NIGHT.pushIn[1], 1.4, 205, 640],
  [NIGHT.pushOut[0], 1.4, 205, 640],
  [NIGHT.pushOut[1], 1, 205, 432],
];
function cam(t: number) {
  let k = 0;
  while (k < KEYS.length - 1 && t > KEYS[k + 1][0]) k++;
  const a = KEYS[k];
  const b = KEYS[Math.min(k + 1, KEYS.length - 1)];
  const x = b[0] === a[0] ? 0 : eio(p(t, a[0], b[0]));
  return { s: lerp(a[1], b[1], x), fx: lerp(a[2], b[2], x), fy: lerp(a[3], b[3], x) };
}

/** Breakdown: the phone turns ~25° to the right and steps left to make room for the layer cards. */
export function breakdownPose(t: number) {
  const out = eio(p(t, AFTERNOON.explode[0], AFTERNOON.explode[0] + 1.1));
  const back = eio(p(t, AFTERNOON.collapse[0] + 0.2, AFTERNOON.collapse[1]));
  return out * (1 - back);
}

/** Cover wall: the phone shrinks into the middle tile of the wall. */
export const WALL_SCALE = 0.43;
export function wallPose(t: number) {
  return eio(p(t, NEXT.pullBack[0], NEXT.pullBack[1]));
}

export function rigTransform(t: number) {
  const c = cam(t);
  const enter = eo(p(t, MORNING.phoneIn[0], MORNING.phoneIn[1]));
  const bd = breakdownPose(t);
  // Afternoon exit and night entrance: turn away to the side, then turn back in.
  const exit = eio(p(t, AFTERNOON.phoneOut[0], AFTERNOON.phoneOut[1]));
  const nightIn = eo(p(t, NIGHT.phoneIn[0], NIGHT.phoneIn[1]));
  const isNightIn = t >= AFTERNOON.phoneOut[1];
  const wall = wallPose(t);
  const gather = eio(p(t, END.gather[0], END.gather[0] + 1.6));

  let s = c.s;
  let ax = ANCHOR.x - 150 * bd;
  let ay = ANCHOR.y;
  let fx = c.fx;
  let fy = c.fy;
  if (wall > 0) {
    s = lerp(s, WALL_SCALE, wall) * (1 - 0.6 * gather);
    ax = lerp(ax, 960, wall);
    ay = lerp(ay, 540, wall);
    fx = 205;
    fy = 432;
  }
  let ry = 25 * bd;
  let op = enter;
  let dy = (1 - enter) * 160;
  let dx = 0;
  if (!isNightIn) {
    ry += 22 * exit;
    op *= 1 - exit;
    dx += 80 * exit;
  } else {
    ry += -22 * (1 - nightIn);
    op *= nightIn;
    dx += -80 * (1 - nightIn);
  }
  op *= 1 - ei(p(t, END.gather[0] + 0.8, END.gather[0] + 1.8));
  const tx = ax - RIG.left - s * fx + dx;
  const ty = ay - RIG.top - s * fy + dy;
  return {
    // 3D only while turning: Chrome rasterises 3D layers at 1x, which blurs the camera push-ins.
    transform:
      `translate(${tx.toFixed(2)}px, ${ty.toFixed(2)}px) scale(${s.toFixed(4)})` +
      (Math.abs(ry) > 0.01 || enter < 1 ? ` rotateY(${ry.toFixed(2)}deg) rotateX(${((1 - enter) * 8).toFixed(2)}deg)` : ""),
    is3d: Math.abs(ry) > 0.01 || enter < 1,
    opacity: op,
    s,
    tx,
    ty,
  };
}

/* ---------------- gestures ---------------- */

const CARD0 = cardRect(0, HOME_LAYOUT.gridTop, 0);
const DIAL_Y = 115 + 150 + 48;
const dragPath = (x: number): [number, number] => {
  const t = lerp(AFTERNOON.drag[0], AFTERNOON.drag[1], x);
  const f = tuneFreq(t);
  return [300 - ((f - 88.7) / (97.4 - 88.7)) * 230, DIAL_Y];
};
const GESTURES: Gesture[] = [
  { a: MORNING.tap[0], b: MORNING.tap[1], x0: CARD0.x + 84, y0: CARD0.y + 84, x1: CARD0.x + 84, y1: CARD0.y + 84, tap: true },
  { a: MORNING.collapseDrag[0], b: MORNING.collapseDrag[1], x0: 195, y0: 90, x1: 195, y1: 470 },
  { a: MORNING.scrollSwipe[0], b: MORNING.scrollSwipe[1], x0: 195, y0: 660, x1: 195, y1: 490 },
  { a: MORNING.tabTap[0], b: MORNING.tabTap[1], x0: 195, y0: 793, x1: 195, y1: 793, tap: true },
  { a: AFTERNOON.drag[0] - 0.15, b: AFTERNOON.drag[1] + 0.1, x0: 0, y0: 0, x1: 0, y1: 0, path: dragPath },
  { a: AFTERNOON.ctaTap[0], b: AFTERNOON.ctaTap[1], x0: 195, y0: 588, x1: 195, y1: 588, tap: true },
  { a: NIGHT.routeTap[0], b: NIGHT.routeTap[1], x0: 332, y0: 786, x1: 332, y1: 786, tap: true },
  { a: NIGHT.collapse[0] - 0.2, b: NIGHT.collapse[1], x0: 195, y0: 90, x1: 195, y1: 470 },
];

/* ---------------- screen state ---------------- */

function homeState(t: number) {
  const next = t >= NIGHT.collapse[0];
  if (!next) {
    const builds = HOME_CARDS.map((_, i) => p(t, MORNING.coversAt + i * MORNING.coverStagger, MORNING.coversAt + i * MORNING.coverStagger + MORNING.coverBuild));
    const textOps = HOME_CARDS.map((_, i) => eo(p(t, MORNING.coversAt + 1.0 + i * MORNING.coverStagger, MORNING.coversAt + 1.8 + i * MORNING.coverStagger)));
    const scrollY = 72 * eio(p(t, MORNING.scroll[0], MORNING.scroll[1]));
    return { cards: HOME_CARDS, builds, textOps, scrollY, why: undefined, whyOp: 0, gridOp: 1 };
  }
  // Next morning: the list opens at "猜你想听"; last night's picks give way to new ones.
  const swap = t >= NEXT.why;
  const scrollY = 228;
  if (!swap) {
    return { cards: HOME_CARDS, builds: [1, 1, 1, 1], textOps: [1, 1, 1, 1], scrollY, why: RECO.why, whyOp: 0, gridOp: 1 - eo(p(t, NEXT.why - 0.6, NEXT.why)) };
  }
  const builds = RECO.cards.map((_, i) => p(t, NEXT.coversAt + i * NEXT.coverStagger, NEXT.coversAt + i * NEXT.coverStagger + NEXT.coverBuild));
  const textOps = RECO.cards.map((_, i) => eo(p(t, NEXT.coversAt + 1.0 + i * NEXT.coverStagger, NEXT.coversAt + 1.8 + i * NEXT.coverStagger)));
  return { cards: RECO.cards, builds, textOps, scrollY, why: RECO.why, whyOp: eo(p(t, NEXT.why, NEXT.why + 0.6)), gridOp: 1 };
}

function playerState(t: number, which: "morning" | "afternoon" | "night", from: number): PlayerState {
  const prog = PROGRAMMES[which];
  const since = Math.max(0, t - from);
  if (which !== "night") {
    return { t, host: 0, hostRoll: 0, play: 0.03 + since * 0.0012, ready: 0.22 + since * 0.004, elapsed: prog.elapsed + since };
  }
  const [h0, h1] = NIGHT.host;
  const hostOn = eo(p(t, h0 - 0.2, h0 + 0.2)) * (1 - eo(p(t, h1, h1 + 0.4)));
  const idx = Math.min(HOST.length - 2, Math.max(0, (t - h0 - NIGHT.hostLine * 0.6) / NIGHT.hostLine));
  const whole = Math.floor(idx);
  const frac = eio(clamp((idx - whole) * 3 - 2));
  const ready = lerp(0.28, 0.36, p(t, 65, NIGHT.progress[0])) + 0.2 * eio(p(t, NIGHT.progress[0], NIGHT.progress[1]));
  return {
    t,
    host: hostOn,
    hostRoll: whole + frac,
    play: lerp(0.12, 0.2, p(t, 65, 98)),
    ready,
    elapsed: prog.elapsed + since,
    routeBtn: Math.sin(Math.PI * p(t, NIGHT.routeTap[0], NIGHT.routeTap[1])),
  };
}

/** Morning open: the tapped card's cover grows into the player artwork. */
function OpeningCover({ t }: { t: number }) {
  const [a, b] = MORNING.open;
  if (t < a || t > b + 0.05) return null;
  const x = eio(p(t, a, b));
  const from = CARD0;
  const to = { x: 47, y: 136, size: 296 };
  const prog = PROGRAMMES.morning;
  return (
    <div
      style={{
        position: "absolute",
        left: lerp(from.x, to.x, x),
        top: lerp(from.y, to.y, x),
        width: lerp(from.size, to.size, x),
        height: lerp(from.size, to.size, x),
        borderRadius: 12,
        overflow: "hidden",
        boxShadow: `0 ${lerp(6, 22, x)}px ${lerp(18, 50, x)}px rgba(0,0,0,${lerp(0.08, 0.4, x)})`,
      }}
    >
      <Cover station={prog.station} seed={prog.seed} heading={prog.heading} radius={0} />
    </div>
  );
}

function Screen({ t }: { t: number }) {
  const home = homeState(t);
  // Visibility windows.
  const homeOp = t < AFTERNOON.tuneIn[1] ? 1 - eo(p(t, AFTERNOON.tuneIn[0], AFTERNOON.tuneIn[1])) : t >= NIGHT.collapse[0] ? 1 : 0;
  const mOpen = eio(p(t, MORNING.open[0], MORNING.open[1]));
  const mClose = eio(p(t, MORNING.collapse[0], MORNING.collapse[1]));
  const morningPlayer = t >= MORNING.open[0] && t < MORNING.collapse[1] + 0.05;
  const tuneOp = eo(p(t, AFTERNOON.tuneIn[0], AFTERNOON.tuneIn[1])) * (1 - eo(p(t, AFTERNOON.tuningIn, AFTERNOON.tuningIn + 0.35)));
  const tuningOp = eo(p(t, AFTERNOON.tuningIn, AFTERNOON.tuningIn + 0.35)) * (1 - eo(p(t, AFTERNOON.player - 0.5, AFTERNOON.player)));
  const aPlayerOp = t < 65 ? eo(p(t, AFTERNOON.player - 0.5, AFTERNOON.player)) : 0;
  const nightPlayer = t >= 65 && t < NIGHT.collapse[1] + 0.05;
  const nClose = eio(p(t, NIGHT.collapse[0], NIGHT.collapse[1]));

  const playerCover = morningPlayer ? clamp(mOpen * 3) * (1 - mClose) : nightPlayer ? 1 - nClose : 0;
  const tabOp = (homeOp > 0 || tuneOp > 0 ? Math.max(homeOp, tuneOp) : 0) * (1 - playerCover);
  const tabActive: 0 | 1 = t >= MORNING.tabTap[0] + 0.3 && t < 65 ? 1 : 0;

  const f = tuneFreq(t);
  const typedN = Math.floor(p(t, AFTERNOON.typing[0], AFTERNOON.typing[1]) * [...TYPED].length);
  const typed = [...TYPED].slice(0, typedN).join("");
  const caret = t > AFTERNOON.typing[0] - 0.4 && t < AFTERNOON.align[0] && Math.floor(t * 2.2) % 2 === 0;

  // Mini bar: morning (Plastic Love, playing) and next morning (Peace Piece, paused).
  const morningMini = t >= MORNING.collapse[0] && t < 33;
  const nextMini = t >= NIGHT.collapse[0];
  const miniProg = nextMini ? PROGRAMMES.night : PROGRAMMES.morning;
  const miniIn = eo(p(t, nextMini ? NIGHT.collapse[0] + 0.4 : MORNING.collapse[0] + 0.4, (nextMini ? NIGHT.collapse[0] : MORNING.collapse[0]) + 1.0));
  const miniOp = (morningMini || nextMini ? miniIn : 0) * (morningMini ? homeOp : 1);

  return (
    <div style={{ position: "absolute", inset: 0, overflow: "hidden", borderRadius: 48, background: "#F2F2F4", fontFamily: SANS }}>
      <Layer op={homeOp}>
        <HomeScreen {...home} hideFirstCover={t >= MORNING.open[0] && t < MORNING.open[1]} aura={t >= NIGHT.collapse[0] ? "#6E62B6" : "#E8834A"} />
      </Layer>
      <Layer op={tuneOp}>
        <TuneScreen t={t} freq={f} typed={typed} chip={eo(p(t, AFTERNOON.chip, AFTERNOON.chip + 0.5))} ctaPress={Math.sin(Math.PI * p(t, AFTERNOON.ctaTap[0] + 0.15, AFTERNOON.ctaTap[1]))} caret={caret} />
      </Layer>
      <Layer op={tuningOp}>
        <TuningScreen t={t} at={AFTERNOON.tuningIn} stationId="crate" />
      </Layer>
      {morningPlayer ? (
        <Layer op={clamp(mOpen * 3)} style={{ transform: `translateY(${(mClose * 860).toFixed(1)}px)` }}>
          <PlayerScreen prog={PROGRAMMES.morning} st={playerState(t, "morning", MORNING.open[1])} hideCover={t < MORNING.open[1]} />
        </Layer>
      ) : null}
      <OpeningCover t={t} />
      <Layer op={aPlayerOp}>
        <PlayerScreen prog={PROGRAMMES.afternoon} st={playerState(t, "afternoon", AFTERNOON.player)} />
      </Layer>
      {nightPlayer ? (
        <Layer op={1} style={{ transform: `translateY(${(nClose * 860).toFixed(1)}px)` }}>
          <PlayerScreen prog={PROGRAMMES.night} st={playerState(t, "night", 65)}>
            <RouteSheet t={t} at={NIGHT.route[0]} out={NIGHT.route[1]} />
          </PlayerScreen>
        </Layer>
      ) : null}
      <MiniBar prog={miniProg} playing={!nextMini} progress={nextMini ? 0.18 : 0.04 + Math.max(0, t - MORNING.open[1]) * 0.0012} op={miniOp} rise={(1 - miniIn) * 16} />
      <TabBar active={tabActive} op={tabOp} />
      <Finger t={t} gestures={GESTURES} />
    </div>
  );
}

export function Phone({ t }: { t: number }) {
  if (t < MORNING.phoneIn[0] || t > END.gather[0] + 2) return null;
  const rig = rigTransform(t);
  if (rig.opacity < 0.002) return null;
  const night = t >= 63.6 && t < 99;
  const glowOp = night ? 0.42 * eo(p(t, NIGHT.phoneIn[0], NIGHT.phoneIn[1] + 0.6)) * (1 - eio(p(t, NIGHT.light2[0], NIGHT.light2[1]))) : 0;
  return (
    <div style={{ position: "absolute", inset: 0, perspective: rig.is3d ? 2200 : undefined }}>
      {/* Night: the screen glows into the room (station colour, .42, blur 140px). */}
      {glowOp > 0.002 ? (
        <div style={{ position: "absolute", left: ANCHOR.x - 520, top: ANCHOR.y - 560, width: 1040, height: 1120, borderRadius: "50%", background: stationById("night").light, opacity: glowOp, filter: "blur(140px)" }} />
      ) : null}
      <div
        style={{
          position: "absolute",
          left: RIG.left,
          top: RIG.top,
          width: RIG.w,
          height: RIG.h,
          transformOrigin: "0 0",
          transformStyle: rig.is3d ? "preserve-3d" : "flat",
          transform: rig.transform,
          opacity: rig.opacity,
        }}
      >
        <div style={{ position: "absolute", inset: 0, borderRadius: 58, background: "#1D1D1F", padding: 10, boxSizing: "border-box", boxShadow: "0 50px 100px rgba(29,29,31,.28)" }}>
          <div style={{ position: "relative", width: 390, height: 844 }}>
            <Screen t={t} />
          </div>
        </div>
      </div>
    </div>
  );
}
