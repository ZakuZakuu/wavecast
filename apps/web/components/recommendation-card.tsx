"use client";

import type { ProgramIdea } from "../lib/types";
import { ProgramArtwork } from "./program-artwork";

export function RecommendationCard({
  idea,
  busy = false,
  onStart,
}: {
  idea: ProgramIdea;
  busy?: boolean;
  onStart: (idea: ProgramIdea) => void;
}) {
  const subtitle = idea.tags.slice(0, 3).join(" · ");

  return (
    <button
      type="button"
      className="program-card recommendation-card"
      disabled={busy}
      onClick={() => onStart(idea)}
      aria-label={`生成节目：${idea.title}`}
    >
      <ProgramArtwork
        title={idea.title}
        subtitle={subtitle || "FOR YOU"}
        seed={idea.id.split("").reduce((hash, value) => hash + value.charCodeAt(0), 0)}
        family="editorial"
      />
      <div className="program-card-copy">
        <strong>{idea.title}</strong>
        <span>{busy ? "正在准备节目…" : idea.reason}</span>
      </div>
    </button>
  );
}
