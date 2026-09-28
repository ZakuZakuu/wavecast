export type ProgramRenderChunk = {
  index: number;
  startSeconds: number;
  durationSeconds: number;
  planFingerprint: string;
  contentSha256: string;
  assetKey: string;
  audioUrl: string;
};

export type ProgramRenderManifest = {
  schemaVersion: 1;
  episodeId: string;
  revision: string;
  chunkDurationSeconds: number;
  holdbackSeconds: number;
  renderedFrontierSeconds: number;
  complete: boolean;
  chunks: ProgramRenderChunk[];
  streamUrl: string;
};

export function supportsNativeHls(): boolean {
  if (typeof document === "undefined") return false;
  const audio = document.createElement("audio");
  return Boolean(
    audio.canPlayType("application/vnd.apple.mpegurl")
    || audio.canPlayType("application/x-mpegURL"),
  );
}

export function clampProgramPosition(
  manifest: ProgramRenderManifest,
  positionSeconds: number,
): number {
  const maximum = Math.max(0, manifest.renderedFrontierSeconds - 0.01);
  return Math.max(0, Math.min(maximum, positionSeconds));
}
