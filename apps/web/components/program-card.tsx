import Link from "next/link";

import type { Seed } from "../lib/types";
import { ProgramArtwork } from "./program-artwork";

function durationLabel(seconds: number) {
  return "约 " + Math.max(1, Math.round(seconds / 60)) + " 分钟";
}

export function ProgramCard({ seed, compact = false }: { seed: Seed; compact?: boolean }) {
  return (
    <Link href={\`/program/\${seed.id}\`} className={compact ? "program-card compact" : "program-card"}>
      <ProgramArtwork
        title={seed.title}
        subtitle={seed.topic}
        palette={seed.cover.palette}
        seed={seed.cover.seed}
        family={seed.cover.family}
      />
      <div className="program-card-copy">
        <strong>{seed.title}</strong>
        <span>{durationLabel(seed.estimated_duration_seconds)} · {seed.opening_track_artist}</span>
      </div>
    </Link>
  );
}
