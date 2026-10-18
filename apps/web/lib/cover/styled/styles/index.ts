import { glow, GLOW_LAYOUTS } from "./glow";
import { WINDOW_LAYOUTS, type StyleFn } from "./kit";
import { poster } from "./poster";
import { scene, SCENE_LAYOUTS } from "./scene";
import { sleeve, SLEEVE_LAYOUTS } from "./sleeve";
import { WINDOWED_STYLES } from "./windowed";
import type { StyledCoverStyle } from "../types";

export const STYLE_FNS: Record<StyledCoverStyle, StyleFn> = { poster, glow, scene, sleeve, ...WINDOWED_STYLES };

/** How many compositions each style has. */
export const LAYOUT_COUNTS: Record<StyledCoverStyle, number> = {
  poster: WINDOW_LAYOUTS.length,
  glow: GLOW_LAYOUTS.length,
  scene: SCENE_LAYOUTS.length,
  sleeve: SLEEVE_LAYOUTS.length,
  line: WINDOW_LAYOUTS.length,
  neon: WINDOW_LAYOUTS.length,
  blue: WINDOW_LAYOUTS.length,
  cut: WINDOW_LAYOUTS.length,
  riso: WINDOW_LAYOUTS.length,
};
