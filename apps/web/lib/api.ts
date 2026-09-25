import { parseMixPlan, type MixPlan } from "./mix-timeline";
import type {
  LiveEpisode,
  ProgramProposal,
  ProgramProposalBatch,
  ProposalGenerationRequest,
  Seed,
} from "./types";
import type { MixdownArtifact, MixdownPreparationResult } from "./episode-export";
import { getApiAuthToken } from "./auth-client";

const listenerStorageKey = "wavecast-anonymous-listener";

function listenerId(): string | undefined {
  if (typeof window === "undefined") return undefined;
  const existing = window.localStorage.getItem(listenerStorageKey);
  if (existing) return existing;
  const created = crypto.randomUUID();
  window.localStorage.setItem(listenerStorageKey, created);
  return created;
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const anonymousListener = listenerId();
  const bearerToken = await getApiAuthToken();
  const response = await fetch(`/api${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(anonymousListener ? { "X-Wavecast-Listener": anonymousListener } : {}),
      ...(bearerToken ? { Authorization: `Bearer ${bearerToken}` } : {}),
      ...init?.headers,
    },
  });
  if (!response.ok) throw new Error((await response.json().catch(() => null))?.detail ?? "Request failed");
  return response.json() as Promise<T>;
}

export const api = {
  seeds: () => request<Seed[]>("/seeds"),
  program: (id: string) => request<ProgramProposal>(`/programs/${id}`),
  createProgramProposals: (input: ProposalGenerationRequest) =>
    request<ProgramProposalBatch>("/program-proposals", {
      method: "POST",
      body: JSON.stringify({ ...input, count: input.count ?? 1 }),
    }),
  start: (seedId: string) => request<LiveEpisode>(`/episodes/from-seed/${seedId}`, { method: "POST" }),
  get: (id: string) => request<LiveEpisode>(`/episodes/${id}`),
  mixPlan: async (id: string): Promise<MixPlan> => parseMixPlan(await request<unknown>(`/episodes/${id}/mix-plan`)),
  ensureBuffer: (id: string, targetChapters = 2) => request<LiveEpisode>(`/episodes/${id}/ensure-buffer`, { method: "POST", body: JSON.stringify({ target_chapters: targetChapters }) }),
  completed: (id: string) => request<LiveEpisode>(`/episodes/${id}/completed`, { method: "POST" }),
  heartbeat: (id: string) => request<LiveEpisode>(`/episodes/${id}/heartbeat`, { method: "POST" }),
  commit: (id: string, segmentId: string) => request<LiveEpisode>(`/episodes/${id}/commit/${segmentId}`, { method: "POST" }),
  next: (id: string) => request<LiveEpisode>(`/episodes/${id}/next`, { method: "POST" }),
  seek: (id: string, position: number) => request<LiveEpisode>(`/episodes/${id}/seek`, { method: "POST", body: JSON.stringify({ position_seconds: position }) }),
  checkpoint: (id: string, position: number) => request<LiveEpisode>(`/episodes/${id}/playback-checkpoint`, { method: "POST", body: JSON.stringify({ position_seconds: position }) }),
  leave: (id: string) => request<LiveEpisode>(`/episodes/${id}/leave`, { method: "POST" }),
  pause: (id: string) => request<LiveEpisode>(`/episodes/${id}/pause`, { method: "POST" }),
  resume: (id: string) => request<LiveEpisode>(`/episodes/${id}/resume`, { method: "POST" }),
  materialize: (id: string) => request<LiveEpisode>(`/episodes/${id}/materialize`, { method: "POST" }),
  prepareMixdown: (id: string) => request<MixdownPreparationResult>(`/episodes/${id}/prepare-mixdown`, { method: "POST" }),
  mixdown: (id: string) => request<MixdownArtifact>(`/episodes/${id}/mixdown`, { method: "POST" }),
  myLibrary: () => request<unknown>("/me/library"),
  mergeMyLibrary: (library: unknown) => request<unknown>("/me/library/merge", {
    method: "POST",
    body: JSON.stringify({ library }),
  }),
  favoriteProgram: (id: string, favorite: boolean) => request<unknown>(
    `/me/library/favorites/${encodeURIComponent(id)}`,
    { method: favorite ? "PUT" : "DELETE" },
  ),
  recordLibraryRecent: (record: unknown) => {
    const value = record as { episodeId: string };
    return request<unknown>(`/me/library/recents/${encodeURIComponent(value.episodeId)}`, {
      method: "PUT",
      body: JSON.stringify(record),
    });
  },
  saveLibraryEpisode: (record: unknown) => {
    const value = record as { episodeId: string };
    return request<unknown>(`/me/library/saved/${encodeURIComponent(value.episodeId)}`, {
      method: "PUT",
      body: JSON.stringify(record),
    });
  },
  removeLibraryEpisode: (id: string) => request<unknown>(
    `/me/library/saved/${encodeURIComponent(id)}`,
    { method: "DELETE" },
  ),
};
