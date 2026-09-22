import { describe, expect, it, vi } from "vitest";

import {
  ExportBlockedError,
  downloadFilename,
  isOwnedAudioUrl,
  prepareEpisodeExport,
  validateMixdownArtifact,
  type EpisodeExportClient,
  type MixdownArtifact,
} from "../lib/episode-export";

const artifact: MixdownArtifact = {
  episodeId: "episode",
  planFingerprint: "fingerprint",
  audioUrl: "/api/assets/audio/mixdowns/episode/fingerprint.mp3",
  contentType: "audio/mpeg",
  durationSeconds: 42,
};

function client(overrides: Partial<EpisodeExportClient> = {}): EpisodeExportClient {
  return {
    prepareMixdown: vi.fn(async () => ({
      episodeId: "episode",
      ready: true,
      ownedMusicCount: 2,
      snapshottedMusicCount: 1,
      reusedMusicCount: 1,
      blockedSources: [],
    })),
    mixdown: vi.fn(async () => artifact),
    ...overrides,
  };
}

describe("episode export contract", () => {
  it("prepares once and renders once for a successful export", async () => {
    const exporter = client();

    await expect(prepareEpisodeExport("episode", exporter)).resolves.toEqual(artifact);

    expect(exporter.prepareMixdown).toHaveBeenCalledOnce();
    expect(exporter.mixdown).toHaveBeenCalledOnce();
  });

  it("reuses a cached artifact without calling either endpoint", async () => {
    const exporter = client();

    await expect(prepareEpisodeExport("episode", exporter, artifact)).resolves.toBe(artifact);

    expect(exporter.prepareMixdown).not.toHaveBeenCalled();
    expect(exporter.mixdown).not.toHaveBeenCalled();
  });

  it("never calls mixdown when preparation is blocked", async () => {
    const exporter = client({
      prepareMixdown: vi.fn(async () => ({
        episodeId: "episode",
        ready: false,
        ownedMusicCount: 1,
        snapshottedMusicCount: 0,
        reusedMusicCount: 0,
        blockedSources: [{ segmentId: "music", sourceKind: "SIDECAR", reasonCode: "snapshot_timeout" }],
      })),
    });

    const promise = prepareEpisodeExport("episode", exporter);

    await expect(promise).rejects.toBeInstanceOf(ExportBlockedError);
    expect(exporter.mixdown).not.toHaveBeenCalled();
  });

  it("does not call mixdown when preparation fails", async () => {
    const exporter = client({
      prepareMixdown: vi.fn(async () => {
        throw new Error("prepare failed");
      }),
    });

    await expect(prepareEpisodeExport("episode", exporter)).rejects.toThrow("prepare failed");
    expect(exporter.mixdown).not.toHaveBeenCalled();
  });

  it("fails closed for non-owned or non-mpeg artifacts", () => {
    expect(isOwnedAudioUrl(artifact.audioUrl)).toBe(true);
    expect(isOwnedAudioUrl("https://evil.example/audio.mp3")).toBe(false);
    expect(isOwnedAudioUrl("//evil.example/audio.mp3")).toBe(false);
    expect(() => validateMixdownArtifact({ ...artifact, audioUrl: "data:audio/mpeg;base64,..." }, "episode")).toThrow();
    expect(() => validateMixdownArtifact({ ...artifact, contentType: "audio/wav" }, "episode")).toThrow();
    expect(() => validateMixdownArtifact({ ...artifact, episodeId: "other" }, "episode")).toThrow();
  });

  it("creates a stable safe download filename", () => {
    expect(downloadFilename("episode/with spaces")).toBe("wavecast-episode_with_spaces.mp3");
  });
});
