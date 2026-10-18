import type { CoverView, Layer } from "./types";

// A styled cover as one self-contained SVG, for the places that cannot render the page's own markup: the
// share preview image and the lock-screen artwork. The styles write their layers as CSS text (see
// StyledCover); this reads the few declarations they use and says the same in SVG. One cqw in the CSS
// is one unit here (the card is 100 wide), so lengths carry over as they are. Text and grain are left out.

type Declarations = Record<string, string>;

function declarations(css: string): Declarations {
  const out: Declarations = {};
  for (const declaration of css.split(";")) {
    const at = declaration.indexOf(":");
    if (at > 0) out[declaration.slice(0, at).trim()] = declaration.slice(at + 1).trim();
  }
  return out;
}

const length = (value: string | undefined, fallback = 0) => (value === undefined ? fallback : parseFloat(value) || 0);
const round = (value: number) => Math.round(value * 1000) / 1000;

/** "#abc", "#aabbcc", "rgba(1,2,3,.5)" or "transparent" as an SVG colour and its opacity. */
function colour(value: string): { color: string; opacity: number } {
  const text = value.trim();
  const rgb = text.match(/^rgba?\(([^)]+)\)$/);
  if (rgb) {
    const [r, g, b, a = "1"] = rgb[1].split(",").map((part) => part.trim());
    return { color: `rgb(${r},${g},${b})`, opacity: parseFloat(a) };
  }
  if (text === "transparent") return { color: "#000", opacity: 0 };
  return { color: text, opacity: 1 };
}

/**
 * Gradient stops "colour 30%". A stop without a position is spread evenly, and `transparent` keeps the colour
 * of the stop before it (CSS fades to nothing without passing through grey).
 */
function stops(list: string[]): string {
  return list
    .map((entry, i) => {
      const [value, position] = entry.trim().split(/\s+(?=[\d.]+%$)/);
      const { color: own, opacity } = colour(value);
      const color = value === "transparent" && i > 0 ? colour(list[i - 1].trim().split(/\s+(?=[\d.]+%$)/)[0]).color : own;
      const at = position ? parseFloat(position) : (i / Math.max(1, list.length - 1)) * 100;
      return `<stop offset="${at}%" stop-color="${color}"${opacity < 1 ? ` stop-opacity="${opacity}"` : ""}/>`;
    })
    .join("");
}

/** Splits "a, b(c, d), e" at the commas outside parentheses. */
const topLevel = (text: string) => {
  const parts: string[] = [];
  let depth = 0;
  let from = 0;
  [...text].forEach((ch, i) => {
    if (ch === "(") depth += 1;
    else if (ch === ")") depth -= 1;
    else if (ch === "," && depth === 0) {
      parts.push(text.slice(from, i));
      from = i + 1;
    }
  });
  parts.push(text.slice(from));
  return parts.map((part) => part.trim());
};

/** The card's background: a flat colour or a linear gradient over the whole card. */
function background(css: string, defs: string[]): string {
  const gradient = css.match(/^linear-gradient\((.*)\)$/);
  if (!gradient) return `<rect width="100" height="100" fill="${css}"/>`;
  const [first, ...rest] = topLevel(gradient[1]);
  const degrees = parseFloat(first);
  const radians = (degrees * Math.PI) / 180;
  const [dx, dy] = [Math.sin(radians), -Math.cos(radians)];
  const half = 50 * (Math.abs(dx) + Math.abs(dy));
  defs.push(
    `<linearGradient id="bg" gradientUnits="userSpaceOnUse" x1="${round(50 - dx * half)}" y1="${round(50 - dy * half)}" x2="${round(50 + dx * half)}" y2="${round(50 + dy * half)}">${stops(rest)}</linearGradient>`,
  );
  return `<rect width="100" height="100" fill="url(#bg)"/>`;
}

/** Graph-paper lines: `size` squares with a hairline along the top and the left, as the CSS gradients draw them. */
function gridLines(image: string, size: number, id: string, defs: string[]): string {
  const lines = (image.match(/linear-gradient\((?:[^()]|\([^()]*\))*\)/g) ?? []).map((gradient) => {
    const [first, ...rest] = topLevel(gradient.slice(16, -1));
    const horizontal = !/deg/.test(first) || parseFloat(first) % 180 === 0;
    const [from] = (/deg/.test(first) ? rest : [first, ...rest]);
    const stroke = from.trim().match(/^(.*)\s+([\d.]+)cqw$/);
    if (!stroke) return "";
    const { color, opacity } = colour(stroke[1]);
    const width = parseFloat(stroke[2]);
    return `<rect width="${horizontal ? size : width}" height="${horizontal ? width : size}" fill="${color}" fill-opacity="${opacity}"/>`;
  });
  defs.push(`<pattern id="${id}" patternUnits="userSpaceOnUse" width="${size}" height="${size}">${lines.join("")}</pattern>`);
  return id;
}

