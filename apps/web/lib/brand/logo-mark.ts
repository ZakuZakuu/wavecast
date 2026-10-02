// Port of docs/design/frost/LogoMark.dc.html, variant "radio" (the final icon).

export type LogoMarkOptions = {
  dark?: boolean;
  /** Draw a square full-bleed background instead of the rounded app tile. */
  square?: boolean;
  /** Scale the radio artwork around the centre (maskable icons use 0.8). */
  contentScale?: number;
};

export const LOGO_ACCENT = "#FF6B2C";

function grillePath(): string {
  let grille = "";
  for (let row = 0; row < 3; row += 1) {
    for (let column = 0; column < 3; column += 1) {
      const cx = 27 + column * 8;
      const cy = 46 + row * 9;
      const r = 2.5;
      grille += `M${cx - r} ${cy}a${r} ${r} 0 1 0 ${2 * r} 0a${r} ${r} 0 1 0 ${-2 * r} 0Z`;
    }
  }
  return grille;
}

export function logoMarkColors(dark = false) {
  return {
    bg: dark ? "#1D1D1F" : "#FFFFFF",
    fg: dark ? "#F5F5F7" : "#1D1D1F",
    accent: LOGO_ACCENT,
  };
}

/** Inner artwork (without the tile), in a 100×100 coordinate space. */
export function logoMarkArtwork(dark = false): string {
  const { bg, fg, accent } = logoMarkColors(dark);
  return [
    `<path d="M27 33 42 20" fill="none" stroke="${fg}" stroke-width="3.2" stroke-linecap="round"/>`,
    `<circle cx="42" cy="20" r="3.6" fill="${accent}"/>`,
    `<rect x="15" y="32" width="70" height="46" rx="12" fill="${fg}"/>`,
    `<path d="${grillePath()}" fill="${bg}"/>`,
    `<rect x="51" y="41" width="26" height="13" rx="4" fill="${bg}"/>`,
    `<path d="M66 38V57" fill="none" stroke="${accent}" stroke-width="3" stroke-linecap="round"/>`,
    `<circle cx="64" cy="66.5" r="5.5" fill="${bg}"/>`,
  ].join("");
}

export function logoMarkSvg(options: LogoMarkOptions = {}): string {
  const { dark = false, square = false, contentScale = 1 } = options;
  const { bg } = logoMarkColors(dark);
  const tile = square
    ? `<rect width="100" height="100" fill="${bg}"/>`
    : `<rect width="100" height="100" rx="22.5" fill="${bg}"/>`;
  const offset = (100 - 100 * contentScale) / 2;
  const art = contentScale === 1
    ? logoMarkArtwork(dark)
    : `<g transform="translate(${offset} ${offset}) scale(${contentScale})">${logoMarkArtwork(dark)}</g>`;
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">${tile}${art}</svg>`;
}
