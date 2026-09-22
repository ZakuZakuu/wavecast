export type BlockedMusicSource = {
  segmentId: string;
  sourceKind: string;
  reasonCode: string;
};

export type MixdownPreparationResult = {
  episodeId: string;
  ready: boolean;
  ownedMusicCount: number;
  snapshottedMusicCount: number;
  reusedMusicCount: number;
  blockedSources: BlockedMusicSource[];
};

export type MixdownArtifact = {
  episodeId: string;
  planFingerprint: string;
  audioUrl: string;
  contentType: string;
  durationSeconds: number;
};

export type EpisodeExportClient = {
  prepareMixdown: (episodeId: string) => Promise<MixdownPreparationResult>;
  mixdown: (episodeId: string) => Promise<MixdownArtifact>;
};

export class ExportBlockedError extends Error {
  readonly blockedSources: BlockedMusicSource[];

  constructor(blockedSources: BlockedMusicSource[]) {
    super("Episode audio is not ready for export");
    this.name = "ExportBlockedError";
    this.blockedSources = blockedSources;
  }
}

const ownedAudioPrefix = "/api/assets/audio/";

export function isOwnedAudioUrl(url: string): boolean {
  return url.startsWith(ownedAudioPrefix) && url.length > ownedAudioPrefix.length;
}

export function validateMixdownArtifact(artifact: MixdownArtifact, episodeId: string): MixdownArtifact {
  if (
    artifact.episodeId !== episodeId
    || artifact.contentType !== "audio/mpeg"
    || !isOwnedAudioUrl(artifact.audioUrl)
  ) {
    throw new Error("Invalid mixdown artifact");
  }
  return artifact;
}

export async function prepareEpisodeExport(
  episodeId: string,
  client: EpisodeExportClient,
  cachedArtifact?: MixdownArtifact | null,
): Promise<MixdownArtifact> {
  if (cachedArtifact?.episodeId === episodeId) return cachedArtifact;

  const prepared = await client.prepareMixdown(episodeId);
  if (!prepared.ready) throw new ExportBlockedError(prepared.blockedSources);

  return validateMixdownArtifact(await client.mixdown(episodeId), episodeId);
}

export function downloadFilename(episodeId: string): string {
  const safeId = episodeId.replace(/[^a-zA-Z0-9_-]/g, "_");
  return `wavecast-${safeId}.mp3`;
}

export function triggerMixdownDownload(artifact: MixdownArtifact, episodeId: string): void {
  const link = document.createElement("a");
  link.href = artifact.audioUrl;
  link.download = downloadFilename(episodeId);
  link.rel = "noopener";
  link.click();
}
