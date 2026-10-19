// The styled cover library (#323), ported from docs/design/frost's CoverV3.dc.html: a cover is a
// motif (a picture), a style (how it is coloured and where the title goes) and a layout (one of the
// style's compositions). Everything is derived from the station and the programme's seed.

export const COVER_STYLES = ["poster", "glow", "scene", "sleeve", "line", "neon", "blue", "cut", "riso", "legacy"] as const;
export type CoverStyle = (typeof COVER_STYLES)[number];
export type StyledCoverStyle = Exclude<CoverStyle, "legacy">;

export const COVER_MOTIFS = [
  "rain", "vinyl", "keys", "skyline", "moon", "sea", "cassette", "headphones", "mic", "tuner",
  "bars", "road", "mountains", "forest", "rays", "windows", "ripples", "strings", "contour", "plant",
] as const;
export type CoverMotif = (typeof COVER_MOTIFS)[number];

/** A fixed choice for a programme (featured cards); anything left out is still derived from the seed. */
export type CoverPin = { style: CoverStyle; motif?: CoverMotif; layout?: number };

export type Rng = () => number;

/** One drawn shape. `css` is for the clipping box (card sized), `t` for the picture inside it; both are CSS text. */
export type Layer = { d: string; fill: string; stroke: string; sw: number; css: string; t: string };
export type TextBox = { text: string; css: string };

export type CoverView = {
  /** CSS background of the card. */
  rootBg: string;
  /** A solid colour that stands for the cover, for theming what is around it. */
  bg: string;
  layers: Layer[];
  grain: { blend: string; opacity: number };
  /** Title and the two caption words; their `css` positions them in cqw. Empty text = not drawn. */
  title: TextBox;
  caption: TextBox;
  caption2: TextBox;
};

export type PictureRole = "primary" | "secondary" | "detail" | "accent" | "cut" | "lit";
export type PictureItem = { role: PictureRole; mode: "fill" | "stroke"; d: string; sw?: number; z?: number; tone?: "light" | "dark" };
/** A motif is drawn on a 100 x 100 box. `view` is where a tight crop centres, `focus`/`fr` the subject. */
export type Motif = { focus: [number, number]; view: [number, number]; fr?: number; noZoom?: boolean; solid?: boolean; items: PictureItem[] };

export type StyleContext = {
  heading: string;
  layout: number;
  bare: boolean;
  station: { hue: number; name: string; freq: string };
};