function layerSvg(layer: Layer, index: number, defs: string[]): string {
  const box = declarations(layer.css);
  const picture = declarations(layer.t);
  const id = `l${index}`;
  const [x, y, w, h] = [length(box.left), length(box.top), length(box.width, 100), length(box.height, 100)];
  const attrs: string[] = [];
  const style: string[] = [];

  if (box["mix-blend-mode"] && box["mix-blend-mode"] !== "normal") style.push(`mix-blend-mode:${box["mix-blend-mode"]}`);
  if (box.opacity) attrs.push(`opacity="${box.opacity}"`);
  const blur = box.filter?.match(/blur\(([\d.]+)cqw\)/);
  if (blur) {
    defs.push(`<filter id="${id}b" filterUnits="userSpaceOnUse" x="-100" y="-100" width="300" height="300"><feGaussianBlur stdDeviation="${blur[1]}"/></filter>`);
    attrs.push(`filter="url(#${id}b)"`);
  }
  const clip = box["clip-path"]?.match(/inset\(([\d.]+)cqw ([\d.]+)cqw ([\d.]+)cqw ([\d.]+)cqw round ([\d.]+)(?:cqw)?\)/);
  if (clip) {
    const [top, right, bottom, left, radius] = clip.slice(1).map(Number);
    defs.push(`<clipPath id="${id}c"><rect x="${x + left}" y="${y + top}" width="${w - left - right}" height="${h - top - bottom}" rx="${radius}"/></clipPath>`);
    attrs.push(`clip-path="url(#${id}c)"`);
  }
  const dots = (box["mask-image"] ?? "").match(/radial-gradient\(circle,(.*)\)$/);
  if (dots) {
    const size = length(box["mask-size"]);
    const [inside, outside] = topLevel(dots[1]);
    // `circle` reaches the farthest corner of the tile: the stops are percentages of that radius.
    defs.push(
      `<radialGradient id="${id}r" gradientUnits="userSpaceOnUse" cx="${size / 2}" cy="${size / 2}" r="${round((size * Math.SQRT2) / 2)}">${stops([inside, outside])}</radialGradient>`,
      `<pattern id="${id}p" patternUnits="userSpaceOnUse" x="${x}" y="${y}" width="${size}" height="${size}"><rect width="${size}" height="${size}" fill="url(#${id}r)"/></pattern>`,
      `<mask id="${id}m" maskUnits="userSpaceOnUse" x="${x}" y="${y}" width="${w}" height="${h}" style="mask-type:alpha"><rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#${id}p)"/></mask>`,
    );
    attrs.push(`mask="url(#${id}m)"`);
  }

  const parts: string[] = [];
  const fill = box.background ?? box["background-color"];
  const glow = fill?.match(/^radial-gradient\(circle at 50% 50%,(.*)\)$/);
  if (glow) {
    // A soft blob of colour: it fades out towards the farthest corner of its box.
    defs.push(`<radialGradient id="${id}f" gradientUnits="userSpaceOnUse" cx="${x + w / 2}" cy="${y + h / 2}" r="${round(Math.hypot(w, h) / 2)}">${stops(topLevel(glow[1]))}</radialGradient>`);
    parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#${id}f)"/>`);
  } else if (fill) {
    const { color, opacity } = colour(fill);
    parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${color}" fill-opacity="${opacity}"/>`);
  }
  if (box["background-image"]) {
    const grid = gridLines(box["background-image"], length(box["background-size"]), `${id}g`, defs);
    parts.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="url(#${grid})"/>`);
  }

  // The picture sits in a box of its own, moved by `transform` about `transform-origin` (the box's corner by default).
  const shadows = [...(picture.filter ?? "").matchAll(/drop-shadow\(([-\d.]+) ([-\d.]+) ([\d.]+)cqw ((?:[^()]|\([^()]*\))+)\)/g)];
  let pictureAttrs = "";
  if (shadows.length) {
    defs.push(
      `<filter id="${id}s" filterUnits="userSpaceOnUse" x="-100" y="-100" width="300" height="300" color-interpolation-filters="sRGB">${shadows
        .map(([, dx, dy, spread, value], i) => {
          const { color, opacity } = colour(value);
          return `<feDropShadow in="${i ? `s${i - 1}` : "SourceGraphic"}" result="s${i}" dx="${dx}" dy="${dy}" stdDeviation="${spread}" flood-color="${color}" flood-opacity="${opacity}"/>`;
        })
        .join("")}</filter>`,
    );
    pictureAttrs = ` filter="url(#${id}s)"`;
  }
  const path = `<path d="${layer.d}" fill="${layer.fill}" stroke="${layer.stroke}" stroke-width="${layer.sw}" stroke-linecap="round" stroke-linejoin="round" fill-rule="evenodd"${picture["stroke-dasharray"] ? ` stroke-dasharray="${picture["stroke-dasharray"]}"` : ""}/>`;
  const drawn = `<g${pictureAttrs}><svg x="${x}" y="${y}" width="${w}" height="${h}" viewBox="0 0 100 100" preserveAspectRatio="xMidYMid slice" overflow="visible">${path}</svg></g>`;
  const [ox, oy] = (picture["transform-origin"] ?? "0 0").split(/\s+/).map((value) => length(value));
  const moves = picture.transform ? ` transform="translate(${x + ox} ${y + oy}) ${picture.transform.replace(/cqw/g, "")} translate(${-(x + ox)} ${-(y + oy)})"` : "";
  parts.push(`<g${moves}>${drawn}</g>`);

  return `<g ${attrs.join(" ")}${style.length ? ` style="${style.join(";")}"` : ""}>${parts.join("")}</g>`;
}

export function coverViewToSvg(view: CoverView, size = 512): string {
  const defs: string[] = [];
  const base = background(view.rootBg, defs);
  const layers = view.layers.map((layer, index) => layerSvg(layer, index, defs)).join("");
  return `<svg xmlns="http://www.w3.org/2000/svg" width="${size}" height="${size}" viewBox="0 0 100 100"><defs>${defs.join("")}</defs>${base}${layers}</svg>`;
}
