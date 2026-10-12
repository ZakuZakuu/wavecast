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

const HLS_MIME = "application/vnd.apple.mpegurl";

/** Blink browsers (Chrome, Edge, Android WebView…); iOS "Chrome"/"Edge" are WebKit and do not match. */
function isChromiumEngine(userAgent: string): boolean {
  return /(Chrome|Chromium|Edg)\//.test(userAgent)
    && !/\b(CriOS|EdgiOS|FxiOS)\b/.test(userAgent);
}

/**
 * Whether the browser's own HLS player should play the programme stream.
 *
 * Safari's is dependable with our growing EVENT playlist. Chromium has shipped
 * a native HLS player too (canPlayType now answers "maybe"), but it treats the
 * playlist as a live stream: it starts at the live edge instead of 0:00 and,
 * after a stall, jumps to the newest chunk while the progress bar keeps its old
 * position. Chromium therefore always goes through hls.js (MSE), which follows
 * the playlist from the position the listener asked for.
 */
export function prefersNativeHls(
  canPlayType: (type: string) => string,
  userAgent: string,
): boolean {
  if (!canPlayType(HLS_MIME) && !canPlayType("application/x-mpegURL")) return false;
  return !isChromiumEngine(userAgent);
}

export function clampProgramPosition(
  manifest: ProgramRenderManifest,
  positionSeconds: number,
): number {
  const maximum = Math.max(0, manifest.renderedFrontierSeconds - 0.01);
  return Math.max(0, Math.min(maximum, positionSeconds));
}
