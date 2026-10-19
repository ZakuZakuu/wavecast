import type { CSSProperties } from "react";

const camel = (name: string) => name.replace(/-([a-z])/g, (_, letter: string) => letter.toUpperCase());

/** Cover styles are written as CSS text, as in the design files; this turns declarations into a React style. */
export function cssToStyle(css: string): CSSProperties {
  const style: Record<string, string> = {};
  for (const declaration of css.split(";")) {
    const at = declaration.indexOf(":");
    if (at < 0) continue;
    const key = camel(declaration.slice(0, at).trim().replace(/^-/, ""));
    style[key.startsWith("webkit") ? key[0].toUpperCase() + key.slice(1) : key] = declaration.slice(at + 1).trim();
  }
  return style as CSSProperties;
}
