import type { CSSProperties } from "react";

type ProgramArtworkProps = {
  title: string;
  subtitle?: string;
  palette?: [string, string];
  seed?: number;
  family?: string;
  className?: string;
};

const FALLBACK_PALETTES: Array<[string, string]> = [
  ["#12395a", "#f45f51"],
  ["#2c2148", "#b677ff"],
  ["#19455c", "#f1b86a"],
  ["#4b2437", "#f07878"],
];

function hashText(value: string): number {
  let hash = 0;
  for (const character of value) hash = (hash * 31 + character.charCodeAt(0)) >>> 0;
  return hash;
}

export function ProgramArtwork({
  title,
  subtitle,
  palette,
  seed,
  family = "editorial",
  className = "",
}: ProgramArtworkProps) {
  const resolvedSeed = seed ?? hashText(title);
  const colors = palette ?? FALLBACK_PALETTES[resolvedSeed % FALLBACK_PALETTES.length];
  const style = {
    "--art-a": colors[0],
    "--art-b": colors[1],
    "--art-shift": (resolvedSeed % 46) + "%",
    "--art-tilt": ((resolvedSeed % 11) - 5) + "deg",
  } as CSSProperties;

  return (
    <div
      className={\`program-artwork artwork-\${family} artwork-variant-\${resolvedSeed % 3} \${className}\`}
      style={style}
      aria-label={title + " 节目封面"}
      role="img"
    >
      <div className="artwork-sun" />
      <div className="artwork-arc" />
      <div className="artwork-city" aria-hidden="true">
        <i /><i /><i /><i /><i />
      </div>
      <div className="artwork-copy">
        <span>WAVECAST</span>
        <strong>{title}</strong>
        {subtitle ? <small>{subtitle}</small> : null}
      </div>
      <div className="artwork-grain" aria-hidden="true" />
    </div>
  );
}
